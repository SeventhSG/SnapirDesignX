"""What each piece of the built body actually is.

A face in the solid is an OCCT ordinal. It changes the moment the body is
rebuilt, and the body is rebuilt every time the operator corrects anything.
That makes a face id useless as the key for a decision meant to be remembered:
remove wall 3, correct something else, and wall 3 is now a different wall.

Survey point names do not move. `P_007` is `P_007` in this build, in the CSV on
disk, and in a re-survey next year. So every element of the body is named after
the points it was built from, and a picked face is attributed back to one of
those names geometrically - the projection `wall_index_at` already does for
walls, generalised to openings, fixtures and stairs.

Face roles used to be decided by which way a face pointed, which cannot tell a
door reveal from a wall, or a stair tread from the ceiling. This can.

No CAD kernel here, on purpose: attribution is plane geometry and stays
testable without OCCT.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .geometry import project_onto_edges
from .model import KIND_LABELS, Role, Room
from .settings import BuildSettings

M_TO_CM = 100.0

# Attribution tolerances, centimetres. Generous: a face centroid sits in the
# middle of the material, not on the surveyed line.
OPENING_PLAN_TOL = 45.0    # how far off the jamb-to-jamb line a reveal can sit
OPENING_Z_TOL = 12.0
FIXTURE_MARGIN = 6.0       # beyond the fixture's own half-width
STAIR_Z_TOL = 6.0


@dataclass
class Element:
    """One addressable piece of the built body."""
    kind: str                                     # wall|floor|ceiling|opening|fixture|stairs
    key: str                                      # stable, built from point names
    label: str                                    # what the inspector shows
    index: int | None = None                      # ordinal, where one exists
    points: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "key": self.key, "label": self.label,
                "index": self.index, "points": self.points}


def wall_key(a: str, b: str) -> str:
    """A wall is named by its two corners, in a fixed order.

    Sorted rather than ring order on purpose: the topology walk's direction is
    not deterministic between the two implementations (see
    tools/compare_dumps.py), and a wall is the same wall whichever way the ring
    was walked.
    """
    lo, hi = sorted((a, b))
    return f"wall:{lo}|{hi}"


def opening_key(op) -> str:
    """An opening is named by the lowest-ordered point of each of its jambs."""
    def anchor(jamb) -> str:
        names = sorted(p.name for p in jamb.points)
        return names[0] if names else f"@{jamb.x:.0f},{jamb.y:.0f}"
    lo, hi = sorted((anchor(op.left), anchor(op.right)))
    return f"opening:{lo}|{hi}"


def elements(room: Room) -> list[Element]:
    """Every addressable element of the body this room would build."""
    out: list[Element] = []
    ring = room.outline
    n = len(ring)

    for i in range(n):
        a, b = ring[i], ring[(i + 1) % n]
        out.append(Element(
            kind="wall", key=wall_key(a.name, b.name),
            label=f"Wall {i + 1} of {n}", index=i, points=[a.name, b.name]))

    if n >= 3:
        out.append(Element(kind="floor", key="floor", label="Floor",
                           points=[p.name for p in ring]))
    if room.ceiling:
        out.append(Element(kind="ceiling", key="ceiling", label="Ceiling",
                           points=[p.name for p in room.ceiling]))

    for i, op in enumerate(room.openings):
        pts = sorted(p.name for p in (op.left.points + op.right.points))
        out.append(Element(
            kind="opening" if op.cuts else "fitting", key=opening_key(op),
            label=KIND_LABELS.get(op.kind, "Opening"),
            index=i, points=pts))

    for p in room.points:
        if p.role is Role.SOCKET:
            out.append(Element(kind="fixture", key=f"fixture:{p.name}",
                               label=f"Socket {p.name}", points=[p.name]))
        elif p.role is Role.PLUMBING:
            out.append(Element(kind="fixture", key=f"fixture:{p.name}",
                               label=f"Pipe {p.name}", points=[p.name]))

    for f, stair in enumerate(room.stairs):
        # One element per shot-to-shot segment, which is a step when the
        # flight was shot at the nosings and half a step when it was traced as
        # the zigzag against the wall.
        for s, (a, b) in enumerate(zip(stair.points, stair.points[1:])):
            step = (s // 2 if stair.kind == "zigzag" else s) + 1
            out.append(Element(
                kind="stairs", key=f"stairs:{stair.points[0].name}#{s}",
                label=f"Step {step} of {stair.steps or step}"
                      + (f" (flight {f + 1})" if len(room.stairs) > 1 else ""),
                index=s, points=[a.name, b.name]))

    for p in room.pervaz:
        out.append(Element(
            kind="pervaz", key=f"pervaz:{p.corner.name}",
            label=f"Skirting {p.height:.0f}×{p.depth:.0f} cm",
            points=p.names))
    return out


def face_element(room: Room, cfg: BuildSettings, centroid_m, normal,
                 table: list[Element] | None = None) -> Element | None:
    """Name the element a picked face belongs to.

    Most specific first: a stair tread also points up, and a door reveal is
    also vertical, so testing the normal first is exactly how the old
    role-by-normal guess got both of them wrong.

    `centroid_m` arrives in metres from the tessellator; everything else here
    is survey centimetres.
    """
    table = elements(room) if table is None else table
    by_key = {e.key: e for e in table}
    x, y, z = (v * M_TO_CM for v in centroid_m)
    nz = normal[2]

    hit = (_stair_at(room, cfg, x, y, z) or _fixture_at(room, cfg, x, y, z)
           or _opening_at(room, x, y, z))
    if hit:
        return by_key.get(hit)

    if nz > 0.9:
        return by_key.get("ceiling")
    if nz < -0.9:
        return by_key.get("floor")

    ring = [p.xy for p in room.outline]
    if len(ring) < 3:
        return None
    edge, _seat, _d = project_onto_edges((x, y), ring)
    a, b = room.outline[edge], room.outline[(edge + 1) % len(room.outline)]
    return by_key.get(wall_key(a.name, b.name))


def _fixture_at(room: Room, cfg: BuildSettings, x: float, y: float, z: float) -> str | None:
    for p in room.points:
        if p.role is Role.SOCKET:
            half, height = cfg.socket_width / 20.0, cfg.socket_height / 10.0
        elif p.role is Role.PLUMBING:
            half = height = cfg.pipe_diameter / 10.0
        else:
            continue
        if (abs(p.z - z) <= height and
                ((p.x - x) ** 2 + (p.y - y) ** 2) ** 0.5 <= half + FIXTURE_MARGIN):
            return f"fixture:{p.name}"
    return None


def _opening_at(room: Room, x: float, y: float, z: float) -> str | None:
    for op in room.openings:
        if not (op.sill - OPENING_Z_TOL <= z <= op.head + OPENING_Z_TOL):
            continue
        span = [(op.left.x, op.left.y), (op.right.x, op.right.y)]
        _i, seat, dist = project_onto_edges((x, y), span)
        if dist <= OPENING_PLAN_TOL:
            return opening_key(op)
    return None


def _stair_at(room: Room, cfg: BuildSettings, x: float, y: float, z: float) -> str | None:
    half = cfg.stair_width / 20.0            # mm setting to cm, halved
    floor_z = room.floor_z if room.floor_z is not None else 0.0
    for stair in room.stairs:
        for s, (a, b) in enumerate(zip(stair.points, stair.points[1:])):
            top = max(a.z, b.z)
            if not (floor_z - STAIR_Z_TOL <= z <= top + STAIR_Z_TOL):
                continue
            _i, _seat, dist = project_onto_edges((x, y), [(a.x, a.y), (b.x, b.y)])
            if dist <= half:
                return f"stairs:{stair.points[0].name}#{s}"
    return None


def wall_edge_for_key(room: Room, key: str) -> int | None:
    """Resolve a stored wall key back to this build's ring edge index.

    Returns None when the corner it names is no longer in the outline - the
    operator dropped the point, or redrew the ring. A decision that no longer
    has anything to apply to is dropped, not applied to the wrong wall.
    """
    ring = room.outline
    for i in range(len(ring)):
        a, b = ring[i], ring[(i + 1) % len(ring)]
        if wall_key(a.name, b.name) == key:
            return i
    return None
