"""Data model for Snapir Design X.

Everything is in centimetres, matching the Leica iCON export.
Conversion to millimetres happens only at STEP export time.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Role(str, Enum):
    """What a measured point represents."""
    FLOOR = "floor"          # room outline corner, on the slab
    CEILING = "ceiling"      # ceiling height shot above a floor corner
    OPENING = "opening"      # door / window jamb, sill or head
    SOCKET = "socket"        # Kontak
    PLUMBING = "plumbing"    # Su tesisat
    CONTROL = "control"      # VTARGET ArUco reference marker
    STATION = "station"      # instrument position
    STAIRS = "stairs"        # one nosing of a climbed flight
    PERVAZ = "pervaz"        # the floor-level shot of a skirting pair
    UNKNOWN = "unknown"      # needs a human decision


@dataclass
class Point:
    name: str
    x: float
    y: float
    z: float
    layer: str
    role: Role = Role.UNKNOWN
    index: int = 0           # shot order, parsed from P_nnn
    # Constructed by the operator - a line extended to where it should reach,
    # or the crossing of two runs - rather than measured by the instrument.
    # Never written back to the survey, and never silently mistaken for a shot.
    derived: bool = False
    source: str = ""         # how it was constructed, for the provenance list
    # The operator said what this point is. Inference must leave it alone -
    # otherwise the next rebuild quietly re-derives the very thing they just
    # corrected, and their decision looks like it never took.
    pinned: bool = False

    @property
    def xy(self) -> tuple[float, float]:
        return (self.x, self.y)


@dataclass
class Jamb:
    """One vertical edge of an opening: a cluster of points sharing an XY."""
    x: float
    y: float
    z_bottom: float
    z_top: float
    points: list[Point] = field(default_factory=list)


# What a rectangle surveyed on a wall turns out to be.
#
# The survey cannot tell these apart: a boiler, a window and a switch panel
# are all four corners on a wall. Only the operator knows, so the classifier
# guesses a door or a window from the sill height and the rest are theirs to
# set. Doors and windows are cut through the wall; the others are fittings
# that hang on it and stand out into the room.
CUT_KINDS = ("door", "window")
FITTING_KINDS = ("boiler", "socket", "lamp", "panel", "empty")
OPENING_KINDS = CUT_KINDS + FITTING_KINDS

# What each one is called on site, for the operator's own layer names.
KIND_LABELS = {
    "door": "Door", "window": "Window",
    "boiler": "Boiler",          # бойлер
    "socket": "Socket",          # щепсел
    "lamp": "Wall lamp",         # лампа
    "panel": "Panel",
    "empty": "Nothing here",
}


@dataclass
class Opening:
    """A rectangle on a wall: two jambs, a sill and a head.

    Doors and windows are holes. A boiler, a socket panel or a wall lamp is
    the same rectangle in the survey and a solid standing in the room, so what
    gets built is decided by `kind`, not by the shape.
    """
    left: Jamb
    right: Jamb
    kind: str = "unknown"    # one of OPENING_KINDS, inferred or set by the user

    @property
    def cuts(self) -> bool:
        """True when this rectangle is a hole rather than a fitting."""
        return self.kind in CUT_KINDS or self.kind == "unknown"

    @property
    def height(self) -> float:
        return self.head - self.sill

    @property
    def sill(self) -> float:
        return min(self.left.z_bottom, self.right.z_bottom)

    @property
    def head(self) -> float:
        return max(self.left.z_top, self.right.z_top)

    @property
    def width(self) -> float:
        return ((self.left.x - self.right.x) ** 2 + (self.left.y - self.right.y) ** 2) ** 0.5

    def infer_kind(self, door_sill_max: float = 20.0) -> str:
        self.kind = "door" if self.sill <= door_sill_max else "window"
        return self.kind


@dataclass
class Stair:
    """A flight climbed in survey order: one point per step nosing.

    Nothing pairs left and right edges here the way a jamb does — the
    surveyor walks up shooting one line of nosings, so a flight is just that
    line, in order.
    """
    points: list[Point] = field(default_factory=list)
    # How the flight was traced: one shot per nosing, or the zigzag where the
    # steps meet the wall, corner by corner. Two shots make up one step in the
    # second case, so the step count cannot be read off the point count.
    kind: str = "nosings"          # "nosings" | "zigzag"
    steps: int = 0                 # risers climbed

    @property
    def rise(self) -> float:
        return abs(self.points[-1].z - self.points[0].z) if len(self.points) >= 2 else 0.0

    @property
    def going(self) -> float:
        """Plan length of the flight, nosing to nosing."""
        return sum(
            ((self.points[i + 1].x - self.points[i].x) ** 2 +
             (self.points[i + 1].y - self.points[i].y) ** 2) ** 0.5
            for i in range(len(self.points) - 1)
        )


@dataclass
class Pervaz:
    """Skirting, shot as a pair at one corner.

    The surveyor puts one shot on the wall just above the board and one at
    floor level on its outer face. The diagonal between them is the whole
    measurement: the rise is the board's height, the plan offset is how far it
    stands proud of the wall behind it.

    The floor-level shot keeps the corner, since that is the one that measured
    the floor. Neither shot is moved.
    """
    corner: Point            # the floor-level shot: this is the outline corner
    wall: Point              # the shot on the wall above the board
    height: float            # cm
    depth: float             # cm the board stands proud of the wall

    @property
    def names(self) -> list[str]:
        return [self.corner.name, self.wall.name]


@dataclass
class Issue:
    """Something the app cannot decide on its own."""
    severity: str            # "error" | "warning" | "info"
    code: str
    message: str
    points: list[str] = field(default_factory=list)


@dataclass
class Room:
    name: str
    source: str                                  # path of the .csv it came from
    points: list[Point] = field(default_factory=list)
    outline: list[Point] = field(default_factory=list)   # floor polygon, shot order
    ceiling: list[Point] = field(default_factory=list)
    openings: list[Opening] = field(default_factory=list)
    stairs: list[Stair] = field(default_factory=list)
    pervaz: list[Pervaz] = field(default_factory=list)
    controls: list[Point] = field(default_factory=list)
    # A room can be surveyed from several setups, each with its own panorama.
    # Distinct positions only: the instrument is written out again every time
    # it is re-levelled without being moved.
    stations: list[Point] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)

    # set by the user or by app settings, not present in the survey data
    # "drawn" when the surveyor's own lines describe the ring, which is the
    # only source that needs no guessing at all.
    outline_source: str = "inferred"   # "drawn" | "surveyed layer" | "inferred"
    segments: list[tuple[str, str]] = field(default_factory=list)
    links: list[tuple[str, str]] = field(default_factory=list)
    floor_z: Optional[float] = None
    ceiling_z: Optional[float] = None
    wall_thickness: Optional[float] = None
    ceiling_height_override: Optional[float] = None

    @property
    def flat(self) -> str:
        """'Daire 53 - Salon' -> 'Daire 53'."""
        return self.name.split(" - ")[0].strip() if " - " in self.name else ""

    @property
    def label(self) -> str:
        return self.name.split(" - ", 1)[1].strip() if " - " in self.name else self.name

    @property
    def unresolved(self) -> list[Point]:
        return [p for p in self.points if p.role is Role.UNKNOWN]

    @property
    def has_errors(self) -> bool:
        return any(i.severity == "error" for i in self.issues)

    def ceiling_height(self) -> Optional[float]:
        if self.ceiling_height_override is not None:
            return self.ceiling_height_override
        if self.ceiling_z is not None and self.floor_z is not None:
            return self.ceiling_z - self.floor_z
        if not self.ceiling:
            return None
        return sum(p.z for p in self.ceiling) / len(self.ceiling) - (self.floor_z or 0.0)


@dataclass
class Project:
    name: str = "Untitled"
    rooms: list[Room] = field(default_factory=list)

    def by_flat(self) -> dict[str, list[Room]]:
        out: dict[str, list[Room]] = {}
        for r in self.rooms:
            out.setdefault(r.flat, []).append(r)
        return out
