#!/usr/bin/env python3
"""Generate packaging/ImageLab.icns and media/icon/app_icon.png (needs Pillow + iconutil)."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ICONSET = ROOT / "build" / "ImageLab.iconset"
ICNS = ROOT / "packaging" / "ImageLab.icns"
README_ICON = ROOT / "media" / "icon" / "app_icon.png"

ICON_SIZES = [
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
]


def draw_icon(size: int):
    from PIL import Image, ImageDraw

    # Draw at 1024 and downsample so small sizes stay crisp.
    s = 1024
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))

    # macOS icon grid: the tile is ~80% of the canvas with transparent margin.
    inset = 100
    tile = s - 2 * inset
    gradient = Image.new("RGBA", (tile, tile))
    top, bottom = (106, 168, 255), (59, 108, 246)
    gd = ImageDraw.Draw(gradient)
    for y in range(tile):
        t = y / (tile - 1)
        gd.line([(0, y), (tile, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)) + (255,))
    mask = Image.new("L", (tile, tile), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, tile - 1, tile - 1), radius=int(tile * 0.225), fill=255)
    img.paste(gradient, (inset, inset), mask)

    d = ImageDraw.Draw(img)
    white = (255, 255, 255, 255)
    stroke = 58
    # Mountains, matching the favicon.
    pts = [(260, 680), (430, 490), (560, 620), (650, 530), (790, 660)]
    d.line(pts, fill=white, width=stroke, joint="curve")
    for x, y in (pts[0], pts[-1]):
        d.ellipse((x - stroke / 2, y - stroke / 2, x + stroke / 2, y + stroke / 2), fill=white)
    # Sun.
    d.ellipse((620, 290, 740, 410), fill=white)
    # Compression brackets.
    soft = (255, 255, 255, 150)
    d.line([(250, 300), (250, 250), (300, 250)], fill=soft, width=26, joint="curve")
    d.line([(774, 800), (824, 800), (824, 750)], fill=soft, width=26, joint="curve")

    return img.resize((size, size), Image.Resampling.LANCZOS)


def main() -> int:
    try:
        import PIL  # noqa: F401
    except ImportError:
        print("Pillow required — pip install pillow", file=sys.stderr)
        return 1

    shutil.rmtree(ICONSET, ignore_errors=True)
    ICONSET.mkdir(parents=True)
    for name, px in ICON_SIZES:
        draw_icon(px).save(ICONSET / name, format="PNG")

    ICNS.parent.mkdir(parents=True, exist_ok=True)
    ICNS.unlink(missing_ok=True)
    subprocess.run(["iconutil", "-c", "icns", str(ICONSET), "-o", str(ICNS)], check=True)
    README_ICON.parent.mkdir(parents=True, exist_ok=True)
    draw_icon(512).save(README_ICON, format="PNG")
    print(f"Created {ICNS.relative_to(ROOT)} and {README_ICON.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
