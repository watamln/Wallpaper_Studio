# Wallpaper Studio 🖼️

Android-style wallpaper cropping, preview, rotation/flipping and **per-monitor wallpapers** for Windows 10/11 — built for multi-monitor setups with mixed aspect ratios.

## ⚡ Download & run (no Python needed)

Grab the single-file executable from the [**Releases** page](../../releases):

- `WallpaperStudio.exe` — download it, double-click it, done. No installation, no Python, nothing else required.

> First launch: Windows SmartScreen may warn *"Windows protected your PC"* because the exe is unsigned (code signing costs money). Click **"More info → Run anyway"**. The source is right here — you can build it yourself with the GitHub Action if you prefer.

## Features

| | |
|---|---|
| ✂️ **Crop like on your phone** | Drag to pan, handles to resize, mouse wheel to zoom, rule-of-thirds grid, aspect presets (Screen / Free / 16:9 / 16:10 / 4:3 / 21:9 / 1:1 / 9:16). Loading an image auto-crops to the biggest centered region matching your screen ratio — so Windows never chops something off unexpectedly. |
| 👀 **Live preview** | Scaled mock-ups of every monitor, arranged in their real relative positions, showing exactly what each screen will display before you apply. |
| 🖼️ **Fit modes** | **Fill** (crop to cover), **Fit** (whole image visible with Black / White / Blur bars — Android style), **Stretch**, **Center**. |
| 🔄 **Rotate & flip** | 90° CW/CCW, 180°, Flip H, Flip V — applied before cropping. |
| 🖥️🖥️ **Different wallpaper per monitor** | Monitor tabs keep an independent image + crop + fit per display (works on extended desktops with different sizes/ratios). "SET WALLPAPER" applies to the selected monitor only; "Apply to ALL" uses each monitor's own saved look. |
| 💾 **Persistent profiles** | Your crops/layout are saved to `%APPDATA%\WallpaperStudio\profile.json`; generated wallpapers live in `%APPDATA%\WallpaperStudio\wallpapers\` so they survive reboots. |

### How per-monitor setting works

The classic Win32 API sets one wallpaper for the whole virtual desktop. Wallpaper Studio renders each monitor's wallpaper at native resolution, stitches them into a single spanned bitmap at exact pixel offsets, writes the proper registry style keys, and applies it via `SystemParametersInfoW` — so every screen shows precisely what the preview showed.

## Building the .exe yourself

The repo ships a GitHub Actions workflow (`.github/workflows/build.yml`). Two ways to trigger it:

1. Push a version tag: `git tag v1.0.0 && git push origin v1.0.0` → builds and attaches `WallpaperStudio.exe` to a new GitHub Release automatically.
2. Or go to **Actions → Build Windows exe → Run workflow** (the artifact tab gets the raw exe).

Locally on Windows: `pip install -r requirements.txt pyinstaller && pyinstaller build.spec` → output in `dist/`.

## Running from source (optional)

```bat
setup.bat   :: creates venv + installs Pillow/customtkinter (needs Python 3.10+)
run.bat     :: launches the GUI
```

CLI (headless):

```bat
wallpaper-studio monitors
wallpaper-studio set photo.jpg --fit fill
wallpaper-studio set-multi 0 left.png 1 right.png --apply
wallpaper-studio render img.jpg --monitor 1 --rotate 90 --crop 0.1,0.2,0.7,0.6 -o out.png
```

## Development

```bash
PYTHONPATH=src pytest tests -q   # 16 unit tests: crop math, transforms, fit/bar rendering, stitching
```

## License

MIT
