"""Build Windows .ico files from the traced mark.

The full logo is a mark stacked over a wordmark. At 16 px on a taskbar the
wordmark is mush, so the icon uses the mark alone, centred on a rounded square.

    python tools/make_icon.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw

SS = 8                       # supersampling factor, for clean diagonals
SIZES = [16, 24, 32, 48, 64, 128, 256]

INK = (38, 38, 42, 255)
GOLD = (201, 155, 63, 255)
PAPER = (250, 250, 248, 255)


def path_points(svg_path: Path) -> list[list[tuple[float, float]]]:
    """Pull the polygon rings out of the traced mark SVG."""
    d = re.search(r'd="([^"]*)"', svg_path.read_text(encoding="utf-8")).group(1)
    rings = []
    for chunk in d.split("Z"):
        pts = [(float(x), float(y))
               for x, y in re.findall(r"[ML]([-\d.]+) ([-\d.]+)", chunk)]
        if len(pts) >= 3:
            rings.append(pts)
    return rings


def render(rings, size: int, fg, bg, inset: float = 0.19, radius: float = 0.22):
    """One icon layer: rounded plate, mark centred on it."""
    n = size * SS
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    if bg is not None:
        draw.rounded_rectangle([0, 0, n - 1, n - 1], radius=int(n * radius), fill=bg)

    # The mark's own artboard is 100x100 but the glyph does not fill it, so
    # measure the real extents and centre on those.
    xs = [p[0] for r in rings for p in r]
    ys = [p[1] for r in rings for p in r]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    span = max(maxx - minx, maxy - miny)
    scale = (n * (1 - inset * 2)) / span
    ox = (n - (maxx - minx) * scale) / 2 - minx * scale
    oy = (n - (maxy - miny) * scale) / 2 - miny * scale

    # Even-odd fill, so counters inside the mark punch through.
    layer = Image.new("1", (n, n), 0)
    ld = ImageDraw.Draw(layer)
    for ring in rings:
        one = Image.new("1", (n, n), 0)
        ImageDraw.Draw(one).polygon(
            [(x * scale + ox, y * scale + oy) for x, y in ring], fill=1)
        layer = Image.frombytes("1", (n, n), bytes(
            a ^ b for a, b in zip(layer.tobytes(), one.tobytes())))
        ld = ImageDraw.Draw(layer)
    del ld

    glyph = Image.new("RGBA", (n, n), fg)
    img.paste(glyph, (0, 0), layer.convert("L").point(lambda v: 255 if v else 0))
    return img.resize((size, size), Image.LANCZOS)


def build(rings, out: Path, fg, bg) -> Path:
    layers = [render(rings, s, fg, bg) for s in SIZES]
    layers[-1].save(out, format="ICO",
                    sizes=[(s, s) for s in SIZES], append_images=layers[:-1])
    return out


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    rings = path_points(root / "assets" / "snapir-mark.svg")

    res = root / "app" / "buildResources"
    res.mkdir(parents=True, exist_ok=True)

    dark = build(rings, res / "icon.ico", GOLD, INK)
    light = build(rings, res / "icon-light.ico", INK, PAPER)
    render(rings, 512, GOLD, INK).save(res / "icon.png")

    for p in (dark, light):
        print(f"{p}  {p.stat().st_size / 1024:.1f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
