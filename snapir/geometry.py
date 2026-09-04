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


def point_in_polygon(q: Pt, ring: list[Pt]) -> bool:
    """Ray cast. Orientation-independent, so it does not care which way the
    ring was wound - which the topology walk does not guarantee."""
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        a, b = ring[i], ring[j]
        crosses_y = (a[1] > q[1]) != (b[1] > q[1])
        if crosses_y and q[0] < (b[0] - a[0]) * (q[1] - a[1]) / (b[1] - a[1]) + a[0]:
            inside = not inside
        j = i
    return inside


def line_intersection(a: Pt, b: Pt, c: Pt, d: Pt) -> Pt | None:
    """Where the infinite lines through a-b and c-d meet.

    Infinite, not segment-bounded, because the useful case is two wall runs
    that stop short of the corner they imply: the corner nobody could stand
    in is exactly the one worth constructing.

    None when they are parallel, or as near parallel as makes no difference.
    """
    r = (b[0] - a[0], b[1] - a[1])
    s = (d[0] - c[0], d[1] - c[1])
    denom = r[0] * s[1] - r[1] * s[0]
    if abs(denom) < 1e-9:
        return None
    t = ((c[0] - a[0]) * s[1] - (c[1] - a[1]) * s[0]) / denom
    return (a[0] + t * r[0], a[1] + t * r[1])


def extend(a: Pt, b: Pt, distance: float) -> Pt:
    """Push b further from a, along their own direction."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = (dx * dx + dy * dy) ** 0.5
    if length < 1e-9:
        return b
    return (b[0] + dx / length * distance, b[1] + dy / length * distance)


def crossings(segments: list[tuple[Pt, Pt]]) -> list[tuple[int, int, Pt]]:
    """Every pair of segments that actually cross, and where.

    Shared endpoints do not count: two walls meeting at a surveyed corner are
    already joined, and reporting that as a crossing would turn every corner
    of every room into a discovery.
    """
    out: list[tuple[int, int, Pt]] = []
    for i in range(len(segments)):
        a, b = segments[i]
        for j in range(i + 1, len(segments)):
            c, d = segments[j]
            if _shares_end((a, b), (c, d)):
                continue
            if not _crosses(a, b, c, d):
                continue
            at = line_intersection(a, b, c, d)
            if at is not None:
                out.append((i, j, at))
    return out


def _shares_end(s1: tuple[Pt, Pt], s2: tuple[Pt, Pt], tol: float = 0.5) -> bool:
    return any(_dist(p, q) <= tol for p in s1 for q in s2)


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
