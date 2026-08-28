"""Local API for the desktop frontend.

Runs as a private sidecar process on a loopback port the user never sees.
Everything heavy (parsing, plane fitting, the kernel) stays on this side.
"""
from __future__ import annotations

import contextlib
import io
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .geometry import polygon_area
from .model import Room
from .parser import read_project, read_room
from .settings import BuildSettings
from .solid import BuildError, build_room, export_step, room_planes, solid_stats
from .store import Store
from .tessellate import tessellate

app = FastAPI(title="Snapir Design X", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)
store = Store()
_rooms: dict[str, dict[str, Room]] = {}          # project id -> room name -> Room


def _quiet(fn, *a, **kw):
    """OCCT writes progress banners to stdout. Keep them out of the API."""
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **kw)


def _load(pid: str) -> dict[str, Room]:
    if pid not in _rooms:
        proj = store.get(pid)
        _rooms[pid] = {r.name: r for r in read_project(proj.folder, proj.name).rooms}
    return _rooms[pid]


def _room(pid: str, name: str) -> Room:
    rooms = _load(pid)
    if name not in rooms:
        raise HTTPException(404, f"No room named {name}")
    return _apply_overrides(pid, rooms[name])


def _apply_overrides(pid: str, room: Room) -> Room:
    """Layer the operator's decisions over the parsed survey."""
    ov = store.get(pid).overrides.get(room.name)
    if not ov:
        return room
    if ov.dropped_points:
        room.outline = [p for p in room.outline if p.name not in ov.dropped_points]
    if ov.outline_order:
        rank = {n: i for i, n in enumerate(ov.outline_order)}
        known = [p for p in room.outline if p.name in rank]
        room.outline = sorted(known, key=lambda p: rank[p.name])
        room.issues = [i for i in room.issues if i.code != "self-intersecting"]
    if ov.ceiling_height is not None:
        room.ceiling_height_override = ov.ceiling_height
        room.issues = [i for i in room.issues if i.code != "no-ceiling"]
    if ov.wall_thickness is not None:
        room.wall_thickness = ov.wall_thickness
    if ov.disabled_openings:
        room.openings = [o for i, o in enumerate(room.openings)
                         if i not in set(ov.disabled_openings)]
    return room


def _room_json(room: Room, ov=None) -> dict:
    area = polygon_area([p.xy for p in room.outline]) / 10_000 if len(room.outline) > 2 else 0.0
    return {
        "name": room.name,
        "flat": room.flat,
        "label": room.label,
        "outlineSource": room.outline_source,
        "area": round(area, 3),
        "ceilingHeight": round(room.ceiling_height(), 1) if room.ceiling_height() else None,
        "outline": [{"name": p.name, "x": p.x, "y": p.y, "z": p.z} for p in room.outline],
        "points": [{"name": p.name, "x": p.x, "y": p.y, "z": p.z,
                    "role": p.role.value, "layer": p.layer} for p in room.points],
        "openings": [{
            "index": i, "kind": o.kind, "width": round(o.width, 1),
            "sill": round(o.sill, 1), "head": round(o.head, 1),
            "left": [o.left.x, o.left.y], "right": [o.right.x, o.right.y],
        } for i, o in enumerate(room.openings)],
        "issues": [{"severity": i.severity, "code": i.code,
                    "message": i.message, "points": i.points} for i in room.issues],
        "status": "needs-you" if room.has_errors else (
            "built" if ov and ov.built_at else "ready"),
        "builtAt": ov.built_at if ov else None,
        "stepPath": ov.step_path if ov else None,
    }


# ---------------------------------------------------------------- projects

class NewProject(BaseModel):
    name: str = ""
    folder: str


@app.get("/health")
def health():
    return {"ok": True, "version": app.version}


@app.get("/projects")
def list_projects():
    out = []
    for p in store.recent():
        exists = Path(p.folder).is_dir()
        n = len([f for f in Path(p.folder).glob("*.csv")
                 if "FUKOKU" not in f.stem.upper()]) if exists else 0
        out.append({"id": p.id, "name": p.name, "folder": p.folder,
                    "rooms": n, "openedAt": p.opened_at, "missing": not exists,
                    "thickness": p.thickness})
    return out


@app.post("/projects")
def create_project(body: NewProject):
    try:
        p = store.create(body.name, body.folder)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(400, str(e))
    return {"id": p.id, "name": p.name, "folder": p.folder}


@app.delete("/projects/{pid}")
def delete_project(pid: str):
    store.delete(pid)
    _rooms.pop(pid, None)
    return {"ok": True}


@app.get("/projects/{pid}/rooms")
def project_rooms(pid: str):
    try:
        proj = store.get(pid)
    except KeyError:
        raise HTTPException(404, "No such project")
    proj.touch()
    store.save()
    rooms = _load(pid)
    return {
        "id": proj.id, "name": proj.name, "folder": proj.folder,
        "thickness": proj.thickness,
        "rooms": [_room_json(_apply_overrides(pid, r), proj.overrides.get(name))
                  for name, r in rooms.items()],
    }


@app.get("/projects/{pid}/rooms/{name}")
def get_room(pid: str, name: str):
    return _room_json(_room(pid, name), store.get(pid).overrides.get(name))


# ---------------------------------------------------------------- decisions

class RoomPatch(BaseModel):
    outlineOrder: list[str] | None = None
    droppedPoints: list[str] | None = None
    ceilingHeight: float | None = None
    wallThickness: float | None = None
    disabledOpenings: list[int] | None = None


@app.patch("/projects/{pid}/rooms/{name}")
def patch_room(pid: str, name: str, body: RoomPatch):
    ov = store.override(pid, name)
    if body.outlineOrder is not None:
        ov.outline_order = body.outlineOrder
    if body.droppedPoints is not None:
        ov.dropped_points = body.droppedPoints
    if body.ceilingHeight is not None:
        ov.ceiling_height = body.ceilingHeight
    if body.wallThickness is not None:
        ov.wall_thickness = body.wallThickness
    if body.disabledOpenings is not None:
        ov.disabled_openings = body.disabledOpenings
    store.save()
    _rooms.pop(pid, None)                     # force a clean re-parse
    return _room_json(_room(pid, name), ov)


class ProjectPatch(BaseModel):
    thickness: float | None = None
    name: str | None = None


@app.patch("/projects/{pid}")
def patch_project(pid: str, body: ProjectPatch):
    p = store.get(pid)
    if body.thickness is not None:
        p.thickness = body.thickness
    if body.name:
        p.name = body.name
    store.save()
    return {"id": p.id, "name": p.name, "thickness": p.thickness}


# ---------------------------------------------------------------- build

def _settings(pid: str) -> BuildSettings:
    cfg = BuildSettings()
    t = store.get(pid).thickness
    cfg.wall_thickness = cfg.floor_thickness = cfg.ceiling_thickness = t
    return cfg


@app.post("/projects/{pid}/rooms/{name}/build")
def build(pid: str, name: str):
    room = _room(pid, name)
    cfg = _settings(pid)
    try:
        shape = _quiet(build_room, room, cfg)
        mesh = _quiet(tessellate, shape)
        stats = _quiet(solid_stats, shape)
        floor, ceiling = room_planes(room, cfg)
    except BuildError as e:
        raise HTTPException(422, str(e))
    return {
        "mesh": mesh.to_dict(),
        "stats": {k: (round(v, 6) if isinstance(v, float) else v)
                  for k, v in stats.items()},
        "planes": {
            "floorTilt": round(floor.tilt_deg, 3), "floorRms": round(floor.rms, 3),
            "ceilingTilt": round(ceiling.tilt_deg, 3), "ceilingRms": round(ceiling.rms, 3),
            "height": round(ceiling.pz - floor.pz, 1),
        },
    }


@app.post("/projects/{pid}/rooms/{name}/export")
def export(pid: str, name: str):
    proj = store.get(pid)
    room = _room(pid, name)
    cfg = _settings(pid)
    out = Path(proj.folder) / "Snapir STEP"
    try:
        shape = _quiet(build_room, room, cfg)
        path = _quiet(export_step, shape, out / f"{name}.step", cfg.step_schema)
    except BuildError as e:
        raise HTTPException(422, str(e))
    ov = store.override(pid, name)
    ov.step_path = str(path)
    from .store import _now
    ov.built_at = _now()
    store.save()
    return {"path": str(path), "bytes": path.stat().st_size}


@app.post("/projects/{pid}/rooms/{name}/export-designx")
def export_designx(pid: str, name: str, fmt: str = "iges"):
    """Exact wireframe for Geomagic Design X. Never a mesh."""
    from .designx import export_curves
    proj = store.get(pid)
    room = _room(pid, name)
    out = Path(proj.folder) / "For Design X"
    try:
        path = _quiet(export_curves, room, out, fmt)
    except BuildError as e:
        raise HTTPException(422, str(e))
    return {"path": str(path), "bytes": Path(path).stat().st_size}


def serve(host: str = "127.0.0.1", port: int = 8765):
    import uvicorn
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    serve()
