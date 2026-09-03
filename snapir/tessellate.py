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
    # Which element of the room this face belongs to. `id` above is an OCCT
    # ordinal and is only good for this one build; `element` survives a
    # rebuild, so it is what a remembered decision is keyed on.
    element: str = ""               # e.g. "wall:P_003|P_004"
    element_kind: str = ""          # wall|floor|ceiling|opening|fitting|fixture|stairs|pervaz
    label: str = ""                 # e.g. "Wall 3 of 11"


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
                    "role": f.role, "element": f.element,
                    "elementKind": f.element_kind, "label": f.label,
                }
                for f in self.faces
            ],
            "triangleCount": self.triangle_count,
        }


def tessellate(shape, deflection: float = 1.0, angular: float = 0.3,
               room=None, cfg=None) -> Mesh:
    """Mesh a solid for display. Deflection is in millimetres.

    One millimetre is far finer than anything visible on screen and keeps the
    buffers small, because every face here is planar and meshes into a handful
    of triangles regardless of the setting.

    Pass the room and its build settings to have every face named: without
    them the mesh still draws, it just cannot say what anything is.
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

    if room is not None:
        _name_faces(mesh, room, cfg)
    return mesh


def _name_faces(mesh: Mesh, room, cfg) -> None:
    """Attribute every meshed face back to the element it was built from."""
    from .elements import elements, face_element
    from .settings import BuildSettings

    cfg = cfg or BuildSettings()
    table = elements(room)
    for f in mesh.faces:
        el = face_element(room, cfg, f.centroid, f.normal, table)
        if el is not None:
            f.element, f.element_kind, f.label = el.key, el.kind, el.label


def _face_role(nz: float) -> str:
    """Name a face by which way it points, so the UI can say 'ceiling'."""
    if nz > 0.9:
        return "ceiling"
    if nz < -0.9:
        return "floor"
    return "wall"
