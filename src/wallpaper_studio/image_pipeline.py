"""
image_pipeline.py - All the pure image maths & rendering for Wallpaper Studio.

No Windows APIs here; everything works with Pillow images so it is fully
unit-testable on any platform.

Key concepts
------------
* A `CropRect` is stored in *normalized* coordinates (0..1) relative to the
  **original** image, after rotate/flip transforms are applied.  Storing the
  crop normalized means the same crop looks identical at any preview zoom.
* Fit modes decide how an image maps into a monitor rectangle:
    - fill   : cover, may crop edges (like Android "crop to fill")
    - fit    : contain, whole image visible, bars around it
    - stretch: ignore aspect ratio, distort to fill
    - center : no scaling at all, original pixels, pad/crop to monitor size
* `render_monitor_wallpaper()` produces the exact bitmap that will be sent
  to Windows for one monitor.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import Enum
from typing import Optional, Tuple

from PIL import Image, ImageOps


# --------------------------------------------------------------- enums / geo
class FitMode(str, Enum):
    FILL = "fill"        # cover - crop overflow
    FIT = "fit"          # contain - letterbox/pillarbox with bar colour
    STRETCH = "stretch"  # distort
    CENTER = "center"    # no resize, centre-crop or pad


class BarStyle(str, Enum):
    BLACK = "black"
    WHITE = "white"
    BLUR = "blur"        # stretched blurred copy behind (Android-style)
    COLOR = "color"


@dataclass(frozen=True)
class CropRect:
    """Normalized rect (x, y, w, h all in 0..1) on the transformed source."""
    x: float = 0.0
    y: float = 0.0
    w: float = 1.0
    h: float = 1.0

    def clamped(self) -> "CropRect":
        w = max(1e-6, min(self.w, 1.0))
        h = max(1e-6, min(self.h, 1.0))
        x = min(max(self.x, 0.0), 1.0 - w)
        y = min(max(self.y, 0.0), 1.0 - h)
        return CropRect(x, y, w, h)

    @property
    def aspect(self) -> float:
        return self.w / self.h if self.h else 1.0

    def scaled_to(self, img_w: int, img_h: int) -> Tuple[int, int, int, int]:
        """Convert to integer pixel box (l, t, r, b) inside an image."""
        l = round(self.x * img_w)
        t = round(self.y * img_h)
        r = round((self.x + self.w) * img_w)
        b = round((self.y + self.h) * img_h)
        return l, t, max(l + 1, r), max(t + 1, b)

    def union_point(self, nx: float, ny: float) -> "CropRect":
        return CropRect(min(self.x, nx), min(self.y, ny),
                        max(self.x + self.w, nx) - min(self.x, nx),
                        max(self.y + self.h, ny) - min(self.y, ny)).clamped()


@dataclass(frozen=True)
class Transform:
    """User edits applied to the source image before cropping."""
    rotation_deg: int = 0      # multiples of 90 (free angles allowed too)
    flip_h: bool = False
    flip_v: bool = False

    def rotated_size(self, w: int, h: int) -> Tuple[int, int]:
        r = self.rotation_deg % 360
        if r in (90, 270) or (90 < abs(r) % 360 < 270 and r not in (0, 180)):
            # For arbitrary angles we keep the canvas the same size and let
            # corners clip; only exact 90/270 swaps dimensions.
            if r in (90, 270):
                return h, w
        return w, h


# -------------------------------------------------------------- transform ops
def apply_transform(img: Image.Image, t: Transform) -> Image.Image:
    """Rotate + flip an image, returning a new image (RGBA-safe)."""
    out = img
    if t.flip_h:
        out = out.transpose(Image.FLIP_LEFT_RIGHT)
    if t.flip_v:
        out = out.transpose(Image.FLIP_TOP_BOTTOM)
    if t.rotation_deg % 360 != 0:
        angle = -t.rotation_deg  # PIL rotates counter-clockwise
        if t.rotation_deg % 90 == 0:
            out = out.rotate(angle % 360, expand=True)
        else:
            # Free-angle: expand canvas, transparent corners
            out = out.rotate(angle % 360, expand=True, resample=Image.BICUBIC)
    return out


def transform_bounds_after_free_rotation(w: int, h: int, deg: int) -> Tuple[int, int]:
    return Transform(rotation_deg=deg).rotated_size(w, h)


# -------------------------------------------------------------- crop helpers
def default_crop_for_aspect(src_w: int, src_h: int, target_aspect: float) -> CropRect:
    """Largest centered crop rect whose *pixel* aspect equals `target_aspect`.

    The returned rect is normalized against the source image, so its w/h
    fraction ratio differs from the pixel aspect by (src_w/src_h).
    """
    src_aspect = src_w / src_h
    if src_aspect > target_aspect:
        # source wider -> full height, trim width
        cw = target_aspect * src_h / src_w
        return CropRect((1.0 - cw) / 2.0, 0.0, cw, 1.0).clamped()
    # source taller -> full width, trim height
    ch = (src_w / target_aspect) / src_h
    return CropRect(0.0, (1.0 - ch) / 2.0, 1.0, ch).clamped()


def crop_pixel_aspect(img: Image.Image, crop: CropRect) -> float:
    box = crop_box_pixels(img, crop)
    w = box[2] - box[0]
    h = box[3] - box[1]
    return w / h if h else 1.0


def crop_box_pixels(img: Image.Image, crop: CropRect) -> Tuple[int, int, int, int]:
    return crop.clamped().scaled_to(img.width, img.height)


def crop_image(img: Image.Image, crop: CropRect) -> Image.Image:
    l, t, r, b = crop_box_pixels(img, crop)
    return img.crop((l, t, r, b))


# -------------------------------------------------------------- rendering
def _blur_backdrop(img: Image.Image, size: Tuple[int, int]) -> Image.Image:
    """Small blurred stretched copy used behind 'fit' mode."""
    bg = img.convert("RGB").resize(size, Image.BILINEAR)
    small = bg.resize((max(8, size[0] // 12), max(8, size[1] // 12)), Image.BILINEAR)
    from PIL import ImageFilter
    small = small.filter(ImageFilter.GaussianBlur(radius=6))
    return small.resize(size, Image.BILINEAR)


def render_into_canvas(src: Image.Image, canvas_size: Tuple[int, int],
                       fit: FitMode, bar_style: BarStyle,
                       bar_color: str = "#000000",
                       crop: Optional[CropRect] = None) -> Image.Image:
    """Composite `src` (already transformed/cropped by caller when needed)
    onto a canvas of `canvas_size` honouring the fit mode. Returns RGB image.
    """
    cw, ch = canvas_size
    sw, sh = src.size
    src = src.convert("RGBA")

    if fit == FitMode.FILL or (fit == FitMode.CENTER and sw >= cw and sh >= ch):
        # cover: scale so the image covers the canvas, then centre-crop
        scale = max(cw / sw, ch / sh)
        nw, nh = max(cw, round(sw * scale)), max(ch, round(sh * scale))
        if fit == FitMode.CENTER:
            nw, nh = sw, sh  # no scaling for center mode
        resized = src.resize((nw, nh), Image.LANCZOS) if (nw, nh) != (sw, sh) else src
        ox = (nw - cw) // 2
        oy = (nh - ch) // 2
        canvas = Image.new("RGB", canvas_size, bar_color)
        canvas.paste(resized.crop((ox, oy, ox + cw, oy + ch)).convert("RGB"), (0, 0))
        return canvas

    if fit == FitMode.STRETCH:
        return src.resize(canvas_size, Image.LANCZOS).convert("RGB")

    # FIT (contain) and CENTER-with-padding share this path: keep native AR
    if fit == FitMode.CENTER:
        scale = 1.0
    else:
        scale = min(cw / sw, ch / sh)
    nw = max(1, round(sw * scale))
    nh = max(1, round(sh * scale))
    resized = src.resize((nw, nh), Image.LANCZOS) if (nw, nh) != (sw, sh) else src

    if bar_style == BarStyle.BLUR:
        canvas = _blur_backdrop(src, canvas_size)
    else:
        color = {"black": "#000000", "white": "#ffffff"}.get(bar_style.value, bar_color)
        canvas = Image.new("RGB", canvas_size, color)

    px = (cw - nw) // 2
    py = (ch - nh) // 2
    canvas.paste(resized.convert("RGB"), (px, py))
    return canvas


def render_monitor_wallpaper(source_path_or_image,
                             monitor_size: Tuple[int, int],
                             transform: Transform,
                             crop: CropRect,
                             fit: FitMode,
                             bar_style: BarStyle = BarStyle.BLACK,
                             bar_color: str = "#000000") -> Image.Image:
    """Full pipeline: load -> rotate/flip -> crop -> fit into monitor size."""
    if isinstance(source_path_or_image, str):
        img = Image.open(source_path_or_image)
        img.load()
    else:
        img = source_path_or_image

    img = apply_transform(img, transform)
    cropped = crop_image(img, crop)
    return render_into_canvas(cropped, monitor_size, fit, bar_style, bar_color)


def make_virtual_desktop_image(per_monitor: list[Tuple["object", Image.Image]],
                               virtual_size: Tuple[int, int],
                               offset: Tuple[int, int]) -> Image.Image:
    """Stitch per-monitor renders into one big desktop bitmap (the classic
    Windows trick for different wallpapers per screen)."""
    vw, vh = virtual_size
    ox, oy = offset
    canvas = Image.new("RGB", (vw, vh), "#000000")
    for mon, im in per_monitor:
        canvas.paste(im, (mon.left - ox, mon.top - oy))
    return canvas


# -------------------------------------------------------------- presets
ASPECT_PRESETS: dict[str, Optional[float]] = {
    "Free": None,
    "Screen": -1,               # sentinel: use current monitor aspect
    "16:9": 16 / 9,
    "16:10": 16 / 10,
    "4:3": 4 / 3,
    "21:9": 21 / 9,
    "1:1": 1.0,
    "9:16": 9 / 16,
}


def preset_aspect(name: str, monitor_aspect: float) -> Optional[float]:
    v = ASPECT_PRESETS.get(name)
    if v is None:
        return None
    if v == -1:
        return monitor_aspect
    return v
