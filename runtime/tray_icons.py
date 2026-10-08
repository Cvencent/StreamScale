"""Tray icon generation.

Icons are drawn programmatically rather than shipped as art assets: it keeps
the repository free of binaries, makes the palette easy to adjust, and means
the ICO used for the executable comes from the same code as the runtime
icons, so they can never drift apart.

The tray actually renders these at 16x16, so the shape is only a secondary
cue -- the colour is what the user reads. Colours are therefore chosen to be
distinguishable at a glance and at small size, not to look tasteful.
"""

from __future__ import annotations

from typing import Dict, Tuple

# Status -> colour. Semantic, high-saturation, and far apart in hue so they
# remain distinguishable when Windows scales them down.
COLORS: Dict[str, str] = {
    "idle":     "#8E8E93",   # grey  - running, nothing to do
    "active":   "#34C759",   # green - stream in progress, rules applied
    "restored": "#0A84FF",   # blue  - stream just ended, settings restored
    "error":    "#FF3B30",   # red   - last operation failed
    "disabled": "#5A5A5F",   # dark grey - switched off in settings
}

# Human-readable descriptions, used in the tooltip and the settings window.
STATUS_TEXT: Dict[str, str] = {
    "idle":     "Idle - waiting for a stream",
    "active":   "Streaming - scaling applied",
    "restored": "Stream ended - settings restored",
    "error":    "Error - see the log",
    "disabled": "Disabled in settings",
}


def make_tray_image(status: str, size: int = 64):
    """Build a PIL image for the given status.

    A rounded square with a white glyph: the square carries the colour, the
    glyph says what the state means without relying on colour perception.
    """
    from PIL import Image, ImageDraw

    color = COLORS.get(status, COLORS["idle"])
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    margin = max(2, size // 32)
    draw.rounded_rectangle(
        (margin, margin, size - margin - 1, size - margin - 1),
        radius=max(4, size // 5),
        fill=color,
    )

    white = (255, 255, 255, 255)
    cx = cy = size / 2
    unit = size / 8.0

    if status == "active":
        # Right-pointing play triangle: the stream is running.
        draw.polygon(
            [(cx - 1.6 * unit, cy - 2.0 * unit),
             (cx - 1.6 * unit, cy + 2.0 * unit),
             (cx + 2.1 * unit, cy)],
            fill=white,
        )
    elif status == "restored":
        # Circular arrow suggestion: settings came back.
        box = (cx - 2.0 * unit, cy - 2.0 * unit, cx + 2.0 * unit, cy + 2.0 * unit)
        draw.arc(box, start=40, end=320, fill=white, width=max(2, size // 14))
        draw.polygon(
            [(cx + 1.1 * unit, cy - 2.4 * unit),
             (cx + 2.6 * unit, cy - 1.0 * unit),
             (cx + 0.7 * unit, cy - 0.6 * unit)],
            fill=white,
        )
    elif status == "error":
        # Exclamation mark.
        w = max(2, size // 9)
        draw.rounded_rectangle(
            (cx - w / 2, cy - 2.2 * unit, cx + w / 2, cy + 0.5 * unit),
            radius=w / 2, fill=white)
        draw.ellipse(
            (cx - w / 2, cy + 1.2 * unit, cx + w / 2, cy + 1.2 * unit + w),
            fill=white)
    elif status == "disabled":
        # Horizontal bar: switched off.
        w = max(2, size // 9)
        draw.rounded_rectangle(
            (cx - 2.2 * unit, cy - w / 2, cx + 2.2 * unit, cy + w / 2),
            radius=w / 2, fill=white)
    else:
        # Pause bars: idle.
        w = max(2, size // 8)
        gap = w * 0.9
        draw.rounded_rectangle(
            (cx - gap - w, cy - 1.8 * unit, cx - gap, cy + 1.8 * unit),
            radius=w / 2, fill=white)
        draw.rounded_rectangle(
            (cx + gap, cy - 1.8 * unit, cx + gap + w, cy + 1.8 * unit),
            radius=w / 2, fill=white)

    return image


def make_ico(path, status: str = "active") -> str:
    """Write a multi-resolution ICO for the executable."""
    image = make_tray_image(status, size=256)
    image.save(
        path,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    return str(path)


def rgb_tuple(status: str) -> Tuple[int, int, int]:
    """Colour as an (r, g, b) tuple, for callers that need raw values."""
    color = COLORS.get(status, COLORS["idle"]).lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))
