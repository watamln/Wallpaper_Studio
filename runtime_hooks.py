# Make customtkinter's __file__-based asset lookups work under PyInstaller:
# point the package directory at the extraction folder (sys._MEIPASS).
import sys

if getattr(sys, "frozen", False):
    import customtkinter
    customtkinter.__path__[0] = meipass_ctk = __import__("os").path.join(
        sys._MEIPASS, "customtkinter")
