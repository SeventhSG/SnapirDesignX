"""Putting the rooms of one survey into a single frame.

Every room is measured from wherever the instrument happened to stand, so a
survey is not one drawing: it is a dozen drawings each in its own coordinate
system, and nothing in the file says how they sit relative to each other. A
stairwell shot floor by floor is the case where that matters most - the flights
are the same staircase, and until the floors are in one frame there is no
staircase, only four unrelated boxes.

Nothing here guesses. The operator says "this corner in this room is that
corner in that one", and two of those are enough to fix a room: the rotation
and the shift that carry one onto the other. What this module does is solve for
that placement, propagate it from room to room, and say how well it fits.

The placement is the same rigid transform a door connection uses - rotate about
the vertical, then translate - so a room placed here and a room placed by a
connection land in the same place.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .model import Room


@dataclass
class Placement:
    """Where a room's own coordinates sit in the project's frame."""
    dx: float = 0.0
    dy: float = 0.0
    dz: float = 0.0
    rotation_deg: float = 0.0
    # How far the paired points ended up from each other, RMS, centimetres.
    # Zero for the anchor, which is the frame by definition.
    residual: float = 0.0
    # How the room got here: the room it was matched against, and on how many
    # pairs. The anchor names nothing.
    via: str = ""
    pairs: int = 0

    def apply(self, x: float, y: float, z: float) -> tuple[float, float, float]:
        rad = math.radians(self.rotation_deg)
        cos, sin = math.cos(rad), math.sin(rad)
        return (x * cos - y * sin + self.dx,
                x * sin + y * cos + self.dy,
                z + self.dz)


@dataclass
class Pair:
    """One point in one room said to be the same place as one in another."""
    room_a: str
    point_a: str
    room_b: str
    point_b: str

    def to_json(self) -> dict:
        return {"roomA": self.room_a, "pointA": self.point_a,
                "roomB": self.room_b, "pointB": self.point_b}

    @classmethod
    def from_json(cls, d: dict) -> "Pair":
        return cls(str(d.get("roomA", "")), str(d.get("pointA", "")),
                   str(d.get("roomB", "")), str(d.get("pointB", "")))

    @property
    def key(self) -> tuple[str, str, str, str]:
        """Direction-independent identity, so the same pair is never made twice."""
        a, b = (self.room_a, self.point_a), (self.room_b, self.point_b)
        return (*min(a, b), *max(a, b))


def _fit(src: list[tuple[float, float, float]],
         dst: list[tuple[float, float, float]]) -> Placement:
    """The rotation and shift carrying src onto dst, in the plan.

    One pair can only give a shift - a single point says nothing about which
    way the room is turned - so the room keeps its own heading until a second
    pair is made. Two or more solve both at once, in the least-squares sense,
    which is what makes a third pair worth making: it does not overrule the
    first two, it averages with them.
    """
    n = len(src)
    if n == 0:
        raise ValueError("no pairs")
    sx = sum(p[0] for p in src) / n
    sy = sum(p[1] for p in src) / n
    sz = sum(p[2] for p in src) / n
    dx_ = sum(p[0] for p in dst) / n
    dy_ = sum(p[1] for p in dst) / n
    dz_ = sum(p[2] for p in dst) / n

    rotation = 0.0
    if n >= 2:
        num = sum((s[0] - sx) * (d[1] - dy_) - (s[1] - sy) * (d[0] - dx_)
                  for s, d in zip(src, dst))
        den = sum((s[0] - sx) * (d[0] - dx_) + (s[1] - sy) * (d[1] - dy_)
                  for s, d in zip(src, dst))
        if abs(num) > 1e-12 or abs(den) > 1e-12:
            rotation = math.atan2(num, den)

    cos, sin = math.cos(rotation), math.sin(rotation)
    place = Placement(
        dx=dx_ - (sx * cos - sy * sin),
        dy=dy_ - (sx * sin + sy * cos),
        dz=dz_ - sz,
        rotation_deg=math.degrees(rotation),
    )
    place.residual = math.sqrt(sum(
        sum((a - b) ** 2 for a, b in zip(place.apply(*s), d))
        for s, d in zip(src, dst)) / n)
    place.pairs = n
    return place


def solve(rooms: dict[str, Room], pairs: list[Pair],
          anchor: str | None = None) -> tuple[dict[str, Placement], list[str]]:
    """Place every room the pairs can reach, and name the ones they cannot.

    The anchor is the frame: it sits where it was surveyed and everything else
    comes to it. Rooms are placed outward from there, each against whatever is
    already placed, so a room matched only to a room matched only to the anchor
    still lands - which is how a stairwell goes together, floor by floor, with
    nobody ever having to see the top and the bottom at once.
    """
    known = {name: room for name, room in rooms.items()}
    if not known:
        return {}, []

    if anchor not in known:
        # The room with the most pairs makes the steadiest frame; failing that,
        # the first one, so an empty merge still has somewhere to start.
        count: dict[str, int] = {}
        for p in pairs:
            count[p.room_a] = count.get(p.room_a, 0) + 1
            count[p.room_b] = count.get(p.room_b, 0) + 1
        anchor = max(known, key=lambda n: (count.get(n, 0), n)) if count else \
            next(iter(known))

    placed: dict[str, Placement] = {anchor: Placement()}
    points = {name: {p.name: p for p in room.points} for name, room in known.items()}

    while True:
        best: tuple[str, Placement] | None = None
        for name in known:
            if name in placed:
                continue
            src: list[tuple[float, float, float]] = []
            dst: list[tuple[float, float, float]] = []
            via: str = ""
            for pair in pairs:
                for mine, theirs in ((pair.room_a, pair.room_b), (pair.room_b, pair.room_a)):
                    if mine != name or theirs not in placed:
                        continue
                    my_pt = pair.point_a if mine == pair.room_a else pair.point_b
                    their_pt = pair.point_b if mine == pair.room_a else pair.point_a
                    a = points.get(name, {}).get(my_pt)
                    b = points.get(theirs, {}).get(their_pt)
                    if a is None or b is None:
                        continue
                    src.append((a.x, a.y, a.z))
                    dst.append(placed[theirs].apply(b.x, b.y, b.z))
                    via = theirs if not via or via == theirs else "several rooms"
                    break
            if not src:
                continue
            place = _fit(src, dst)
            place.via = via
            # The best-fitting room goes down first: placing a shaky one early
            # makes every room measured against it shaky too.
            if best is None or (len(src), -place.residual) > \
                    (best[1].pairs, -best[1].residual):
                best = (name, place)
        if best is None:
            break
        placed[best[0]] = best[1]

    return placed, sorted(n for n in known if n not in placed)


def endpoints_for_lines(room_a: Room, line_a: tuple[str, str],
                        room_b: Room, line_b: tuple[str, str],
                        place_a: Placement | None = None,
                        place_b: Placement | None = None) -> list[Pair]:
    """Two pairs from two lines said to be the same wall.

    A line matches a line either way round, and the drawing does not say which
    end is which. Where the rooms are already placed, the ends that are nearer
    each other are the ones that correspond; where they are not, the two runs
    are laid nose to tail and the reading that keeps them pointing the same way
    wins. Either answer is one click from being deleted if it is wrong.
    """
    pa = {p.name: p for p in room_a.points}
    pb = {p.name: p for p in room_b.points}
    if not all(n in pa for n in line_a) or not all(n in pb for n in line_b):
        return []

    a0, a1 = (pa[line_a[0]], pa[line_a[1]])
    b0, b1 = (pb[line_b[0]], pb[line_b[1]])
    A = place_a or Placement()
    B = place_b or Placement()

    def at(p, t):
        return t.apply(p.x, p.y, p.z)

    if place_a is not None and place_b is not None:
        straight = (math.dist(at(a0, A), at(b0, B)) + math.dist(at(a1, A), at(b1, B)))
        crossed = (math.dist(at(a0, A), at(b1, B)) + math.dist(at(a1, A), at(b0, B)))
    else:
        # No placement yet: agree on direction rather than on distance.
        va = (a1.x - a0.x, a1.y - a0.y)
        vb = (b1.x - b0.x, b1.y - b0.y)
        dot = va[0] * vb[0] + va[1] * vb[1]
        straight, crossed = (0.0, 1.0) if dot >= 0 else (1.0, 0.0)

    ends = ((line_b[0], line_b[1]) if straight <= crossed
            else (line_b[1], line_b[0]))
    return [Pair(room_a.name, line_a[0], room_b.name, ends[0]),
            Pair(room_a.name, line_a[1], room_b.name, ends[1])]


def merged_bounds(rooms: dict[str, Room],
                  placed: dict[str, Placement]) -> tuple[float, float, float, float]:
    """The plan extent of everything placed, for framing a view on it."""
    xs: list[float] = []
    ys: list[float] = []
    for name, place in placed.items():
        room = rooms.get(name)
        if not room:
            continue
        for p in room.outline or room.points:
            x, y, _z = place.apply(p.x, p.y, p.z)
            xs.append(x)
            ys.append(y)
    if not xs:
        return (0.0, 0.0, 0.0, 0.0)
    return (min(xs), min(ys), max(xs), max(ys))


def build_merged(rooms: dict[str, Room], placed: dict[str, Placement], cfg,
                 fuse: bool = True):
    """Every placed room, built and moved into the project frame.

    Fused where the kernel will have it, which is the honest answer for a
    stairwell: the flights share their walls, and one body is what the building
    is. Where a fuse fails - two rooms that only touch along an edge, a room
    that overlaps another because a pair was wrong - the rooms are handed back
    side by side in one file rather than not at all, and the caller is told
    which happened.
    """
    from OCP.BRep import BRep_Builder
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec
    from OCP.TopoDS import TopoDS_Compound

    from .solid import CM_TO_MM, BuildError, build_room

    bodies = []
    failed: list[str] = []
    for name in sorted(placed):
        room = rooms.get(name)
        if room is None:
            continue
        try:
            shape = build_room(room, cfg)
        except (BuildError, RuntimeError) as e:
            failed.append(f"{name}: {e}")
            continue
        place = placed[name]
        move = gp_Trsf()
        move.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)),
                         math.radians(place.rotation_deg))
        shift = gp_Trsf()
        shift.SetTranslation(gp_Vec(place.dx * CM_TO_MM, place.dy * CM_TO_MM,
                                    place.dz * CM_TO_MM))
        bodies.append(BRepBuilderAPI_Transform(shape, shift.Multiplied(move),
                                               True).Shape())

    if not bodies:
        raise BuildError("Nothing is placed yet, so there is nothing to merge.")

    if fuse and len(bodies) > 1:
        whole = bodies[0]
        for body in bodies[1:]:
            run = BRepAlgoAPI_Fuse(whole, body)
            run.Build()
            if not run.IsDone():
                whole = None
                break
            whole = run.Shape()
        if whole is not None:
            return whole, failed, "fused"

    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    for body in bodies:
        builder.Add(compound, body)
    return compound, failed, "side by side"
