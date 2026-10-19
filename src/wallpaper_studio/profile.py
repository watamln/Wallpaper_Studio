"""
profile.py - Per-monitor editing state + persistence.

A `MonitorProfile` holds everything needed to reproduce one monitor's
wallpaper render: source path, transform, crop, fit mode, bar style.
`AppProfile` maps monitor-index -> profile and is saved as JSON so your
layouts survive restarts (keyed by device name with index fallback).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Dict, Optional

from .image_pipeline import BarStyle, CropRect, FitMode, Transform

APP_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")),
                       "WallpaperStudio")
PROFILE_PATH = os.path.join(APP_DIR, "profile.json")


@dataclass
class MonitorProfile:
    source_path: str = ""
    transform: Transform = field(default_factory=Transform)
    crop: CropRect = field(default_factory=CropRect)
    fit: FitMode = FitMode.FILL
    bar_style: BarStyle = BarStyle.BLACK
    bar_color: str = "#000000"
    # cached source pixel size after transform (for UI layout only)
    src_w: int = 0
    src_h: int = 0

    def copy(self) -> "MonitorProfile":
        return MonitorProfile(self.source_path, self.transform, self.crop,
                              self.fit, self.bar_style, self.bar_color,
                              self.src_w, self.src_h)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["fit"] = self.fit.value
        d["bar_style"] = self.bar_style.value
        return d

    @staticmethod
    def from_dict(d: dict) -> "MonitorProfile":
        return MonitorProfile(
            source_path=d.get("source_path", ""),
            transform=Transform(**d.get("transform", {})),
            crop=CropRect(**d.get("crop", {})),
            fit=FitMode(d.get("fit", "fill")),
            bar_style=BarStyle(d.get("bar_style", "black")),
            bar_color=d.get("bar_color", "#000000"),
            src_w=d.get("src_w", 0),
            src_h=d.get("src_h", 0),
        )


@dataclass
class AppProfile:
    monitors: Dict[str, MonitorProfile] = field(default_factory=dict)
    # global default used when a new monitor appears without saved state
    last_image_dir: str = ""

    def get(self, key: str) -> MonitorProfile:
        return self.monitors.setdefault(key, MonitorProfile())

    def set(self, key: str, prof: MonitorProfile) -> None:
        self.monitors[key] = prof

    # ---------------- persistence
    @classmethod
    def load(cls, path: str = PROFILE_PATH) -> "AppProfile":
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            mons = {k: MonitorProfile.from_dict(v)
                    for k, v in raw.get("monitors", {}).items()}
            return cls(monitors=mons, last_image_dir=raw.get("last_image_dir", ""))
        except Exception:
            return cls()

    def save(self, path: str = PROFILE_PATH) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        raw = {"monitors": {k: v.to_dict() for k, v in self.monitors.items()},
               "last_image_dir": self.last_image_dir}
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(raw, f, indent=2)
        os.replace(tmp, path)
