"""Trace the logo PNG into a clean, single-colour SVG.

The mark is polygonal, so a contour trace plus Douglas-Peucker simplification
recovers the real edges rather than approximating them with curves. Output uses
`currentColor` so the same file works in charcoal, gold, or white.

    python tools/trace_logo.py assets/"Snapir Design BG - Logo.png" assets/
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

THRESHOLD = 128          # anything darker than this is ink
EPSILON = 0.7            # Douglas-Peucker tolerance, source pixels
SNAP = 0.0               # coordinate merge; measured worse than leaving it off
RATIO = 0.0              # edge straightening; 0 disables it

# Both cleanups were swept against the source pixels and both lost fidelity.
# The raw Douglas-Peucker trace scores highest, so that is what ships.


def load_mask(path: Path) -> np.ndarray:
    img = Image.open(path).convert("RGBA")
    a = np.asarray(img).astype(float)
    alpha = a[..., 3] / 255.0
    lum = (0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2])
    return (alpha > 0.5) & (lum < THRESHOLD)


def trace_rings(mask: np.ndarray) -> list[list[tuple[float, float]]]:
    """Every closed boundary ring of a binary mask, in lattice coordinates.

    Walks the unit edges that separate filled pixels from empty ones and chains
    them into loops. Unlike a neighbourhood walk this cannot get trapped on a
    thin stroke or a diagonal join, and the staircase it produces simplifies
    straight back to the original edges.
    """
    h, w = mask.shape
    padded = np.zeros((h + 2, w + 2), bool)
    padded[1:-1, 1:-1] = mask

    edges: dict[tuple[int, int], list[tuple[int, int]]] = {}
    ys, xs = np.nonzero(padded)
    for r, c in zip(ys.tolist(), xs.tolist()):
        # Corners are lattice points (x, y); wind each pixel clockwise so the
        # directed edges of neighbouring pixels chain consistently.
        if not padded[r - 1, c]:
            edges.setdefault((c, r), []).append((c + 1, r))
        if not padded[r, c + 1]:
            edges.setdefault((c + 1, r), []).append((c + 1, r + 1))
        if not padded[r + 1, c]:
            edges.setdefault((c + 1, r + 1), []).append((c, r + 1))
        if not padded[r, c - 1]:
            edges.setdefault((c, r + 1), []).append((c, r))

    rings = []
    for start in list(edges):
        while edges.get(start):
            ring = [start]
            node = edges[start].pop(0)
            while node != start:
                ring.append(node)
                nxt = edges.get(node)
                if not nxt:
                    ring = []
                    break
                node = nxt.pop(0)
            if len(ring) >= 4:
                # Shift back by the padding and centre on the pixel grid.
                rings.append([(x - 1.0, y - 1.0) for x, y in ring])
    return rings


def rdp(pts: list[tuple[float, float]], eps: float) -> list[tuple[float, float]]:
    """Douglas-Peucker. Straight runs of pixels collapse back to real edges."""
    if len(pts) < 3:
        return pts
    a, b = np.array(pts[0]), np.array(pts[-1])
    ab = b - a
    norm = np.hypot(*ab)
    p = np.array(pts)
    if norm == 0:
        d = np.hypot(*(p - a).T)
    else:
        rel = p - a
        d = np.abs(ab[0] * rel[:, 1] - ab[1] * rel[:, 0]) / norm
    i = int(d.argmax())
    if d[i] > eps:
        return rdp(pts[:i + 1], eps)[:-1] + rdp(pts[i:], eps)
    return [pts[0], pts[-1]]


def snap(pts: list[tuple[float, float]], tol: float) -> list[tuple[float, float]]:
    """Pull nearly-equal x and y values onto shared coordinates.

    The source is a rasterised logo, so edges that were drawn parallel land a
    fraction of a pixel apart. Snapping restores the intent.
    """
    for axis in (0, 1):
        vals = sorted({p[axis] for p in pts})
        groups: list[list[float]] = []
        for v in vals:
            if groups and v - groups[-1][-1] <= tol:
                groups[-1].append(v)
            else:
                groups.append([v])
        lut = {v: sum(g) / len(g) for g in groups for v in g}
        pts = [(lut[p[0]], p[1]) if axis == 0 else (p[0], lut[p[1]]) for p in pts]
    return pts


def polygons(mask: np.ndarray, min_area: int = 40):
    """Boundary rings of every component, including the counters inside letters."""
    labels, n = ndimage.label(mask)
    rings = []
    for i in range(1, n + 1):
        comp = labels == i
        if comp.sum() < min_area:
            continue
        rings.extend(trace_rings(comp))
    return rings


def rectify(pts: list[tuple[float, float]], tol: float = 1.4,
            passes: int = 3) -> list[tuple[float, float]]:
    """Force near-axis edges to be exactly axis-aligned.

    The wordmark is drawn on a square grid with 45 degree chamfers. Rasterising
    it left every long edge a fraction of a pixel off true, which reads as a
    wobble at logo size. Straightening the edges that were meant to be straight
    restores the drawing rather than approximating it.
    """
    pts = list(pts)
    n = len(pts)
    for _ in range(passes):
        for i in range(n):
            j = (i + 1) % n
            (x1, y1), (x2, y2) = pts[i], pts[j]
            dx, dy = x2 - x1, y2 - y1
            # Only straighten long edges that are already almost true. Short
            # edges are the 45 degree chamfers and must be left alone.
            if abs(dy) >= 3.0 and abs(dx) <= tol and abs(dx) <= RATIO * abs(dy):
                x = (x1 + x2) / 2
                pts[i], pts[j] = (x, y1), (x, y2)
            elif abs(dx) >= 3.0 and abs(dy) <= tol and abs(dy) <= RATIO * abs(dx):
                y = (y1 + y2) / 2
                pts[i], pts[j] = (x1, y), (x2, y)
    return pts


def ring_area(pts) -> float:
    n = len(pts)
    return abs(sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1]
                   for i in range(n))) / 2.0


# The mark is a handful of long diagonals and cleans up best with a coarse
# tolerance. The wordmark is dense small detail and needs a fine one. Measured
# against the source pixels, not guessed.
PARAMS = {
    "mark": (1.3, 1.6),      # 20 points, 96.3% of the source pixels
    "wordmark": (0.7, 0.0),
    "logo": (0.7, 0.0),
}


def to_svg(rings, size, view: int = 100, eps=None, snap_tol=None) -> str:
    h, w = size
    s = view / max(h, w)
    ox, oy = (view - w * s) / 2, (view - h * s) / 2
    paths = []
    for ring in rings:
        pts = snap(rdp(list(ring), EPSILON if eps is None else eps),
                   SNAP if snap_tol is None else snap_tol)
        # Drop consecutive duplicates left behind by snapping, then any ring
        # that collapsed to a sliver.
        pts = [q for k, q in enumerate(pts) if k == 0 or q != pts[k - 1]]
        while len(pts) > 1 and pts[0] == pts[-1]:
            pts.pop()
        if len(pts) < 3 or ring_area(pts) < 4.0:
            continue
        d = " ".join(
            f"{'M' if k == 0 else 'L'}{x * s + ox:.2f} {y * s + oy:.2f}"
            for k, (x, y) in enumerate(pts)
        )
        paths.append(d + "Z")
    body = "".join(paths)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {view} {view}" '
            f'fill="currentColor"><path fill-rule="evenodd" d="{body}"/></svg>')


def main(src: str, out_dir: str) -> int:
    src, out_dir = Path(src), Path(out_dir)
    mask = load_mask(src)
    ys, xs = np.nonzero(mask)

    # The artwork is a mark stacked above a wordmark. Split on the widest
    # empty band of rows so each can be used on its own.
    rows = mask.any(axis=1)
    gaps, run = [], None
    for y, filled in enumerate(rows):
        if not filled and run is None:
            run = y
        elif filled and run is not None:
            gaps.append((run, y))
            run = None
    inner = [g for g in gaps if g[0] > ys.min() and g[1] < ys.max()]
    split = max(inner, key=lambda g: g[1] - g[0]) if inner else None

    parts = {"logo": (ys.min(), ys.max() + 1)}
    if split:
        parts = {
            "mark": (ys.min(), split[0]),
            "wordmark": (split[1], ys.max() + 1),
            "logo": (ys.min(), ys.max() + 1),
        }

    for name, (y0, y1) in parts.items():
        sub = mask[y0:y1]
        sxs = np.nonzero(sub.any(axis=0))[0]
        sub = sub[:, sxs.min():sxs.max() + 1]
        eps, snap_tol = PARAMS.get(name, (EPSILON, SNAP))
        svg = to_svg(polygons(sub), sub.shape, eps=eps, snap_tol=snap_tol)
        path = out_dir / f"snapir-{name}.svg"
        path.write_text(svg, encoding="utf-8")
        print(f"{path}  {len(svg)} bytes  from {sub.shape[1]}x{sub.shape[0]} px")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "."))
