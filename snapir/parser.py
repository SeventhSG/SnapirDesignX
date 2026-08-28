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
import re
from pathlib import Path

from .model import Issue, Jamb, Opening, Point, Project, Role, Room

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
Z_BAND_TOL = 8.0         # Z readings this close belong to the same plane
FLOOR_TOL = 12.0         # a shot this near the floor datum sits on the slab
CEILING_TOL = 18.0       # ceilings are not flat; allow real sag
MIN_ROOM_HEIGHT = 150.0  # below this, the high band is not a ceiling
MIN_JAMB_SPAN = 40.0     # a jamb has to be taller than this to be an opening
JAMB_XY_TOL = 12.0       # two shots this close in plan are the same vertical


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
            room.station = Point(name, x, y, z, layer, Role.STATION)
            continue

        m = INDEX_RE.search(name)
        pt = Point(name, x, y, z, layer, index=int(m.group(1)) if m else 0)
        room.points.append(pt)

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

    # When the operator tagged the outline on site, that beats any inference
    # we can make. Only fall back to geometry for the untagged exports.
    tagged = [p for p in room.points if _norm(p.layer) == "zemin"]
    for p in tagged:
        p.role = Role.FLOOR
    room.outline_source = "surveyed layer" if tagged else "inferred"

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

    for a, b in zip(jambs[0::2], jambs[1::2]):
        op = Opening(left=a, right=b)
        op.infer_kind(door_sill_max=floor_z + 20.0)
        room.openings.append(op)

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
