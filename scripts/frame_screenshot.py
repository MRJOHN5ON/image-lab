#!/usr/bin/env python3
"""Wrap a 2x app screenshot in a macOS window frame (title bar, traffic lights, rounded corners, shadow).

    python scripts/frame_screenshot.py raw.png out.png --theme dark [--width 2000]
"""

from __future__ import annotations

import argparse

from PIL import Image, ImageDraw, ImageFilter, ImageFont

SCALE = 2
TITLEBAR = 28 * SCALE
RADIUS = 10 * SCALE
MARGIN = 36 * SCALE
FONT = "/System/Library/Fonts/SFNS.ttf"
THEMES = {
    "dark": {"bar": (36, 37, 41), "text": (206, 207, 212), "line": (0, 0, 0), "edge": (255, 255, 255, 34)},
    "light": {"bar": (246, 246, 247), "text": (72, 72, 78), "line": (222, 222, 226), "edge": (0, 0, 0, 40)},
}
LIGHTS = [(255, 95, 87), (254, 188, 46), (40, 200, 64)]


def frame(shot: Image.Image, theme: str, title: str) -> Image.Image:
    colors = THEMES[theme]
    w, h = shot.width, shot.height + TITLEBAR
    window = Image.new("RGBA", (w, h), colors["bar"] + (255,))
    window.paste(shot.convert("RGBA"), (0, TITLEBAR))
    draw = ImageDraw.Draw(window)
    draw.line([(0, TITLEBAR - 1), (w, TITLEBAR - 1)], fill=colors["line"], width=1)
    for i, color in enumerate(LIGHTS):
        cx, cy, r = (14 + 20 * i) * SCALE, TITLEBAR // 2, 6 * SCALE
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)
    font = ImageFont.truetype(FONT, 13 * SCALE)
    tw = draw.textlength(title, font=font)
    draw.text(((w - tw) / 2, TITLEBAR / 2), title, font=font, fill=colors["text"], anchor="lm")

    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), RADIUS, fill=255)
    window.putalpha(mask)
    ImageDraw.Draw(window).rounded_rectangle((0, 0, w - 1, h - 1), RADIUS, outline=colors["edge"], width=1)

    canvas = Image.new("RGBA", (w + MARGIN * 2, h + MARGIN * 2), (0, 0, 0, 0))
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        (MARGIN, MARGIN + 14 * SCALE, MARGIN + w, MARGIN + h + 6 * SCALE), RADIUS, fill=(0, 0, 0, 120)
    )
    canvas = Image.alpha_composite(canvas, shadow.filter(ImageFilter.GaussianBlur(18 * SCALE)))
    canvas.alpha_composite(window, (MARGIN, MARGIN))
    return canvas


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("src")
    parser.add_argument("dst")
    parser.add_argument("--theme", choices=THEMES, default="dark")
    parser.add_argument("--title", default="Image Lab")
    parser.add_argument("--width", type=int, default=0, help="downscale the result to this width")
    args = parser.parse_args()
    out = frame(Image.open(args.src), args.theme, args.title)
    if args.width and out.width > args.width:
        out = out.resize((args.width, round(out.height * args.width / out.width)), Image.LANCZOS)
    out.save(args.dst, optimize=True)


if __name__ == "__main__":
    main()
