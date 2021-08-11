import PyInstaller.__main__
from glob import glob
from shutil import copy
from os import mkdir
from os.path import exists

PyInstaller.__main__.run([
    'gui.py',
    '--onefile',
    '--windowed'
])

if exists('./dist') and exists('./icons') and exists('./snp_dict.pickle'):
    try:
        mkdir('./dist/icons')
        for filename in glob('./icons/*'):
            copy(filename, './dist/icons')
        copy('./snp_dict.pickle', './dist')
        copy('./README.txt', './dist')
    except FileExistsError:
        if exists('./dist/icons'):
            print('ICON FILES ALREADY EXIST IN DIST FOLDER.')
        if exists('./dist/snp_dict.pickle'):
            print('snp_dict.pickle ALREADY EXIST IN DIST FOLDER.')
        if exists('./dist/README.txt'):
            print('README.txt ALREADY EXIST IN DIST FOLDER.')
    except:
        print("NOT COPYING NECESSARY FILES. SOMETHING WENT WRONG.")

else:
    print("NOT COPYING NECESSARY FILES. SOMETHING WENT WRONG.")