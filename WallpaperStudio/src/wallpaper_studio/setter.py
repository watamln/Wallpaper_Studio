"""
setter.py - Apply rendered wallpapers to the Windows desktop.

Strategy for "different wallpaper per monitor":
    Windows' classic SystemParametersInfo(SPI_SETDESKWALLPAPER) applies ONE
    image to the whole virtual desktop.  So when monitors have different
    per-monitor images we render a single stitched bitmap the size of the
    entire virtual desktop, place each monitor's render at its exact pixel
    offset, and set THAT as the wallpaper with WallpaperStyle=10 (span) / or
    6 (fit) depending on geometry.  Result: each screen shows exactly what
    the preview showed.

Registry values written (HKCU\\Control Panel\\Desktop):
    Wallpaper            -> path of the generated bmp
    WallpaperStyle       -> 10 (span) when stitching, 6 (fit), 2 (tile)...
    TileWallpaper        -> 0
    PicturePosition      -> same semantics for Win10/11 Settings UI

After writing we call SystemParametersInfoW so the change is immediate.
"""
from __future__ import annotations

import ctypes
import os
import sys
import tempfile
from dataclasses import dataclass
from typing import List, Optional, Tuple

from PIL import Image

from . import win_api as W
from .image_pipeline import make_virtual_desktop_image
from .monitors import MonitorInfo, get_monitors

if W.IS_WINDOWS:
    import winreg  # Windows only

# Where generated bitmaps live (kept so Windows can re-load them at logon!)
OUTPUT_DIR = os.path.join(os.environ.get("APPDATA", tempfile.gettempdir()),
                          "WallpaperStudio", "wallpapers")


@dataclass
class ApplyResult:
    ok: bool
    paths: List[str]
    message: str = ""


def _ensure_output_dir() -> str:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    return OUTPUT_DIR


def save_wallpaper_bmp(img: Image.Image, name_hint: str = "wallpaper") -> str:
    """Windows requires BMP (uncompressed) or JPG for the wallpaper file;
    JPG is smaller and works fine on Win10/11. We write JPEG quality 95."""
    out_dir = _ensure_output_dir()
    safe = "".join(c for c in name_hint if c.isalnum() or c in "_-")[:48] or "wallpaper"
    path = os.path.join(out_dir, f"{safe}.jpg")
    img.convert("RGB").save(path, "JPEG", quality=95)
    return path


def set_registry_style(style: str = "span", tile: bool = False) -> None:
    """style: fit/fill/stretch/tile/center/span -> WallpaperStyle codes."""
    if not W.IS_WINDOWS:
        return
    codes = {"center": "0", "tile": "2", "stretch": "6", "fit": "7",
             "fill": "10", "span": "10"}
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Control Panel\\Desktop",
                         0, winreg.KEY_SET_VALUE)
    with key:
        winreg.SetValueEx(key, "WallpaperStyle", 0, winreg.REG_SZ,
                          codes.get(style, "10"))
        winreg.SetValueEx(key, "TileWallpaper", 0, winreg.REG_SZ,
                          "1" if tile else "0")
        # PicturePosition used by modern Settings app mirrors the above
        pos = {"center": "0", "tile": "0", "stretch": "2", "fit": "3",
               "fill": "6", "span": "6"}.get(style, "6")
        try:
            winreg.SetValueEx(key, "PicturePosition", 0, winreg.REG_DWORD, int(pos))
        except OSError:
            pass  # optional value


def apply_wallpaper_file(path: str) -> bool:
    """Set an already-existing image file as the desktop wallpaper."""
    if not W.IS_WINDOWS:
        print(f"[dry-run] would set wallpaper: {path}")
        return True
    abs_path = os.path.abspath(path)
    res = W.user32.SystemParametersInfoW(
        W.SPI_SETDESKWALLPAPER, 0, abs_path,
        W.SPIF_UPDATEINIFILE | W.SPIF_SENDCHANGE)
    return bool(res)


def apply_single(img: Image.Image, style: str = "fill",
                 name_hint: str = "single") -> ApplyResult:
    path = save_wallpaper_bmp(img, name_hint)
    set_registry_style(style)
    ok = apply_wallpaper_file(path)
    return ApplyResult(ok, [path],
                       "" if ok else "SystemParametersInfo failed")


def apply_per_monitor(per_monitor: List[Tuple[MonitorInfo, Image.Image]],
                      monitors: Optional[List[MonitorInfo]] = None) -> ApplyResult:
    """Stitch per-monitor renders across the virtual desktop and apply."""
    monitors = monitors or get_monitors()
    if not per_monitor:
        return ApplyResult(False, [], "nothing to apply")

    min_x = min(m.left for m in monitors)
    min_y = min(m.top for m in monitors)
    max_x = max(m.right for m in monitors)
    max_y = max(m.bottom for m in monitors)
    vw, vh = max_x - min_x, max_y - min_y

    # If every monitor got the *same* image object, just apply it once.
    uniq = {id(im) for _m, im in per_monitor}
    if len(per_monitor) == 1 or len(uniq) == 1:
        return apply_single(per_monitor[0][1], "fill", "single")

    stitched = make_virtual_desktop_image(per_monitor, (vw, vh), (min_x, min_y))
    path = save_wallpaper_bmp(stitched, "spanned")
    # 'span' keeps 1:1 pixels across the virtual desktop.
    set_registry_style("span")
    ok = apply_wallpaper_file(path)
    return ApplyResult(ok, [path],
                       "" if ok else "SystemParametersInfo failed")


def current_wallpaper_path() -> Optional[str]:
    if not W.IS_WINDOWS:
        return None
    buf = ctypes.create_unicode_buffer(260)
    W.user32.SystemParametersInfoW(W.SPI_GETDESKWALLPAPER, 260, buf, 0)
    return buf.value or None
