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


@dataclass
class Opening:
    """A door or window, defined by two jambs on the same wall."""
    left: Jamb
    right: Jamb
    kind: str = "unknown"    # "door" | "window", inferred or set by the user

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
