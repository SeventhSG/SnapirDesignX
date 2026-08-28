"""Escape hatch: hand a room to Geomagic Design X instead.

Exact wireframe, not a point cloud. Design X reads IGES and STEP curves
natively, and a curve carries the surveyed corner exactly where the instrument
put it. Sampling the same lines into points would throw that away and then
charge you the labour of fitting it back.

ASC points are offered too, for the cases where a cloud really is wanted.
"""
from __future__ import annotations

from pathlib import Path

from .model import Room
from .solid import CM_TO_MM, BuildError

_SUFFIX = {"iges": ".igs", "step": ".stp", "asc": ".asc"}


def export_curves(room: Room, out_dir: str | Path, fmt: str = "iges") -> Path:
    """Write the room outline, ceiling ring and openings as exact curves."""
    fmt = fmt.lower()
    if fmt not in _SUFFIX:
        raise BuildError(f"Unknown format: {fmt}")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{room.name}{_SUFFIX[fmt]}"

    if fmt == "asc":
        return _write_asc(room, path)
    if len(room.outline) < 3:
        raise BuildError(f"{room.name}: outline has fewer than three points")
    return _write_curves(room, path, fmt)


def _rings(room: Room):
    """Every closed or open polyline worth handing over."""
    from .planes import fit_or_level, level_plane

    rings: list[list[tuple[float, float, float]]] = []
    ring = [(p.x, p.y, p.z) for p in room.outline]
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
    return rings


def _write_curves(room: Room, path: Path, fmt: str) -> Path:
    from OCP.BRep import BRep_Builder
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon
    from OCP.gp import gp_Pnt
    from OCP.TopoDS import TopoDS_Compound

    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)

    for ring in _rings(room):
        poly = BRepBuilderAPI_MakePolygon()
        for x, y, z in ring:
            poly.Add(gp_Pnt(x * CM_TO_MM, y * CM_TO_MM, z * CM_TO_MM))
        if ring[0] != ring[-1]:
            poly.Close()
        builder.Add(compound, poly.Wire())

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
