"""
Wallpaper Studio - entry point for the packaged Windows executable.

Run directly:  python main.py
PyInstaller:   pyinstaller build.spec   (uses this file as the entry script)
"""
import os
import sys
import traceback


def _bootstrap_path() -> None:
    """Make `wallpaper_studio` importable both from a source checkout
    (src/ layout) and from a frozen PyInstaller bundle."""
    here = os.path.dirname(os.path.abspath(__file__))
    src = os.path.join(here, "src")
    if os.path.isdir(src) and src not in sys.path:
        sys.path.insert(0, src)


def _show_crash(err: str) -> None:
    """The windowed exe has no console, so surface fatal errors in a dialog."""
    log = ""
    try:
        appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
        log = os.path.join(appdata, "WallpaperStudio", "crash.log")
        os.makedirs(os.path.dirname(log), exist_ok=True)
        with open(log, "w", encoding="utf-8") as f:
            f.write(err)
    except OSError:
        pass
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "Wallpaper Studio failed to start",
            (err[:1500] + "\n\nFull log: " + log) if log else err[:2000])
        root.destroy()
    except Exception:
        sys.stderr.write(err)


def main() -> int:
    _bootstrap_path()
    try:
        from wallpaper_studio.app import run
        run()
    except Exception:
        _show_crash(traceback.format_exc())
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
