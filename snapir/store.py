"""Project store. Survey folders in, room overrides remembered.

A project is a survey folder plus whatever the operator has told us that the
survey could not: a corrected outline order, a ceiling height nobody shot, a
thickness for one particular wall. The CSVs are never modified.
"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path


def app_dir() -> Path:
    base = os.environ.get("APPDATA") or os.path.expanduser("~/.config")
    d = Path(base) / "SnapirDesignX"
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class RoomOverride:
    """Operator decisions for one room. Absent means nothing was overridden."""
    outline_order: list[str] | None = None       # point names, in ring order
    dropped_points: list[str] = field(default_factory=list)
    ceiling_height: float | None = None          # cm above the floor plane
    wall_thickness: float | None = None          # whole-room override
    face_thickness: dict[str, float] = field(default_factory=dict)  # edge -> cm
    disabled_openings: list[int] = field(default_factory=list)
    # Keyed by element key ("opening:P_012|P_015"), not by position in the
    # openings list: that list is rebuilt from scratch on every correction, so
    # an index silently comes to mean a different opening.
    opening_kind_overrides: dict[str, str] = field(default_factory=dict)
    # Same keying: element key -> "box" | "round".
    opening_shape_overrides: dict[str, str] = field(default_factory=dict)
    fixture_overrides: dict[str, dict] = field(default_factory=dict)
    role_overrides: dict[str, str] = field(default_factory=dict)  # point -> role
    added_segments: list[list[str]] = field(default_factory=list)
    removed_segments: list[list[str]] = field(default_factory=list)
    added_openings: list[dict] = field(default_factory=list)
    # Points the operator constructed rather than measured: a run extended to
    # the corner it stops short of, or where two runs cross. Each carries
    # name, x, y, z, an optional role, and how it was made.
    derived_points: list[dict] = field(default_factory=list)
    # Walls the operator says are not really there, keyed by their corners
    # ("wall:P_003|P_004"). A corner name outlives a rebuild; an edge index
    # does not.
    removed_walls: list[str] = field(default_factory=list)
    built_at: str | None = None
    step_path: str | None = None
    # Same contract as ProjectRecord.extra: an override the other core made
    # and this one has no field for is carried, not dropped.
    extra: dict = field(default_factory=dict, repr=False, compare=False)


@dataclass
class ProjectRecord:
    id: str
    name: str
    folder: str
    created_at: str
    opened_at: str
    thickness: float = 200.0   # mm
    overrides: dict[str, RoomOverride] = field(default_factory=dict)
    # Doors linked between rooms. Only the C++ core acts on these; the
    # reference implementation carries them through untouched so that opening
    # a store the app wrote, and writing it back, never destroys them.
    connections: list[dict] = field(default_factory=list)
    # Anything a newer core wrote that this implementation has no field for.
    # Never interpreted, always written back.
    extra: dict = field(default_factory=dict, repr=False, compare=False)

    def touch(self) -> None:
        self.opened_at = _now()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _override_json(ov: RoomOverride) -> dict:
    return {**ov.extra, **{k: v for k, v in asdict(ov).items() if k != "extra"}}


class Store:
    def __init__(self, path: Path | None = None):
        self.path = path or (app_dir() / "projects.json")
        self.projects: dict[str, ProjectRecord] = {}
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        known = {f.name for f in fields(ProjectRecord)}
        ov_known = {f.name for f in fields(RoomOverride)}
        for pid, p in raw.get("projects", {}).items():
            # Thicknesses used to be stored in centimetres. Anything that small
            # is an old file, not a 2 cm wall.
            if p.get("thickness", 200.0) < 50.0:
                p["thickness"] = p.get("thickness", 20.0) * 10.0
            ov = {}
            for name, v in p.pop("overrides", {}).items():
                o = RoomOverride(**{a: b for a, b in v.items() if a in ov_known})
                o.extra = {a: b for a, b in v.items() if a not in ov_known}
                ov[name] = o
            # The C++ core owns fields this implementation knows nothing about.
            # They are carried through rather than rejected, so that loading a
            # store the shipped app wrote cannot fail, and saving it back
            # cannot quietly destroy a decision made on the other side.
            extra = {k: v for k, v in p.items() if k not in known}
            rec = ProjectRecord(**{k: v for k, v in p.items() if k in known},
                                overrides=ov)
            rec.extra = extra
            self.projects[pid] = rec

    def save(self) -> None:
        payload = {
            "version": 1,
            "projects": {
                pid: {**p.extra, **{k: v for k, v in asdict(p).items() if k != "extra"},
                      "overrides": {k: _override_json(v) for k, v in p.overrides.items()}}
                for pid, p in self.projects.items()
            },
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def create(self, name: str, folder: str) -> ProjectRecord:
        f = Path(folder)
        if not f.is_dir():
            raise FileNotFoundError(f"No such folder: {folder}")
        if not any(p for p in f.glob("*.csv") if "FUKOKU" not in p.stem.upper()):
            raise ValueError("No Leica room CSVs found in that folder.")
        rec = ProjectRecord(
            id=uuid.uuid4().hex[:12], name=name or f.name,
            folder=str(f), created_at=_now(), opened_at=_now(),
        )
        self.projects[rec.id] = rec
        self.save()
        return rec

    def get(self, pid: str) -> ProjectRecord:
        if pid not in self.projects:
            raise KeyError(pid)
        return self.projects[pid]

    def delete(self, pid: str) -> None:
        self.projects.pop(pid, None)
        self.save()

    def override(self, pid: str, room: str) -> RoomOverride:
        proj = self.get(pid)
        return proj.overrides.setdefault(room, RoomOverride())

    def recent(self) -> list[ProjectRecord]:
        return sorted(self.projects.values(), key=lambda p: p.opened_at, reverse=True)
