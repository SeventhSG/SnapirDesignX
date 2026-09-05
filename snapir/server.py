"""Local API for the desktop frontend.

Runs as a private sidecar process on a loopback port the user never sees.
Everything heavy (parsing, plane fitting, the kernel) stays on this side.
"""
from __future__ import annotations

import contextlib
import io
import os
import threading
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .elements import elements as room_elements
from .elements import opening_key as _opening_key
from .geometry import polygon_area
from .model import KIND_LABELS, OPENING_KINDS, SHAPES, Room
from .parser import read_project, read_room
from .settings import BuildSettings
from .solid import BuildError, build_room, export_step, room_planes, solid_stats
from .store import Store, app_dir
from .tessellate import tessellate

app = FastAPI(title="Snapir Design X", version="1.4.1")
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
    if ov.imported_sketch:
        # The drawing that came back from Design X, before anything else: its
        # points have to be in the room for a ring, a line or a role override
        # to be able to name one. Points that matched a shot on the way out
        # kept that shot's name, so most of this record is lines.
        from .model import Point, Role
        have = {p.name for p in room.points}
        for i, d in enumerate(ov.imported_sketch.get("points", [])):
            if d.get("name") in have:
                continue
            try:
                role = Role(d.get("role", "unknown"))
            except ValueError:
                role = Role.UNKNOWN
            room.points.append(Point(
                name=d["name"], x=float(d["x"]), y=float(d["y"]),
                z=float(d.get("z", room.floor_z or 0.0)), layer="", role=role,
                index=20_000 + i, derived=True,
                source=str(d.get("from", "Design X"))))
        segs = {tuple(sorted(s)) for s in room.segments}
        for a, b in ov.imported_sketch.get("segments", []):
            if tuple(sorted((a, b))) not in segs:
                room.segments.append((a, b))
                segs.add(tuple(sorted((a, b))))
    if ov.moved_points:
        # A point picked up and put somewhere else. Everything the room is
        # worked out from - the ring, the openings, the lines - reads the
        # moved position, so this has to land before any of that is derived.
        for p in room.points:
            xyz = ov.moved_points.get(p.name)
            if not xyz or len(xyz) != 3:
                continue
            p.x, p.y, p.z = float(xyz[0]), float(xyz[1]), float(xyz[2])
            p.moved = True
    if ov.imported_sketch or ov.moved_points:
        # Lines came in, or a corner is somewhere else than it was shot. Either
        # way the room no longer follows from what the classifier decided on
        # the first pass, so it is worked out again from where things now are.
        from .parser import reread_topology
        reread_topology(room)
    if ov.derived_points:
        # Constructed points join the room before anything else is layered on,
        # so a ring, a line or an opening can be built through them. They are
        # flagged, so nothing downstream mistakes one for a measurement, and
        # they are placed by the same outline_order / role_overrides the
        # operator uses for any other point rather than by re-classifying.
        from .model import Point, Role
        have = {p.name for p in room.points}
        for i, d in enumerate(ov.derived_points):
            if d.get("name") in have:
                continue
            try:
                role = Role(d.get("role", "floor"))
            except ValueError:
                role = Role.FLOOR
            room.points.append(Point(
                name=d["name"], x=float(d["x"]), y=float(d["y"]),
                z=float(d.get("z", room.floor_z or 0.0)), layer="", role=role,
                index=10_000 + i, derived=True,
                source=str(d.get("from", "constructed"))))
    if ov.dropped_points:
        # A deleted point leaves the room entirely, and every line that touched
        # it goes with it. Nothing on disk is changed.
        gone = set(ov.dropped_points)
        room.points = [p for p in room.points if p.name not in gone]
        room.segments = [s for s in room.segments
                         if s[0] not in gone and s[1] not in gone]
        from .parser import reread_topology
        reread_topology(room)
    if ov.added_segments or ov.removed_segments:
        # Operator edits sit on top of the surveyed lines, and the room is
        # re-read from the combined set so the outline follows.
        gone = {tuple(sorted(x)) for x in ov.removed_segments}
        segs = [s for s in room.segments if tuple(sorted(s)) not in gone]
        segs += [tuple(x) for x in ov.added_segments]
        room.segments = segs
        from .parser import reread_topology
        reread_topology(room)
    if ov.role_overrides:
        # A relabelled point changes what the room is, so everything derived
        # from the old reading is worked out again.
        from .parser import apply_roles
        apply_roles(room, ov.role_overrides)
    ring = list((ov.imported_sketch or {}).get("outline") or [])
    if len(ring) >= 3 and not ov.outline_order:
        # The floor loop as it came back from Design X. It only wins where the
        # operator has not drawn a ring of their own in the app - that is a
        # later decision than the file, and the later one stands.
        by_name = {p.name: p for p in room.points}
        room.outline = [by_name[n] for n in ring if n in by_name]
        room.outline_source = "Design X"
        room.issues = [i for i in room.issues if i.code != "no-outline"]
    if ov.outline_order:
        # The operator can pull in any surveyed point, not just the ones the
        # classifier called a floor corner. Their ring wins outright.
        by_name = {p.name: p for p in room.points}
        room.outline = [by_name[n] for n in ov.outline_order if n in by_name]
        from .geometry import self_intersections
        room.issues = [i for i in room.issues if i.code not in
                       ("self-intersecting", "no-outline")]
        if len(room.outline) >= 3 and self_intersections([p.xy for p in room.outline]):
            from .model import Issue
            room.issues.append(Issue(
                "error", "self-intersecting",
                "The ring you drew still crosses itself."))
    if ov.ceiling_height is not None:
        room.ceiling_height_override = ov.ceiling_height
        room.issues = [i for i in room.issues if i.code != "no-ceiling"]
    if ov.wall_thickness is not None:
        room.wall_thickness = ov.wall_thickness
    if ov.opening_kind_overrides:
        # Correcting a door read as a window, or the other way round. Matched
        # on the jamb points the opening was built from, so the correction
        # follows the opening rather than its position in the list.
        from .elements import opening_key
        from .model import OPENING_KINDS
        for o in room.openings:
            kind = ov.opening_kind_overrides.get(opening_key(o))
            if kind in OPENING_KINDS:
                o.kind = kind
    if ov.opening_shape_overrides:
        # Round or square is the operator's call: four corners on a wall look
        # the same either way.
        from .elements import opening_key
        from .model import SHAPES
        for o in room.openings:
            shape = ov.opening_shape_overrides.get(opening_key(o))
            if shape in SHAPES:
                o.shape = shape
    if ov.disabled_openings:
        room.openings = [o for i, o in enumerate(room.openings)
                         if i not in set(ov.disabled_openings)]
    return room


def _panoramas(folder: str, room: str) -> list[Path]:
    """Panoramas sit in "<room name>_Panorama" beside the room CSV, straight
    off the survey camera. The folder is only ever read, never written."""
    root = Path(folder)
    if not root.is_dir():
        return []
    d = root / f"{room}_Panorama"
    if not d.is_dir():
        # The camera and the total station do not always agree on how a room
        # name is capitalised.
        want = f"{room}_Panorama".upper()
        d = next((c for c in root.iterdir()
                  if c.is_dir() and c.name.upper() == want), None)
        if d is None:
            return []
    return sorted(p for p in d.iterdir()
                  if p.is_file() and p.suffix.lower() in (".jpg", ".jpeg", ".png"))


def _crossings_json(room: Room) -> list[dict]:
    """Every place two of the room's drawn lines cross."""
    from .geometry import crossings

    by_name = {p.name: p for p in room.points}
    segs, names = [], []
    for a, b in room.segments:
        if a in by_name and b in by_name:
            segs.append((by_name[a].xy, by_name[b].xy))
            names.append((a, b))
    return [{"at": [round(x, 2), round(y, 2)],
             "lines": [list(names[i]), list(names[j])]}
            for i, j, (x, y) in crossings(segs)]


def _room_json(room: Room, ov=None, folder: str = "") -> dict:
    area = polygon_area([p.xy for p in room.outline]) / 10_000 if len(room.outline) > 2 else 0.0
    return {
        "name": room.name,
        "flat": room.flat,
        "panoramas": len(_panoramas(folder, room.name)),
        "label": room.label,
        "outlineSource": room.outline_source,
        "area": round(area, 3),
        "ceilingHeight": round(room.ceiling_height(), 1) if room.ceiling_height() else None,
        "outline": [p.name for p in room.outline],
        "floorZ": room.floor_z,
        # Set only when this room departs from the job thickness.
        "wallThickness": room.wall_thickness,
        # Every line the surveyor drew, plus anything the operator added.
        "segments": [list(s) for s in room.segments],
        "links": [list(l) for l in room.links],
        "points": [{"name": p.name, "x": p.x, "y": p.y, "z": p.z,
                    "role": p.role.value, "layer": p.layer,
                    "derived": p.derived, "source": p.source, "moved": p.moved}
                   for p in room.points],
        # Where two drawn lines actually cross. The sketch offers each one as a
        # corner the operator can adopt; nothing is created behind their back.
        "crossings": _crossings_json(room),
        # Where the instrument stood. One setup per panorama, so this is also
        # where each panorama was shot from.
        "stations": [{"name": s.name, "x": s.x, "y": s.y, "z": s.z}
                     for s in room.stations],
        "openings": [{
            "index": i, "kind": o.kind, "width": round(o.width, 1),
            "sill": round(o.sill, 1), "head": round(o.head, 1),
            "left": [o.left.x, o.left.y], "right": [o.right.x, o.right.y],
            # What this rectangle is keyed on, so the operator's choice of
            # what it really is survives a rebuild.
            "key": _opening_key(o), "cuts": o.cuts,
            # Measured off the middle shots, when the surveyor took them. A
            # rectangle can carry one on each side at once.
            "outDepth": round(o.out_depth, 1) if o.out_depth else None,
            "inDepth": round(o.in_depth, 1) if o.in_depth else None,
            "depthPoints": o.depth_points,
            "shape": o.solid_shape,
        } for i, o in enumerate(room.openings)],
        # Everything a wall rectangle is allowed to be. The survey cannot tell
        # a boiler from a window, so the picker is the answer, not a better
        # guess.
        "openingKinds": [{"kind": k, "label": KIND_LABELS.get(k, k)}
                         for k in OPENING_KINDS],
        "shapes": list(SHAPES),
        "stairs": [{
            "points": [p.name for p in s.points],
            "steps": s.steps, "rise": round(s.rise, 1), "going": round(s.going, 1),
        } for s in room.stairs],
        # Everything in this room that can be clicked, named by the survey
        # points it was built from. These keys outlive a rebuild; face ids do
        # not, so a remembered decision is keyed on these.
        "elements": [e.to_dict() for e in room_elements(room)],
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
    return {"ok": True, "version": app.version, "pid": os.getpid()}


@app.post("/shutdown")
def shutdown():
    """Stand down so a newer instance can take the port.

    Only ever called by the desktop app, which asks an orphaned backend to
    exit before starting its own.
    """
    threading.Timer(0.25, lambda: os._exit(0)).start()
    return {"ok": True}


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
        "rooms": [_room_json(_apply_overrides(pid, r), proj.overrides.get(name),
                             proj.folder)
                  for name, r in rooms.items()],
    }


@app.get("/projects/{pid}/rooms/{name}")
def get_room(pid: str, name: str):
    proj = store.get(pid)
    return _room_json(_room(pid, name), proj.overrides.get(name), proj.folder)


@app.get("/projects/{pid}/rooms/{name}/panorama/{index}")
def panorama(pid: str, name: str, index: int):
    """One panorama out of the room's folder, by index. The card grid asks
    for 0; the viewer walks the rest."""
    shots = _panoramas(store.get(pid).folder, name)
    if not 0 <= index < len(shots):
        raise HTTPException(404, f"No panorama {index} for {name}")
    # The survey folder is read-only to us, so a shot never changes under a
    # client that has already cached it.
    return FileResponse(shots[index], headers={
        "Cache-Control": "public, max-age=31536000, immutable"})


# ---------------------------------------------------------------- decisions

class RoomPatch(BaseModel):
    outlineOrder: list[str] | None = None
    droppedPoints: list[str] | None = None
    ceilingHeight: float | None = None
    wallThickness: float | None = None
    disabledOpenings: list[int] | None = None
    openingKindOverrides: dict[str, str] | None = None
    openingShapeOverrides: dict[str, str] | None = None
    fixtureOverrides: dict[str, dict] | None = None
    roleOverrides: dict[str, str] | None = None
    addedSegments: list[list[str]] | None = None
    removedSegments: list[list[str]] | None = None
    faceThickness: dict[str, float] | None = None
    removedWalls: list[str] | None = None       # element keys, e.g. "wall:P_003|P_004"
    derivedPoints: list[dict] | None = None     # constructed corners: name/x/y/z/role/from
    movedPoints: dict[str, list[float]] | None = None   # name -> [x, y, z], survey cm


@app.patch("/projects/{pid}/rooms/{name}")
def patch_room(pid: str, name: str, body: RoomPatch):
    ov = store.override(pid, name)
    if body.outlineOrder is not None:
        ov.outline_order = body.outlineOrder
    if body.droppedPoints is not None:
        ov.dropped_points = body.droppedPoints
    if body.ceilingHeight is not None:
        ov.ceiling_height = body.ceilingHeight
    if "wallThickness" in body.model_fields_set:
        # An explicit null hands the room back to the job default, which is a
        # different thing from not mentioning thickness at all.
        ov.wall_thickness = body.wallThickness
    if body.disabledOpenings is not None:
        ov.disabled_openings = body.disabledOpenings
    if body.openingKindOverrides is not None:
        ov.opening_kind_overrides = {**ov.opening_kind_overrides, **body.openingKindOverrides}
    if body.openingShapeOverrides is not None:
        ov.opening_shape_overrides = {**ov.opening_shape_overrides,
                                      **body.openingShapeOverrides}
    if body.removedWalls is not None:
        ov.removed_walls = body.removedWalls
    if body.derivedPoints is not None:
        ov.derived_points = body.derivedPoints
    if body.movedPoints is not None:
        # A point put back where it was shot is not "moved to its original
        # place", it is not moved. Dropping the entry rather than storing the
        # shot's own coordinates keeps the provenance list honest.
        ov.moved_points = {k: [float(v[0]), float(v[1]), float(v[2])]
                           for k, v in body.movedPoints.items() if v}
    if body.fixtureOverrides is not None:
        ov.fixture_overrides = body.fixtureOverrides
    if body.roleOverrides is not None:
        ov.role_overrides = {**ov.role_overrides, **body.roleOverrides}
    if body.addedSegments is not None:
        ov.added_segments = [list(x) for x in body.addedSegments]
    if body.removedSegments is not None:
        ov.removed_segments = [list(x) for x in body.removedSegments]
    if body.faceThickness is not None:
        ov.face_thickness = {**ov.face_thickness, **body.faceThickness}
    store.save()
    _rooms.pop(pid, None)                     # force a clean re-parse
    return _room_json(_room(pid, name), ov, store.get(pid).folder)


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

SETTINGS_PATH = app_dir() / "settings.json"


def _global_settings() -> BuildSettings:
    try:
        cfg = BuildSettings.from_json(SETTINGS_PATH)
    except (FileNotFoundError, TypeError, ValueError):
        return BuildSettings()
    # Settings written before the move to millimetres held centimetres.
    if cfg.wall_thickness < 50.0:
        for f in ("wall_thickness", "floor_thickness", "ceiling_thickness",
                  "socket_width", "socket_height", "socket_proud",
                  "socket_embed", "socket_recess", "pipe_diameter",
                  "pipe_length", "pipe_min_length", "pipe_embed"):
            setattr(cfg, f, getattr(cfg, f) * 10.0)
        cfg.to_json(SETTINGS_PATH)
    return cfg


def _settings(pid: str) -> BuildSettings:
    """Global settings, with the project's own thickness layered on top."""
    cfg = _global_settings()
    t = store.get(pid).thickness
    cfg.wall_thickness = cfg.floor_thickness = cfg.ceiling_thickness = t
    return cfg


@app.get("/settings")
def get_settings():
    return asdict(_global_settings())


@app.patch("/settings")
def patch_settings(body: dict):
    cfg = _global_settings()
    for k, v in body.items():
        if hasattr(cfg, k):
            setattr(cfg, k, v)
    cfg.to_json(SETTINGS_PATH)
    return asdict(cfg)


@app.post("/projects/{pid}/rooms/{name}/build")
def build(pid: str, name: str):
    room = _room(pid, name)
    cfg = _settings(pid)
    try:
        ov = store.get(pid).overrides.get(name)
        shape = _quiet(build_room, room, cfg,
                       fixture_overrides=ov.fixture_overrides if ov else None,
                       removed_walls=ov.removed_walls if ov else None)
        mesh = _quiet(tessellate, shape, room=room, cfg=cfg)
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
    ov_in = store.get(pid).overrides.get(name)
    try:
        # Same fixture decisions the preview was built with, so the file on disk
        # is the body that was approved on screen.
        shape = _quiet(build_room, room, cfg,
                       fixture_overrides=ov_in.fixture_overrides if ov_in else None,
                       removed_walls=ov_in.removed_walls if ov_in else None)
        path = _quiet(export_step, shape, out / f"{name}.step", cfg.step_schema)
    except BuildError as e:
        raise HTTPException(422, str(e))
    ov = store.override(pid, name)
    ov.step_path = str(path)
    from .store import _now
    ov.built_at = _now()
    store.save()
    return {"path": str(path), "bytes": path.stat().st_size}


@app.post("/projects/{pid}/rooms/{name}/export-wall")
def export_wall(pid: str, name: str, faceId: int):
    """Export the wall under a picked face as its own STEP body."""
    from .elements import wall_edge_for_key
    from .solid import wall_body

    proj = store.get(pid)
    room = _room(pid, name)
    cfg = _settings(pid)
    ov = store.get(pid).overrides.get(name)
    fx = ov.fixture_overrides if ov else None

    try:
        # Same body the preview and /export produce, removed walls included -
        # otherwise this endpoint exports a wall out of a room nobody built.
        shape = _quiet(build_room, room, cfg, fixture_overrides=fx,
                       removed_walls=ov.removed_walls if ov else None)
        mesh = _quiet(tessellate, shape, room=room, cfg=cfg)
        face = next((f for f in mesh.faces if f.id == faceId), None)
        if face is None:
            raise HTTPException(404, f"No face {faceId}")
        # Asking which wall a face belongs to used to mean projecting its
        # centroid onto the ring, which cheerfully answered "wall 4" for a
        # stair riser or a door reveal and exported the wrong body.
        if face.element_kind != "wall":
            raise HTTPException(
                400, f"That face is {face.label or face.element_kind}, not a wall.")

        edge = wall_edge_for_key(room, face.element)
        if edge is None:
            raise HTTPException(404, f"{face.label} is no longer in the outline")
        body, length, pieces = _quiet(wall_body, room, cfg, edge, fx)
        stats = _quiet(solid_stats, body)
        out = Path(proj.folder) / "Snapir STEP" / "Walls"
        path = _quiet(export_step, body,
                      out / f"{name} - wall {edge + 1}.step", cfg.step_schema)
    except BuildError as e:
        raise HTTPException(422, str(e))

    return {
        "path": str(path), "bytes": path.stat().st_size,
        "wall": edge + 1, "length": round(length, 1), "pieces": pieces,
        "stats": {k: (round(v, 6) if isinstance(v, float) else v)
                  for k, v in stats.items()},
    }


@app.post("/projects/{pid}/rooms/{name}/export-designx")
def export_designx(pid: str, name: str, fmt: str = "iges"):
    """Exact wireframe for Geomagic Design X. Never a mesh."""
    from .designx import export_curves
    proj = store.get(pid)
    room = _room(pid, name)
    out = Path(proj.folder) / "For Design X"
    try:
        path = _quiet(export_curves, room, out, fmt, _settings(pid))
    except BuildError as e:
        raise HTTPException(422, str(e))
    return {"path": str(path), "bytes": Path(path).stat().st_size}


# ---------------------------------------------------------------- the merge
#
# Every room is measured from wherever the instrument stood, so a survey is a
# dozen drawings each in its own frame. The operator says which corner in one
# room is which corner in another, and that is enough to solve where each room
# sits relative to the rest. Nothing is guessed and nothing is stored but the
# pairs themselves: the placements are worked out from them on every read, so a
# pair deleted never leaves a stale transform behind it.


def _merge_state(pid: str):
    from .merge import Pair, solve

    proj = store.get(pid)
    rooms = {name: _apply_overrides(pid, room) for name, room in _load(pid).items()}
    pairs = [Pair.from_json(d) for d in proj.merge_pairs]
    placed, loose = solve(rooms, pairs, proj.merge_anchor)
    return proj, rooms, pairs, placed, loose


def _merge_json(pid: str) -> dict:
    proj, rooms, pairs, placed, loose = _merge_state(pid)
    anchor = next((n for n, p in placed.items() if not p.via), None)
    return {
        "anchor": anchor,
        "unplaced": loose,
        "pairs": [{**p.to_json(), "index": i} for i, p in enumerate(pairs)],
        "rooms": [
            {
                "name": name,
                "placed": name in placed,
                "dx": round(placed[name].dx, 3) if name in placed else None,
                "dy": round(placed[name].dy, 3) if name in placed else None,
                "dz": round(placed[name].dz, 3) if name in placed else None,
                "rotationDeg": round(placed[name].rotation_deg, 4)
                if name in placed else None,
                "residual": round(placed[name].residual, 2) if name in placed else None,
                "via": placed[name].via if name in placed else "",
                "pairs": placed[name].pairs if name in placed else 0,
                # The plan, in the room's own frame. The app places it; sending
                # it placed would mean re-sending every room on every pair.
                "outline": [[p.x, p.y, p.z] for p in room.outline],
                "points": [{"name": p.name, "x": p.x, "y": p.y, "z": p.z,
                            "role": p.role.value} for p in room.points],
                "segments": [list(s) for s in room.segments],
            }
            for name, room in rooms.items()
        ],
    }


@app.get("/projects/{pid}/merge")
def get_merge(pid: str):
    return _merge_json(pid)


class MergePair(BaseModel):
    roomA: str
    pointA: str | None = None
    roomB: str
    pointB: str | None = None
    # Two lines said to be the same wall, as [start, end] in each room. Which
    # end answers to which is worked out here rather than asked for.
    lineA: list[str] | None = None
    lineB: list[str] | None = None


@app.post("/projects/{pid}/merge/pairs")
def add_merge_pair(pid: str, body: MergePair):
    from .merge import Pair, endpoints_for_lines

    proj, rooms, pairs, placed, _loose = _merge_state(pid)
    if body.roomA not in rooms or body.roomB not in rooms:
        raise HTTPException(404, "No such room in this project")
    if body.roomA == body.roomB:
        raise HTTPException(422, "A room cannot be matched against itself.")

    if body.lineA and body.lineB:
        if len(body.lineA) != 2 or len(body.lineB) != 2:
            raise HTTPException(422, "A line is two points.")
        fresh = endpoints_for_lines(
            rooms[body.roomA], (body.lineA[0], body.lineA[1]),
            rooms[body.roomB], (body.lineB[0], body.lineB[1]),
            placed.get(body.roomA), placed.get(body.roomB))
        if not fresh:
            raise HTTPException(422, "Those lines are not in those rooms.")
    else:
        if not body.pointA or not body.pointB:
            raise HTTPException(422, "Pick a point in each room.")
        fresh = [Pair(body.roomA, body.pointA, body.roomB, body.pointB)]

    have = {p.key for p in pairs}
    for pair in fresh:
        if pair.key not in have:
            proj.merge_pairs.append(pair.to_json())
            have.add(pair.key)
    store.save()
    return _merge_json(pid)


@app.delete("/projects/{pid}/merge/pairs/{index}")
def drop_merge_pair(pid: str, index: int):
    proj = store.get(pid)
    if not 0 <= index < len(proj.merge_pairs):
        raise HTTPException(404, "No such pair")
    proj.merge_pairs.pop(index)
    store.save()
    return _merge_json(pid)


class MergePatch(BaseModel):
    anchor: str | None = None
    clear: bool = False


@app.patch("/projects/{pid}/merge")
def patch_merge(pid: str, body: MergePatch):
    proj = store.get(pid)
    if body.clear:
        proj.merge_pairs = []
        proj.merge_anchor = None
    if body.anchor is not None:
        proj.merge_anchor = body.anchor or None
    store.save()
    return _merge_json(pid)


@app.post("/projects/{pid}/merge/export")
def export_merge(pid: str):
    """Every placed room, in one frame, in one file."""
    from .merge import build_merged

    proj, rooms, _pairs, placed, loose = _merge_state(pid)
    if len(placed) < 2:
        raise HTTPException(422, "Match at least two rooms before merging.")
    cfg = _settings(pid)
    try:
        shape, failed, how = _quiet(build_merged, rooms, placed, cfg)
        out = Path(proj.folder) / "Snapir STEP"
        path = _quiet(export_step, shape, out / f"{proj.name} - merged.step",
                      cfg.step_schema)
    except BuildError as e:
        raise HTTPException(422, str(e))
    return {"path": str(path), "bytes": Path(path).stat().st_size,
            "rooms": len(placed), "how": how, "failed": failed,
            "unplaced": loose}


class SketchImport(BaseModel):
    path: str


@app.post("/projects/{pid}/rooms/{name}/import-designx")
def import_designx(pid: str, name: str, body: SketchImport):
    """Take the sketch back from Design X, over the top of the old one.

    The file replaces whatever the last import brought in rather than adding
    to it, so importing the same drawing twice leaves the room where importing
    it once did, and re-importing after another edit does not accumulate the
    corners that were deleted in between.
    """
    from .importx import sketch_for
    room = _room(pid, name)
    try:
        sketch = _quiet(sketch_for, room, body.path)
    except BuildError as e:
        raise HTTPException(422, str(e))
    except Exception as e:                      # a file that is not a sketch
        raise HTTPException(422, f"Could not read that sketch: {e}")

    ov = store.override(pid, name)
    ov.imported_sketch = sketch
    # The ring that came in is the ring. A ring the operator drew before the
    # trip to Design X described the old shape and would fight this one.
    ov.outline_order = None
    store.save()
    _rooms.pop(pid, None)
    out = _room_json(_room(pid, name), ov, store.get(pid).folder)
    out["imported"] = {"points": len(sketch["points"]), "matched": sketch["matched"],
                       "segments": len(sketch["segments"]),
                       "outline": len(sketch["outline"]), "file": sketch["file"]}
    return out


@app.delete("/projects/{pid}/rooms/{name}/import-designx")
def clear_designx(pid: str, name: str):
    """Forget the imported sketch and go back to the survey as shot."""
    ov = store.override(pid, name)
    ov.imported_sketch = None
    store.save()
    _rooms.pop(pid, None)
    return _room_json(_room(pid, name), ov, store.get(pid).folder)


def serve(host: str = "127.0.0.1", port: int = 8765):
    import uvicorn
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    serve()
