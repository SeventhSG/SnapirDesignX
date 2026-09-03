#include "snapir/geometry.hpp"
#include <algorithm>
#include <cmath>
#include <limits>

namespace snapir {
namespace {

double cross3(const Pt& o, const Pt& p, const Pt& q) {
  return (p.x - o.x) * (q.y - o.y) - (p.y - o.y) * (q.x - o.x);
}

bool crosses(const Pt& a, const Pt& b, const Pt& c, const Pt& d) {
  const double d1 = cross3(c, d, a), d2 = cross3(c, d, b);
  const double d3 = cross3(a, b, c), d4 = cross3(a, b, d);
  return ((d1 > 0) != (d2 > 0)) && ((d3 > 0) != (d4 > 0));
}

Pt closest_on_segment(const Pt& p, const Pt& a, const Pt& b) {
  const double dx = b.x - a.x, dy = b.y - a.y;
  const double l2 = dx * dx + dy * dy;
  if (l2 == 0) return a;
  double t = ((p.x - a.x) * dx + (p.y - a.y) * dy) / l2;
  t = std::max(0.0, std::min(1.0, t));
  return {a.x + t * dx, a.y + t * dy};
}

}  // namespace

double dist(const Pt& a, const Pt& b) {
  return std::sqrt((a.x - b.x) * (a.x - b.x) + (a.y - b.y) * (a.y - b.y));
}

double signed_area(const std::vector<Pt>& pts) {
  const size_t n = pts.size();
  if (n < 3) return 0.0;
  double s = 0.0;
  for (size_t i = 0; i < n; ++i) {
    const Pt& a = pts[i];
    const Pt& b = pts[(i + 1) % n];
    s += a.x * b.y - b.x * a.y;
  }
  return s / 2.0;
}

double polygon_area(const std::vector<Pt>& pts) { return std::abs(signed_area(pts)); }

std::vector<Pt> ensure_ccw(const std::vector<Pt>& pts) {
  if (signed_area(pts) > 0) return pts;
  return std::vector<Pt>(pts.rbegin(), pts.rend());
}

double perimeter(const std::vector<Pt>& pts) {
  const size_t n = pts.size();
  double s = 0.0;
  for (size_t i = 0; i < n; ++i) s += dist(pts[i], pts[(i + 1) % n]);
  return s;
}

std::vector<std::pair<int, int>> self_intersections(const std::vector<Pt>& pts) {
  std::vector<std::pair<int, int>> hits;
  const int n = static_cast<int>(pts.size());
  if (n < 4) return hits;
  for (int i = 0; i < n; ++i) {
    for (int j = i + 2; j < n; ++j) {
      if (i == 0 && j == n - 1) continue;  // adjacent across the seam
      if (crosses(pts[i], pts[(i + 1) % n], pts[j], pts[(j + 1) % n]))
        hits.emplace_back(i, j);
    }
  }
  return hits;
}

std::vector<Pt> dedupe(const std::vector<Pt>& pts, double tol) {
  std::vector<Pt> out;
  for (const auto& p : pts)
    if (out.empty() || dist(out.back(), p) > tol) out.push_back(p);
  while (out.size() > 1 && dist(out.front(), out.back()) <= tol) out.pop_back();
  return out;
}

Bounds bounds(const std::vector<Pt>& pts) {
  Bounds b{std::numeric_limits<double>::infinity(), std::numeric_limits<double>::infinity(),
           -std::numeric_limits<double>::infinity(), -std::numeric_limits<double>::infinity()};
  for (const auto& p : pts) {
    b.min_x = std::min(b.min_x, p.x);
    b.min_y = std::min(b.min_y, p.y);
    b.max_x = std::max(b.max_x, p.x);
    b.max_y = std::max(b.max_y, p.y);
  }
  return b;
}

Projection project_onto_edges(const Pt& pt, const std::vector<Pt>& ring) {
  const int n = static_cast<int>(ring.size());
  Projection best{0, ring.empty() ? Pt{} : ring[0], std::numeric_limits<double>::infinity()};
  for (int i = 0; i < n; ++i) {
    const Pt q = closest_on_segment(pt, ring[i], ring[(i + 1) % n]);
    const double d = dist(pt, q);
    if (d < best.distance) best = {i, q, d};
  }
  return best;
}

std::optional<Pt> line_intersection(const Pt& a, const Pt& b, const Pt& c,
                                    const Pt& d) {
  const double rx = b.x - a.x, ry = b.y - a.y;
  const double sx = d.x - c.x, sy = d.y - c.y;
  const double denom = rx * sy - ry * sx;
  if (std::fabs(denom) < 1e-9) return std::nullopt;
  const double t = ((c.x - a.x) * sy - (c.y - a.y) * sx) / denom;
  return Pt{a.x + t * rx, a.y + t * ry};
}

Pt extend(const Pt& a, const Pt& b, double distance) {
  const double dx = b.x - a.x, dy = b.y - a.y;
  const double length = std::sqrt(dx * dx + dy * dy);
  if (length < 1e-9) return b;
  return Pt{b.x + dx / length * distance, b.y + dy / length * distance};
}

namespace {
bool shares_end(const std::pair<Pt, Pt>& s1, const std::pair<Pt, Pt>& s2,
                double tol = 0.5) {
  const Pt a[2] = {s1.first, s1.second};
  const Pt b[2] = {s2.first, s2.second};
  for (const Pt& p : a)
    for (const Pt& q : b)
      if (dist(p, q) <= tol) return true;
  return false;
}
}  // namespace

std::vector<Crossing> crossings(const std::vector<std::pair<Pt, Pt>>& segments) {
  std::vector<Crossing> out;
  const int n = static_cast<int>(segments.size());
  for (int i = 0; i < n; ++i) {
    for (int j = i + 1; j < n; ++j) {
      if (shares_end(segments[i], segments[j])) continue;
      if (!crosses(segments[i].first, segments[i].second, segments[j].first,
                   segments[j].second))
        continue;
      const auto at = line_intersection(segments[i].first, segments[i].second,
                                        segments[j].first, segments[j].second);
      if (at) out.push_back({i, j, *at});
    }
  }
  return out;
}

}  // namespace snapir
