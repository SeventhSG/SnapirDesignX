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

from dataclasses import dataclass
from pathlib import Path

from shapely.geometry import Polygon

from .geometry import ensure_ccw, project_onto_edges
from .model import Jamb, Opening, Room
from .planes import Plane, fit_or_level, level_plane
from .settings import BuildSettings

CM_TO_MM = 10.0


def cm(mm: float) -> float:
    """Settings are millimetres; the survey and this module work in
    centimetres. One conversion, in one place."""
    return mm / 10.0


class BuildError(RuntimeError):
    pass


def _occ():
    """Import OCCT lazily so the parser and viewer load without the kernel."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
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
        "Fuse": BRepAlgoAPI_Fuse,
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
    reach = cm(cfg.wall_thickness) * 3.0
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


def build_room(room: Room, cfg: BuildSettings, openings=None,
               fixture_overrides: dict | None = None,
               removed_walls: list[str] | None = None):
    """Build one room shell. Returns an OCCT solid."""
    if len(room.outline) < 3:
        raise BuildError(f"{room.name}: outline has fewer than three points")
    occ = _occ()

    floor, ceiling = room_planes(room, cfg)
    inner_ring = [p.xy for p in room.outline]

    thickness = cm(room.wall_thickness if room.wall_thickness is not None
                 else cfg.wall_thickness)
    outer_ring = _offset_ring(inner_ring, thickness)

    outer_floor = Plane(floor.px, floor.py, floor.pz - cm(cfg.floor_thickness),
                        floor.nx, floor.ny, floor.nz)
    outer_ceiling = Plane(ceiling.px, ceiling.py, ceiling.pz + cm(cfg.ceiling_thickness),
                          ceiling.nx, ceiling.ny, ceiling.nz)

    outer = _prism(outer_ring, outer_floor, outer_ceiling, occ)
    inner = _prism(inner_ring, floor, ceiling, occ)

    cut = occ["Cut"](outer, inner)
    cut.Build()
    if not cut.IsDone():
        raise BuildError(f"{room.name}: could not subtract the room volume")
    shape = cut.Shape()

    # A wall the operator marked as not really there is cut the same way a
    # doorway is: full height, corner to corner, through the whole edge. The
    # key names its two corners, so a wall that no longer exists in the ring
    # (its corner was dropped, or the ring redrawn) is skipped rather than
    # taking a different wall down with it.
    from .elements import wall_edge_for_key

    for key in sorted(set(removed_walls or [])):
        i = wall_edge_for_key(room, key)
        if i is None:
            continue
        c = occ["Cut"](shape, _removed_wall_opening(inner_ring, floor, ceiling, i, cfg, occ))
        c.Build()
        if not c.IsDone():
            raise BuildError(f"{room.name}: could not remove wall {i + 1}")
        shape = c.Shape()

    rects = list(openings if openings is not None else room.openings)

    if cfg.cut_openings:
        # Only the rectangles that are actually holes. A boiler or a socket
        # panel is the same four corners in the survey and must not be cut
        # through the wall.
        for op in (o for o in rects if o.cuts):
            c = occ["Cut"](shape, _opening_cutter(op, inner_ring, cfg, occ))
            c.Build()
            if not c.IsDone():
                raise BuildError(f"{room.name}: opening cut failed")
            shape = c.Shape()

    if cfg.include_fittings:
        for op in (o for o in rects if not o.cuts and o.kind != "empty"):
            try:
                body = _fitting_body(op, inner_ring, cfg, occ)
            except (BuildError, RuntimeError):
                continue
            f = occ["Fuse"](shape, body)
            f.Build()
            if not f.IsDone():
                raise BuildError(f"{room.name}: could not place the {op.kind}")
            shape = f.Shape()

    if cfg.include_fixtures:
        shape, stray = _add_fixtures(shape, room, inner_ring, cfg, occ,
                                     fixture_overrides)
        if stray:
            from .model import Issue
            room.issues.append(Issue(
                "info", "fixture-off-wall",
                f"{len(stray)} service point(s) did not meet any wall and were "
                "left out of the body.", points=stray))

    if cfg.include_stairs and room.stairs:
        for step, body in enumerate(_stairs_bodies(room, cfg, floor, occ)):
            f = occ["Fuse"](shape, body)
            f.Build()
            if not f.IsDone():
                raise BuildError(f"{room.name}: could not fuse stair step {step + 1}")
            shape = f.Shape()

    if not occ["Check"](shape).IsValid():
        raise BuildError(f"{room.name}: resulting solid is not valid")
    return shape


def _removed_wall_opening(ring, floor: Plane, ceiling: Plane, i: int,
                          cfg: BuildSettings, occ):
    """A synthetic opening spanning the whole edge, floor to ceiling.

    Reuses the opening cutter rather than re-deriving a variable-thickness
    offset ring: cutting the entire wall out is exactly what an opening the
    width of the wall already does.
    """
    ax, ay = ring[i]
    bx, by = ring[(i + 1) % len(ring)]
    left = Jamb(x=ax, y=ay, z_bottom=floor.z_at(ax, ay), z_top=ceiling.z_at(ax, ay))
    right = Jamb(x=bx, y=by, z_bottom=floor.z_at(bx, by), z_top=ceiling.z_at(bx, by))
    return _opening_cutter(Opening(left=left, right=right, kind="removed"), ring, cfg, occ)


def _fitting_body(op: Opening, ring, cfg: BuildSettings, occ):
    """The solid a wall rectangle stands up as, when it is not a hole.

    All of them are seated on the wall the rectangle was shot on and grow
    inward from it, so the surveyed face stays where the instrument put it -
    the same rule the walls themselves follow. Depth is not in the survey; it
    comes from settings, per kind.
    """
    cx, cy = (op.left.x + op.right.x) / 2, (op.left.y + op.right.y) / 2
    (sx, sy), (nx, ny), (tx, ty), _dist = _wall_frame(cx, cy, ring)

    # A shot in the middle of the rectangle measured how far the thing sticks
    # out. Where the surveyor took one it wins outright; the settings are only
    # for rectangles nobody measured the depth of.
    depth = op.depth if op.depth else {
        "boiler": cm(cfg.boiler_depth), "lamp": cm(cfg.lamp_depth),
    }.get(op.kind, cm(cfg.panel_depth))
    # Every fitting reaches a little way into the wall. Sitting exactly on the
    # surface looks right and fuses badly: a round tank touching a flat wall
    # meets it along a single line, and the kernel hands back two solids that
    # merely happen to touch instead of one body.
    bite = cm(cfg.socket_embed)

    if op.kind == "boiler":
        # A tank: round, upright, its back in the wall.
        from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
        from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

        radius = min(depth, max(op.width, 1.0) / 2)
        reach = max(radius - min(bite, radius / 2), 0.1)
        base = gp_Pnt((sx + nx * reach) * CM_TO_MM,
                      (sy + ny * reach) * CM_TO_MM, op.sill * CM_TO_MM)
        axis = gp_Ax2(base, gp_Dir(0.0, 0.0, 1.0))
        return BRepPrimAPI_MakeCylinder(
            axis, radius * CM_TO_MM, max(op.height, 1.0) * CM_TO_MM).Shape()

    # Everything else is a box the size of the rectangle, standing proud.
    half = max(op.width, 1.0) / 2
    back, front = -bite, depth
    corners = [
        (sx + tx * half + nx * back, sy + ty * half + ny * back),
        (sx - tx * half + nx * back, sy - ty * half + ny * back),
        (sx - tx * half + nx * front, sy - ty * half + ny * front),
        (sx + tx * half + nx * front, sy + ty * half + ny * front),
    ]
    return _prism(corners, level_plane(op.sill), level_plane(op.head), occ)


def _stairs_bodies(room: Room, cfg: BuildSettings, floor: Plane, occ) -> list:
    """One box per step, stacked from the floor up to that step's height.

    Only the nosing line is shot, so each box is centred on the line and
    given the settings' flight width - there is nothing else in the survey to
    derive it from. This is the stair as built mass, not the void beneath it.
    """
    width = cm(cfg.stair_width)
    bodies = []
    for stair in room.stairs:
        pts = stair.points
        for i in range(len(pts) - 1):
            a, b = pts[i], pts[i + 1]
            dx, dy = b.x - a.x, b.y - a.y
            length = (dx * dx + dy * dy) ** 0.5
            if length < 1.0:
                continue
            tx, ty = dx / length, dy / length
            nx, ny = ty, -tx
            hw = width / 2
            corners = [
                (a.x + nx * hw, a.y + ny * hw),
                (b.x + nx * hw, b.y + ny * hw),
                (b.x - nx * hw, b.y - ny * hw),
                (a.x - nx * hw, a.y - ny * hw),
            ]
            bottom = level_plane(floor.z_at(a.x, a.y))
            top = level_plane(max(a.z, b.z))
            try:
                bodies.append(_prism(corners, bottom, top, occ))
            except BuildError:
                continue
    return bodies


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

# ---------------------------------------------------------------- fixtures


@dataclass
class Fixture:
    """One building service, seated on the wall it belongs to."""
    name: str
    kind: str                 # "socket" | "pipe"
    mode: str                 # "box" | "hole" | "stub"
    solid: object
    seat: tuple[float, float]
    normal: tuple[float, float]
    reach: float              # cm the fixture stands out from the inner face


def _wall_frame(x: float, y: float, ring):
    """Seat a surveyed point on its wall and return the inward normal.

    Service points are never shot on the surface. A socket reads a centimetre
    or two out at the faceplate, a pipe reads wherever its open end happens to
    be, up to ten centimetres into the room. Projecting onto the nearest wall
    is what puts the fixture where the building actually has it.
    """
    from shapely.geometry import Point, Polygon

    idx, seat, dist = project_onto_edges((x, y), list(ring))
    a, b = ring[idx], ring[(idx + 1) % len(ring)]
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = (dx * dx + dy * dy) ** 0.5 or 1.0
    nx, ny = -dy / length, dx / length

    poly = Polygon(ring)
    if not poly.contains(Point(seat[0] + nx * 0.5, seat[1] + ny * 0.5)):
        nx, ny = -nx, -ny            # normal must point into the room
    return seat, (nx, ny), (dx / length, dy / length), dist


def _socket_shape(pt, ring, cfg: BuildSettings, mode: str, occ):
    """A back box standing proud of the wall, or a recess cut into it.

    Anchored on the seat rather than the reading, and always reaching into the
    wall by `socket_embed`, so it cannot end up floating in the room.
    """
    (sx, sy), (nx, ny), (tx, ty), dist = _wall_frame(pt.x, pt.y, ring)
    hw = cm(cfg.socket_width) / 2

    if mode == "hole":
        near, far = 0.5, -cm(cfg.socket_recess)          # into the wall
    else:
        near = max(dist, cm(cfg.socket_proud))           # out to the faceplate
        far = -cm(cfg.socket_embed)
    corners = [
        (sx + tx * hw + nx * far, sy + ty * hw + ny * far),
        (sx - tx * hw + nx * far, sy - ty * hw + ny * far),
        (sx - tx * hw + nx * near, sy - ty * hw + ny * near),
        (sx + tx * hw + nx * near, sy + ty * hw + ny * near),
    ]
    half = cm(cfg.socket_height) / 2
    solid = _prism(corners, level_plane(pt.z - half), level_plane(pt.z + half), occ)
    return solid, (sx, sy), (nx, ny), near


def _pipe_shape(pt, ring, cfg: BuildSettings, mode: str):
    """A pipe stub reaching the surveyed point, or a sleeve through the wall.

    The surveyed reading is the open end of the pipe, so the stub is built to
    reach exactly that far and no further. Nothing is invented.
    """
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

    (sx, sy), (nx, ny), _t, dist = _wall_frame(pt.x, pt.y, ring)
    reach = cm(cfg.pipe_length) or max(dist, cm(cfg.pipe_min_length))
    embed = cm(cfg.wall_thickness) * 1.5 if mode == "hole" else cm(cfg.pipe_embed)

    origin = gp_Pnt((sx - nx * embed) * CM_TO_MM, (sy - ny * embed) * CM_TO_MM,
                    pt.z * CM_TO_MM)
    axis = gp_Ax2(origin, gp_Dir(nx, ny, 0.0))
    height = (embed + (0.5 if mode == "hole" else reach)) * CM_TO_MM
    solid = BRepPrimAPI_MakeCylinder(axis, cm(cfg.pipe_diameter) / 2 * CM_TO_MM,
                                     height).Shape()
    return solid, (sx, sy), (nx, ny), reach


def _merge_sockets(room: Room, ring, cfg: BuildSettings):
    """Group sockets that sit shoulder to shoulder into single runs.

    Two boxes 80 mm wide whose centres are 80 mm apart share a face. Left
    alone they fuse into one lumpy body with a seam down the middle; grouped,
    they become one clean outlet the length of the run, which is what a double
    or triple socket actually is.
    """
    from .model import Role

    sockets = [p for p in room.points if p.role is Role.SOCKET]
    seats = {}
    for p in sockets:
        seat, _n, tan, _d = _wall_frame(p.x, p.y, ring)
        idx, _s, _dd = project_onto_edges(seat, list(ring))
        # Distance along the wall, so neighbours can be ordered and measured.
        along = seat[0] * tan[0] + seat[1] * tan[1]
        seats[p.name] = (idx, along)

    half = cm(cfg.socket_width) / 2
    gap = cm(cfg.sockets_merge_gap)
    groups: list[list] = []
    for p in sorted(sockets, key=lambda q: (seats[q.name][0], seats[q.name][1])):
        idx, along = seats[p.name]
        if groups:
            last = groups[-1][-1]
            lidx, lalong = seats[last.name]
            same_wall = lidx == idx
            touching = abs(along - lalong) - 2 * half <= gap
            level = abs(p.z - last.z) <= cm(cfg.socket_height)
            if same_wall and touching and level:
                groups[-1].append(p)
                continue
        groups.append([p])
    return groups


def _socket_run(group, ring, cfg: BuildSettings, mode: str, occ):
    """One box spanning a whole run of touching sockets."""
    if len(group) == 1:
        return _socket_shape(group[0], ring, cfg, mode, occ)

    (sx, sy), (nx, ny), (tx, ty), dist = _wall_frame(
        sum(p.x for p in group) / len(group),
        sum(p.y for p in group) / len(group), ring)

    # Span from the outer edge of the first box to the outer edge of the last.
    alongs = [ (p.x - sx) * tx + (p.y - sy) * ty for p in group ]
    half = cm(cfg.socket_width) / 2
    lo, hi = min(alongs) - half, max(alongs) + half

    if mode == "hole":
        near, far = 0.5, -cm(cfg.socket_recess)
    else:
        near = max(dist, cm(cfg.socket_proud))
        far = -cm(cfg.socket_embed)

    corners = [
        (sx + tx * lo + nx * far, sy + ty * lo + ny * far),
        (sx + tx * hi + nx * far, sy + ty * hi + ny * far),
        (sx + tx * hi + nx * near, sy + ty * hi + ny * near),
        (sx + tx * lo + nx * near, sy + ty * lo + ny * near),
    ]
    zc = sum(p.z for p in group) / len(group)
    h = cm(cfg.socket_height) / 2
    solid = _prism(corners, level_plane(zc - h), level_plane(zc + h), occ)
    return solid, (sx, sy), (nx, ny), near


def fixtures(room: Room, ring, cfg: BuildSettings, occ,
             overrides: dict | None = None) -> list[Fixture]:
    """Every service fixture in the room, each carrying the point it came from."""
    from .model import Role

    overrides = overrides or {}
    out: list[Fixture] = []

    # Sockets first, in runs, so neighbours arrive as one outlet.
    for group in _merge_sockets(room, ring, cfg):
        mode = overrides.get(group[0].name, {}).get("mode", cfg.socket_mode)
        try:
            solid, seat, nrm, reach = _socket_run(group, ring, cfg, mode, occ)
        except (BuildError, RuntimeError):
            continue
        name = group[0].name if len(group) == 1 else \
            f"{group[0].name}+{len(group) - 1}"
        out.append(Fixture(name, "socket", mode, solid, seat, nrm, reach))

    for p in room.points:
        if p.role is not Role.PLUMBING:
            continue
        mode = overrides.get(p.name, {}).get("mode", cfg.pipe_mode)
        try:
            solid, seat, nrm, reach = _pipe_shape(p, ring, cfg, mode)
        except (BuildError, RuntimeError):
            continue
        out.append(Fixture(p.name, "pipe", mode, solid, seat, nrm, reach))
    return out


def _add_fixtures(shape, room: Room, ring, cfg: BuildSettings, occ,
                  overrides: dict | None = None):
    """Fuse or cut every fixture, and report any that would not attach."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse

    stray: list[str] = []
    for f in fixtures(room, ring, cfg, occ, overrides):
        op = BRepAlgoAPI_Cut if f.mode == "hole" else BRepAlgoAPI_Fuse
        run = op(shape, f.solid)
        run.Build()
        if not run.IsDone():
            stray.append(f.name)
            continue
        result = run.Shape()
        if _solid_count(result) != 1:
            stray.append(f.name)          # it detached; keep the body whole
            continue
        shape = result
    return shape, stray


def _solid_count(shape) -> int:
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer

    exp, n = TopExp_Explorer(shape, TopAbs_SOLID), 0
    while exp.More():
        n += 1
        exp.Next()
    return n


def wall_index_at(room: Room, x_m: float, y_m: float) -> int:
    """Which outline edge a point in the plan belongs to.

    Takes metres, because that is what the viewport reports for a picked face.
    """
    ring = [p.xy for p in room.outline]
    if len(ring) < 2:
        raise BuildError("room has no outline")
    idx, _seat, _d = project_onto_edges((x_m * 100.0, y_m * 100.0), ring)
    return idx


def _outward(ring):
    """A function giving the outward normal of any edge of the ring.

    Taken from the ring's winding rather than by testing each corner. A test
    per corner gets reflex corners backwards, and a room with a niche has
    several of those.
    """
    from .geometry import signed_area
    ccw = signed_area(list(ring)) > 0

    def normal(a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = (dx * dx + dy * dy) ** 0.5 or 1.0
        tx, ty = dx / L, dy / L
        return ((ty, -tx) if ccw else (-ty, tx)), (tx, ty)

    return normal


def _mitre_vertex(ring, i: int, dist: float):
    """The outer corner where two offset wall faces meet.

    Solved as the intersection of the two offset edge lines, so neighbouring
    walls share exactly this point and tile back into the room with no overlap
    and no gap.
    """
    n = len(ring)
    prev, here, nxt = ring[(i - 1) % n], ring[i], ring[(i + 1) % n]
    normal = _outward(ring)
    n1, t1 = normal(prev, here)
    n2, t2 = normal(here, nxt)

    p1 = (here[0] + n1[0] * dist, here[1] + n1[1] * dist)
    p2 = (here[0] + n2[0] * dist, here[1] + n2[1] * dist)
    denom = t1[0] * t2[1] - t1[1] * t2[0]
    if abs(denom) < 1e-9:
        return p1                      # the two walls run straight through
    s_ = ((p2[0] - p1[0]) * t2[1] - (p2[1] - p1[1]) * t2[0]) / denom
    return (p1[0] + t1[0] * s_, p1[1] + t1[1] * s_)


def wall_body(room: Room, cfg: BuildSettings, edge: int,
              fixture_overrides: dict | None = None):
    """One wall of the room as its own usable solid.

    A straight extrusion of the face, and nothing else. The footprint is the
    surveyed wall line pushed back by the wall thickness, with square ends on
    the two corner points. The result is the rectangular panel you were looking
    at when you picked it, not a piece fanned out to fill the corners.

    The corner blocks are therefore not part of any wall. That is deliberate:
    a wall exported this way is a part with the dimensions it appears to have.

    The wall arrives finished. Door and window openings are already cut through
    it with their reveals, and the sockets and pipe stubs that belong to this
    wall are fused onto it. Fixtures on the other walls are left behind.
    """
    from dataclasses import replace

    ring = [p.xy for p in room.outline]
    n = len(ring)
    if not 0 <= edge < n:
        raise BuildError(f"{room.name}: no wall {edge}")

    occ = _occ()
    a, b = ring[edge], ring[(edge + 1) % n]
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = (dx * dx + dy * dy) ** 0.5
    if length < 1.0:
        raise BuildError("wall has no length")

    thickness = cm(room.wall_thickness if room.wall_thickness is not None
                 else cfg.wall_thickness)

    # Fixtures stand proud of the wall face, so they would be shaved off by a
    # cut that stops at the surface. The shell is built bare and this wall's
    # own fixtures are added back afterwards.
    bare = build_room(room, replace(cfg, include_fixtures=False))
    floor, ceiling = room_planes(room, cfg)

    (nx, ny), _t = _outward(ring)(a, b)
    footprint = [a, b,
                 (b[0] + nx * thickness, b[1] + ny * thickness),
                 (a[0] + nx * thickness, a[1] + ny * thickness)]
    box = _prism(footprint, floor, ceiling, occ)

    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
    common = BRepAlgoAPI_Common(bare, box)
    common.Build()
    if not common.IsDone():
        raise BuildError(f"{room.name}: could not separate wall {edge + 1}")
    body = common.Shape()

    if cfg.include_fixtures:
        for f in fixtures(room, ring, cfg, occ, fixture_overrides):
            idx, _seat, _d = project_onto_edges(f.seat, ring)
            if idx != edge:
                continue                      # belongs to another wall
            op = BRepAlgoAPI_Cut if f.mode == "hole" else BRepAlgoAPI_Fuse
            run = op(body, f.solid)
            run.Build()
            if run.IsDone():
                body = run.Shape()

    count = _solid_count(body)
    if count == 0:
        raise BuildError(f"{room.name}: wall {edge + 1} came out empty")
    # More than one solid is a real outcome, not a fault: an opening at the end
    # of a wall can leave the head and sill bands unconnected. STEP carries
    # them as separate bodies, which is still a usable part.
    if not occ["Check"](body).IsValid():
        raise BuildError(f"{room.name}: wall {edge + 1} is not a valid solid")
    return body, length, count
