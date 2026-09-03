"""Job settings. Everything the survey cannot tell us lives here.

Every length here is in millimetres, the same unit the STEP files are
written in. The survey itself arrives in centimetres; the conversion
happens once, where the geometry is built.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class BuildSettings:
    # Shell dimensions, centimetres. The surveyed surface is always the INNER
    # face, so every offset grows outward and never disturbs the measurement.
    wall_thickness: float = 200.0
    floor_thickness: float = 200.0
    ceiling_thickness: float = 200.0

    # Ceiling handling
    fit_ceiling_plane: bool = True       # False levels it at the mean height
    max_ceiling_tilt_deg: float = 3.0    # degrees
    sockets_merge_gap: float = 5.0       # mm; closer than this, sockets join

    # Openings
    cut_openings: bool = True
    confirm_openings_per_room: bool = True
    door_sill_max: float = 80.0          # sill at or under this reads as a door

    # Stairs. Only the nosing line is shot, so the flight is given a width
    # rather than measured across - there is nothing else to derive it from.
    include_stairs: bool = True
    stair_width: float = 900.0           # mm

    # Wall fittings. The survey gives the rectangle on the wall; how far the
    # thing stands out of it is not measured, so it comes from here.
    include_fittings: bool = True
    boiler_depth: float = 400.0          # mm; a tank, drawn round
    lamp_depth: float = 120.0            # mm
    panel_depth: float = 40.0            # mm, a socket or switch plate

    # Fixtures. Single surveyed points on the Kontak and Su tesisat layers are
    # real building services, so they become real geometry. Every fixture is
    # anchored to the wall it belongs to, never left floating.
    include_fixtures: bool = True

    # "box" adds a back box standing proud of the wall.
    # "hole" cuts a recess into the wall instead.
    socket_mode: str = "box"
    socket_width: float = 80.0       # mm, along the wall
    socket_height: float = 80.0      # mm
    socket_proud: float = 12.0       # mm the box stands out from the inner face
    socket_embed: float = 50.0       # mm the box reaches into the wall
    socket_recess: float = 50.0      # mm deep when the mode is "hole"

    # "stub" adds a pipe coming out of the wall, reaching the surveyed point.
    # "hole" cuts a sleeve through the wall instead.
    pipe_mode: str = "stub"
    pipe_diameter: float = 25.0      # mm
    pipe_length: float = 0.0         # 0 means reach the surveyed point
    pipe_min_length: float = 40.0    # mm, floor for a point shot on the wall
    pipe_embed: float = 50.0         # mm the stub reaches into the wall

    # Export
    units: str = "mm"                    # every length above, and STEP
    step_schema: str = "AP214"
    output_dir: str = "out"

    def to_json(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @classmethod
    def from_json(cls, path: str | Path) -> "BuildSettings":
        return cls(**json.loads(Path(path).read_text(encoding="utf-8")))
