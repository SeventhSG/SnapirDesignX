"""Reader for Leica iCON trades CSV exports (iCS50 and friends).

The CSV is the authoritative source. The accompanying _2D.dxf / _3D.dxf hold
only the segments the operator happened to draw on site, duplicated across
three sheet frames, so they are deliberately ignored.

File shape:
    Kimlik;X (cm);Y (cm);Z (cm);Katman
    LEICA_ICON_TOOL;166.86;-459.32;127.29
    P_001;0.00;0.00;0.00;Zemin
    ...
"""
from __future__ import annotations

import csv
import math
import re
from pathlib import Path

from .model import (Issue, Jamb, Opening, Pervaz, Point, Project, Role, Room,
                    Stair)
from .topology import build as build_topology, read_segments

# Layer names as written by iCON trades, and what they mean.
LAYER_ROLES = {
    "zemin": Role.FLOOR,
    "kontak": Role.SOCKET,
    "su tesisat": Role.PLUMBING,
    "kontrol noktalari": Role.CONTROL,
    "kontrol noktaları": Role.CONTROL,
}

# Layers that carry no meaning: the operator left the default on.
NEUTRAL_LAYERS = {"", "katman 0", "0", "layer 0"}

STATION_RE = re.compile(r"(LEICA|LEİCA).*TOOL", re.IGNORECASE)
INDEX_RE = re.compile(r"(\d+)")

# Tolerances, all in centimetres.
CEILING_XY_TOL = 30.0    # a ceiling shot sits this close to a floor corner
MAX_OPENING_WIDTH = 320.0  # cm; wider than this is two walls, not one opening
Z_BAND_TOL = 8.0         # Z readings this close belong to the same plane
STATION_MERGE_CM = 5.0   # re-levelled in place, not a new setup
FLOOR_TOL = 12.0         # a shot this near the floor datum sits on the slab
CEILING_TOL = 18.0       # ceilings are not flat; allow real sag
MIN_ROOM_HEIGHT = 150.0  # below this, the high band is not a ceiling
MIN_JAMB_SPAN = 40.0     # a jamb has to be taller than this to be an opening
JAMB_XY_TOL = 12.0       # two shots this close in plan are the same vertical

# A flight climbs at a near-constant riser and tread, shot in survey order as
# the surveyor walks up. Nothing else in a room survey produces that
# signature, so it is recognised without asking the operator.
STAIR_MIN_STEPS = 3      # fewer looks like noise, not a staircase
STAIR_RISER_MIN = 10.0   # cm
STAIR_RISER_MAX = 22.0   # cm
STAIR_TREAD_MIN = 15.0   # cm, plan distance across one tread
STAIR_TREAD_MAX = 40.0   # cm
STAIR_RISER_TOL = 5.0    # cm, how much the riser may vary step to step
STAIR_RUN_GAP = 3        # survey-order gap that still counts as the same flight
STAIR_FLAT_TOL = 5.0     # cm; a tread move rises no more than this
STAIR_PLUMB_TOL = 8.0    # cm; a riser move travels no further in plan than this

# Pervaz: skirting, shot as two points at one corner. Nothing else in a survey
# puts two floor shots this close together at two different heights.
PERVAZ_DEPTH_MIN = 0.3   # cm the board stands proud of the wall
PERVAZ_DEPTH_MAX = 8.0   # cm; beyond this it is not a skirting board
PERVAZ_HEIGHT_MIN = 3.0  # cm
PERVAZ_HEIGHT_MAX = 30.0  # cm


def _f(v: str) -> float:
    return float(v.replace(",", ".").strip())


def _norm(v: str) -> str:
    return v.strip().lower()


def read_room(path: str | Path) -> Room:
    """Parse one room CSV into a classified Room."""
    path = Path(path)
    room = Room(name=path.stem, source=str(path))

    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh, delimiter=";"))

    for row in rows[1:]:
        if not row or not row[0].strip():
            continue
        name = row[0].strip()
        try:
            x, y, z = _f(row[1]), _f(row[2]), _f(row[3])
        except (IndexError, ValueError):
            continue
        layer = row[4].strip() if len(row) > 4 else ""

        if STATION_RE.search(name):
            if not any(math.dist((s.x, s.y, s.z), (x, y, z)) < STATION_MERGE_CM
                       for s in room.stations):
                room.stations.append(Point(name, x, y, z, layer, Role.STATION))
            continue

        m = INDEX_RE.search(name)
        pt = Point(name, x, y, z, layer, index=int(m.group(1)) if m else 0)
        room.points.append(pt)

    room.segments = read_segments(path)
    _classify(room)
    return room


def _z_datums(room: Room) -> tuple[float | None, float | None]:
    """Find the floor and ceiling planes by clustering Z values.

    The instrument is not always levelled to the slab. One surveyor left the
    origin at instrument height, putting the whole floor at Z = -126.66, so a
    hardcoded zero is not safe. The floor is simply the lowest dense band of
    readings, the ceiling the highest one far enough above it.
    """
    zs = sorted(p.z for p in room.points)
    if not zs:
        return None, None

    bands: list[list[float]] = []
    for z in zs:
        if bands and z - bands[-1][-1] <= Z_BAND_TOL:
            bands[-1].append(z)
        else:
            bands.append([z])

    dense = [b for b in bands if len(b) >= 3] or bands
    floor = sum(dense[0]) / len(dense[0])

    ceiling = None
    for b in reversed(bands):
        mean = sum(b) / len(b)
        if len(b) >= 2 and mean - floor >= MIN_ROOM_HEIGHT:
            ceiling = mean
            break
    return floor, ceiling


def _classify(room: Room) -> None:
    """Assign a Role to every point, then build outline / ceiling / openings.

    Both surveying styles in the field data reduce to the same operation:
    cluster the shots by plan position, then read each cluster's vertical
    extent. A cluster that runs floor to ceiling is a room corner, whether the
    operator shot it as one top-and-bottom pair or walked the floor first and
    the ceiling after. A cluster that stops short of the ceiling is a door or
    window jamb.
    """
    for p in room.points:
        key = _norm(p.layer)
        if p.name.upper().startswith("VTARGET"):
            p.role = Role.CONTROL
        elif key in LAYER_ROLES and key not in ("zemin",):
            p.role = LAYER_ROLES[key]
        else:
            p.role = Role.UNKNOWN

    floor_z, ceil_z = _z_datums(room)
    room.floor_z = floor_z
    room.ceiling_z = ceil_z

    if floor_z is None:
        return

    # The surveyor's own lines beat anything we could infer from shot order.
    if room.segments and _from_drawn_lines(room):
        _validate(room)
        return

    # When the operator tagged the outline on site, that beats any inference
    # we can make. Only fall back to geometry for the untagged exports.
    tagged = [p for p in room.points if _norm(p.layer) == "zemin"]
    for p in tagged:
        p.role = Role.FLOOR
    room.outline_source = "surveyed layer" if tagged else "inferred"

    # Before anything is clustered or ringed: a skirting pair is two floor
    # shots at one corner, and both of them landing in the outline is what
    # doubles the ring.
    _detect_pervaz(room)

    # Ceiling shots must be claimed before anything is clustered. A ceiling
    # corner often lands within a few centimetres of a window jamb in plan, and
    # if the two merge the cluster spans floor to ceiling and gets read as an
    # opening the width of the whole wall.
    if ceil_z is not None:
        floor_pts = [q for q in room.points if q.role is Role.FLOOR] or tagged
        for q in room.points:
            if q.role is not Role.UNKNOWN or abs(q.z - ceil_z) > CEILING_TOL:
                continue
            if any(_dist2d(q, f) <= CEILING_XY_TOL for f in floor_pts):
                q.role = Role.CEILING

    clusters = _cluster_xy([p for p in room.points if p.role is Role.UNKNOWN])
    jambs: list[Jamb] = []

    for c in clusters:
        lo = min(p.z for p in c)
        hi = max(p.z for p in c)
        at_floor = abs(lo - floor_z) <= FLOOR_TOL
        at_ceiling = ceil_z is not None and abs(hi - ceil_z) <= CEILING_TOL

        if at_floor and at_ceiling and not tagged:
            _mark_corner(c, floor_z, ceil_z)
        elif at_floor and not tagged and ceil_z is None and hi - lo <= FLOOR_TOL:
            for p in c:
                p.role = Role.FLOOR
        elif at_ceiling and not at_floor and hi - lo <= CEILING_TOL:
            for p in c:
                p.role = Role.CEILING
        elif hi - lo > MIN_JAMB_SPAN:
            jambs.append(Jamb(
                x=sum(p.x for p in c) / len(c),
                y=sum(p.y for p in c) / len(c),
                z_bottom=lo, z_top=hi, points=c,
            ))
            for p in c:
                p.role = Role.OPENING
        # anything else stays UNKNOWN and is surfaced for the operator

    for a, b in _pair_jambs(jambs, [q.xy for q in room.points if q.role is Role.FLOOR]):
        op = Opening(left=a, right=b)
        op.infer_kind(door_sill_max=floor_z + 20.0)
        room.openings.append(op)

    # Depth shots first: they sit inside a rectangle and would otherwise be
    # loose UNKNOWN points for the stair scan to trip over.
    _attach_depth_points(room)
    _detect_stairs(room)
    room.stairs = _group_stairs([p for p in room.points if p.role is Role.STAIRS])

    room.outline = sorted(
        (p for p in room.points if p.role is Role.FLOOR), key=lambda p: p.index
    )
    room.ceiling = sorted(
        (p for p in room.points if p.role is Role.CEILING), key=lambda p: p.index
    )
    room.controls = [p for p in room.points if p.role is Role.CONTROL]
    _validate(room)


def _mark_corner(cluster: list[Point], floor_z: float, ceil_z: float) -> None:
    """Split a full-height corner cluster into its floor and ceiling shots."""
    order = min(p.index for p in cluster)
    for p in cluster:
        p.role = Role.FLOOR if abs(p.z - floor_z) < abs(p.z - ceil_z) else Role.CEILING
        if p.role is Role.FLOOR:
            p.index = order          # keep the corner in survey order


def _cluster_xy(points: list[Point], tol: float = JAMB_XY_TOL) -> list[list[Point]]:
    """Group shots that share a plan position, preserving survey order."""
    clusters: list[list[Point]] = []
    for p in sorted(points, key=lambda p: p.index):
        for c in clusters:
            if _dist2d(p, c[0]) <= tol:
                c.append(p)
                break
        else:
            clusters.append([p])
    return clusters




def _detect_pervaz(room: Room) -> None:
    """Fold every skirting pair back into a single outline corner.

    Left alone, both shots are floor corners and the ring doubles: eight
    corners where the room has four, a two-centimetre zigzag at each one, and
    a floor plane fitted through two different heights. The room still
    validates, which is the dangerous part.

    The pair is recognised by its own geometry - two floor shots a
    board's-depth apart in plan and a board's-height apart in Z. The
    floor-level shot keeps the corner, because it is the one that measured
    the floor; the wall shot leaves the outline and is remembered as the
    skirting, standing proud by the distance between them.

    Nothing is moved. An earlier version snapped the wall shot down to floor
    level, which read well and destroyed the height difference the pair is
    recognised by - so a second pass found nothing and every skirting record
    vanished on the first correction the operator made.
    """
    # Both roles are candidates, not just FLOOR: after the first pass one of
    # every pair is already PERVAZ, and a detector that could not see it would
    # fail to re-pair and drop the board on the next rebuild.
    floor_pts = sorted((p for p in room.points
                        if p.role in (Role.FLOOR, Role.PERVAZ)),
                       key=lambda p: p.index)
    taken: set[str] = set()

    for i, a in enumerate(floor_pts):
        if a.name in taken or a.pinned:
            continue
        for b in floor_pts[i + 1:]:
            if b.name in taken or b.pinned:
                continue
            dz = abs(a.z - b.z)
            depth = _dist2d(a, b)
            if not (PERVAZ_DEPTH_MIN <= depth <= PERVAZ_DEPTH_MAX
                    and PERVAZ_HEIGHT_MIN <= dz <= PERVAZ_HEIGHT_MAX):
                continue
            wall, outer = (a, b) if a.z > b.z else (b, a)
            room.pervaz.append(Pervaz(corner=outer, wall=wall,
                                      height=dz, depth=depth))
            outer.role = Role.FLOOR
            wall.role = Role.PERVAZ
            taken.add(a.name)
            taken.add(b.name)
            break


# A shot in the middle of a wall rectangle, standing off the wall. Nothing else
# lands inside a rectangle's own span at its own height.
DEPTH_MAX = 200.0        # cm; further out than this is not a fitting on a wall
DEPTH_MIN = 0.5          # cm; closer than this is a shot on the wall itself
DEPTH_EDGE_TOL = 5.0     # cm the shot may sit outside the rectangle's width


def _attach_depth_points(room: Room) -> None:
    """Give every rectangle the depth its middle shot measured.

    The surveyor marks a thing that sticks out of the wall by shooting the
    rectangle and then one point in the middle of it. The distance from that
    point to the wall is how far the thing stands out - measured, not assumed,
    which is the whole reason to take the shot.

    Without one the fitting still builds, on the depth in settings.
    """
    for op in room.openings:
        ax, ay = op.left.x, op.left.y
        bx, by = op.right.x, op.right.y
        dx, dy = bx - ax, by - ay
        length = (dx * dx + dy * dy) ** 0.5
        if length < 1.0:
            continue
        tx, ty = dx / length, dy / length

        best: tuple[float, Point] | None = None
        for p in room.points:
            if p.role is not Role.UNKNOWN or p.pinned:
                continue
            if not (op.sill <= p.z <= op.head):
                continue
            along = (p.x - ax) * tx + (p.y - ay) * ty
            if not (-DEPTH_EDGE_TOL <= along <= length + DEPTH_EDGE_TOL):
                continue
            off = abs((p.x - ax) * -ty + (p.y - ay) * tx)
            if not (DEPTH_MIN <= off <= DEPTH_MAX):
                continue
            if best is None or off < best[0]:
                best = (off, p)

        if best is not None:
            op.depth, op.depth_point = best[0], best[1].name
            best[1].role = Role.DEPTH
            # The shot itself says what this is. Nobody measures how far a
            # doorway sticks out of a wall, so a rectangle with a depth shot is
            # a thing standing on the wall - and the wall behind it stays
            # whole. An operator's own choice still overrides this later.
            if op.kind in ("door", "window", "unknown"):
                op.kind = "object"


def _step_move(a: Point, b: Point) -> str | None:
    """What one shot-to-shot move is, if it is part of a flight at all.

    Two ways a surveyor traces a staircase, and the app must not care which:

    `nosing`  one shot per step at the front edge, so every move goes forward
              and up at once.
    `tread` / `riser`
              the zigzag where the steps meet the wall, shot corner by corner,
              so moves alternate between flat along a tread and straight up a
              riser. This is what comes back when only the side wall is shot.
    """
    dz = b.z - a.z
    dxy = _dist2d(a, b)
    riser = STAIR_RISER_MIN <= abs(dz) <= STAIR_RISER_MAX
    tread = STAIR_TREAD_MIN <= dxy <= STAIR_TREAD_MAX
    if riser and tread:
        return "nosing"
    if riser and dxy <= STAIR_PLUMB_TOL:
        return "riser"
    if tread and abs(dz) <= STAIR_FLAT_TOL:
        return "tread"
    return None


def _stair_run(pts: list[Point], start: int) -> tuple[int, int]:
    """Longest coherent flight starting at `start`.

    Returns (one past the last point of the run, how many risers it climbed).
    A flight is either all nosing moves or a clean alternation of treads and
    risers - never a mixture, which is what noise looks like.
    """
    mode = prev = None
    climbing = last_rise = None
    risers = 0
    j = start
    while j < len(pts) - 1:
        move = _step_move(pts[j], pts[j + 1])
        if move is None:
            break
        if mode is None:
            mode = "nosing" if move == "nosing" else "zigzag"
        if (mode == "nosing") != (move == "nosing"):
            break
        if mode == "zigzag" and move == prev:
            break                       # two treads or two risers in a row
        if move in ("nosing", "riser"):
            dz = pts[j + 1].z - pts[j].z
            if climbing is None:
                climbing = dz > 0
            elif (dz > 0) != climbing:
                break                   # a flight does not change its mind
            if last_rise is not None and abs(abs(dz) - last_rise) > STAIR_RISER_TOL:
                break
            last_rise = abs(dz)
            risers += 1
        prev = move
        j += 1
    return (j + 1 if j > start else start + 1), risers


def _detect_stairs(room: Room) -> None:
    """Tag a stepped run of leftover shots as Role.STAIRS.

    Works in survey order, not plan clusters: a flight advances as it climbs,
    so its shots never land in the same XY cluster the way a jamb's do. A run
    counts once it climbs at least STAIR_MIN_STEPS risers at a consistent
    height; anything shorter or less regular is left UNKNOWN, same as any
    other unresolved shot, for the operator to tag by hand.
    """
    pts = sorted((p for p in room.points
                  if p.role is Role.UNKNOWN and not p.pinned), key=lambda p: p.index)
    i = 0
    while i < len(pts) - 1:
        end, risers = _stair_run(pts, i)
        if risers >= STAIR_MIN_STEPS:
            for p in pts[i:end]:
                p.role = Role.STAIRS
            i = end
        else:
            i += 1


def _run_shape(points: list[Point]) -> tuple[str, int]:
    """How a tagged flight was shot, and how many risers it climbs."""
    moves = [_step_move(a, b) for a, b in zip(points, points[1:])]
    kind = "nosings" if any(m == "nosing" for m in moves) else "zigzag"
    return kind, sum(1 for m in moves if m in ("nosing", "riser"))


def _group_stairs(points: list[Point]) -> list[Stair]:
    """Split every Role.STAIRS point into flights by survey-order gaps.

    Covers both the auto-detected run and any points the operator promoted or
    demoted by hand afterwards - grouping is all that is needed once the role
    is already decided.
    """
    pts = sorted(points, key=lambda p: p.index)
    if not pts:
        return []
    runs: list[list[Point]] = [[pts[0]]]
    for p in pts[1:]:
        if p.index - runs[-1][-1].index <= STAIR_RUN_GAP:
            runs[-1].append(p)
        else:
            runs.append([p])
    out = []
    for r in runs:
        if len(r) < 2:
            continue
        kind, risers = _run_shape(r)
        out.append(Stair(points=r, kind=kind, steps=risers))
    return out


def _validate(room: Room) -> None:
    from .geometry import polygon_area, self_intersections

    n = len(room.outline)
    if n < 3:
        room.issues.append(Issue(
            "error", "no-outline",
            f"Only {n} floor point(s) found. Cannot form a room outline."))
        return

    crossings = self_intersections([p.xy for p in room.outline])
    if crossings:
        room.issues.append(Issue(
            "error", "self-intersecting",
            f"Outline crosses itself in {len(crossings)} place(s). Usually a "
            "re-shoot appended after the loop was closed. Reorder or drop "
            "points in the plan view.",
            points=sorted({room.outline[i].name for pair in crossings for i in pair})))

    area = polygon_area([p.xy for p in room.outline]) / 10_000
    if area < 0.5:
        room.issues.append(Issue(
            "warning", "tiny-area", f"Outline encloses only {area:.2f} m2."))

    if room.ceiling_z is None:
        room.issues.append(Issue(
            "warning", "no-ceiling",
            "No ceiling shots. A height must be supplied before this room can "
            "be built."))

    stray = [p for p in room.points if p.role is Role.UNKNOWN]
    if stray:
        room.issues.append(Issue(
            "info", "unclassified",
            f"{len(stray)} point(s) could not be classified automatically.",
            points=[p.name for p in stray]))


def _dist2d(a: Point, b: Point) -> float:
    return ((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5


def read_project(folder: str | Path, name: str = "") -> Project:
    """Read every room CSV in a folder, skipping the _FUKOKU report variants."""
    folder = Path(folder)
    proj = Project(name=name or folder.name)
    for p in sorted(folder.glob("*.csv")):
        if "FUKOKU" in p.stem.upper():
            continue
        proj.rooms.append(read_room(p))
    return proj


def _pair_jambs(jambs: list[Jamb], ring) -> list[tuple[Jamb, Jamb]]:
    """Match jambs into openings, but only where they share a wall.

    Pairing in survey order alone is not safe: an operator can shoot one side
    of a door, wander to a window on another wall, then come back. Two jambs
    only form an opening when they sit on the same wall run, at a believable
    width, and span a similar height.
    """
    from .geometry import project_onto_edges

    if len(jambs) < 2 or len(ring) < 3:
        return []

    edge_of = {}
    for j in jambs:
        idx, _seat, _d = project_onto_edges((j.x, j.y), list(ring))
        edge_of[id(j)] = idx

    used: set[int] = set()
    pairs: list[tuple[Jamb, Jamb]] = []
    for i, a in enumerate(jambs):
        if i in used:
            continue
        best, best_d = None, None
        for k in range(i + 1, len(jambs)):
            if k in used:
                continue
            b = jambs[k]
            if edge_of[id(a)] != edge_of[id(b)]:
                continue
            width = ((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5
            if not 25.0 <= width <= MAX_OPENING_WIDTH:
                continue
            if abs(a.z_top - b.z_top) > 25.0 or abs(a.z_bottom - b.z_bottom) > 40.0:
                continue
            if best_d is None or width < best_d:
                best, best_d = k, width
        if best is not None:
            used.add(i)
            used.add(best)
            pairs.append((a, jambs[best]))
    return pairs


def rebuild(room: Room) -> None:
    """Re-derive the room from whatever roles its points currently carry.

    The classifier's guess is a starting point, not a verdict. When the
    operator says a point is a socket rather than a jamb, everything that was
    inferred from the old reading has to be worked out again: the outline, the
    ceiling set, and the openings.
    """
    # Skirting pairs first: one of the two shots leaves the outline, so this
    # has to settle before the ring is read off the floor roles.
    room.pervaz = []
    _detect_pervaz(room)

    room.outline = sorted(
        (p for p in room.points if p.role is Role.FLOOR), key=lambda p: p.index)
    room.ceiling = sorted(
        (p for p in room.points if p.role is Role.CEILING), key=lambda p: p.index)
    room.controls = [p for p in room.points if p.role is Role.CONTROL]

    room.openings = []
    marked = [p for p in room.points if p.role is Role.OPENING]
    if len(marked) >= 4:
        jambs = []
        for c in _cluster_xy(marked):
            lo, hi = min(p.z for p in c), max(p.z for p in c)
            if len(c) >= 2 and hi - lo > MIN_JAMB_SPAN:
                jambs.append(Jamb(
                    x=sum(p.x for p in c) / len(c), y=sum(p.y for p in c) / len(c),
                    z_bottom=lo, z_top=hi, points=c))
        floor_z = room.floor_z or 0.0
        for a, b in _pair_jambs(jambs, [p.xy for p in room.outline]):
            op = Opening(left=a, right=b)
            op.infer_kind(door_sill_max=floor_z + 20.0)
            room.openings.append(op)

    # Depth shots first: they sit inside a rectangle and would otherwise be
    # loose UNKNOWN points for the stair scan to trip over.
    _attach_depth_points(room)
    _detect_stairs(room)
    room.stairs = _group_stairs([p for p in room.points if p.role is Role.STAIRS])

    room.issues = []
    _validate(room)


ASSIGNABLE = ("floor", "ceiling", "opening", "socket", "plumbing",
              "control", "unknown", "stairs", "pervaz", "depth")


def apply_roles(room: Room, roles: dict[str, str]) -> None:
    """Set point roles by name, then rebuild everything derived from them.

    A point the operator has named is pinned: the detectors that run during
    the rebuild skip it, so their guess cannot quietly overwrite the answer
    they just gave.
    """
    for p in room.points:
        wanted = roles.get(p.name)
        if wanted in ASSIGNABLE:
            p.role = Role(wanted)
            p.pinned = True
    rebuild(room)


def _from_drawn_lines(room: Room) -> bool:
    """Take the room straight from the lines the surveyor drew.

    Returns False when the file has no closed ring, in which case the caller
    falls back to inferring one.
    """
    coords = {p.name: (p.x, p.y, p.z) for p in room.points}
    topo = build_topology(room.segments, coords)
    if len(topo.floor_ring) < 3:
        return False

    # A ring only counts as the floor if it sits on the floor. Without this a
    # broken floor ring lets the ceiling ring take its place, and the room
    # would be built from the wrong loop at the right corner count.
    mean_z = sum(coords[n][2] for n in topo.floor_ring) / len(topo.floor_ring)
    if room.floor_z is not None and abs(mean_z - room.floor_z) > 40.0:
        return False

    by_name = {p.name: p for p in room.points}
    room.links = topo.links
    room.outline_source = "drawn"

    for name in topo.floor_ring:
        by_name[name].role = Role.FLOOR
    for name in topo.ceiling_ring:
        by_name[name].role = Role.CEILING

    room.outline = [by_name[n] for n in topo.floor_ring]
    room.ceiling = [by_name[n] for n in topo.ceiling_ring]

    # Each opening was drawn as a closed loop: two jambs, a sill line and a
    # head line. Split the loop back into its two verticals.
    for loop in topo.openings:
        pts = [by_name[n] for n in loop if n in by_name]
        if len(pts) < 4:
            continue
        clusters = _cluster_xy(pts)
        jambs = [
            Jamb(x=sum(q.x for q in c) / len(c), y=sum(q.y for q in c) / len(c),
                 z_bottom=min(q.z for q in c), z_top=max(q.z for q in c), points=c)
            for c in clusters
            if len(c) >= 2 and (max(q.z for q in c) - min(q.z for q in c)) > MIN_JAMB_SPAN
        ]
        if len(jambs) == 2:
            op = Opening(left=jambs[0], right=jambs[1])
            op.infer_kind(door_sill_max=(room.floor_z or 0.0) + 8.0)
            room.openings.append(op)
            for q in pts:
                q.role = Role.OPENING

    # Anything the drawn lines did not account for keeps its layer meaning.
    for p in room.points:
        if p.role is not Role.UNKNOWN:
            continue
        key = _norm(p.layer)
        if p.name.upper().startswith("VTARGET"):
            p.role = Role.CONTROL
        elif key in LAYER_ROLES:
            p.role = LAYER_ROLES[key]

    # A surveyor who never closed a loop around a door still shot its jambs.
    # Whatever the drawn lines did not account for gets the same clustering the
    # inferred path uses, so an opening is not lost purely because no line was
    # drawn round it. This runs after the layer meanings above, so a socket or a
    # pipe is never mistaken for a jamb. Points that do not pair stay UNKNOWN
    # and are still reported to the operator.
    leftover = [p for p in room.points if p.role is Role.UNKNOWN]
    if leftover and len(room.outline) >= 3:
        jambs = []
        for c in _cluster_xy(leftover):
            lo, hi = min(q.z for q in c), max(q.z for q in c)
            if len(c) >= 2 and hi - lo > MIN_JAMB_SPAN:
                jambs.append(Jamb(
                    x=sum(q.x for q in c) / len(c), y=sum(q.y for q in c) / len(c),
                    z_bottom=lo, z_top=hi, points=c))
        for a, b in _pair_jambs(jambs, [p.xy for p in room.outline]):
            op = Opening(left=a, right=b)
            op.infer_kind(door_sill_max=(room.floor_z or 0.0) + 20.0)
            room.openings.append(op)
            for q in a.points + b.points:
                q.role = Role.OPENING

    # Depth shots first: they sit inside a rectangle and would otherwise be
    # loose UNKNOWN points for the stair scan to trip over.
    _attach_depth_points(room)
    _detect_stairs(room)
    room.stairs = _group_stairs([p for p in room.points if p.role is Role.STAIRS])

    room.controls = [p for p in room.points if p.role is Role.CONTROL]
    return True


def reread_topology(room: Room) -> None:
    """Re-derive the room after its lines were edited."""
    for p in room.points:
        p.role = Role.UNKNOWN
    room.outline_source = "inferred"
    room.outline = []
    room.ceiling = []
    room.openings = []
    room.stairs = []
    room.pervaz = []
    room.links = []
    room.issues = []
    if not _from_drawn_lines(room):
        _classify(room)
    else:
        _validate(room)
