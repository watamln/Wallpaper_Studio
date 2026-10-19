"""
crop_canvas.py - CustomTkinter canvas implementing the Android-style
interactive crop box over the source image.

Features
--------
* Displays the (rotated/flipped) source image scaled to fit the canvas.
* A draggable / resizable crop rectangle, locked to a chosen aspect ratio
  (or free).  Handles at corners + edge midpoints.
* Dimmed mask outside the crop rect, rule-of-thirds grid inside.
* Pan: drag *inside* the crop rect to move it.  Zoom via mouse wheel
  changes the crop size (respecting the aspect lock), centred on the
  pointer - like pinch-zoom on a phone.
* Emits normalized CropRect through a callback whenever it changes.
"""
from __future__ import annotations

import tkinter as tk
from typing import Callable, Optional

from .image_pipeline import CropRect

MIN_FRAC = 0.05   # smallest crop as fraction of image


class CropCanvas(tk.Canvas):
    def __init__(self, master, width: int, height: int,
                 on_change: Optional[Callable[[CropRect], None]] = None,
                 bg: str = "#101014"):
        super().__init__(master, width=width, height=height, bg=bg,
                         highlightthickness=0, bd=0)
        self.on_change = on_change
        self._img: Optional[tk.PhotoImage] = None      # displayed photo
        self._img_w = self._img_h = 0                  # displayed px size
        self._aspect_lock: Optional[float] = None      # w/h or None=free
        self._crop = CropRect(0, 0, 1, 1)              # normalized
        self._drag_mode: Optional[str] = None          # 'move','nw',...
        self._drag_start = (0, 0)
        self._start_crop = CropRect()
        self._box_id = self.create_rectangle(0, 0, 0, 0, outline="#2cc97c",
                                             width=2, tags="crop")
        self._grid_ids = []
        self._mask_ids = [self.create_rectangle(0, 0, 0, 0, fill="#000000",
                                                stipple="gray50", outline="",
                                                tags="mask") for _ in range(4)]
        self._handle_ids = {}
        for name in ("nw", "ne", "sw", "se", "n", "s", "e", "w"):
            hid = self.create_rectangle(0, 0, 0, 0, fill="#2cc97c",
                                        outline="#0b3d22", tags="handle")
            self._handle_ids[name] = hid

        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_motion)
        self.bind("<ButtonRelease-1>", lambda e: self._end_drag())
        self.bind("<MouseWheel>", self._on_wheel)          # windows
        self.bind("<Button-4>", lambda e: self._on_wheel_delta(e, 1))
        self.bind("<Button-5>", lambda e: self._on_wheel_delta(e, -1))
        self.bind("<Configure>", lambda e: self._redraw())

    # ----------------------------------------------------------- public API
    def set_image(self, pil_image):
        """Scale-to-fit `pil_image` into the canvas and show it."""
        from PIL import Image, ImageTk
        cw, ch = self.winfo_width(), self.winfo_height()
        cw, ch = max(cw, 50), max(ch, 50)
        im = pil_image.convert("RGBA")
        scale = min(cw / im.width, ch / im.height)
        nw, nh = max(1, round(im.width * scale)), max(1, round(im.height * scale))
        self._disp_pil = im.resize((nw, nh))
        self._img = ImageTk.PhotoImage(self._disp_pil)
        self._img_w, self._img_h = nw, nh
        # centre the image inside canvas
        self._ox = (cw - nw) // 2
        self._oy = (ch - nh) // 2
        self.delete("srcimg")
        self.create_image(self._ox, self._oy, anchor="nw", image=self._img,
                          tags="srcimg")
        self.tag_lower("srcimg")
        self.tag_raise("mask")
        self._redraw()

    def set_aspect(self, aspect: Optional[float]):
        """Lock crop to `aspect` (w/h); re-centre the biggest allowed box."""
        self._aspect_lock = aspect
        if aspect is not None:
            self._fit_crop_to_aspect()
        self._redraw()

    def set_crop(self, crop: CropRect):
        self._crop = crop.clamped()
        self._redraw()

    @property
    def crop(self) -> CropRect:
        return self._crop

    # ----------------------------------------------------------- geometry
    def _norm_to_canvas(self, c: CropRect):
        x0 = self._ox + c.x * self._img_w
        y0 = self._oy + c.y * self._img_h
        x1 = self._ox + (c.x + c.w) * self._img_w
        y1 = self._oy + (c.y + c.h) * self._img_h
        return x0, y0, x1, y1

    def _canvas_to_norm(self, x: float, y: float):
        nx = (x - self._ox) / self._img_w if self._img_w else 0
        ny = (y - self._oy) / self._img_h if self._img_h else 0
        return nx, ny

    def _fit_crop_to_aspect(self):
        assert self._aspect_lock is not None
        img_ar = (self._img_w / self._img_h) if self._img_h else 1.0
        ar = self._aspect_lock * img_ar  # normalized-space aspect
        cur = self._crop
        # shrink whichever dimension is too big
        if cur.w / cur.h > ar:
            w = cur.h * ar
            x = cur.x + (cur.w - w) / 2
            self._crop = CropRect(x, cur.y, w, cur.h)
        else:
            h = cur.w / ar
            y = cur.y + (cur.h - h) / 2
            self._crop = CropRect(cur.x, y, cur.w, h)
        self._crop = self._crop.clamped()

    # ----------------------------------------------------------- events
    HANDLE_R = 6

    def _hit_test(self, x, y) -> Optional[str]:
        x0, y0, x1, y1 = self._norm_to_canvas(self._crop)
        r = self.HANDLE_R + 3
        tests = {
            "nw": (x0, y0), "ne": (x1, y0), "sw": (x0, y1), "se": (x1, y1),
            "n": ((x0 + x1) / 2, y0), "s": ((x0 + x1) / 2, y1),
            "w": (x0, (y0 + y1) / 2), "e": (x1, (y0 + y1) / 2),
        }
        for name, (hx, hy) in tests.items():
            if abs(x - hx) <= r and abs(y - hy) <= r:
                return name
        if x0 < x < x1 and y0 < y < y1:
            return "move"
        return None

    def _on_press(self, e):
        mode = self._hit_test(e.x, e.y)
        if mode is None:
            # start a brand-new crop by dragging? keep simple: ignore
            return
        self._drag_mode = mode
        self._drag_start = (e.x, e.y)
        self._start_crop = self._crop

    def _on_motion(self, e):
        if not self._drag_mode or not self._img_w:
            return
        dx_n = (e.x - self._drag_start[0]) / self._img_w
        dy_n = (e.y - self._drag_start[1]) / self._img_h
        s = self._start_crop
        if self._drag_mode == "move":
            new = CropRect(s.x + dx_n, s.y + dy_n, s.w, s.h).clamped()
        else:
            new = self._resize(s, self._drag_mode, dx_n, dy_n)
            if self._aspect_lock is not None:
                new = self._resize_locked(s, self._drag_mode, dx_n, dy_n)
            new = new.clamped()
        self._crop = new
        self._redraw(notify=True)

    def _resize(self, s: CropRect, handle: str, dx: float, dy: float) -> CropRect:
        x0, y0, x1, y1 = s.x, s.y, s.x + s.w, s.y + s.h
        if "w" in handle: x0 = min(x0 + dx, x1 - MIN_FRAC)
        if "e" in handle: x1 = max(x1 + dx, x0 + MIN_FRAC)
        if "n" in handle: y0 = min(y0 + dy, y1 - MIN_FRAC)
        if "s" in handle: y1 = max(y1 + dy, y0 + MIN_FRAC)
        return CropRect(x0, y0, x1 - x0, y1 - y0)

    def _resize_locked(self, s: CropRect, handle: str, dx: float, dy: float) -> CropRect:
        """Resize keeping aspect; anchor is the opposite corner/edge."""
        ar = self._aspect_lock * (self._img_w / self._img_h) if self._img_h else 1
        # choose dominant delta
        d = dx if abs(dx) >= abs(dy) else dy
        if handle in ("e", "se", "ne"):
            w = max(MIN_FRAC, min(s.x + s.w + d, 1.0) - s.x)
        elif handle in ("w", "sw", "nw"):
            right = s.x + s.w
            left = max(0.0, min(s.x + d, right - MIN_FRAC))
            w = right - left
            s = CropRect(left, s.y, w, s.h)
        elif handle in ("n",):
            bottom = s.y + s.h
            top = max(0.0, min(s.y + d, bottom - MIN_FRAC))
            h = bottom - top
            w = h * ar
            return CropRect(s.x + (s.w - w) / 2, top, w, h)
        elif handle in ("s",):
            h = max(MIN_FRAC, min(s.h + d, 1.0 - s.y))
            w = h * ar
            return CropRect(s.x + (s.w - w) / 2, s.y, w, h)
        else:  # corner e/se/w/sw handled partially above; unify:
            w = s.w + (d if handle in ("e", "se", "ne") else -d)
            w = max(MIN_FRAC, min(w, 1.0 - s.x if handle != "nw" else 1.0))
        if handle in ("nw", "sw", "w"):
            pass
        h = w / ar
        # vertical clamp
        if handle.endswith("e") or handle in ("e", "se", "ne"):
            cy = s.y + s.h / 2
        else:
            cy = s.y + s.h / 2
        y0 = max(0.0, min(cy - h / 2, 1.0 - h))
        x0 = s.x if handle in ("e", "se", "ne") else max(0.0, min(s.x + s.w - w, 1.0 - w))
        return CropRect(x0, y0, w, h)

    def _on_wheel(self, e):
        factor = 1.1 if e.delta > 0 else 1 / 1.1
        self._zoom_at(e.x, e.y, factor)

    def _on_wheel_delta(self, e, sign):
        self._zoom_at(e.x, e.y, 1.1 if sign > 0 else 1 / 1.1)

    def _zoom_at(self, cx: float, cy: float, factor: float):
        if not self._img_w:
            return
        nx, ny = self._canvas_to_norm(cx, cy)
        s = self._crop
        nw = min(1.0, max(MIN_FRAC, s.w * factor))
        nh = nw / (s.aspect) if self._aspect_lock is None else nw / (
            self._aspect_lock * (self._img_w / self._img_h))
        nh = min(1.0, max(MIN_FRAC, nh))
        # keep pointer anchored inside the crop
        fx = 0.5 if s.w == 0 else (nx - s.x) / s.w
        fy = 0.5 if s.h == 0 else (ny - s.y) / s.h
        x0 = min(max(nx - fx * nw, 0.0), 1.0 - nw)
        y0 = min(max(ny - fy * nh, 0.0), 1.0 - nh)
        self._crop = CropRect(x0, y0, nw, nh)
        self._redraw(notify=True)

    def _end_drag(self):
        self._drag_mode = None

    # ----------------------------------------------------------- drawing
    def _redraw(self, notify: bool = False):
        if not self._img_w:
            return
        x0, y0, x1, y1 = self._norm_to_canvas(self._crop)
        cw, ch = self.winfo_width(), self.winfo_height()
        self.coords(self._box_id, x0, y0, x1, y1)
        # masks: top, bottom, left, right regions outside crop
        ix0, iy0 = self._ox, self._oy
        ix1, iy1 = self._ox + self._img_w, self._oy + self._img_h
        t, b, l, r = self._mask_ids
        self.coords(t, ix0, iy0, ix1, y0)
        self.coords(b, ix0, y1, ix1, iy1)
        self.coords(l, ix0, y0, x0, y1)
        self.coords(r, x1, y0, ix1, y1)
        # handles
        hr = self.HANDLE_R
        pts = {"nw": (x0, y0), "ne": (x1, y0), "sw": (x0, y1), "se": (x1, y1),
               "n": ((x0 + x1) / 2, y0), "s": ((x0 + x1) / 2, y1),
               "w": (x0, (y0 + y1) / 2), "e": (x1, (y0 + y1) / 2)}
        for name, hid in self._handle_ids.items():
            hx, hy = pts[name]
            self.coords(hid, hx - hr, hy - hr, hx + hr, hy + hr)
        # thirds grid
        for gid in self._grid_ids:
            self.delete(gid)
        self._grid_ids = []
        for i in (1, 2):
            gx0, gy0, gx1, gy1 = x0, y0 + i * (y1 - y0) / 3, x1, y0 + i * (y1 - y0) / 3
            self._grid_ids.append(self.create_line(gx0, gy0, gx1, gy1,
                                                   fill="#ffffff55"[:7], dash="."))
            vx, vy0, vy1 = x0 + i * (x1 - x0) / 3, y0, y1
            self._grid_ids.append(self.create_line(vx, vy0, vx, vy1,
                                                   fill="#ffffff"[:7], dash="."))
        if notify and self.on_change:
            self.on_change(self._crop)
