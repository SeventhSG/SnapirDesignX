"""Escape hatch: hand a room to Geomagic Design X instead.

Exact wireframe, not a point cloud. Design X reads IGES and STEP curves
natively, and a curve carries the surveyed corner exactly where the instrument
put it. Sampling the same lines into points would throw that away and then
charge you the labour of fitting it back.

ASC points are offered too, for the cases where a cloud really is wanted.
"""
from __future__ import annotations

from pathlib import Path

from .model import Role, Room
from .settings import BuildSettings
from .solid import CM_TO_MM, BuildError, cm

_SUFFIX = {"iges": ".igs", "step": ".stp", "asc": ".asc"}

# Half-arm of the cross drawn through a single shot, centimetres.
MARK = 5.0


def export_curves(room: Room, out_dir: str | Path, fmt: str = "iges",
                  cfg: BuildSettings | None = None) -> Path:
    """Write the room outline, ceiling ring and openings as exact curves."""
    cfg = cfg or BuildSettings()
    fmt = fmt.lower()
    if fmt not in _SUFFIX:
        raise BuildError(f"Unknown format: {fmt}")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{room.name}{_SUFFIX[fmt]}"

    if fmt == "asc":
        return _write_asc(room, path)
    if len(room.outline) < 3 and not room.segments:
        raise BuildError(f"{room.name}: outline has fewer than three points")
    return _write_curves(room, path, fmt, cfg)


def _fixtures(room: Room, cfg: BuildSettings, ring):
    """Sockets and pipes as the shapes they are, drawn on their own wall.

    Both arrive as a single reading, and as a single reading they leave as two
    identical dots - which tells you where a service is and nothing about what
    it is. A socket is a faceplate and a pipe is a bore, so one goes over as
    the square it measures and the other as a real circle, seated on the wall
    face the way the body seats them.
    """
    from .solid import _wall_frame

    squares: list[list[tuple[float, float, float]]] = []
    circles: list[tuple[tuple[float, float, float], tuple[float, float], float]] = []
    if not cfg.include_fixtures or len(ring) < 3:
        return squares, circles

    for p in room.points:
        if p.role not in (Role.SOCKET, Role.PLUMBING):
            continue
        try:
            (sx, sy), (nx, ny), (tx, ty), _d = _wall_frame(p.x, p.y, list(ring))
        except Exception:
            continue
        if p.role is Role.PLUMBING:
            circles.append(((sx, sy, p.z), (nx, ny), cm(cfg.pipe_diameter) / 2))
            continue
        hw, hh = cm(cfg.socket_width) / 2, cm(cfg.socket_height) / 2
        face = [(sx + tx * hw, sy + ty * hw, p.z - hh),
                (sx - tx * hw, sy - ty * hw, p.z - hh),
                (sx - tx * hw, sy - ty * hw, p.z + hh),
                (sx + tx * hw, sy + ty * hw, p.z + hh)]
        squares.append(face + [face[0]])
    return squares, circles


def _rings(room: Room, cfg: BuildSettings):
    """Every polyline worth handing over, and every shot none of them carries.

    Returns them together because the second is worked out from the first: a
    shot is loose exactly when no curve already passes through it.
    """
    from .planes import fit_or_level, level_plane

    rings: list[list[tuple[float, float, float]]] = []
    ring = [(p.x, p.y, p.z) for p in room.outline]
    if not ring:
        # A merged room has no ring of its own - a stairwell is not one ring -
        # so its drawing is the lines it is made of, every one of them.
        by = {p.name: p for p in room.points}
        for a, b in room.segments:
            p, q = by.get(a), by.get(b)
            if p and q:
                rings.append([(p.x, p.y, p.z), (q.x, q.y, q.z)])
        for op in room.openings:
            rings.extend(_depth_box(op, []))
        loose = _vertices(room, rings)
        for x, y, z in loose:
            rings.append([(x - MARK, y, z), (x + MARK, y, z)])
            rings.append([(x, y - MARK, z), (x, y + MARK, z)])
            rings.append([(x, y, z - MARK), (x, y, z + MARK)])
        return rings, loose, []
    rings.append(ring)

    ceil_pts = [(p.x, p.y, p.z) for p in room.ceiling]
    if len(ceil_pts) >= 3:
        plane = fit_or_level(ceil_pts)
    elif room.ceiling_height_override is not None:
        plane = level_plane((room.floor_z or 0.0) + room.ceiling_height_override)
    else:
        plane = None
    if plane is not None:
        rings.append([(x, y, plane.z_at(x, y)) for x, y, _ in ring])

    for op in room.openings:
        (ax, ay), (bx, by) = (op.left.x, op.left.y), (op.right.x, op.right.y)
        rings.append([
            (ax, ay, op.sill), (bx, by, op.sill),
            (bx, by, op.head), (ax, ay, op.head), (ax, ay, op.sill),
        ])
        rings.extend(_depth_box(op, ring))

    # A flight is the line the surveyor walked up, nosing by nosing. Handing
    # over the room without it leaves the stairs to be drawn again from the
    # loose points, which is the work the survey already did.
    for flight in room.stairs:
        if len(flight.points) >= 2:
            rings.append([(p.x, p.y, p.z) for p in flight.points])

    # Skirting: the pair that measured one board, as the diagonal it was shot
    # as. Two points, so it reads as the depth and height it is.
    for v in room.pervaz:
        rings.append([(v.corner.x, v.corner.y, v.corner.z),
                      (v.wall.x, v.wall.y, v.wall.z)])

    squares, circles = _fixtures(room, cfg, [(x, y) for x, y, _z in ring])
    rings.extend(squares)

    # A single shot is written as an IGES point as well, which is the exact
    # thing. The cross is for STEP, whose writer drops a loose vertex on the
    # floor: three short lines through the shot, so it arrives either way.
    #
    # A service already has a shape of its own, so it gets no cross: two marks
    # on one reading is one more than the drawing needs.
    loose = _vertices(room, rings)
    marked = {(round(p.x, 3), round(p.y, 3), round(p.z, 3)) for p in room.points
              if p.role in (Role.SOCKET, Role.PLUMBING)}
    for x, y, z in loose:
        if (round(x, 3), round(y, 3), round(z, 3)) in marked:
            continue
        rings.append([(x - MARK, y, z), (x + MARK, y, z)])
        rings.append([(x, y - MARK, z), (x, y + MARK, z)])
        rings.append([(x, y, z - MARK), (x, y, z + MARK)])
    return rings, loose, circles


def _depth_box(op, ring) -> list[list[tuple[float, float, float]]]:
    """The wireframe of what a measured rectangle actually becomes.

    A shot in the middle of a rectangle says how far the thing standing on the
    wall reaches, and that is the one number the drawing cannot show on its
    own: the rectangle looks identical whether the boiler is 8 cm deep or 40.
    So the far face is drawn where the shot put it, joined back to the
    rectangle corner by corner - a box, in the round, at the measured depth.
    """
    from .solid import _wall_frame

    out: list[list[tuple[float, float, float]]] = []
    if not op.measured or len(ring) < 3:
        return out

    cx, cy = (op.left.x + op.right.x) / 2, (op.left.y + op.right.y) / 2
    try:
        _seat, (nx, ny), _t, _d = _wall_frame(cx, cy, list(ring))
    except Exception:
        return out

    for depth in (op.out_depth, -op.in_depth if op.in_depth else None):
        if not depth:
            continue
        dx, dy = nx * depth, ny * depth
        face = [(op.left.x + dx, op.left.y + dy, op.sill),
                (op.right.x + dx, op.right.y + dy, op.sill),
                (op.right.x + dx, op.right.y + dy, op.head),
                (op.left.x + dx, op.left.y + dy, op.head)]
        out.append(face + [face[0]])
        for (fx, fy, fz), (bx, by) in zip(face, [
                (op.left.x, op.left.y), (op.right.x, op.right.y),
                (op.right.x, op.right.y), (op.left.x, op.left.y)]):
            out.append([(bx, by, fz), (fx, fy, fz)])
    return out


def _vertices(room: Room, carried) -> list[tuple[float, float, float]]:
    """Every shot no curve carries.

    A depth shot, a socket, a point the classifier could not place, a corner
    the surveyor took and never joined to anything - none of them are on a
    polyline, so a room exported without them arrives in Design X missing
    exactly the readings that still need a decision. Whatever the drawing
    already says is left to the drawing; the rest go over as points.

    The instrument's own stations go too: they are where the panoramas were
    taken from.
    """
    seen = {(round(x, 3), round(y, 3), round(z, 3)) for ring in carried
            for x, y, z in ring}
    loose = [(p.x, p.y, p.z) for p in room.points
             if (round(p.x, 3), round(p.y, 3), round(p.z, 3)) not in seen]
    return loose + [(s.x, s.y, s.z) for s in room.stations]


def _write_curves(room: Room, path: Path, fmt: str, cfg: BuildSettings) -> Path:
    from OCP.BRep import BRep_Builder
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeVertex
    from OCP.gp import gp_Pnt
    from OCP.TopoDS import TopoDS_Compound

    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)

    rings, loose, circles = _rings(room, cfg)
    for ring in rings:
        if len(ring) < 2:
            continue
        poly = BRepBuilderAPI_MakePolygon()
        for x, y, z in ring:
            poly.Add(gp_Pnt(x * CM_TO_MM, y * CM_TO_MM, z * CM_TO_MM))
        # An open run - a flight of stairs, a skirting pair - is a line, not a
        # loop. Closing it would draw a wall that was never measured.
        if len(ring) > 2 and ring[0] != ring[-1]:
            poly.Close()
        builder.Add(compound, poly.Wire())

    # A real circle, not a polygon pretending to be one: Design X reads the
    # arc and gives back a diameter you can dimension off.
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
    from OCP.gp import gp_Ax2, gp_Circ, gp_Dir

    for (cx, cy, cz), (nx, ny), radius in circles:
        axis = gp_Ax2(gp_Pnt(cx * CM_TO_MM, cy * CM_TO_MM, cz * CM_TO_MM),
                      gp_Dir(nx, ny, 0.0))
        builder.Add(compound,
                    BRepBuilderAPI_MakeEdge(gp_Circ(axis, radius * CM_TO_MM)).Edge())

    # Single shots, as points. Design X shows a vertex where the instrument
    # stood; a wire cannot carry one.
    for x, y, z in loose:
        builder.Add(compound, BRepBuilderAPI_MakeVertex(
            gp_Pnt(x * CM_TO_MM, y * CM_TO_MM, z * CM_TO_MM)).Vertex())

    if fmt == "iges":
        from OCP.IGESControl import IGESControl_Controller, IGESControl_Writer
        IGESControl_Controller.Init_s()
        writer = IGESControl_Writer("MM", 0)
        writer.AddShape(compound)
        writer.ComputeModel()
        if not writer.Write(str(path)):
            raise BuildError(f"IGES write failed: {path}")
    else:
        from OCP.IFSelect import IFSelect_RetDone
        from OCP.Interface import Interface_Static
        from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
        Interface_Static.SetCVal_s("write.step.unit", "MM")
        writer = STEPControl_Writer()
        writer.Transfer(compound, STEPControl_AsIs)
        if writer.Write(str(path)) != IFSelect_RetDone:
            raise BuildError(f"STEP write failed: {path}")
    return path


def _write_asc(room: Room, path: Path) -> Path:
    """Plain XYZ, millimetres, one point per line."""
    lines = [
        f"{p.x * CM_TO_MM:.4f} {p.y * CM_TO_MM:.4f} {p.z * CM_TO_MM:.4f}"
        for p in room.points
    ]
    path.write_text("\n".join(lines) + "\n", encoding="ascii")
    return path
