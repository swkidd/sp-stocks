
import tkinter as tk
from tkinter.scrolledtext import ScrolledText
import tkinter.ttk as ttk
from ttkthemes import ThemedStyle

import numpy as np
from datetime import datetime
from functools import partial

import matplotlib
matplotlib.use('TkAgg')
matplotlib.rcParams['axes.unicode_minus'] = False

from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.backend_bases import key_press_handler
import mplfinance as mpf

from api import CompanyInfo, SNPPrice

# truncate long date string (%Y-%m-%d)
def to_datestrings(dates):
    return [str(_)[:10] for _ in dates]

# CUSTOM WIDGETS
class StockChart(ttk.Frame):
    def __init__(self, parent, info, *args, **kwargs):
        self.companyinfo = CompanyInfo()
        ttk.Frame.__init__(self, parent, *args, **kwargs)
        self.parent = parent

        try:
            self.symbol = info['symbol']
            start = info['dates'].min()
            self.plot(self.symbol, str(start)[:10], to_datestrings(info['dates']))
        except:
            tk.Label(self, text=f"Cannot get chart for {self.symbol}").pack()

    # use matplot lib tk connector to plot stock data
    def plot(self, symbol, start, dates):
            stock_data = self.companyinfo.stock_data(symbol, start)
            markers = ["^" if _ in dates else None for _ in to_datestrings(
                stock_data.index)]
            adp = mpf.make_addplot(
                stock_data['Open'] * 0.95, marker=markers, type="scatter", markersize=200)

            fig = mpf.plot(stock_data, type="line",
                        addplot=adp, returnfig=True)
            canvas = FigureCanvasTkAgg(fig[0], master=self)
            canvas.mpl_connect("key_press_event", key_press_handler)
            widget = canvas.get_tk_widget()
            # set chart width/ height
            # width = int(widget['width'])
            # height = int(widget['height'])
            # widget.config(width=width*0.7, height=height*0.7)
            toolbar = NavigationToolbar2Tk(canvas, self, pack_toolbar=True)
            toolbar.update()
            widget.pack()
            canvas.draw()

# Custom treeview with built in sorting
class SortTreeview(ttk.Treeview):
    def __init__(self, parent, types, *args, **kwargs):
        ttk.Treeview.__init__(self, parent, *args, **kwargs)
        self.sort = types

    def heading(self, column, sort_by=None, **kwargs):
        if sort_by and not hasattr(kwargs, 'command'):
            func = getattr(self, f"_sort_by_{sort_by}", None)
            if func:
                kwargs['command'] = partial(func, column, False)
        return super().heading(column, **kwargs)

    def _sort(self, column, reverse, data_type, callback):
        l = [(self.set(k, column), k) for k in self.get_children('')]
        l.sort(key=lambda t: data_type(t[0]), reverse=reverse)
        for index, (_, k) in enumerate(l):
            self.move(k, '', index)
        self.heading(column, command=partial(callback, column, not reverse))

    def _sort_by_num(self, column, reverse):
        self._sort(column, reverse, float, self._sort_by_num)

    def _sort_by_name(self, column, reverse):
        self._sort(column, reverse, str, self._sort_by_name)

    def _sort_by_date(self, column, reverse):
        def _str_to_datetime(string):
            return datetime.strptime(string, "%Y-%m-%d")
        self._sort(column, reverse, _str_to_datetime, self._sort_by_date)


class NavButton(ttk.Frame):
    def __init__(self, parent, command=None, text=None, image=None, *args, **kwargs):
        ttk.Frame.__init__(self, parent, *args, **kwargs)
        self.parent = parent
        self.button = ttk.Button(
            self, text=text, image=image, command=command)

        self.button.pack(side=tk.TOP, fill=tk.X, expand=True)


# VIEWS // api data formatting
class CompanyDetailView:
    def __init__(self, symbol):
        self.companyinfo = CompanyInfo()
        changes = self.companyinfo.earnings_averages(symbol)
        self.info = {
            'symbol': symbol,
            'earnings_dates': self.companyinfo.earnings_dates(symbol),
            'next_earnings': self.companyinfo.next_earnings_date(symbol).strftime('%Y-%m-%d'),
            'average_point_change': abs(round(changes['point_avg'], 2)),
            'average_point_change_pos': True if changes['point_avg'] > 0 else False,
            'average_percent_change': abs(round(changes['percent_avg'], 2)),
            'average_percent_change_pos': True if changes['percent_avg'] > 0 else False,
            'description': self.companyinfo.company_detail(symbol)
        }


class InfoView:
    def format_values(self, sort, values):
        for sort, value in zip(sort, values):
            if sort == "date":
                if isinstance(value, datetime):
                    yield value.strftime("%Y-%m-%d")
                else:
                    # error datetime
                    yield datetime(year=1970, month=1, day=1)

            elif sort == "num":
                if isinstance(value, int) or isinstance(value, float):
                    yield round(value, 2)
                else:
                    try:
                        yield float(value)
                    except:
                        yield 0
            else:
                yield value


class EarningsInfoView(InfoView):
    def __init__(self, symbol):
        self.companyinfo = CompanyInfo()
        self.symbol = symbol
        info = {
            'text': f"{symbol} Past Earnings",
            'columns': ('Current Price', 'Earnings Date', 'Close Before', 'Close After', 'Percent Change'),
            'sort': ('num', 'date', 'num', 'num', 'num'),
            'values': {},
            'indicator': {},
        }

        prices = SNPPrice.prices([symbol])
        for index, values in enumerate(self.companyinfo.earnings_change(self.symbol)):
            price = prices[symbol]
            avgs = self.companyinfo.earnings_averages(symbol)
            next_earnings_date = self.companyinfo.next_earnings_date(symbol)
            info['values'][index] = tuple(
                self.format_values(info['sort'], [price, *values]))

        self.info = info


class SPInfoView(InfoView):
    percentaverage = "Percent Average"
    currentprice = "Current Price"
    earningsdate = "Upcomming Earnings Date"

    def __init__(self):
        self.companyinfo = CompanyInfo()
        info = {
            'text': 'Current S&P 500 Companies',
            'columns': ('Symbol', 'Company Name', self.currentprice, 'Point Average', self.percentaverage, self.earningsdate),
            'sort': ('name', 'name', 'num', 'num', 'num', 'date'),
            'values': {}
        }

        prices = SNPPrice.prices([ _['symbol'] for _ in self.companyinfo.companies ])
        for company in self.companyinfo.companies:
            symbol = company['symbol']
            name = company['name']
            price = prices[symbol]
            avgs = self.companyinfo.earnings_averages(symbol)
            next_earnings_date = self.companyinfo.next_earnings_date(symbol)
            info['values'][symbol] = tuple(self.format_values(info['sort'], [
                                           symbol, name, price, avgs['point_avg'], avgs['percent_avg'], next_earnings_date]))

        self.info = info

# UI ELEMENTS
class InfoPane(ttk.Frame):
    def __init__(self, parent, info, onclick=None, *args, **kwargs):
        ttk.Frame.__init__(self, parent, *args, **kwargs)
        self.parent = parent

        self.header = ttk.Label(
            self, text=info['text'], anchor=tk.CENTER, style='Heading.TLabel')

        self.list = SortTreeview(
            self, info['sort'], columns=info['columns'], show='headings')

        if onclick:
            self.list.bind("<ButtonRelease-1>", onclick(self.list))

        for index, column in enumerate(info['columns']):
            self.list.column(column, anchor=tk.CENTER, width=150)
            self.list.heading(
                column, sort_by=info['sort'][index], text=column, anchor=tk.CENTER)

        for value in info['values']:
            self.list.insert('', tk.END, values=info['values'][value])

        self.header.pack(side=tk.TOP, fill=tk.X)
        self.list.pack(fill=tk.BOTH, expand=True)

# 3 classes handle search functionality
# SearchResult displays the search reslut in a new toplevel
class SearchResult(ttk.Frame):
    def __init__(self, parent, tree_meta, *args, **kwargs):
        ttk.Frame.__init__(self, parent, *args, **kwargs)

        sort = tree_meta['sort']
        columns = tree_meta['columns']
        value_list = tree_meta['values']

        self.parent = parent
        self.tree_meta = tree_meta
        self.list = SortTreeview(self, sort, columns=columns, show='headings')
        self.list.bind("<ButtonRelease-1>", self.onClick)

        for index, column in enumerate(columns):
            self.list.column(column, anchor=tk.CENTER)
            self.list.heading(
                column, sort_by=sort[index], text=column, anchor=tk.CENTER)

        for values in value_list:
            self.list.insert('', tk.END, values=values)

        self.list.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

    def onClick(self, event):
        selection = self.list.selection()
        if len(selection) > 0:
            item = selection[0]
            symbol = self.list.item(item, 'values')[0]
            self.tree_meta['root'].showEarningsDetail(symbol)
            self.parent.destroy()

# Search text entry and button as well as the actual search function
class SearchBox(ttk.Frame):
    def __init__(self, parent, root, tree, *args, **kwargs):
        ttk.Frame.__init__(self, parent, *args, **kwargs)
        self.parent = parent
        self.root = root
        self.tree = tree
        self.entry = ttk.Entry(self)

        try:
            self.searchIcon = tk.PhotoImage(
                file='icons/search-button-text.png')
        except:
            self.searchIcon = None

        self.button = NavButton(
            self, image=self.searchIcon, command=self.search)

        self.entry.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)
        self.button.pack(side=tk.BOTTOM)

    def search(self):
        query = self.entry.get()
        if query == "":
            return
        selections = []
        for child in self.tree.get_children():
            values = self.tree.item(child)['values']
            if any([query.lower() == str(_).lower()[:len(query)] for _ in values]):
                selections.append(values)

        top = tk.Toplevel(self.root)
        tree_meta = {
            'root': self.root,
            'sort': self.tree.sort,
            'columns': self.tree['columns'],
            'values': selections,
        }
        search_results = SearchResult(top, tree_meta)
        search_results.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

# Frame wrapper for the search box
class SearchPane(ttk.Frame):
    def __init__(self, parent, root, tree, *args, **kwargs):
        ttk.Frame.__init__(self, parent, *args, **kwargs)
        self.parent = parent
        self.searchbox = SearchBox(self, root, tree)

        self.searchbox.pack(side=tk.TOP, fill=tk.X, expand=True)

# Expandable textbox
class ExpandingText(ttk.Frame):
    def __init__(self, parent, text, *args, **kwargs):
        ttk.Frame.__init__(self, parent, *args, **kwargs)
        self.parent = parent
        self.full_text = text
        self.truncated = False

        self.scrolltext = ScrolledText(self, wrap=tk.WORD)
        self.scrolltext.insert(tk.END, self.full_text)
        self.scrolltext.config(state=tk.DISABLED)
        self.scrolltext.pack()


# Frame wrapper for company detail labels
# Next Earnings Date, Average Point/ Percent Change and Company Summary
class CompanyDetailPane(ttk.Frame):
    def __init__(self, parent, info, *args, **kwargs):
        ttk.Frame.__init__(self, parent, *args, **kwargs)
        self.parent = parent

        ttk.Label(
            self, text=f"Upcoming Earnings: {info['next_earnings']}", style="Subheading.TLabel").pack(pady=5)

        averagechange = ttk.Frame(self)
        ttk.Label(averagechange, text="AVERAGE CHANGE",
                  style="Subheading.TLabel").pack(pady=5)

        try:
            self.upArrow = tk.PhotoImage(file="icons/up-arrow.png")
            self.downArrow = tk.PhotoImage(file="icons/down-arrow.png")
        except:
            self.upArrow = None
            self.downArrow = None

        pointImage = self.upArrow if info['average_point_change_pos'] else self.downArrow
        percentImage = self.upArrow if info['average_percent_change_pos'] else self.downArrow

        frame = ttk.Frame(averagechange)
        ttk.Label(
            frame, image=percentImage, text=f"Percent: {info['average_percent_change']}", compound=tk.RIGHT, style="Subheading.TLabel").pack(side=tk.RIGHT, padx=1)

        ttk.Label(
            frame, image=pointImage, text=f"Point: {info['average_point_change']}", compound=tk.RIGHT, style="Subheading.TLabel").pack(side=tk.RIGHT, padx=1)
        frame.pack(pady=2)

        ExpandingText(averagechange, info['description']).pack(
            side=tk.BOTTOM, expand=True, pady=4)

        averagechange.pack()

# Basic two column layout
class TwoColFrame(ttk.Frame):
    def __init__(self, parent, *args, **kwargs):
        ttk.Frame.__init__(self, parent, *args, **kwargs)
        self.parent = parent

        self.left = ttk.Frame(self)
        self.right = ttk.Frame(self)

        self.left.pack(side=tk.LEFT, fill=tk.Y)
        self.right.pack(fill=tk.BOTH, expand=True)

# three row layout used for the right column of the app
class ThreeRowFrame(ttk.Frame):
    def __init__(self, parent, *args, **kwargs):
        ttk.Frame.__init__(self, parent, *args, **kwargs)
        self.parent = parent

        self.top = ttk.Frame(self)
        self.mid = ttk.Frame(self)
        self.bot = ttk.Frame(self)

        self.top.pack(side=tk.TOP, fill=tk.X)
        self.mid.pack(expand=True)
        self.bot.pack(side=tk.BOTTOM, fill=tk.X)

# Rigth column shared buttons
class BaseRightCol(ThreeRowFrame):
    def __init__(self, parent, info, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.parent = parent

        try:
            self.exitIcon = tk.PhotoImage(file='icons/exit-icon-image.png')
            self.homeIcon = tk.PhotoImage(file='icons/home-icon-image.png')
            self.exitText = tk.PhotoImage(file='icons/exit-button-text.png')
            self.helpText = tk.PhotoImage(file='icons/help-button-text.png')
        except:
            self.exitIcon = None
            self.homeIcon = None
            self.exitText = None
            self.helpText = None

        NavButton(self.top, command=info['exit_command'], image=self.exitIcon).pack(
            side=tk.RIGHT, fill=tk.X, expand=True)
        NavButton(self.top, command=info['home_command'], image=self.homeIcon).pack(
            side=tk.RIGHT, fill=tk.X, expand=True)

        NavButton(self.bot, command=info['exit_command'], image=self.exitText).pack(
            side=tk.RIGHT, fill=tk.X, expand=True)
        NavButton(self.bot, command=info['help_command'], image=self.helpText).pack(
            side=tk.RIGHT, fill=tk.X, expand=True)

# App entry point and main Frame
class MainApplication(ttk.Frame):
    def __init__(self, parent, views, *args, **kwargs):
        ttk.Frame.__init__(self, parent, *args, **kwargs)
        self.views = views
        self.snpinfo = views['snp'].info
        self.parent = parent
        self.root = self
        self.sortByImage = None

        snp = views['snp']
        self.sortcommands = [
            {
                'filename': 'average-text.png',
                'command': lambda list: partial(list._sort_by_num, snp.percentaverage, True)
            },
            {
                'filename': 'current-text.png',
                'command': lambda list: partial(list._sort_by_num, snp.currentprice, True)
            },
            {
                'filename': 'earnings-text.png',
                'command': lambda list: partial(list._sort_by_date, snp.earningsdate, False)
            },
        ]

        self.button_info = {
            'exit_command': lambda: parent.destroy(),
            'help_command': lambda: self.showHelpWindow(),
            'home_command': lambda: self.showSPWindow()
        }

        self.showSPWindow()

    # show the Home page of the app
    def showSPWindow(self):
        mainwindow = getattr(self, 'mainwindow', None)
        if mainwindow:
            mainwindow.destroy()

        # main two column layout
        twocols = TwoColFrame(self)
        twocols.pack(fill=tk.BOTH, anchor=tk.CENTER, expand=True)
        self.mainwindow = twocols

        # left column
        infopane = InfoPane(
            twocols.left, self.snpinfo, onclick=self.spOnClick)
        infopane.pack(fill=tk.BOTH, expand=True, padx=40, pady=80)

        # right column
        rightcol = BaseRightCol(twocols.right, self.button_info)

        searchpane = SearchPane(rightcol.mid, self, infopane.list)
        # sort buttons
        # prevent icon garbage collection by saving to class variable
        self.images = []

        if self.sortByImage is None:
            try:
                self.sortByImage = tk.PhotoImage(file=f'icons/sort-by-text.png')
            except:
                self.sortByImage = None

        if self.sortByImage is not None:
            ttk.Label(searchpane, image=self.sortByImage).pack(pady=2)

        for sorts in self.sortcommands:
            try:
                image = tk.PhotoImage(file=f'icons/{sorts["filename"]}')
                command = sorts['command']
                NavButton(searchpane, command=command(infopane.list), image=image).pack(pady=4)
                self.images.append(image)
            except:
                continue

        searchpane.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        rightcol.pack(fill=tk.BOTH, expand=True, pady=40, padx=40)

    # shows the earnings detail for a symbol, creates a new page
    def showEarningsDetail(self, symbol):
        mainwindow = getattr(self, 'mainwindow', None)
        if mainwindow:
            mainwindow.destroy()

        # main two column layout
        twocols = TwoColFrame(self)
        twocols.pack(fill=tk.BOTH, anchor=tk.CENTER, expand=True)
        self.mainwindow = twocols

        companydetail = CompanyDetailView(symbol)

        # left column
        earnings_info = EarningsInfoView(symbol)
        infopane = InfoPane(twocols.left, earnings_info.info)
        CompanyDetailPane(infopane, companydetail.info).pack()
        infopane.pack(fill=tk.BOTH, expand=True, padx=40, pady=80)

        # right column
        rightrows = BaseRightCol(twocols.right, self.button_info)
        StockChart(
            rightrows.mid, {'dates': companydetail.info['earnings_dates'], 'symbol': companydetail.info['symbol']}).pack()
        rightrows.pack(fill=tk.BOTH, expand=True, pady=40, padx=40)

    def showHelpWindow(self):
        top = tk.Toplevel(self.root)
        with open('README.txt', 'r') as readme:
            text = ScrolledText(top, wrap=tk.WORD)
            text.insert(tk.END, readme.read())
            text.config(state=tk.DISABLED)
            text.pack(fill=tk.BOTH, expand=True)

    def spOnClick(self, list):
        def onClick(event):
            selection = list.selection()
            if len(selection) > 0:
                item = selection[0]
                symbol = list.item(item, 'values')[0]
                self.showEarningsDetail(symbol)
        return onClick


if __name__ == "__main__":
    root = tk.Tk()
    root.title("S&P 500 Tracker")

    # styles
    style = ThemedStyle(root)
    style.set_theme('arc') #imported from ttkthemes library

    text_base = {'background': 'white', 'relief': tk.SOLID, 'padding': 16}
    style.configure('Heading.TLabel', **text_base, font=('Roboto', 24, 'bold'))
    style.configure('Subheading.TLabel', **text_base,
                    font=('Roboto', 10, 'bold'))

    style.configure('TLabel', background="white")
    style.configure('TEntry', padding=10)

    style.configure("Treeview", rowheight=25, padding=8, font=('Roboto', 10))
    style.configure("Treeview.Heading", font=('Roboto', 8, 'bold'))
    style.configure("Treeview.treearea", relief=tk.SOLID,
                    font=('Roboto', 8, 'bold'))
    style.layout(
        "Treeview", [('mystyle.Treeview.treearea', {'sticky': 'nswe'})])

    # window size
    root.geometry("1440x1024")

    snpinfoview = SPInfoView()
    views = {'snp': snpinfoview}

    MainApplication(root, views).pack(side="top", fill="both", expand=True)
    root.mainloop()
