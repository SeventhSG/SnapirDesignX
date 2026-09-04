"""The way back: a sketch edited in Geomagic Design X, read into the room.

The room goes out as exact curves; if the corner of a wall was in the wrong
place, that is where it gets fixed, with the tools that are good at it. What
comes back is the same drawing with something changed - a corner moved, a
wall added, a point put in - and the room has to become that drawing without
losing what the survey knows.

So an imported point that lands on a surveyed one keeps that point's name.
That is the whole trick: identity survives the trip, the operator's earlier
decisions still find the points they were made about, and only what actually
moved actually moves.

Nothing is read from the file but geometry. Edges become lines between their
end points, loose vertices become points, and a closed loop of lines down at
floor level becomes the outline.
"""
from __future__ import annotations

import math
from pathlib import Path

from .model import Room
from .solid import CM_TO_MM, BuildError

Pt3 = tuple[float, float, float]

# Two shots this close are the same corner. The survey is exact and so is the
# file, so this only has to swallow the millimetre rounding in between.
MATCH = 2.0        # cm
WELD = 0.2         # cm; two ends this close in the file are one point
# Below this a run is a marker, not a wall: the cross drawn through a single
# shot on the way out has arms of exactly this order.
MIN_RUN = 12.0     # cm


def read_sketch(path: str | Path) -> tuple[list[Pt3], list[tuple[int, int]]]:
    """Points and lines out of an IGES or STEP file, in survey centimetres.

    A curve that is not a straight line arrives as its two ends. Design X
    writes sketch lines as lines, so that costs nothing in practice, and
    guessing at a spline would put corners where the drawing has none.
    """
    p = Path(path)
    if not p.is_file():
        raise BuildError(f"No such file: {p}")

    from OCP.IFSelect import IFSelect_RetDone

    suffix = p.suffix.lower()
    if suffix in (".igs", ".iges"):
        from OCP.IGESControl import IGESControl_Reader
        reader = IGESControl_Reader()
    elif suffix in (".stp", ".step"):
        from OCP.STEPControl import STEPControl_Reader
        reader = STEPControl_Reader()
    else:
        raise BuildError(f"Not a Design X sketch: {p.name}")

    if reader.ReadFile(str(p)) != IFSelect_RetDone:
        raise BuildError(f"Could not read {p.name}")
    reader.TransferRoots()
    shape = reader.OneShape()
    if shape.IsNull():
        raise BuildError(f"{p.name} holds no geometry")

    from OCP.BRep import BRep_Tool
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_VERTEX
    from OCP.TopExp import TopExp, TopExp_Explorer
    from OCP.TopoDS import TopoDS
    from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape

    pts: list[Pt3] = []

    def seat(v) -> int:
        """The index of this vertex's place, welding what coincides."""
        g = BRep_Tool.Pnt_s(TopoDS.Vertex_s(v))
        q = (g.X() / CM_TO_MM, g.Y() / CM_TO_MM, g.Z() / CM_TO_MM)
        for i, r in enumerate(pts):
            if abs(r[0] - q[0]) < WELD and abs(r[1] - q[1]) < WELD \
               and abs(r[2] - q[2]) < WELD:
                return i
        pts.append(q)
        return len(pts) - 1

    lines: list[tuple[int, int]] = []
    exp = TopExp_Explorer(shape, TopAbs_EDGE)
    while exp.More():
        edge = exp.Current()
        ends = TopExp_Explorer(edge, TopAbs_VERTEX)
        idx = []
        while ends.More():
            idx.append(seat(ends.Current()))
            ends.Next()
        if len(idx) >= 2 and idx[0] != idx[-1]:
            lines.append((idx[0], idx[-1]))
        exp.Next()

    # Vertices no edge uses: the single shots, written as points.
    free: set[int] = set()
    owners = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_VERTEX, TopAbs_EDGE, owners)
    exp = TopExp_Explorer(shape, TopAbs_VERTEX)
    while exp.More():
        v = exp.Current()
        if owners.Contains(v) and owners.FindFromKey(v).Extent() == 0:
            free.add(seat(v))
        exp.Next()

    keep = _dedupe_lines([(a, b) for a, b in lines
                          if _far(pts[a], pts[b]) >= MIN_RUN])
    # The ends of the runs that were dropped go with them. A cross through a
    # single shot is six of those, and left behind they would arrive as six
    # points nobody measured, clustered a few centimetres around one that was.
    used = free | {i for line in keep for i in line}
    order = sorted(used)
    at = {old: new for new, old in enumerate(order)}
    return ([pts[i] for i in order],
            [(at[a], at[b]) for a, b in keep])


def _far(a: Pt3, b: Pt3) -> float:
    return math.dist(a, b)


def _dedupe_lines(lines: list[tuple[int, int]]) -> list[tuple[int, int]]:
    seen, out = set(), []
    for a, b in lines:
        k = (a, b) if a < b else (b, a)
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def _cycles(n: int, lines: list[tuple[int, int]]) -> list[list[int]]:
    """Every closed loop where each corner joins exactly two lines.

    That is what a ring drawn as a ring looks like. A rectangle with its
    corners tied back to a second face - the box drawn around a fitting's
    measured depth - is not one, and is left alone.
    """
    adj: dict[int, list[int]] = {}
    for a, b in lines:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)

    seen: set[int] = set()
    out: list[list[int]] = []
    for start in adj:
        if start in seen or len(adj[start]) != 2:
            continue
        loop, node, prev = [], start, -1
        while True:
            if len(adj.get(node, [])) != 2:
                loop = []
                break
            loop.append(node)
            nxt = [q for q in adj[node] if q != prev]
            if not nxt:
                loop = []
                break
            prev, node = node, nxt[0]
            if node == start:
                break
            if len(loop) > n:
                loop = []
                break
        if len(loop) >= 3:
            seen.update(loop)
            out.append(loop)
    return out


def _area(ring: list[tuple[float, float]]) -> float:
    return abs(sum(ring[i][0] * ring[(i + 1) % len(ring)][1]
                   - ring[(i + 1) % len(ring)][0] * ring[i][1]
                   for i in range(len(ring)))) / 2.0


def outline_loop(pts: list[Pt3], lines: list[tuple[int, int]]) -> list[int]:
    """The loop that is the floor of the room.

    A room exported for editing carries at least two rings of the same plan
    shape, the floor and the ceiling above it, plus a rectangle for every
    opening. The floor is the big one down at the bottom.
    """
    loops = _cycles(len(pts), lines)
    if not loops:
        return []
    level = [sum(pts[i][2] for i in loop) / len(loop) for loop in loops]
    floor = min(level)
    low = [loop for loop, z in zip(loops, level) if z - floor <= 40.0]
    return max(low, key=lambda loop: _area([(pts[i][0], pts[i][1]) for i in loop]))


def sketch_for(room: Room, path: str | Path) -> dict:
    """Read the edited file and say what the room becomes.

    Returns the whole imported sketch as one record, which replaces whatever
    the last import left behind rather than piling on top of it: importing
    twice leaves the room exactly as importing once did.
    """
    pts, lines = read_sketch(path)
    if not pts:
        raise BuildError("That file has nothing in it to import.")

    # A point that lands on a surveyed shot is that shot, under its own name.
    # Everything the operator has already decided - a role they corrected, a
    # wall they took out, the kind of an opening - is keyed on these names,
    # and all of it survives the trip out and back because of this.
    taken: set[str] = set()
    names: list[str] = []
    matched = 0
    # A point that only exists because the last import brought it in has to be
    # carried again, under the same name. Matching it and then leaving it out of
    # the record would delete it on the very next read, and every line drawn to
    # it would go with it.
    carry: list[int] = []
    for i, q in enumerate(pts):
        best, best_d = None, MATCH
        for p in room.points:
            if p.name in taken:
                continue
            d = math.dist((p.x, p.y, p.z), q)
            if d < best_d:
                best, best_d = p, d
        if best is not None:
            taken.add(best.name)
            names.append(best.name)
            matched += 1
            if best.derived:
                carry.append(i)
        else:
            names.append("")

    loop = outline_loop(pts, lines)
    on_ring = set(loop)

    n = 1
    used = {p.name for p in room.points} | set(names)
    fresh: list[dict] = []
    for i, name in enumerate(names):
        if name and i not in carry:
            continue
        if not name:
            while f"X_{n:03d}" in used:
                n += 1
            name = f"X_{n:03d}"
            used.add(name)
            names[i] = name
        # A corner of the floor loop is a floor corner; that much the drawing
        # says outright. Anything else the file brought is left unknown rather
        # than guessed at, so it shows up as a point waiting to be told what
        # it is instead of quietly joining the room as something it is not.
        fresh.append({"name": name, "x": pts[i][0], "y": pts[i][1], "z": pts[i][2],
                      "role": "floor" if i in on_ring else "unknown",
                      "from": f"Design X, {Path(path).name}"})

    return {
        "points": fresh,
        "segments": [[names[a], names[b]] for a, b in lines],
        "outline": [names[i] for i in loop],
        "file": Path(path).name,
        "matched": matched,
    }
