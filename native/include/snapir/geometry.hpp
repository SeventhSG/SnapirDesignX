// Plane geometry helpers. No CAD kernel here, so this stays link-cheap and
// testable on its own.
#pragma once
#include <optional>
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

// Ray cast. Orientation-independent, so it does not care which way the ring
// was wound - which the topology walk does not guarantee.
bool point_in_polygon(const Pt& q, const std::vector<Pt>& ring);

// Where the infinite lines through a-b and c-d meet.
//
// Infinite, not segment-bounded, because the useful case is two wall runs that
// stop short of the corner they imply: the corner nobody could stand in is
// exactly the one worth constructing. Empty when they are parallel, or as near
// parallel as makes no difference.
std::optional<Pt> line_intersection(const Pt& a, const Pt& b, const Pt& c,
                                    const Pt& d);

// Push b further from a, along their own direction.
Pt extend(const Pt& a, const Pt& b, double distance);

// Every pair of segments that actually cross, and where. Shared endpoints do
// not count: two walls meeting at a surveyed corner are already joined, and
// reporting that as a crossing would turn every corner of every room into a
// discovery.
struct Crossing { int i; int j; Pt at; };
std::vector<Crossing> crossings(
    const std::vector<std::pair<Pt, Pt>>& segments);

}  // namespace snapir
