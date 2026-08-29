// Plane geometry helpers. No CAD kernel here, so this stays link-cheap and
// testable on its own.
#pragma once
#include <utility>
#include <vector>

namespace snapir {

struct Pt {
  double x = 0, y = 0;
  bool operator==(const Pt& o) const { return x == o.x && y == o.y; }
};

double signed_area(const std::vector<Pt>& pts);  // positive when CCW
double polygon_area(const std::vector<Pt>& pts);
std::vector<Pt> ensure_ccw(const std::vector<Pt>& pts);
double perimeter(const std::vector<Pt>& pts);

// Indices of every pair of non-adjacent edges that cross.
std::vector<std::pair<int, int>> self_intersections(const std::vector<Pt>& pts);

// Drop consecutive points closer together than tol.
std::vector<Pt> dedupe(const std::vector<Pt>& pts, double tol = 0.5);

struct Bounds { double min_x, min_y, max_x, max_y; };
Bounds bounds(const std::vector<Pt>& pts);

struct Projection { int edge; Pt point; double distance; };
// Nearest point on the ring to pt. Used to seat an opening's jambs exactly on
// the wall they belong to, since a jamb reading sits a centimetre or two off
// the surveyed corner line.
Projection project_onto_edges(const Pt& pt, const std::vector<Pt>& ring);

double dist(const Pt& a, const Pt& b);

}  // namespace snapir
