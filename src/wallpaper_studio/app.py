"""
app.py - Wallpaper Studio main window (CustomTkinter).

Layout
------
+------------------------------------------------------------------+
| [Open Image]   filename...                       Monitor tabs:    |
|                                                                  |
|  +------------------------+   +--------------------------------+ |
|  |   CROP / PAN CANVAS    |   |     LIVE PREVIEW (per screen)  | |
|  |  (Android-style box)   |   |  monitor mockups with taskbar  | |
|  +------------------------+   +--------------------------------+ |
|                                                                  |
|  Fit: (fill)(fit)(stretch)(center)   Bars: (black)(white)(blur)  |
|  Aspect: [Screen v]  Rotate [90ccw][90cw][180] Flip [H][V]       |
|  [Reset crop]                          [SET WALLPAPER]           |
+------------------------------------------------------------------+
"""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import Dict, List, Optional

import customtkinter as ctk
from PIL import Image

from .crop_canvas import CropCanvas
from .image_pipeline import (ASPECT_PRESETS, BarStyle, CropRect, FitMode,
                             Transform, apply_transform, default_crop_for_aspect,
                             preset_aspect, render_into_canvas,
                             render_monitor_wallpaper)
from .monitors import MonitorInfo, get_monitors
from .profile import AppProfile, MonitorProfile
from .setter import ApplyResult, apply_per_monitor, apply_single, save_wallpaper_bmp

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tiff")


def profile_key(m: MonitorInfo, all_monitors: List[MonitorInfo]) -> str:
    """Stable-ish key per monitor: device name first, geometry fallback."""
    return m.name or f"{m.left}x{m.top}x{m.width}x{m.height}"


class PreviewPanel(ctk.CTkFrame):
    """Draws scaled mock-ups of each monitor showing exactly what will land
    on that screen, arranged in their real relative positions."""

    def __init__(self, master, max_w=520, max_h=430):
        super().__init__(master, fg_color="#1b1b22")
        self.max_w, self.max_h = max_w, max_h
        self.canvas = tk.Canvas(self, bg="#1b1b22", highlightthickness=0,
                                width=max_w, height=max_h)
        self.canvas.pack(fill="both", expand=True, padx=6, pady=6)
        self._photos: List = []

    def update_preview(self, monitors: List[MonitorInfo],
                      renders: Dict[int, Image.Image],
                      selected: int):
        c = self.canvas
        c.delete("all")
        self._photos.clear()
        if not monitors:
            return
        min_x = min(m.left for m in monitors)
        min_y = min(m.top for m in monitors)
        vw = max(m.right for m in monitors) - min_x
        vh = max(m.bottom for m in monitors) - min_y
        scale = min(self.max_w / vw, self.max_h / vh)
        ox = (self.max_w - vw * scale) / 2
        oy = (self.max_h - vh * scale) / 2

        for m in monitors:
            x0 = ox + (m.left - min_x) * scale
            y0 = oy + (m.top - min_y) * scale
            x1 = x0 + m.width * scale
            y1 = y0 + m.height * scale
            img = renders.get(m.index)
            if img is not None:
                pw, ph = max(1, int(x1 - x0)), max(1, int(y1 - y0))
                disp = img.convert("RGB").resize((pw, ph))
                photo = _photo(disp)
                self._photos.append(photo)
                c.create_image(x0, y0, anchor="nw", image=photo, tags="wall")
            border = "#2cc97c" if m.index == selected else "#555a66"
            bw = 3 if m.index == selected else 2
            c.create_rectangle(x0, y0, x1, y1, outline=border, width=bw)
            label = f"M{m.index + 1}  {m.width}\u00d7{m.height}"
            c.create_text((x0 + x1) / 2, y1 + 12, text=label,
                          fill="#c9ccd6", font=("Segoe UI", 10))
        # connector line showing layout continuity
        c.create_text(self.max_w / 2, 8,
                      text="Desktop preview \u2014 what each screen will show",
                      fill="#8a8f9e", font=("Segoe UI", 9))


def _photo(im: Image.Image):
    from PIL import ImageTk
    return ImageTk.PhotoImage(im)


class AppWindow(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("green")
        self.title("Wallpaper Studio \u2014 crop, preview & set (multi-monitor)")
        self.geometry("1180x760")
        self.minsize(980, 640)

        self.monitors: List[MonitorInfo] = get_monitors()
        self.profile: AppProfile = AppProfile.load()
        self.selected: int = self.monitors[0].index if self.monitors else 0

        self.source_img: Optional[Image.Image] = None      # original
        self.transformed: Optional[Image.Image] = None     # after rotate/flip
        self.aspect_choice: str = "Screen"
        self._preview_job: Optional[str] = None

        self._build_ui()
        self._load_monitor_state()
        self.after(120, self._refresh_all)

    # ------------------------------------------------------------- UI build
    def _build_ui(self):
        # ---- top bar
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=14, pady=(12, 4))

        ctk.CTkButton(top, text="Open Image\u2026", width=130,
                      command=self.open_image).pack(side="left")
        self.file_lbl = ctk.CTkLabel(top, text="no image loaded",
                                     text_color="#9aa0ae")
        self.file_lbl.pack(side="left", padx=10)

        # monitor selector
        self.seg = ctk.CTkSegmentedButton(top, values=[], command=self._select_monitor)
        self.seg.pack(side="right")
        self._update_monitor_buttons()

        # ---- middle: crop canvas | preview
        mid = ctk.CTkFrame(self, fg_color="transparent")
        mid.pack(fill="both", expand=True, padx=14, pady=6)
        mid.columnconfigure(0, weight=3)
        mid.columnconfigure(1, weight=2)
        mid.rowconfigure(0, weight=1)

        left = ctk.CTkFrame(mid)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        self.crop = CropCanvas(left, 640, 460, on_change=self._on_crop_change)
        self.crop.pack(fill="both", expand=True, padx=6, pady=6)
        ctk.CTkLabel(left, text="Drag the box to move \u00b7 drag handles to resize "
                                "\u00b7 mouse wheel = zoom crop",
                     text_color="#8a8f9e").pack(pady=(0, 4))

        right = ctk.CTkFrame(mid)
        right.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        self.preview = PreviewPanel(right)
        self.preview.pack(fill="both", expand=True)

        # ---- bottom toolbar
        bot = ctk.CTkFrame(self, fg_color="#202028")
        bot.pack(fill="x", padx=14, pady=(4, 12))

        row1 = ctk.CTkFrame(bot, fg_color="transparent")
        row1.pack(fill="x", padx=10, pady=(8, 2))
        ctk.CTkLabel(row1, text="Fit:").pack(side="left")
        self.fit_var = tk.StringVar(value=FitMode.FILL.value)
        for mode, txt in [(FitMode.FILL, "Fill (crop)"), (FitMode.FIT, "Fit (bars)"),
                          (FitMode.STRETCH, "Stretch"), (FitMode.CENTER, "Center")]:
            ctk.CTkRadioButton(row1, text=txt, variable=self.fit_var,
                               value=mode.value, command=self._on_fit_change)\
                .pack(side="left", padx=6)

        ctk.CTkLabel(row1, text="    Bars:").pack(side="left")
        self.bar_var = tk.StringVar(value=BarStyle.BLACK.value)
        for bs, txt in [(BarStyle.BLACK, "Black"), (BarStyle.WHITE, "White"),
                        (BarStyle.BLUR, "Blur")]:
            ctk.CTkRadioButton(row1, text=txt, variable=self.bar_var,
                               value=bs.value, command=self._debounced_refresh)\
                .pack(side="left", padx=4)

        row2 = ctk.CTkFrame(bot, fg_color="transparent")
        row2.pack(fill="x", padx=10, pady=(2, 8))
        ctk.CTkLabel(row2, text="Aspect:").pack(side="left")
        self.aspect_menu = ctk.CTkOptionMenu(row2, values=list(ASPECT_PRESETS.keys()),
                                             width=90, command=self._on_aspect)
        self.aspect_menu.set("Screen")
        self.aspect_menu.pack(side="left", padx=4)

        ctk.CTkButton(row2, text="\u21ba 90\u00b0", width=54,
                      command=lambda: self._rotate(-90)).pack(side="left", padx=(14, 2))
        ctk.CTkButton(row2, text="90\u00b0 \u21bb", width=54,
                      command=lambda: self._rotate(90)).pack(side="left", padx=2)
        ctk.CTkButton(row2, text="180\u00b0", width=54,
                      command=lambda: self._rotate(180)).pack(side="left", padx=2)
        ctk.CTkButton(row2, text="Flip H", width=64,
                      command=lambda: self._flip(True, False)).pack(side="left", padx=(14, 2))
        ctk.CTkButton(row2, text="Flip V", width=64,
                      command=lambda: self._flip(False, True)).pack(side="left", padx=2)
        ctk.CTkButton(row2, text="Reset crop", width=90,
                      fg_color="#3a3a45", command=self._reset_crop).pack(side="left", padx=(14, 2))

        ctk.CTkButton(row2, text="Apply to ALL monitors", width=150,
                      fg_color="#3a3a45", command=self._apply_all).pack(side="right")
        ctk.CTkButton(row2, text="SET WALLPAPER", width=170, height=34,
                      font=ctk.CTkFont(size=14, weight="bold"),
                      command=self._apply_selected).pack(side="right", padx=8)

        # status bar
        self.status = ctk.CTkLabel(self, text="", text_color="#9aa0ae", anchor="w")
        self.status.pack(fill="x", padx=16, pady=(0, 8))

    # ------------------------------------------------------- state helpers
    def _update_monitor_buttons(self):
        vals = [m.label for m in self.monitors]
        try:
            self.seg.configure(values=vals)
            if vals:
                self.seg.set(vals[self.selected])
        except Exception:
            pass

    def _cur(self) -> MonitorProfile:
        return self.profile.get(profile_key(self.monitors[self.selected], self.monitors))

    def _set_cur(self, prof: MonitorProfile):
        self.profile.set(profile_key(self.monitors[self.selected], self.monitors), prof)

    def _select_monitor(self, label: str):
        idx = [m.label for m in self.monitors].index(label)
        self.selected = self.monitors[idx].index
        self._load_monitor_state()
        self._refresh_all()

    def _load_monitor_state(self):
        prof = self._cur()
        self.fit_var.set(prof.fit.value)
        self.bar_var.set(prof.bar_style.value)
        if prof.source_path and os.path.isfile(prof.source_path):
            # (re)load only when switching to a profile with a different file
            if getattr(self, "source_path", None) != prof.source_path:
                self._set_source(prof.source_path, keep_crop=True)
            else:
                self._rebuild_transformed(keep_crop=True)
        # if the monitor has no image, leave whatever is loaded visible in
        # the editor but do NOT claim it belongs to this monitor.

    # --------------------------------------------------------- source mgmt
    def open_image(self):
        start = self.profile.last_image_dir or os.path.expanduser("~")
        path = filedialog.askopenfilename(
            title="Choose wallpaper image", initialdir=start,
            filetypes=[("Images", "*" + " *".join(IMAGE_EXTS)), ("All files", "*.*")])
        if not path:
            return
        self.profile.last_image_dir = os.path.dirname(path)
        self._set_source(path, keep_crop=False)
        # new image => sensible default crop for THIS monitor aspect
        self._auto_crop()
        self._refresh_all()
        self._save_profile()

    def _set_source(self, path: str, keep_crop: bool):
        try:
            img = Image.open(path)
            img.load()
        except Exception as e:
            messagebox.showerror("Cannot open image", str(e))
            return
        self.source_path = path
        self.source_img = img
        prof = self._cur()
        prof.source_path = path
        self._rebuild_transformed(keep_crop=keep_crop)
        self.file_lbl.configure(text=os.path.basename(path))

    def _rebuild_transformed(self, keep_crop: bool = True):
        if self.source_img is None:
            return
        prof = self._cur()
        self.transformed = apply_transform(self.source_img, prof.transform)
        prof.src_w, prof.src_h = self.transformed.size
        self.crop.set_image(self.transformed)
        if keep_crop:
            self.crop.set_crop(prof.crop)
        self._apply_aspect_lock()

    def _auto_crop(self):
        mon = self.monitors[self.selected]
        if self.transformed is None:
            return
        ar = preset_aspect(self.aspect_choice, mon.aspect) or mon.aspect
        prof = self._cur()
        prof.crop = default_crop_for_aspect(self.transformed.width,
                                            self.transformed.height, ar)
        self.crop.set_crop(prof.crop)

    # ------------------------------------------------------------ editing
    def _on_crop_change(self, crop: CropRect):
        self._cur().crop = crop
        self._debounced_refresh()

    def _on_fit_change(self):
        try:
            self._cur().fit = FitMode(self.fit_var.get())
        except ValueError:
            pass
        self._refresh_all()

    def _on_aspect(self, choice: str):
        self.aspect_choice = choice
        ar = preset_aspect(choice, self.monitors[self.selected].aspect)
        self.crop.set_aspect(ar)
        self._cur().crop = self.crop.crop
        self._refresh_all()

    def _rotate(self, deg: int):
        prof = self._cur()
        prof.transform = Transform(rotation_deg=(prof.transform.rotation_deg + deg) % 360,
                                   flip_h=prof.transform.flip_h,
                                   flip_v=prof.transform.flip_v)
        self._rebuild_transformed(keep_crop=True)
        self._refresh_all()

    def _flip(self, h: bool, v: bool):
        prof = self._cur()
        t = prof.transform
        prof.transform = Transform(t.rotation_deg,
                                   t.flip_h ^ h, t.flip_v ^ v)
        self._rebuild_transformed(keep_crop=True)
        self._refresh_all()

    def _reset_crop(self):
        self._auto_crop()
        self._refresh_all()

    def _apply_aspect_lock(self):
        ar = preset_aspect(self.aspect_choice, self.monitors[self.selected].aspect)
        self.crop.set_aspect(ar)

    # ---------------------------------------------------------- rendering
    def _render_for_monitor(self, m: MonitorInfo,
                            prof: Optional[MonitorProfile] = None
                            ) -> Optional[Image.Image]:
        """Render exactly what monitor `m` will show for profile `prof`.

        If the profile's source is the image currently loaded in the editor
        we reuse the live (already rotated/flipped) bitmap; otherwise we run
        the full pipeline from disk so other monitors can preview their own
        saved images.
        """
        from .image_pipeline import crop_image
        prof = prof or self._cur()
        if not prof.source_path:
            return None
        if (self.transformed is not None and self.source_path
                and prof.source_path == self.source_path):
            src = self.transformed
        else:
            try:
                img = Image.open(prof.source_path)
                img.load()
            except Exception:
                return None
            src = apply_transform(img, prof.transform)
        cropped = crop_image(src, prof.crop)
        return render_into_canvas(cropped, (m.width, m.height),
                                  prof.fit, prof.bar_style, prof.bar_color)

    def _refresh_all(self):
        renders: Dict[int, Image.Image] = {}
        cur_prof = self._cur()
        for m in self.monitors:
            key = profile_key(m, self.monitors)
            p = self.profile.monitors.get(key)
            # Each monitor previews its own saved profile when it has one;
            # otherwise it mirrors what you are editing right now.
            use_prof = p if p is not None else cur_prof
            im = self._render_for_monitor(m, use_prof)
            if im is not None:
                renders[m.index] = im
        self.preview.update_preview(self.monitors, renders, self.selected)
        self._update_status(renders)

    def _update_status(self, renders: Dict[int, Image.Image]):
        if not self.source_img:
            self.status.configure(text="Open an image to begin.")
            return
        m = self.monitors[self.selected]
        src_ar = (self.transformed.width / self.transformed.height
                  if self.transformed else 0)
        note = ""
        if abs(src_ar - m.aspect) > 0.01:
            note = (f"\u26a0 source AR {src_ar:.2f} \u2260 screen AR {m.aspect:.2f} "
                    f"\u2014 adjust crop box or choose Fill/Fit.")
        self.status.configure(
            text=f"Editing for {m.label} ({m.width}\u00d7{m.height}). {note}")

    def _debounced_refresh(self):
        if self._preview_job:
            self.after_cancel(self._preview_job)
        self._preview_job = self.after(80, self._refresh_all)

    # ------------------------------------------------------------- apply
    def _apply_selected(self):
        self._do_apply([self.selected])

    def _apply_all(self):
        self._do_apply([m.index for m in self.monitors])

    def _do_apply(self, indices: List[int]):
        if self.transformed is None:
            messagebox.showinfo("No image", "Open an image first.")
            return
        pairs = []
        for m in self.monitors:
            if m.index not in indices:
                continue
            key = profile_key(m, self.monitors)
            p = self.profile.monitors.get(key)
            # The monitor you are actively editing always uses the live
            # editor state; others use their own saved profiles.
            use = self._cur() if m.index == self.selected else (p or self._cur())
            img = self._render_for_monitor(m, use)
            if img is not None:
                pairs.append((m, img))
        if not pairs:
            return
        result: ApplyResult = apply_per_monitor(pairs, self.monitors)
        if result.ok:
            self._save_profile()
            where = "all monitors" if len(pairs) > 1 else f"monitor {pairs[0][0].index + 1}"
            self.status.configure(text=f"\u2714 Wallpaper applied to {where}. "
                                       f"(file: {os.path.basename(result.paths[0])})")
        else:
            messagebox.showerror("Failed to set wallpaper", result.message or
                                 "Windows refused the request.")

    def _save_profile(self):
        try:
            self.profile.save()
        except Exception as e:
            print("profile save failed:", e)


def run():
    app = AppWindow()
    app.mainloop()


if __name__ == "__main__":
    run()
