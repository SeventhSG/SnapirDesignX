"""Triangles for the viewport, with the B-rep face each one came from.

The mesh exists only to put pixels on screen. Export never touches it. What
makes selection behave like Design X is the face id carried alongside every
triangle: clicking a triangle in the viewport resolves to the real OCCT face,
so 'this wall' means a face in the solid, not a bag of triangles.
"""
from __future__ import annotations

from dataclasses import dataclass, field

MM_TO_M = 0.001


@dataclass
class FaceInfo:
    id: int
    kind: str                       # "plane" | "cylinder" | "other"
    area_m2: float
    normal: tuple[float, float, float]
    centroid: tuple[float, float, float]
    role: str = "wall"              # "floor" | "ceiling" | "wall" | "reveal"


@dataclass
class Mesh:
    """Flat-shaded, non-indexed. Three vertices per triangle."""
    positions: list[float] = field(default_factory=list)
    normals: list[float] = field(default_factory=list)
    face_ids: list[int] = field(default_factory=list)      # one per triangle
    faces: list[FaceInfo] = field(default_factory=list)

    @property
    def triangle_count(self) -> int:
        return len(self.face_ids)

    def to_dict(self) -> dict:
        return {
            "positions": self.positions,
            "normals": self.normals,
            "faceIds": self.face_ids,
            "faces": [
                {
                    "id": f.id, "kind": f.kind, "area": round(f.area_m2, 4),
                    "normal": [round(v, 6) for v in f.normal],
                    "centroid": [round(v, 4) for v in f.centroid],
                    "role": f.role,
                }
                for f in self.faces
            ],
            "triangleCount": self.triangle_count,
        }


def tessellate(shape, deflection: float = 1.0, angular: float = 0.3) -> Mesh:
    """Mesh a solid for display. Deflection is in millimetres.

    One millimetre is far finer than anything visible on screen and keeps the
    buffers small, because every face here is planar and meshes into a handful
    of triangles regardless of the setting.
    """
    from OCP.BRep import BRep_Tool
    from OCP.BRepGProp import BRepGProp
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Plane
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    BRepMesh_IncrementalMesh(shape, deflection, False, angular, True)

    mesh = Mesh()
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    face_id = 0

    while explorer.More():
        face = TopoDS.Face_s(explorer.Current())
        explorer.Next()

        from OCP.TopLoc import TopLoc_Location
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face, loc)
        if tri is None:
            continue

        trsf = loc.Transformation()
        reversed_ = face.Orientation() == TopAbs_REVERSED

        nodes = [tri.Node(i).Transformed(trsf) for i in range(1, tri.NbNodes() + 1)]

        surf = BRepAdaptor_Surface(face)
        kind = {GeomAbs_Plane: "plane", GeomAbs_Cylinder: "cylinder"}.get(
            surf.GetType(), "other")

        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(face, props)
        c = props.CentreOfMass()

        nx = ny = nz = 0.0
        for i in range(1, tri.NbTriangles() + 1):
            a, b, cc = tri.Triangle(i).Get()
            if reversed_:
                b, cc = cc, b
            p1, p2, p3 = nodes[a - 1], nodes[b - 1], nodes[cc - 1]

            ux, uy, uz = p2.X() - p1.X(), p2.Y() - p1.Y(), p2.Z() - p1.Z()
            vx, vy, vz = p3.X() - p1.X(), p3.Y() - p1.Y(), p3.Z() - p1.Z()
            tnx, tny, tnz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
            length = (tnx * tnx + tny * tny + tnz * tnz) ** 0.5 or 1.0
            tnx, tny, tnz = tnx / length, tny / length, tnz / length
            nx, ny, nz = tnx, tny, tnz

            for p in (p1, p2, p3):
                mesh.positions += [p.X() * MM_TO_M, p.Y() * MM_TO_M, p.Z() * MM_TO_M]
                mesh.normals += [tnx, tny, tnz]
            mesh.face_ids.append(face_id)

        mesh.faces.append(FaceInfo(
            id=face_id, kind=kind, area_m2=props.Mass() / 1.0e6,
            normal=(nx, ny, nz),
            centroid=(c.X() * MM_TO_M, c.Y() * MM_TO_M, c.Z() * MM_TO_M),
            role=_face_role(nz),
        ))
        face_id += 1

    return mesh


def _face_role(nz: float) -> str:
    """Name a face by which way it points, so the UI can say 'ceiling'."""
    if nz > 0.9:
        return "ceiling"
    if nz < -0.9:
        return "floor"
    return "wall"
