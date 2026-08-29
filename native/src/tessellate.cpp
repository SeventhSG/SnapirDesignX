#include "snapir/tessellate.hpp"

#include <algorithm>
#include <cmath>

#include <BRepAdaptor_Surface.hxx>
#include <BRepGProp.hxx>
#include <BRepMesh_IncrementalMesh.hxx>
#include <BRep_Tool.hxx>
#include <GProp_GProps.hxx>
#include <GeomAbs_SurfaceType.hxx>
#include <Poly_Triangulation.hxx>
#include <TopAbs_Orientation.hxx>
#include <TopExp_Explorer.hxx>
#include <TopLoc_Location.hxx>
#include <TopoDS.hxx>

namespace snapir {
namespace {

// Name a face by which way it points, so the UI can say "ceiling".
std::string face_role(double nz) {
  if (nz > 0.9) return "ceiling";
  if (nz < -0.9) return "floor";
  return "wall";
}

}  // namespace

Mesh tessellate(const TopoDS_Shape& shape, double deflection, double angular) {
  BRepMesh_IncrementalMesh mesher(shape, deflection, Standard_False, angular,
                                  Standard_True);
  (void)mesher;

  Mesh mesh;
  int face_id = 0;

  for (TopExp_Explorer explorer(shape, TopAbs_FACE); explorer.More(); explorer.Next()) {
    const TopoDS_Face face = TopoDS::Face(explorer.Current());

    TopLoc_Location loc;
    const Handle(Poly_Triangulation) tri = BRep_Tool::Triangulation(face, loc);
    if (tri.IsNull()) continue;

    const gp_Trsf trsf = loc.Transformation();
    const bool is_reversed = face.Orientation() == TopAbs_REVERSED;

    std::vector<gp_Pnt> nodes;
    nodes.reserve(tri->NbNodes());
    for (int i = 1; i <= tri->NbNodes(); ++i) nodes.push_back(tri->Node(i).Transformed(trsf));

    BRepAdaptor_Surface surf(face);
    std::string kind = "other";
    if (surf.GetType() == GeomAbs_Plane) kind = "plane";
    else if (surf.GetType() == GeomAbs_Cylinder) kind = "cylinder";

    GProp_GProps props;
    BRepGProp::SurfaceProperties(face, props);
    const gp_Pnt c = props.CentreOfMass();

    double nx = 0, ny = 0, nz = 0;
    for (int i = 1; i <= tri->NbTriangles(); ++i) {
      int a = 0, b = 0, cc = 0;
      tri->Triangle(i).Get(a, b, cc);
      if (is_reversed) std::swap(b, cc);
      const gp_Pnt& p1 = nodes[a - 1];
      const gp_Pnt& p2 = nodes[b - 1];
      const gp_Pnt& p3 = nodes[cc - 1];

      const double ux = p2.X() - p1.X(), uy = p2.Y() - p1.Y(), uz = p2.Z() - p1.Z();
      const double vx = p3.X() - p1.X(), vy = p3.Y() - p1.Y(), vz = p3.Z() - p1.Z();
      double tnx = uy * vz - uz * vy;
      double tny = uz * vx - ux * vz;
      double tnz = ux * vy - uy * vx;
      double length = std::sqrt(tnx * tnx + tny * tny + tnz * tnz);
      if (length == 0.0) length = 1.0;
      tnx /= length;
      tny /= length;
      tnz /= length;
      nx = tnx;
      ny = tny;
      nz = tnz;

      for (const gp_Pnt* p : {&p1, &p2, &p3}) {
        mesh.positions.push_back(p->X() * kMmToM);
        mesh.positions.push_back(p->Y() * kMmToM);
        mesh.positions.push_back(p->Z() * kMmToM);
        mesh.normals.push_back(tnx);
        mesh.normals.push_back(tny);
        mesh.normals.push_back(tnz);
      }
      mesh.face_ids.push_back(face_id);
    }

    mesh.faces.push_back({face_id, kind, props.Mass() / 1.0e6,
                          {nx, ny, nz},
                          {c.X() * kMmToM, c.Y() * kMmToM, c.Z() * kMmToM},
                          face_role(nz)});
    ++face_id;
  }

  return mesh;
}

}  // namespace snapir
