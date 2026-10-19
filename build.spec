# -*- mode: python ; coding: utf-8 -*-
# PyInstaller build spec for Wallpaper Studio (Windows, one-file GUI exe).
# Built automatically by .github/workflows/build.yml on every v* tag push.

a = Analysis(
    ['src/wallpaper_studio/app.py'],
    pathex=['src'],
    binaries=[],
    datas=[],
    hiddenimports=[
        'customtkinter',
        'PIL._tkinter_finder',
        'wallpaper_studio.win_api',
        'wallpaper_studio.monitors',
        'wallpaper_studio.image_pipeline',
        'wallpaper_studio.crop_canvas',
        'wallpaper_studio.profile',
        'wallpaper_studio.setter',
    ],
    hookspath=['hooks'],
    runtime_hooks=['runtime_hooks.py'],
    excludes=['matplotlib', 'numpy', 'scipy'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='WallpaperStudio',
    debug=False,
    strip=False,
    upx=False,
    console=False,          # windowed app: no black console window
    icon=None,
)
