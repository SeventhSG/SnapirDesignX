"""Solid construction and STEP export, on OpenCASCADE.

Shape of a room body: the surveyed outline is the inner face of the walls.
An outer ring is offset outward by the wall thickness, floor and ceiling
planes are pushed out by their own slab thicknesses, and the inner volume is
subtracted. What is left is walls, floor and ceiling as one closed solid with
an empty room inside.

Nothing is tessellated at any point. Faces are planes, edges are lines, and
the body is watertight because the kernel refuses to build it otherwise.
"""
from __future__ import annotations

from pathlib import Path

from shapely.geometry import Polygon

from .geometry import ensure_ccw, project_onto_edges
from .model import Opening, Room
from .planes import Plane, fit_or_level, level_plane
from .settings import BuildSettings

CM_TO_MM = 10.0


class BuildError(RuntimeError):
    pass


def _occ():
    """Import OCCT lazily so the parser and viewer load without the kernel."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.BRepBuilderAPI import (BRepBuilderAPI_MakeFace,
                                    BRepBuilderAPI_MakePolygon,
                                    BRepBuilderAPI_MakeSolid,
                                    BRepBuilderAPI_Sewing)
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.gp import gp_Pnt
    from OCP.TopAbs import TopAbs_SHELL
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    return {
        "Cut": BRepAlgoAPI_Cut,
        "Polygon": BRepBuilderAPI_MakePolygon,
        "Face": BRepBuilderAPI_MakeFace,
        "Sewing": BRepBuilderAPI_Sewing,
        "Solid": BRepBuilderAPI_MakeSolid,
        "Check": BRepCheck_Analyzer,
        "Pnt": gp_Pnt,
        "Explorer": TopExp_Explorer,
        "SHELL": TopAbs_SHELL,
        "TopoDS": TopoDS,
    }


def _planar_face(pts, occ):
    """A face forced onto a true plane, never a spline that happens to be flat.

    OCCT will happily hand back a BSpline surface for a face that is exactly
    planar. Downstream that is a worse file: no analytic plane to snap to, no
    clean face for a toolpath. Building the face plane-only keeps the B-rep
    honest.
    """
    poly = occ["Polygon"]()
    for p in pts:
        poly.Add(p)
    poly.Close()
    face = occ["Face"](poly.Wire(), True)          # OnlyPlane
    if not face.IsDone():
        raise BuildError("face is not planar")
    return face.Face()


def room_planes(room: Room, cfg: BuildSettings) -> tuple[Plane, Plane]:
    """The floor and ceiling planes this room will be built between."""
    floor_pts = [(p.x, p.y, p.z) for p in room.outline]
    if len(floor_pts) >= 3:
        floor = fit_or_level(floor_pts, cfg.max_ceiling_tilt_deg)
    else:
        floor = level_plane(room.floor_z or 0.0)

    ceil_pts = [(p.x, p.y, p.z) for p in room.ceiling]
    if len(ceil_pts) >= 3 and cfg.fit_ceiling_plane:
        ceiling = fit_or_level(ceil_pts, cfg.max_ceiling_tilt_deg)
    elif room.ceiling_height_override is not None:
        ceiling = level_plane(floor.pz + room.ceiling_height_override)
    elif room.ceiling_z is not None:
        ceiling = level_plane(room.ceiling_z)
    else:
        raise BuildError(f"{room.name}: no ceiling height. Supply one first.")
    return floor, ceiling


def _prism(ring, bottom: Plane, top: Plane, occ):
    """A solid between two planes, with the given plan outline.

    Every face is built explicitly and forced planar. The caps sit on the
    fitted planes. Each side face is a quad whose two lower corners share a
    plan position with its two upper corners, so all four lie in the vertical
    plane through that plan edge: exactly coplanar, not approximately.
    """
    ring = ensure_ccw(list(ring))
    n = len(ring)
    pnt = occ["Pnt"]

    lower = [pnt(x * CM_TO_MM, y * CM_TO_MM, bottom.z_at(x, y) * CM_TO_MM)
             for x, y in ring]
    upper = [pnt(x * CM_TO_MM, y * CM_TO_MM, top.z_at(x, y) * CM_TO_MM)
             for x, y in ring]

    faces = [
        _planar_face(list(reversed(lower)), occ),
        _planar_face(upper, occ),
    ]
    for i in range(n):
        j = (i + 1) % n
        faces.append(_planar_face([lower[i], lower[j], upper[j], upper[i]], occ))

    sew = occ["Sewing"](1.0e-6)
    for f in faces:
        sew.Add(f)
    sew.Perform()

    exp = occ["Explorer"](sew.SewedShape(), occ["SHELL"])
    if not exp.More():
        raise BuildError("faces did not sew into a closed shell")
    solid = occ["Solid"](occ["TopoDS"].Shell_s(exp.Current()))
    if not solid.IsDone():
        raise BuildError("shell did not close into a solid")
    return solid.Solid()


def _offset_ring(ring, distance: float):
    """Grow the outline outward, keeping sharp corners.

    Mitred joins matter here. A rounded join would put an arc where the
    building has a corner, and the whole point is that corners stay exact.
    """
    poly = Polygon(ensure_ccw(list(ring)))
    if not poly.is_valid:
        raise BuildError("outline is not a simple polygon")
    grown = poly.buffer(distance, join_style=2, mitre_limit=10.0)
    if grown.geom_type != "Polygon":
        raise BuildError("wall offset split the outline; thickness is too large")
    return list(grown.exterior.coords)[:-1]


def _opening_cutter(op: Opening, ring, cfg: BuildSettings, occ):
    """A box spanning the wall at an opening, overshooting both faces."""
    reach = cfg.wall_thickness * 3.0
    ax, ay = op.left.x, op.left.y
    bx, by = op.right.x, op.right.y
    dx, dy = bx - ax, by - ay
    length = (dx * dx + dy * dy) ** 0.5
    if length < 1.0:
        raise BuildError("opening jambs coincide")

    nx, ny = -dy / length, dx / length          # wall normal, direction TBD
    cx, cy = (ax + bx) / 2, (ay + by) / 2
    _edge, near, _d = project_onto_edges((cx, cy), list(ring))
    if (near[0] - cx) * nx + (near[1] - cy) * ny < 0:
        nx, ny = -nx, -ny

    corners = [
        (ax - nx * reach, ay - ny * reach),
        (bx - nx * reach, by - ny * reach),
        (bx + nx * reach, by + ny * reach),
        (ax + nx * reach, ay + ny * reach),
    ]
    return _prism(corners, level_plane(op.sill), level_plane(op.head), occ)


def build_room(room: Room, cfg: BuildSettings, openings=None):
    """Build one room shell. Returns an OCCT solid."""
    if len(room.outline) < 3:
        raise BuildError(f"{room.name}: outline has fewer than three points")
    occ = _occ()

    floor, ceiling = room_planes(room, cfg)
    inner_ring = [p.xy for p in room.outline]

    thickness = room.wall_thickness if room.wall_thickness is not None \
        else cfg.wall_thickness
    outer_ring = _offset_ring(inner_ring, thickness)

    outer_floor = Plane(floor.px, floor.py, floor.pz - cfg.floor_thickness,
                        floor.nx, floor.ny, floor.nz)
    outer_ceiling = Plane(ceiling.px, ceiling.py, ceiling.pz + cfg.ceiling_thickness,
                          ceiling.nx, ceiling.ny, ceiling.nz)

    outer = _prism(outer_ring, outer_floor, outer_ceiling, occ)
    inner = _prism(inner_ring, floor, ceiling, occ)

    cut = occ["Cut"](outer, inner)
    cut.Build()
    if not cut.IsDone():
        raise BuildError(f"{room.name}: could not subtract the room volume")
    shape = cut.Shape()

    if cfg.cut_openings:
        for op in (openings if openings is not None else room.openings):
            c = occ["Cut"](shape, _opening_cutter(op, inner_ring, cfg, occ))
            c.Build()
            if not c.IsDone():
                raise BuildError(f"{room.name}: opening cut failed")
            shape = c.Shape()

    if cfg.include_fixtures:
        shape, stray = _add_fixtures(shape, room, inner_ring, cfg, occ)
        if stray:
            from .model import Issue
            room.issues.append(Issue(
                "info", "fixture-off-wall",
                f"{len(stray)} service point(s) did not meet any wall and were "
                "left out of the body.", points=stray))

    if not occ["Check"](shape).IsValid():
        raise BuildError(f"{room.name}: resulting solid is not valid")
    return shape


def solid_stats(shape) -> dict:
    """Face and volume report, used to prove a body is what we think it is."""
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_FACE, TopAbs_SHELL, TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer

    def count(kind):
        exp, n = TopExp_Explorer(shape, kind), 0
        while exp.More():
            n += 1
            exp.Next()
        return n

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return {
        "solids": count(TopAbs_SOLID),
        "shells": count(TopAbs_SHELL),
        "faces": count(TopAbs_FACE),
        "volume_m3": props.Mass() / 1.0e9,      # mm3 to m3
    }


def export_step(shape, path, schema: str = "AP214") -> Path:
    """Write a STEP file in millimetres."""
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.Interface import Interface_Static
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    Interface_Static.SetCVal_s("write.step.schema", schema)
    Interface_Static.SetCVal_s("write.step.unit", "MM")
    writer = STEPControl_Writer()
    writer.Transfer(shape, STEPControl_AsIs)
    if writer.Write(str(path)) != IFSelect_RetDone:
        raise BuildError(f"STEP write failed: {path}")
    return path


def _wall_frame(x: float, y: float, ring):
    """Seat a surveyed point on its wall and return the inward normal.

    Service points are shot a centimetre or two off the surface, so the raw
    coordinate floats in space. Projecting it onto the nearest wall puts the
    fixture where it physically is.
    """
    from shapely.geometry import Point, Polygon
    from .geometry import project_onto_edges

    idx, seat, dist = project_onto_edges((x, y), list(ring))
    a, b = ring[idx], ring[(idx + 1) % len(ring)]
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = (dx * dx + dy * dy) ** 0.5 or 1.0
    nx, ny = -dy / length, dx / length
    # Point the normal into the room.
    poly = Polygon(ring)
    if not poly.contains(Point(seat[0] + nx * 0.5, seat[1] + ny * 0.5)):
        nx, ny = -nx, -ny
    return seat, (nx, ny), (dx / length, dy / length), dist


def _socket_solid(pt, ring, cfg: BuildSettings, occ):
    """A back box on the wall face, protruding into the room."""
    (sx, sy), (nx, ny), (tx, ty), _d = _wall_frame(pt.x, pt.y, ring)
    hw = cfg.socket_width / 2
    out = cfg.socket_depth
    back = cfg.wall_thickness * 0.5          # bed it into the wall so it fuses
    corners = [
        (sx + tx * hw - nx * back, sy + ty * hw - ny * back),
        (sx - tx * hw - nx * back, sy - ty * hw - ny * back),
        (sx - tx * hw + nx * out, sy - ty * hw + ny * out),
        (sx + tx * hw + nx * out, sy + ty * hw + ny * out),
    ]
    half = cfg.socket_height / 2
    return _prism(corners, level_plane(pt.z - half), level_plane(pt.z + half), occ)


def _pipe_solid(pt, ring, cfg: BuildSettings):
    """A pipe stub coming out of the wall, along the wall normal."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

    (sx, sy), (nx, ny), _t, _d = _wall_frame(pt.x, pt.y, ring)
    back = cfg.wall_thickness * 0.5
    origin = gp_Pnt((sx - nx * back) * CM_TO_MM, (sy - ny * back) * CM_TO_MM,
                    pt.z * CM_TO_MM)
    axis = gp_Ax2(origin, gp_Dir(nx, ny, 0.0))
    return BRepPrimAPI_MakeCylinder(
        axis, cfg.pipe_diameter / 2 * CM_TO_MM,
        (cfg.pipe_length + back) * CM_TO_MM).Shape()


def fixture_solids(room: Room, ring, cfg: BuildSettings, occ):
    """Every service fixture in the room, as (kind, solid) pairs."""
    from .model import Role

    out = []
    for p in room.points:
        try:
            if p.role is Role.SOCKET:
                out.append(("socket", _socket_solid(p, ring, cfg, occ)))
            elif p.role is Role.PLUMBING:
                out.append(("pipe", _pipe_solid(p, ring, cfg)))
        except (BuildError, RuntimeError):
            continue          # a stray point off any wall is skipped, not fatal
    return out


def _touches(a, b) -> bool:
    """True when two solids actually share volume, not just proximity."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    common = BRepAlgoAPI_Common(a, b)
    common.Build()
    if not common.IsDone():
        return False
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(common.Shape(), props)
    return props.Mass() > 1.0        # mm3


def _add_fixtures(shape, room: Room, ring, cfg: BuildSettings, occ):
    """Fuse sockets and pipe stubs onto the shell.

    A fixture that misses the wall entirely would fuse into a floating body and
    quietly turn one solid into several. Those are dropped and reported instead,
    so the export is always a single watertight solid.
    """
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse
    from .model import Role

    stray: list[str] = []
    pts = [p for p in room.points if p.role in (Role.SOCKET, Role.PLUMBING)]
    solids = fixture_solids(room, ring, cfg, occ)

    for point, (_kind, solid) in zip(pts, solids):
        if not _touches(shape, solid):
            stray.append(point.name)
            continue
        fuse = BRepAlgoAPI_Fuse(shape, solid)
        fuse.Build()
        if fuse.IsDone():
            shape = fuse.Shape()
        else:
            stray.append(point.name)
    return shape, stray
