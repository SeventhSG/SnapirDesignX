"""Plane geometry helpers. No CAD kernel here, so this stays import-cheap
and testable on its own."""
from __future__ import annotations

Pt = tuple[float, float]


def polygon_area(pts: list[Pt]) -> float:
    """Unsigned shoelace area."""
    return abs(signed_area(pts))


def signed_area(pts: list[Pt]) -> float:
    """Positive when the ring winds counter-clockwise."""
    n = len(pts)
    if n < 3:
        return 0.0
    return sum(
        pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1]
        for i in range(n)
    ) / 2.0


def ensure_ccw(pts: list[Pt]) -> list[Pt]:
    return pts if signed_area(pts) > 0 else list(reversed(pts))


def perimeter(pts: list[Pt]) -> float:
    n = len(pts)
    return sum(_dist(pts[i], pts[(i + 1) % n]) for i in range(n))


def self_intersections(pts: list[Pt]) -> list[tuple[int, int]]:
    """Indices of every pair of non-adjacent edges that cross."""
    n = len(pts)
    hits: list[tuple[int, int]] = []
    if n < 4:
        return hits
    for i in range(n):
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue                       # adjacent across the seam
            if _crosses(pts[i], pts[(i + 1) % n], pts[j], pts[(j + 1) % n]):
                hits.append((i, j))
    return hits


def dedupe(pts: list[Pt], tol: float = 0.5) -> list[Pt]:
    """Drop consecutive points closer together than tol."""
    out: list[Pt] = []
    for p in pts:
        if not out or _dist(out[-1], p) > tol:
            out.append(p)
    while len(out) > 1 and _dist(out[0], out[-1]) <= tol:
        out.pop()
    return out


def bounds(pts: list[Pt]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def project_onto_edges(pt: Pt, ring: list[Pt]) -> tuple[int, Pt, float]:
    """Nearest point on the ring to pt. Returns (edge index, point, distance).

    Used to seat an opening's jambs exactly on the wall they belong to, since
    a jamb reading sits a centimetre or two off the surveyed corner line.
    """
    n = len(ring)
    best = (0, ring[0], float("inf"))
    for i in range(n):
        a, b = ring[i], ring[(i + 1) % n]
        q = _closest_on_segment(pt, a, b)
        d = _dist(pt, q)
        if d < best[2]:
            best = (i, q, d)
    return best


def _closest_on_segment(p: Pt, a: Pt, b: Pt) -> Pt:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return a
    t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
    return (ax + t * dx, ay + t * dy)


def _cross(o: Pt, p: Pt, q: Pt) -> float:
    return (p[0] - o[0]) * (q[1] - o[1]) - (p[1] - o[1]) * (q[0] - o[0])


def _crosses(a: Pt, b: Pt, c: Pt, d: Pt) -> bool:
    d1, d2 = _cross(c, d, a), _cross(c, d, b)
    d3, d4 = _cross(a, b, c), _cross(a, b, d)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def _dist(a: Pt, b: Pt) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
