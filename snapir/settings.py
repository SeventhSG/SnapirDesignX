"""Job settings. Everything the survey cannot tell us lives here."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class BuildSettings:
    # Shell dimensions, centimetres. The surveyed surface is always the INNER
    # face, so every offset grows outward and never disturbs the measurement.
    wall_thickness: float = 20.0
    floor_thickness: float = 20.0
    ceiling_thickness: float = 20.0

    # Ceiling handling
    fit_ceiling_plane: bool = True       # False levels it at the mean height
    max_ceiling_tilt_deg: float = 3.0    # beyond this, level it and flag

    # Openings
    cut_openings: bool = True
    confirm_openings_per_room: bool = True
    door_sill_max: float = 20.0          # sill at or under this reads as a door

    # Fixtures. Single surveyed points on the Kontak and Su tesisat layers are
    # real building services, so they are built as real geometry rather than
    # dropped: a socket becomes a back box on the wall face, a plumbing point
    # becomes a pipe stub coming out of the wall.
    include_fixtures: bool = True
    socket_width: float = 8.0        # cm, along the wall
    socket_height: float = 8.0       # cm
    socket_depth: float = 2.5        # cm, proud of the inner face
    pipe_diameter: float = 2.5       # cm
    pipe_length: float = 6.0         # cm, proud of the inner face

    # Export
    export_units: str = "mm"             # STEP is written in millimetres
    step_schema: str = "AP214"
    output_dir: str = "out"

    def to_json(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @classmethod
    def from_json(cls, path: str | Path) -> "BuildSettings":
        return cls(**json.loads(Path(path).read_text(encoding="utf-8")))
