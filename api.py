import pickle
import pandas as pd
import requests
from glob import glob
from os import makedirs, remove
from os.path import isfile, exists
import io
from json import loads

import yfinance as yf
import datetime
from dateutil import parser
from dateutil.relativedelta import relativedelta
import pytz

from concurrent.futures import ThreadPoolExecutor, as_completed
from requests_futures.sessions import FuturesSession
from bs4 import BeautifulSoup

from tqdm import tqdm # console progress bar


class Singleton(type):
    _instances = {}

    def __call__(self, *args, **kwargs):
        if self not in self._instances:
            self._instances[self] = super(
                Singleton, self).__call__(*args, **kwargs)
        return self._instances[self]


class _CurrentSPXCompanies(metaclass=Singleton):
    _wiki_source = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
    def __init__(self):

        _WIKI_ERROR_MSG = "Can't parse Wikipedia's table! It's possible Wikipedia S&P Column Headers Changed."

        # first table on page _wiki_sorce lists company data
        try:
            table = pd.read_html(self._wiki_source)[0]
            col0 = table.columns[0]
            col1 = table.columns[1]
        except:
            raise Exception(_WIKI_ERROR_MSG)

        if (col0.rstrip() != "Symbol" or
                col1.rstrip() != "Security"):
            raise Exception(_WIKI_ERROR_MSG)

        symbol_name_zip = zip(
            table['Symbol'].to_list(), table['Security'].to_list())
        sorted_symbol_name_zip = sorted(symbol_name_zip, key=lambda _: _[0])
        self.companies = [{
            "symbol": _[0],
            "name": _[1],
        } for _ in sorted_symbol_name_zip]

class _EarningsDates(metaclass=Singleton):
    _EASTERN_TZ = pytz.timezone('US/Eastern')
    _REQUEST_HEADER = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/50.0.2661.75 Safari/537.36",
        "X-Requested-With": "XMLHttpRequest"
    }
    _TIMEOUT = 300

    def __init__(self):
        self._pool = ThreadPoolExecutor(max_workers=8)
        self._session = FuturesSession()

    def _ftodate(self, filename):
        return self._EASTERN_TZ.localize(parser.parse(filename, fuzzy=True))

    # zacks stores earnings dates data in a script tag in the page
    # parse dates from that script tag and return dates offest by earnings time
    def earnings_by_symbol(self, symbol):
        symbol = symbol.upper()
        url = "https://www.zacks.com/stock/research/%s/earnings-announcements"
        content = requests.get(
            url % symbol, headers=self._REQUEST_HEADER, timeout=(5, 27)).content
        soup = BeautifulSoup(content, 'html.parser')
        scripts = soup.find_all('script')
        table_scripts = [
            _ for _ in scripts if _.string and "earnings_announcements_earnings_table" in _.string]
        if len(table_scripts) > 0:
            js = table_scripts[0].string
            obj = loads(js[js.find('{'): js.rfind('}')+1])
            earnings_ann_table = obj["earnings_announcements_earnings_table"]
            dates = map(lambda _: self._ftodate(_[0]), earnings_ann_table)
            offests = map(lambda _: datetime.timedelta(days=1) if _[
                          6] == "After Close" else None, earnings_ann_table)
            return [d + o if o else d for d, o in zip(dates, offests)]

    def earnings(self, symbols):
        futures = []
        for symbol in symbols:
            future = self._pool.submit(self.earnings_by_symbol, symbol)
            future.symbol = symbol
            futures.append(future)

        dates_dict = {}
        pbar = tqdm(total=len(futures))
        try:
            for future in as_completed(futures, timeout=self._TIMEOUT):

                # console progress bar
                pbar.set_description(future.symbol)
                pbar.update()

                dates = future.result()
                symbol = future.symbol
                if isinstance(dates, list) and len(dates) > 0:
                    dates_dict[symbol] = dates
        except:
            pass
        return dates_dict

    def next_earnings_by_symbol(self, symbol):
        _ZACKS_URL = 'https://www.zacks.com/stock/quote/%s/detailed-estimates'
        _ZACKS_ERROR_MSG = 'Unable to get next earnings date for %s from Zacks.'
        try:
            r = requests.get(_ZACKS_URL % symbol, headers=self._REQUEST_HEADER)
            next_earnings_table = pd.read_html(
                r.content, match="Next Report Date", index_col=0, parse_dates=True)
            if len(next_earnings_table) == 0:
                raise Exception(_ZACKS_ERROR_MSG % symbol)
            date_string = next_earnings_table[0].loc['Next Report Date'].values[0]
            date = self._EASTERN_TZ.localize(
                parser.parse(date_string, fuzzy=True))
            return [date]
        except:
            pass
        return []

    def next_earnings(self, symbols):
        futures = []
        for symbol in symbols:
            future = self._pool.submit(self.next_earnings_by_symbol, symbol)
            future.symbol = symbol
            futures.append(future)

        dates_dict = {}
        pbar = tqdm(total=len(futures))
        try:
            for future in as_completed(futures, self._TIMEOUT):

                # console progress bar
                pbar.set_description(future.symbol)
                pbar.update()

                dates = future.result()
                symbol = future.symbol
                if isinstance(dates, list) and len(dates) > 0:
                    dates_dict[symbol] = dates
        except:
            pass
        return dates_dict


class SNPData(metaclass=Singleton):
    _EASTERN_TZ = pytz.timezone('US/Eastern')
    _TIMEOUT = 300
    def __init__(self):
        self.companies = _CurrentSPXCompanies().companies

        self._pool = ThreadPoolExecutor(max_workers=8)
        self._session = FuturesSession()

        earningsInstance = _EarningsDates()

        self.snp_dict = {}
        if exists('snp_dict.pickle'):
            self.snp_dict = pickle.load(open('snp_dict.pickle', 'rb'))

        current_symbols = [_['symbol'] for _ in self.companies]


        # remove delisted companies
        for symbol in [_ for _ in self.snp_dict]:
            if symbol not in current_symbols:
                del self.snp_dict[symbol]

        # update earnings estimates for companies with earnings in the next 15 days
        self.update_upcomming_earnings(15)

        # new S&P 500 companies
        new_companies = [_ for _ in current_symbols if _ not in self.snp_dict]

        # companies with recent earnings
        recent_earnings_companies = []
        for symbol in self.snp_dict:
            try:
                earnings_date = self.snp_dict[symbol].get('next_earnings', [])
                if len(earnings_date) > 0:
                    now = datetime.datetime.now(tz=self._EASTERN_TZ)
                    if earnings_date[0] + datetime.timedelta(days=1) < now:
                        recent_earnings_companies.append(symbol)
            except:
                continue

        ## all companies that need updating
        companies_to_update = [*new_companies, *recent_earnings_companies]

        ## new companies
        print("\n\nUpdating company earnings:\n\n")
        earnings = earningsInstance.earnings(companies_to_update)
        print("\n\nUpdating company earnings dates:\n\n")
        next_earnings_dates = earningsInstance.next_earnings(companies_to_update)
        # merge earnings with new_earnings and update snp_dict
        for symbol in new_companies:
            dates = earnings.get(symbol, [])[:10]
            table = self.daily_prices(symbol, dates)
            self.snp_dict[symbol] = {
                'earnings': dates,
                'next_earnings': next_earnings_dates.get(symbol, []),
                'table': table,
                'avg': self.avg_price(table, 10)
            }

        futures = []
        # make sure all averages and tables are up to date
        for symbol in self.snp_dict:
            info = self.snp_dict[symbol]
            if 'earnings' in info and 'table' not in info:
                dates = info['earnings']
                future = self._pool.submit(self.daily_prices, symbol, dates)
                future.symbol = symbol
                futures.append(future)

        # wait and consume all futures
        pbar = tqdm(total=len(futures))
        print("\n\nUpdating price data and averages:\n\n")
        try:
            for future in as_completed(futures, timeout=self._TIMEOUT):

                # console progress bar
                pbar.set_description(future.symbol)
                pbar.update()
                table = future.result()
                symbol = future.symbol
                if isinstance(table, pd.DataFrame):
                    self.snp_dict[symbol] = {
                        **self.snp_dict[symbol],
                        'table': table,
                        'avg': self.avg_price(table, 10)
                    }
        except:
            pass


        ## get company details
        futures = []
        for symbol in self.snp_dict:
            if not 'detail' in self.snp_dict[symbol]:
                self.snp_dict[symbol]['detail'] = ''
                future = self._pool.submit(
                    self.market_watch_company_detail, symbol)
                future.symbol = symbol
                futures.append(future)

        # wait and consume all futures
        print("\n\nGetting company details:\n\n")
        pbar = tqdm(total=len(futures))
        try:
            for future in as_completed(futures, timeout=self._TIMEOUT):

                # console progress bar
                pbar.set_description(future.symbol)
                pbar.update()

                detail = future.result()
                symbol = future.symbol
                if isinstance(detail, str):
                    self.snp_dict[symbol]['detail'] = detail
        except:
            pass

        ## add date as index to each table in snp_dict
        ##
        for symbol in self.snp_dict:
            info = self.snp_dict[symbol]
            info['table']['Date'] = pd.Series(self.snp_dict[symbol]['earnings'])
            info['table'].set_index('Date')
        ##

        pickle.dump(self.snp_dict, open('snp_dict.pickle', 'wb'))

    @property
    def data(self):
        return self.snp_dict

    def first_date(self):
        dates = []
        for symbol in self.snp_dict:
            dates.append(self.snp_dict[symbol]['table']['Date'].min())
        return pd.Series(dates).min()


    # update the earnings estimates for companies with earnings dates in the next 'days' days
    def update_upcomming_earnings(self, days):
        update_symbols = []
        for symbol in self.snp_dict:
            try:
                earnings_date = self.snp_dict[symbol].get('next_earnings', [])
                if len(earnings_date) > 0:
                    now = datetime.datetime.now(tz=self._EASTERN_TZ)
                    if earnings_date[0] < now and earnings_date[0] + datetime.timedelta(days=days) < now:
                        update_symbols.append(symbol)
                else:
                    update_symbols.append(symbol)
            except:
                continue

        print("\n\nUpdating upcommings earnings:\n\n")
        update_next_earnings = _EarningsDates().next_earnings(update_symbols)
        for symbol in update_next_earnings:
            if symbol in self.snp_dict:
                self.snp_dict[symbol]['next_earnings'] = update_next_earnings[symbol]

    ###
    # for each date in dates return the daily for the market day before and after date
    ###
    def daily_prices(self, symbol, dates):

        if len(dates) == 0:
            ret = pd.DataFrame(columns=['Date', 'Open_Pre', 'High_Pre', 'Low_Pre', 'Close_Pre', 'Volume_Pre',
                                        'Dividends_Pre', 'Stock Splits_Pre', 'Date_Pre', 'Open_Post',
                                        'High_Post', 'Low_Post', 'Close_Post', 'Volume_Post', 'Dividends_Post',
                                        'Stock Splits_Post', 'Date_Post', 'Point_Change', 'Percent_Change'])
            ret.set_index('Date')
            return ret

        # yfinance uses dashes and not dots in symbols
        symbol = symbol.replace('.', '-')

        ticker = yf.Ticker(symbol)

        if isinstance(dates, list):
            dates = pd.Series(dates)

        # pull dates 10 days ahead of max date to make sure that we always have a next market day
        min_date = pd.to_datetime(
            str(dates.min() - datetime.timedelta(days=10))).strftime('%Y-%m-%d')
        max_date = pd.to_datetime(
            str(dates.max() + datetime.timedelta(days=10))).strftime('%Y-%m-%d')

        price_history = ticker.history(
            start=min_date, end=max_date, interval="1d")
        price_history.index = price_history.index.map(
            lambda date: self._EASTERN_TZ.localize(date.to_pydatetime()))

        # closest market day greater than each date in dates
        def date_upper_bound(
            df, date): return df.loc[df.loc[df.index >= date].index.min()]
        def date_lower_bound(df, date): return df.loc[df.loc[df.index < date.replace(
            hour=0, minute=0)].index.max()]

        # closest market day before earning date
        pre_daily = pd.DataFrame(
            [date_lower_bound(price_history, date) for date in dates])
        pre_daily['Date'] = pre_daily.index
        pre_daily = pre_daily.reset_index(drop=True)

        # closest market day after earning date
        post_daily = pd.DataFrame(
            [date_upper_bound(price_history, date) for date in dates])
        post_daily['Date'] = post_daily.index
        post_daily = post_daily.reset_index(drop=True)

        daily = pre_daily.join(post_daily, lsuffix="_Pre", rsuffix="_Post")
        daily = daily.assign(
            Point_Change=lambda row: row['Close_Post'] - row['Close_Pre'],
            Percent_Change=lambda row: (row['Close_Post'] - row['Close_Pre']) * 100 / row['Close_Pre'])
        daily['Date'] = dates
        daily.set_index('Date')

        return daily

    def avg_price(self, prices, n):
        return {'point_avg': prices['Point_Change'][:n].mean(), 'percent_avg': prices['Percent_Change'][:n].mean()}

    def market_watch_company_detail(self, symbol):
        _MARKET_WATCH_URL = 'https://www.marketwatch.com/investing/stock/%s'
        try:
            content = requests.get(_MARKET_WATCH_URL %
                                   symbol, timeout=5).content
        except:
            return ''
        details = BeautifulSoup(content, 'html.parser').find_all(
            class_='description__text')
        if len(details) > 0:
            return details[0].text
        return ''

# main api singleton


class CompanyInfo(metaclass=Singleton):
    _EASTERN_TZ = pytz.timezone('US/Eastern')

    def __init__(self):
        snp = SNPData()
        self.companies = snp.companies
        self.snp_dict = snp.data

    def earnings_averages(self, symbol):
        symbol = symbol.upper()
        if symbol in self.snp_dict:
            return self.snp_dict[symbol]['avg']

    def earnings_change(self, symbol):
        symbol = symbol.upper()
        if symbol in self.snp_dict:
            return self.snp_dict[symbol]['table'][['Date', 'Close_Pre', 'Close_Post', 'Percent_Change']].values

    def earnings_dates(self, symbol):
        symbol = symbol.upper()
        if symbol in self.snp_dict:
            return self.snp_dict[symbol]['table']['Date'].values

    def next_earnings_date(self, symbol):
        symbol = symbol.upper()
        if symbol in self.snp_dict:
            dates = self.snp_dict[symbol]['next_earnings']
            if len(dates) > 0:
                return dates[0]
            else:
                # try to get the next_earnings for symbol
                next_earnings = _EarningsDates().next_earnings_by_symbol(symbol)
                if len(next_earnings) > 0:
                    self.snp_dict[symbol]['next_earnings'] = next_earnings
                    pickle.dump(self.snp_dict, open('snp_dict.pickle', 'wb'))
                    return next_earnings[0]

        #error datetime to cause update next start
        return datetime.datetime(year=1970, month=1, day=1)

    def company_detail(self, symbol):
        symbol = symbol.upper()
        if symbol in self.snp_dict:
            return self.snp_dict[symbol]['detail']

    def earnings_range(self, symbol):
        symbol = symbol.upper()
        if symbol in self.snp_dict:
            table = self.snp_dict[symbol]['table']
            min_date = table['Date'].min()
            max_date = table['Date'].max()
            return {'start': min_date, 'end': max_date}

    def stock_data(self, symbol, start, end=None):
        # yahoo uses '-' and not '.' in ex BRK-B
        symbol = symbol.replace('.', '-')
        return yf.Ticker(symbol).history(start=start, end=end)


class SNPPrice:
    _BASE_URL = "http://quote-feed.zacks.com/?t=%s"
    _REQUEST_HEADER = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/50.0.2661.75 Safari/537.36",
        "X-Requested-With": "XMLHttpRequest"
    }

    @staticmethod
    def prices(symbols):
        try:
            url = SNPPrice._BASE_URL % ",".join(symbols)
            resp = requests.get(url, timeout=5).content
            obj = loads(resp)
            return {k: obj[k].get('last', '') for k in obj}
        except:
            pass
        return {k: '' for k in symbols}

