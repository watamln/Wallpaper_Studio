# PyInstaller hook: customtkinter loads its JSON themes, .otf/.ttf fonts and
# .ico icon via plain os.path.dirname(__file__) paths, which break in a frozen
# one-file exe (files live in sys._MEIPASS). Collect them as package data.
from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files("customtkinter")
