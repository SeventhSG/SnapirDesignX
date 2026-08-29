// Triangles for the viewport, with the B-rep face each one came from.
//
// The mesh exists only to put pixels on screen. Export never touches it. What
// makes selection behave like Design X is the face id carried alongside every
// triangle: clicking a triangle in the viewport resolves to the real OCCT face,
// so "this wall" means a face in the solid, not a bag of triangles.
#pragma once
#include <array>
#include <string>
#include <vector>

#include <TopoDS_Shape.hxx>

namespace snapir {

inline constexpr double kMmToM = 0.001;

struct FaceInfo {
  int id = 0;
  std::string kind;  // "plane" | "cylinder" | "other"
  double area_m2 = 0;
  std::array<double, 3> normal{};
  std::array<double, 3> centroid{};
  std::string role = "wall";  // "floor" | "ceiling" | "wall" | "reveal"
};

// Flat-shaded, non-indexed. Three vertices per triangle.
struct Mesh {
  std::vector<double> positions;
  std::vector<double> normals;
  std::vector<int> face_ids;  // one per triangle
  std::vector<FaceInfo> faces;

  size_t triangle_count() const { return face_ids.size(); }
};

// Mesh a solid for display. Deflection is in millimetres.
//
// One millimetre is far finer than anything visible on screen and keeps the
// buffers small, because every face here is planar and meshes into a handful of
// triangles regardless of the setting.
Mesh tessellate(const TopoDS_Shape& shape, double deflection = 1.0,
                double angular = 0.3);

}  // namespace snapir
