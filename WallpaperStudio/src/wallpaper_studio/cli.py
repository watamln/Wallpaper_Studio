"""
cli.py - Command line interface (handy for scripting & headless testing).

Examples
--------
# same image on every monitor, cropped to fill each screen:
python -m wallpaper_studio.cli set photo.jpg --mode all --fit fill

# one image stretched across both screens (span):
python -m wallpaper_studio.cli set ultrawide.jpg --mode span

# different image per monitor:
python -m wallpaper_studio.cli set-multi a.png --monitor 0 \
        b.png --monitor 1 --apply

# rotate/flip/crop then preview-only render to a file:
python -m wallpaper_studio.cli render photo.jpg --monitor 0 --rotate 90 \
        --flip-h --crop 0.1,0.0,0.8,1.0 --fit fit --bars blur -o out.png

python -m wallpaper_studio.cli monitors     # list screens
"""
from __future__ import annotations

import argparse
import sys
from typing import List

from PIL import Image

from .image_pipeline import (BarStyle, CropRect, FitMode, Transform,
                             apply_transform, crop_image,
                             default_crop_for_aspect, render_into_canvas)
from .monitors import get_monitors
from .setter import apply_per_monitor, apply_single, save_wallpaper_bmp


def _parse_crop(s: str) -> CropRect:
    try:
        x, y, w, h = (float(v) for v in s.split(","))
        return CropRect(x, y, w, h).clamped()
    except Exception:
        raise argparse.ArgumentTypeError("crop must be 'x,y,w,h' normalized floats")


def _render(img_path: str, mon, transform: Transform, crop: CropRect | None,
            fit: FitMode, bars: BarStyle) -> Image.Image:
    src = Image.open(img_path)
    src.load()
    src = apply_transform(src, transform)
    if crop is None:
        crop = default_crop_for_aspect(src.width, src.height, mon.aspect)
    cropped = crop_image(src, crop)
    return render_into_canvas(cropped, (mon.width, mon.height), fit, bars)


def cmd_monitors(_args):
    from .monitors import describe
    print(describe())
    return 0


def cmd_set(args):
    mons = get_monitors()
    t = Transform(rotation_deg=args.rotate % 360, flip_h=args.flip_h,
                  flip_v=args.flip_v)
    crop = args.crop if isinstance(args.crop, CropRect) else (
        _parse_crop(args.crop) if args.crop else None)
    fit = FitMode(args.fit)
    bars = BarStyle(args.bars)

    if args.mode == "span":
        # single image scaled to whole virtual desktop
        min_x = min(m.left for m in mons); min_y = min(m.top for m in mons)
        vw = max(m.right for m in mons) - min_x
        vh = max(m.bottom for m in mons) - min_y
        img = _render(args.image, type("S", (), {"aspect": vw / vh, "width": vw,
                                                 "height": vh})(), t, crop, fit, bars)
        res = apply_single(img, "span" if len(mons) > 1 else "fill", "spanned")
    else:
        pairs = [(m, _render(args.image, m, t, crop, fit, bars)) for m in mons]
        res = apply_per_monitor(pairs, mons)
    print(("OK " if res.ok else "FAIL ") + "; ".join(res.paths) +
          (" " + res.message if res.message else ""))
    return 0 if res.ok else 1


def cmd_set_multi(args):
    """--monitor IDX path --monitor IDX path ..."""
    mons = {m.index: m for m in get_monitors()}
    pairs = []
    it = iter(args.pairs)
    for idx_s, path in zip(it, it):
        idx = int(idx_s)
        if idx not in mons:
            print(f"unknown monitor index {idx}", file=sys.stderr); return 2
        m = mons[idx]
        t = Transform(rotation_deg=args.rotate % 360, flip_h=args.flip_h,
                      flip_v=args.flip_v)
        pairs.append((m, _render(path, m, t, None, FitMode(args.fit),
                                 BarStyle(args.bars))))
    if not pairs:
        print("nothing to do", file=sys.stderr); return 2
    if args.apply:
        res = apply_per_monitor(pairs, get_monitors())
        print(("OK " if res.ok else "FAIL ") + "; ".join(res.paths))
        return 0 if res.ok else 1
    for m, img in pairs:
        p = save_wallpaper_bmp(img, f"preview_m{m.index}")
        print(f"monitor {m.index}: {p}")
    return 0


def cmd_render(args):
    mons = {m.index: m for m in get_monitors()}
    m = mons.get(args.monitor or 0)
    if m is None:
        print("bad monitor", file=sys.stderr); return 2
    t = Transform(rotation_deg=args.rotate % 360, flip_h=args.flip_h,
                  flip_v=args.flip_v)
    img = _render(args.image, m, t,
                  args.crop if isinstance(args.crop, CropRect) else (
                      _parse_crop(args.crop) if args.crop else None),
                  FitMode(args.fit), BarStyle(args.bars))
    out = args.output or f"wallpaper_m{m.index}.png"
    img.save(out)
    print(out)
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="wallpaper-studio",
                                description="Crop/preview/set wallpapers on Windows")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("monitors", help="list detected monitors"); sp.set_defaults(fn=cmd_monitors)

    def common(pp):
        pp.add_argument("--fit", choices=[f.value for f in FitMode], default="fill")
        pp.add_argument("--bars", choices=[b.value for b in BarStyle], default="black")
        pp.add_argument("--rotate", type=int, default=0)
        pp.add_argument("--flip-h", action="store_true")
        pp.add_argument("--flip-v", action="store_true")

    sp = sub.add_parser("set", help="same image on all monitors")
    sp.add_argument("image"); sp.add_argument("--mode", choices=["all", "span"], default="all")
    sp.add_argument("--crop", type=_parse_crop, default=None)
    common(sp); sp.set_defaults(fn=cmd_set)

    sp = sub.add_parser("set-multi", help="different image per monitor")
    sp.add_argument("pairs", nargs="*", metavar="MONITOR INDEX IMAGE PATH")
    sp.add_argument("--apply", action="store_true", help="actually set it (else preview files)")
    common(sp); sp.set_defaults(fn=cmd_set_multi)

    sp = sub.add_parser("render", help="render preview to a PNG file")
    sp.add_argument("image"); sp.add_argument("--monitor", type=int, default=0)
    sp.add_argument("--crop", type=_parse_crop, default=None)
    sp.add_argument("-o", "--output")
    common(sp); sp.set_defaults(fn=cmd_render)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
