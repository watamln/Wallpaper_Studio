"""Tests for the pure image pipeline (runnable on any OS)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PIL import Image  # noqa: E402

from wallpaper_studio.image_pipeline import (  # noqa: E402
    BarStyle, CropRect, FitMode, Transform,
    apply_transform, crop_image, crop_pixel_aspect, default_crop_for_aspect,
    make_virtual_desktop_image, render_into_canvas, render_monitor_wallpaper)


def solid(w, h, color):
    return Image.new("RGB", (w, h), color)


class TestCropRect(unittest.TestCase):
    def test_clamp(self):
        c = CropRect(-0.2, 0.5, 1.4, 1.2).clamped()
        self.assertGreaterEqual(c.x, 0.0)
        self.assertLessEqual(c.x + c.w, 1.0 + 1e-9)
        self.assertLessEqual(c.y + c.h, 1.0 + 1e-9)

    def test_scaled_to(self):
        l, t, r, b = CropRect(0.25, 0.25, 0.5, 0.5).scaled_to(100, 200)
        self.assertEqual((l, t, r, b), (25, 50, 75, 150))

    def test_default_crop_wider_source(self):
        # source 2000x1000 (AR 2.0) target 16/9 -> full height, trimmed width
        c = default_crop_for_aspect(2000, 1000, 16 / 9)
        self.assertAlmostEqual(c.h, 1.0, places=6)
        self.assertLess(c.w, 1.0)
        img = solid(2000, 1000, "red")
        self.assertAlmostEqual(crop_pixel_aspect(img, c), 16 / 9, places=2)

    def test_default_crop_taller_source(self):
        c = default_crop_for_aspect(1000, 2000, 16 / 9)
        self.assertAlmostEqual(c.w, 1.0, places=6)
        img = solid(1000, 2000, "red")
        self.assertAlmostEqual(crop_pixel_aspect(img, c), 16 / 9, places=2)


class TestTransforms(unittest.TestCase):
    def test_rotate_90_swaps_size(self):
        img = solid(200, 100, "red")
        out = apply_transform(img, Transform(rotation_deg=90))
        self.assertEqual(out.size, (100, 200))

    def test_flip_h_moves_pixels(self):
        img = Image.new("RGB", (2, 1))
        img.putpixel((0, 0), (255, 0, 0)); img.putpixel((1, 0), (0, 0, 255))
        out = apply_transform(img, Transform(flip_h=True))
        self.assertEqual(out.getpixel((0, 0)), (0, 0, 255))  # blue now left

    def test_flip_v(self):
        img = Image.new("RGB", (1, 2))
        img.putpixel((0, 0), (255, 0, 0)); img.putpixel((0, 1), (0, 0, 255))
        out = apply_transform(img, Transform(flip_v=True))
        self.assertEqual(out.getpixel((0, 0))[2], 255)

    def test_double_flip_identity(self):
        img = solid(30, 20, (12, 200, 55))
        t = Transform(flip_h=True, flip_v=True)
        once = apply_transform(img, t)
        twice = apply_transform(once, t)
        self.assertEqual(list(twice.getdata()), list(img.getdata()))


class TestFitModes(unittest.TestCase):
    def setUp(self):
        # tall narrow source into wide monitor
        self.src = solid(400, 1000, (10, 200, 10))

    def test_fill_covers_and_crops(self):
        out = render_into_canvas(self.src, (800, 600), FitMode.FILL, BarStyle.BLACK)
        self.assertEqual(out.size, (800, 600))
        # entire canvas should be the image colour (no bars)
        self.assertEqual(set(out.convert("RGB").getdata()), {(10, 200, 10)})

    def test_fit_adds_bars(self):
        out = render_into_canvas(self.src, (800, 600), FitMode.FIT, BarStyle.BLACK)
        self.assertEqual(out.size, (800, 600))
        colors = set(out.convert("RGB").getdata())
        self.assertIn((0, 0, 0), colors)      # black bars present
        self.assertIn((10, 200, 10), colors)  # image present
        # white bars option
        out2 = render_into_canvas(self.src, (800, 600), FitMode.FIT, BarStyle.WHITE)
        self.assertIn((255, 255, 255), set(out2.convert("RGB").getdata()))

    def test_stretch_distorts(self):
        out = render_into_canvas(self.src, (800, 600), FitMode.STRETCH, BarStyle.BLACK)
        self.assertEqual(out.size, (800, 600))
        self.assertEqual(set(out.convert("RGB").getdata()), {(10, 200, 10)})

    def test_center_small_image_pads(self):
        small = solid(100, 100, (5, 5, 200))
        out = render_into_canvas(small, (400, 300), FitMode.CENTER, BarStyle.BLACK)
        self.assertEqual(out.size, (400, 300))
        self.assertEqual(out.getpixel((0, 0)), (0, 0, 0))       # padded
        self.assertEqual(out.getpixel((200, 150)), (5, 5, 200))  # centred

    def test_blur_backdrop(self):
        out = render_into_canvas(self.src, (800, 600), FitMode.FIT, BarStyle.BLUR)
        self.assertEqual(out.size, (800, 600))
        # corner pixel is a blurred tint of the image, not pure black
        self.assertNotEqual(out.getpixel((0, 0)), (0, 0, 0))


class TestPipeline(unittest.TestCase):
    def test_full_render_matches_monitor_size(self):
        img = solid(3000, 2000, "blue")
        out = render_monitor_wallpaper(
            img, (2560, 1440), Transform(rotation_deg=90),
            default_crop_for_aspect(2000, 3000, 2560 / 1440), FitMode.FILL)
        self.assertEqual(out.size, (2560, 1440))

    def test_crop_selects_right_half(self):
        img = Image.new("RGB", (200, 100))
        for x in range(200):
            col = (255, 0, 0) if x < 100 else (0, 255, 0)
            for y in range(100):
                img.putpixel((x, y), col)
        cropped = crop_image(img, CropRect(0.5, 0, 0.5, 1))
        self.assertEqual(cropped.size, (100, 100))
        self.assertEqual(set(cropped.convert("RGB").getdata()), {(0, 255, 0)})

    def test_virtual_desktop_stitch(self):
        class M:  # minimal duck-typed monitor
            def __init__(self, l, t, w, h):
                self.left, self.top, self.width, self.height = l, t, w, h
        m1, m2 = M(0, 0, 100, 50), M(100, 0, 150, 90)
        i1, i2 = solid(100, 50, "red"), solid(150, 90, "blue")
        out = make_virtual_desktop_image([(m1, i1), (m2, i2)], (250, 90), (0, 0))
        self.assertEqual(out.size, (250, 90))
        self.assertEqual(out.getpixel((10, 10)), (255, 0, 0))
        self.assertEqual(out.getpixel((200, 60)), (0, 0, 255))
        self.assertEqual(out.getpixel((10, 70)), (0, 0, 0))  # uncovered gap


if __name__ == "__main__":
    unittest.main(verbosity=2)
