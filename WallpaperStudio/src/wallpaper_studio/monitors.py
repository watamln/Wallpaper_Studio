"""
monitors.py - Enumerate the physical monitors attached to the machine.

Returns simple dataclasses with *pixel* geometry (DPI-aware), device names,
and whether the monitor is primary / active.  On non-Windows systems a fake
two-monitor setup can be injected for testing (see `fake_monitors`).
"""
from __future__ import annotations

import ctypes
from dataclasses import dataclass, field
from typing import List, Optional

from . import win_api as W


@dataclass(frozen=True)
class MonitorInfo:
    index: int                  # 0-based order in the desktop layout
    name: str                   # e.g. "\\\\.\\DISPLAY1"
    device_string: str          # friendly path, e.g. "\\DISPLAY1"
    left: int                   # virtual-desktop pixel coords (can be negative)
    top: int
    width: int
    height: int
    is_primary: bool = False
    is_active: bool = True      # == attached & part of the desktop
    dpi: int = 96               # per-monitor DPI (best effort)

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    @property
    def aspect(self) -> float:
        return self.width / self.height if self.height else 1.0

    @property
    def label(self) -> str:
        star = " *" if self.is_primary else ""
        return f"Monitor {self.index + 1}{star}  {self.width}\u00d7{self.height}"

    def contains_point(self, x: int, y: int) -> bool:
        return self.left <= x < self.right and self.top <= y < self.bottom


# A module-level override used by tests / dry-run mode on other OSes.
_fake_monitors: Optional[List[MonitorInfo]] = None


def fake_monitors(monitors: Optional[List[MonitorInfo]]) -> None:
    """Install a synthetic monitor list (pass None to clear)."""
    global _fake_monitors
    _fake_monitors = monitors


def get_monitors() -> List[MonitorInfo]:
    """Return every monitor currently participating in the desktop."""
    if _fake_monitors is not None:
        return list(_fake_monitors)

    if not W.IS_WINDOWS:
        # Sensible default so previews still work off-Windows (tests/demos).
        return [
            MonitorInfo(0, r"\\.\DISPLAY1", "\\DISPLAY1", 0, 0, 1920, 1080,
                        is_primary=True),
            MonitorInfo(1, r"\\.\DISPLAY2", "\\DISPLAY2", 1920, 0, 2560, 1440),
        ]

    monitors: List[MonitorInfo] = []

    MONITOR_ENUM_PROC = ctypes.WINFUNCTYPE(
        ctypes.c_int,                 # BOOL callback return
        ctypes.c_void_p,              # hMonitor (HMONITOR)
        ctypes.c_void_p,              # hdc
        ctypes.POINTER(W.RECT),       # lprcMonitor
        ctypes.c_long,                # lParam
    )

    def _cb(h_monitor, _hdc, _lprc, _lparam):
        info = W.MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(W.MONITORINFOEXW)
        if W.user32.GetMonitorInfoW(ctypes.c_void_p(h_monitor), ctypes.byref(info)):
            rc = info.rcMonitor
            flags = info.dwFlags
            monitors.append(MonitorInfo(
                index=len(monitors),
                name=info.szDevice,
                device_string=info.szDevice,
                left=rc.left, top=rc.top,
                width=rc.width, height=rc.height,
                is_primary=bool(flags & 1),   # MONITORINFOF_PRIMARY
                is_active=bool(flags & 2) or True,
            ))
        return 1

    proc = MONITOR_ENUM_PROC(_cb)
    W.user32.EnumDisplayMonitors(None, None, ctypes.cast(proc, ctypes.c_void_p), 0)
    # `proc` must outlive the enumeration call; keeping the reference here.

    # Order by position so "Monitor 1" is deterministic (left-to-right, top-down)
    monitors.sort(key=lambda m: (m.left, m.top))
    ordered = [
        MonitorInfo(i, m.name, m.device_string, m.left, m.top, m.width, m.height,
                    m.is_primary, m.is_active, m.dpi)
        for i, m in enumerate(monitors)
    ]
    return ordered


def describe() -> str:
    lines = []
    for m in get_monitors():
        lines.append(
            f"[{m.index}] {m.name}: {m.width}x{m.height} at ({m.left},{m.top})"
            f"{' PRIMARY' if m.is_primary else ''}")
    return "\n".join(lines)
