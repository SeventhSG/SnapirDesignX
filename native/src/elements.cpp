#include "snapir/elements.hpp"

#include <algorithm>
#include <cmath>
#include <map>

#include "snapir/geometry.hpp"

namespace snapir {
namespace {

constexpr double kMToCm = 100.0;

// Attribution tolerances, centimetres. Generous: a face centroid sits in the
// middle of the material, not on the surveyed line.
constexpr double kOpeningPlanTol = 45.0;  // how far off the jamb line a reveal can sit
constexpr double kOpeningZTol = 12.0;
constexpr double kFixtureMargin = 6.0;  // beyond the fixture's own half-width
constexpr double kStairZTol = 6.0;

std::string jamb_anchor(const Jamb& jamb) {
  std::vector<std::string> names;
  for (const auto& p : jamb.points) names.push_back(p.name);
  if (names.empty()) {
    char buf[64];
    std::snprintf(buf, sizeof(buf), "@%.0f,%.0f", jamb.x, jamb.y);
    return buf;
  }
  std::sort(names.begin(), names.end());
  return names.front();
}

std::string fixture_at(const Room& room, const BuildSettings& cfg, double x,
                       double y, double z) {
  for (const auto& p : room.points) {
    double half = 0.0, height = 0.0;
    if (p.role == Role::Socket) {
      half = cfg.socket_width / 20.0;
      height = cfg.socket_height / 10.0;
    } else if (p.role == Role::Plumbing) {
      half = height = cfg.pipe_diameter / 10.0;
    } else {
      continue;
    }
    const double dx = p.x - x, dy = p.y - y;
    if (std::fabs(p.z - z) <= height &&
        std::sqrt(dx * dx + dy * dy) <= half + kFixtureMargin)
      return "fixture:" + p.name;
  }
  return "";
}

std::string opening_at(const Room& room, double x, double y, double z) {
  for (const auto& op : room.openings) {
    if (!(z >= op.sill() - kOpeningZTol && z <= op.head() + kOpeningZTol)) continue;
    const std::vector<Pt> span = {{op.left.x, op.left.y}, {op.right.x, op.right.y}};
    if (project_onto_edges({x, y}, span).distance <= kOpeningPlanTol)
      return opening_key(op);
  }
  return "";
}

std::string stair_at(const Room& room, const BuildSettings& cfg, double x,
                     double y, double z) {
  const double half = cfg.stair_width / 20.0;  // mm setting to cm, halved
  const double floor_z = room.floor_z ? *room.floor_z : 0.0;
  for (const auto& stair : room.stairs) {
    for (size_t s = 0; s + 1 < stair.points.size(); ++s) {
      const Point& a = stair.points[s];
      const Point& b = stair.points[s + 1];
      const double top = std::max(a.z, b.z);
      if (!(z >= floor_z - kStairZTol && z <= top + kStairZTol)) continue;
      const std::vector<Pt> span = {{a.x, a.y}, {b.x, b.y}};
      if (project_onto_edges({x, y}, span).distance <= half)
        return "stairs:" + stair.points.front().name + "#" + std::to_string(s);
    }
  }
  return "";
}

}  // namespace

std::string wall_key(const std::string& a, const std::string& b) {
  const std::string& lo = a < b ? a : b;
  const std::string& hi = a < b ? b : a;
  return "wall:" + lo + "|" + hi;
}

std::string opening_key(const Opening& op) {
  std::string a = jamb_anchor(op.left), b = jamb_anchor(op.right);
  if (b < a) std::swap(a, b);
  return "opening:" + a + "|" + b;
}

std::vector<Element> elements(const Room& room) {
  std::vector<Element> out;
  const auto& ring = room.outline;
  const int n = static_cast<int>(ring.size());

  for (int i = 0; i < n; ++i) {
    const Point& a = ring[i];
    const Point& b = ring[(i + 1) % n];
    out.push_back({"wall", wall_key(a.name, b.name),
                   "Wall " + std::to_string(i + 1) + " of " + std::to_string(n),
                   i, {a.name, b.name}});
  }

  if (n >= 3) {
    std::vector<std::string> names;
    for (const auto& p : ring) names.push_back(p.name);
    out.push_back({"floor", "floor", "Floor", std::nullopt, names});
  }
  if (!room.ceiling.empty()) {
    std::vector<std::string> names;
    for (const auto& p : room.ceiling) names.push_back(p.name);
    out.push_back({"ceiling", "ceiling", "Ceiling", std::nullopt, names});
  }

  for (size_t i = 0; i < room.openings.size(); ++i) {
    const Opening& op = room.openings[i];
    std::vector<std::string> pts;
    for (const auto& p : op.left.points) pts.push_back(p.name);
    for (const auto& p : op.right.points) pts.push_back(p.name);
    std::sort(pts.begin(), pts.end());
    out.push_back({op.cuts() ? "opening" : "fitting", opening_key(op),
                   kind_label(op.kind), static_cast<int>(i), pts});
  }

  for (const auto& p : room.points) {
    if (p.role == Role::Socket)
      out.push_back({"fixture", "fixture:" + p.name, "Socket " + p.name,
                     std::nullopt, {p.name}});
    else if (p.role == Role::Plumbing)
      out.push_back({"fixture", "fixture:" + p.name, "Pipe " + p.name,
                     std::nullopt, {p.name}});
  }

  for (size_t f = 0; f < room.stairs.size(); ++f) {
    const Stair& stair = room.stairs[f];
    // One element per shot-to-shot segment, which is a step when the flight was
    // shot at the nosings and half a step when it was traced as the zigzag.
    for (size_t s = 0; s + 1 < stair.points.size(); ++s) {
      const int step =
          static_cast<int>(stair.kind == "zigzag" ? s / 2 : s) + 1;
      std::string label = "Step " + std::to_string(step) + " of " +
                          std::to_string(stair.steps ? stair.steps : step);
      if (room.stairs.size() > 1)
        label += " (flight " + std::to_string(f + 1) + ")";
      out.push_back({"stairs",
                     "stairs:" + stair.points.front().name + "#" + std::to_string(s),
                     label, static_cast<int>(s),
                     {stair.points[s].name, stair.points[s + 1].name}});
    }
  }

  for (const auto& v : room.pervaz) {
    char buf[64];
    std::snprintf(buf, sizeof(buf), "Skirting %.0f\xC3\x97%.0f cm", v.height, v.depth);
    out.push_back({"pervaz", "pervaz:" + v.corner.name, buf, std::nullopt,
                   {v.corner.name, v.wall.name}});
  }
  return out;
}

std::optional<Element> face_element(const Room& room, const BuildSettings& cfg,
                                    const std::array<double, 3>& centroid_m,
                                    const std::array<double, 3>& normal,
                                    const std::vector<Element>& table) {
  std::map<std::string, const Element*> by_key;
  for (const auto& e : table) by_key[e.key] = &e;

  const double x = centroid_m[0] * kMToCm;
  const double y = centroid_m[1] * kMToCm;
  const double z = centroid_m[2] * kMToCm;
  const double nz = normal[2];

  std::string hit = stair_at(room, cfg, x, y, z);
  if (hit.empty()) hit = fixture_at(room, cfg, x, y, z);
  if (hit.empty()) hit = opening_at(room, x, y, z);
  if (!hit.empty()) {
    const auto it = by_key.find(hit);
    if (it != by_key.end()) return *it->second;
    return std::nullopt;
  }

  if (nz > 0.9) {
    const auto it = by_key.find("ceiling");
    return it == by_key.end() ? std::nullopt : std::optional<Element>(*it->second);
  }
  if (nz < -0.9) {
    const auto it = by_key.find("floor");
    return it == by_key.end() ? std::nullopt : std::optional<Element>(*it->second);
  }

  std::vector<Pt> ring;
  for (const auto& p : room.outline) ring.push_back({p.x, p.y});
  if (ring.size() < 3) return std::nullopt;
  const int edge = project_onto_edges({x, y}, ring).edge;
  const Point& a = room.outline[edge];
  const Point& b = room.outline[(edge + 1) % room.outline.size()];
  const auto it = by_key.find(wall_key(a.name, b.name));
  return it == by_key.end() ? std::nullopt : std::optional<Element>(*it->second);
}

std::optional<int> wall_edge_for_key(const Room& room, const std::string& key) {
  const int n = static_cast<int>(room.outline.size());
  for (int i = 0; i < n; ++i) {
    const Point& a = room.outline[i];
    const Point& b = room.outline[(i + 1) % n];
    if (wall_key(a.name, b.name) == key) return i;
  }
  return std::nullopt;
}

}  // namespace snapir
