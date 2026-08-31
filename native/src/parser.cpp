#include "snapir/parser.hpp"
#include "snapir/csv.hpp"
#include "snapir/geometry.hpp"
#include "snapir/topology.hpp"

#include <algorithm>
#include <array>
#include <cctype>
#include <cmath>
#include <filesystem>
#include <optional>
#include <set>
#include <sstream>
#include <stdexcept>
#include <unordered_map>

namespace fs = std::filesystem;

namespace snapir {
namespace {

// Layer names as written by iCON trades, and what they mean.
const std::map<std::string, Role>& layer_roles() {
  static const std::map<std::string, Role> m = {
      {"zemin", Role::Floor},
      {"kontak", Role::Socket},
      {"su tesisat", Role::Plumbing},
      {"kontrol noktalari", Role::Control},
      {"kontrol noktalar\xc4\xb1", Role::Control},  // kontrol noktalari, dotless i
  };
  return m;
}

double parse_number(const std::string& v) {
  std::string s;
  for (char c : v) s += (c == ',') ? '.' : c;
  s = trim(s);
  if (s.empty()) throw std::invalid_argument("empty");
  size_t used = 0;
  const double d = std::stod(s, &used);
  if (used != s.size()) throw std::invalid_argument("trailing");
  return d;
}

std::string norm(const std::string& v) {
  std::string s = trim(v);
  for (char& c : s) {
    const auto u = static_cast<unsigned char>(c);
    if (u < 128) c = static_cast<char>(std::tolower(u));
  }
  return s;
}

std::string ascii_upper(const std::string& v) {
  std::string s = v;
  for (char& c : s) {
    const auto u = static_cast<unsigned char>(c);
    if (u < 128) c = static_cast<char>(std::toupper(u));
  }
  return s;
}

// (LEICA|LEICA).*TOOL, case-insensitive, where the second spelling carries the
// Turkish dotted capital. That is what the iCS50 actually writes, so both have
// to be accepted.
bool is_station(const std::string& name) {
  const std::string up = ascii_upper(name);
  const char* brands[2] = {"LEICA", "LE\xc4\xb0" "CA"};
  for (const char* brand : brands) {
    const auto at = up.find(brand);
    if (at != std::string::npos && up.find("TOOL", at) != std::string::npos) return true;
  }
  return false;
}

int first_index(const std::string& name) {
  for (size_t i = 0; i < name.size(); ++i) {
    if (std::isdigit(static_cast<unsigned char>(name[i]))) {
      size_t j = i;
      while (j < name.size() && std::isdigit(static_cast<unsigned char>(name[j]))) ++j;
      return std::stoi(name.substr(i, j - i));
    }
  }
  return 0;
}

bool starts_with(const std::string& s, const std::string& prefix) {
  return s.size() >= prefix.size() && s.compare(0, prefix.size(), prefix) == 0;
}

double dist2d(const Point& a, const Point& b) {
  return std::sqrt((a.x - b.x) * (a.x - b.x) + (a.y - b.y) * (a.y - b.y));
}

Pt xy(const Point& p) { return {p.x, p.y}; }

// Find the floor and ceiling planes by clustering Z values.
//
// The instrument is not always levelled to the slab. One surveyor left the
// origin at instrument height, putting the whole floor at Z = -126.66, so a
// hardcoded zero is not safe. The floor is simply the lowest dense band of
// readings, the ceiling the highest one far enough above it.
std::pair<std::optional<double>, std::optional<double>> z_datums(const Room& room) {
  std::vector<double> zs;
  zs.reserve(room.points.size());
  for (const auto& p : room.points) zs.push_back(p.z);
  if (zs.empty()) return {std::nullopt, std::nullopt};
  std::sort(zs.begin(), zs.end());

  std::vector<std::vector<double>> bands;
  for (double z : zs) {
    if (!bands.empty() && z - bands.back().back() <= kZBandTol) bands.back().push_back(z);
    else bands.push_back({z});
  }

  std::vector<const std::vector<double>*> dense;
  for (const auto& b : bands)
    if (b.size() >= 3) dense.push_back(&b);
  if (dense.empty())
    for (const auto& b : bands) dense.push_back(&b);

  const auto mean = [](const std::vector<double>& b) {
    double s = 0.0;
    for (double v : b) s += v;
    return s / static_cast<double>(b.size());
  };

  const double floor = mean(*dense.front());
  std::optional<double> ceiling;
  for (auto it = bands.rbegin(); it != bands.rend(); ++it) {
    const double m = mean(*it);
    if (it->size() >= 2 && m - floor >= kMinRoomHeight) { ceiling = m; break; }
  }
  return {floor, ceiling};
}

// Group shots that share a plan position, preserving survey order.
std::vector<std::vector<Point*>> cluster_xy(std::vector<Point*> points,
                                            double tol = kJambXyTol) {
  std::stable_sort(points.begin(), points.end(),
                   [](const Point* a, const Point* b) { return a->index < b->index; });
  std::vector<std::vector<Point*>> clusters;
  for (Point* p : points) {
    bool placed = false;
    for (auto& c : clusters) {
      if (dist2d(*p, *c.front()) <= tol) { c.push_back(p); placed = true; break; }
    }
    if (!placed) clusters.push_back({p});
  }
  return clusters;
}

Jamb jamb_from(const std::vector<Point*>& c) {
  Jamb j;
  double sx = 0, sy = 0;
  double lo = c.front()->z, hi = c.front()->z;
  for (const Point* p : c) {
    sx += p->x;
    sy += p->y;
    lo = std::min(lo, p->z);
    hi = std::max(hi, p->z);
    j.points.push_back(*p);
  }
  j.x = sx / static_cast<double>(c.size());
  j.y = sy / static_cast<double>(c.size());
  j.z_bottom = lo;
  j.z_top = hi;
  return j;
}

// Split a full-height corner cluster into its floor and ceiling shots.
void mark_corner(const std::vector<Point*>& cluster, double floor_z, double ceil_z) {
  int order = cluster.front()->index;
  for (const Point* p : cluster) order = std::min(order, p->index);
  for (Point* p : cluster) {
    p->role =
        std::abs(p->z - floor_z) < std::abs(p->z - ceil_z) ? Role::Floor : Role::Ceiling;
    if (p->role == Role::Floor) p->index = order;  // keep the corner in survey order
  }
}

// Match jambs into openings, but only where they share a wall.
//
// Pairing in survey order alone is not safe: an operator can shoot one side of
// a door, wander to a window on another wall, then come back. Two jambs only
// form an opening when they sit on the same wall run, at a believable width,
// and span a similar height.
std::vector<std::pair<Jamb, Jamb>> pair_jambs(const std::vector<Jamb>& jambs,
                                              const std::vector<Pt>& ring) {
  std::vector<std::pair<Jamb, Jamb>> pairs;
  if (jambs.size() < 2 || ring.size() < 3) return pairs;

  std::vector<int> edge_of(jambs.size());
  for (size_t i = 0; i < jambs.size(); ++i)
    edge_of[i] = project_onto_edges({jambs[i].x, jambs[i].y}, ring).edge;

  std::set<size_t> used;
  for (size_t i = 0; i < jambs.size(); ++i) {
    if (used.count(i)) continue;
    const Jamb& a = jambs[i];
    long long best = -1;
    double best_d = 0;
    for (size_t k = i + 1; k < jambs.size(); ++k) {
      if (used.count(k)) continue;
      const Jamb& b = jambs[k];
      if (edge_of[i] != edge_of[k]) continue;
      const double width =
          std::sqrt((a.x - b.x) * (a.x - b.x) + (a.y - b.y) * (a.y - b.y));
      if (!(width >= 25.0 && width <= kMaxOpeningWidth)) continue;
      if (std::abs(a.z_top - b.z_top) > 25.0 || std::abs(a.z_bottom - b.z_bottom) > 40.0)
        continue;
      if (best < 0 || width < best_d) { best = static_cast<long long>(k); best_d = width; }
    }
    if (best >= 0) {
      used.insert(i);
      used.insert(static_cast<size_t>(best));
      pairs.emplace_back(a, jambs[static_cast<size_t>(best)]);
    }
  }
  return pairs;
}

std::vector<Point> sorted_by_index(const Room& room, Role role) {
  std::vector<Point> out;
  for (const auto& p : room.points)
    if (p.role == role) out.push_back(p);
  std::stable_sort(out.begin(), out.end(),
                   [](const Point& a, const Point& b) { return a.index < b.index; });
  return out;
}

std::string fmt(double v, int places) {
  std::ostringstream os;
  os.setf(std::ios::fixed);
  os.precision(places);
  os << v;
  return os.str();
}

void classify(Room& room);

// Take the room straight from the lines the surveyor drew. Returns false when
// the file has no closed ring, in which case the caller falls back to inferring.
bool from_drawn_lines(Room& room) {
  std::map<std::string, std::array<double, 3>> coords;
  for (const auto& p : room.points) coords[p.name] = {p.x, p.y, p.z};

  const Topology topo = build_topology(room.segments, coords);
  if (topo.floor_ring.size() < 3) return false;

  // A ring only counts as the floor if it sits on the floor. Without this a
  // broken floor ring lets the ceiling ring take its place, and the room would
  // be built from the wrong loop at the right corner count.
  double s = 0.0;
  for (const auto& n : topo.floor_ring) s += coords[n][2];
  const double mean_z = s / static_cast<double>(topo.floor_ring.size());
  if (room.floor_z && std::abs(mean_z - *room.floor_z) > 40.0) return false;

  std::unordered_map<std::string, Point*> by_name;
  for (auto& p : room.points) by_name[p.name] = &p;

  room.links = topo.links;
  room.outline_source = "drawn";

  for (const auto& n : topo.floor_ring) by_name[n]->role = Role::Floor;
  for (const auto& n : topo.ceiling_ring) by_name[n]->role = Role::Ceiling;

  room.outline.clear();
  for (const auto& n : topo.floor_ring) room.outline.push_back(*by_name[n]);
  room.ceiling.clear();
  for (const auto& n : topo.ceiling_ring) room.ceiling.push_back(*by_name[n]);

  // Each opening was drawn as a closed loop: two jambs, a sill line and a head
  // line. Split the loop back into its two verticals.
  for (const auto& loop : topo.openings) {
    std::vector<Point*> pts;
    for (const auto& n : loop) {
      const auto it = by_name.find(n);
      if (it != by_name.end()) pts.push_back(it->second);
    }
    if (pts.size() < 4) continue;

    std::vector<Jamb> jambs;
    for (const auto& c : cluster_xy(pts)) {
      double lo = c.front()->z, hi = c.front()->z;
      for (const Point* q : c) {
        lo = std::min(lo, q->z);
        hi = std::max(hi, q->z);
      }
      if (c.size() >= 2 && hi - lo > kMinJambSpan) jambs.push_back(jamb_from(c));
    }
    if (jambs.size() == 2) {
      Opening op;
      op.left = jambs[0];
      op.right = jambs[1];
      op.infer_kind((room.floor_z ? *room.floor_z : 0.0) + 8.0);
      room.openings.push_back(op);
      for (Point* q : pts) q->role = Role::Opening;
    }
  }

  // Anything the drawn lines did not account for keeps its layer meaning.
  for (auto& p : room.points) {
    if (p.role != Role::Unknown) continue;
    const std::string key = norm(p.layer);
    if (starts_with(ascii_upper(p.name), "VTARGET")) {
      p.role = Role::Control;
    } else {
      const auto it = layer_roles().find(key);
      if (it != layer_roles().end()) p.role = it->second;
    }
  }

  // A surveyor who never closed a loop around a door still shot its jambs.
  // Whatever the drawn lines did not account for gets the same clustering the
  // inferred path uses, so an opening is not lost purely because no line was
  // drawn round it. This runs after the layer meanings above, so a socket or a
  // pipe is never mistaken for a jamb. Points that do not pair stay Unknown and
  // are still reported to the operator.
  std::vector<Point*> leftover;
  for (auto& p : room.points)
    if (p.role == Role::Unknown) leftover.push_back(&p);

  if (!leftover.empty() && room.outline.size() >= 3) {
    std::vector<Jamb> jambs;
    std::vector<std::vector<Point*>> jamb_clusters;
    for (const auto& c : cluster_xy(leftover)) {
      double lo = c.front()->z, hi = c.front()->z;
      for (const Point* q : c) {
        lo = std::min(lo, q->z);
        hi = std::max(hi, q->z);
      }
      if (c.size() >= 2 && hi - lo > kMinJambSpan) {
        jambs.push_back(jamb_from(c));
        jamb_clusters.push_back(c);
      }
    }

    std::vector<Pt> ring;
    for (const auto& p : room.outline) ring.push_back(xy(p));
    for (const auto& pr : pair_jambs(jambs, ring)) {
      Opening op;
      op.left = pr.first;
      op.right = pr.second;
      op.infer_kind((room.floor_z ? *room.floor_z : 0.0) + 20.0);
      room.openings.push_back(op);
      // Mark the shots that became this opening, matching the jambs by seat.
      for (size_t k = 0; k < jambs.size(); ++k) {
        const bool used = (jambs[k].x == pr.first.x && jambs[k].y == pr.first.y) ||
                          (jambs[k].x == pr.second.x && jambs[k].y == pr.second.y);
        if (used)
          for (Point* q : jamb_clusters[k]) q->role = Role::Opening;
      }
    }
  }

  room.controls.clear();
  for (const auto& p : room.points)
    if (p.role == Role::Control) room.controls.push_back(p);
  return true;
}

// Assign a Role to every point, then build outline / ceiling / openings.
//
// Both surveying styles in the field data reduce to the same operation: cluster
// the shots by plan position, then read each cluster's vertical extent. A
// cluster that runs floor to ceiling is a room corner, whether the operator
// shot it as one top-and-bottom pair or walked the floor first and the ceiling
// after. A cluster that stops short of the ceiling is a door or window jamb.
void classify(Room& room) {
  for (auto& p : room.points) {
    const std::string key = norm(p.layer);
    if (starts_with(ascii_upper(p.name), "VTARGET")) p.role = Role::Control;
    else if (key != "zemin" && layer_roles().count(key)) p.role = layer_roles().at(key);
    else p.role = Role::Unknown;
  }

  const auto datums = z_datums(room);
  room.floor_z = datums.first;
  room.ceiling_z = datums.second;
  if (!room.floor_z) return;
  const double floor_z = *room.floor_z;

  // The surveyor's own lines beat anything we could infer from shot order.
  if (!room.segments.empty() && from_drawn_lines(room)) {
    validate(room);
    return;
  }

  // When the operator tagged the outline on site, that beats any inference we
  // can make. Only fall back to geometry for the untagged exports.
  std::vector<Point*> tagged;
  for (auto& p : room.points)
    if (norm(p.layer) == "zemin") {
      p.role = Role::Floor;
      tagged.push_back(&p);
    }
  room.outline_source = tagged.empty() ? "inferred" : "surveyed layer";

  // Ceiling shots must be claimed before anything is clustered. A ceiling
  // corner often lands within a few centimetres of a window jamb in plan, and
  // if the two merge the cluster spans floor to ceiling and gets read as an
  // opening the width of the whole wall.
  if (room.ceiling_z) {
    const double ceil_z = *room.ceiling_z;
    std::vector<Point*> floor_pts;
    for (auto& p : room.points)
      if (p.role == Role::Floor) floor_pts.push_back(&p);
    if (floor_pts.empty()) floor_pts = tagged;

    for (auto& q : room.points) {
      if (q.role != Role::Unknown || std::abs(q.z - ceil_z) > kCeilingTol) continue;
      for (const Point* f : floor_pts) {
        if (dist2d(q, *f) <= kCeilingXyTol) {
          q.role = Role::Ceiling;
          break;
        }
      }
    }
  }

  std::vector<Point*> unknown;
  for (auto& p : room.points)
    if (p.role == Role::Unknown) unknown.push_back(&p);

  std::vector<Jamb> jambs;
  for (const auto& c : cluster_xy(unknown)) {
    double lo = c.front()->z, hi = c.front()->z;
    for (const Point* p : c) {
      lo = std::min(lo, p->z);
      hi = std::max(hi, p->z);
    }
    const bool at_floor = std::abs(lo - floor_z) <= kFloorTol;
    const bool at_ceiling =
        room.ceiling_z.has_value() && std::abs(hi - *room.ceiling_z) <= kCeilingTol;

    if (at_floor && at_ceiling && tagged.empty()) {
      mark_corner(c, floor_z, *room.ceiling_z);
    } else if (at_floor && tagged.empty() && !room.ceiling_z && hi - lo <= kFloorTol) {
      for (Point* p : c) p->role = Role::Floor;
    } else if (at_ceiling && !at_floor && hi - lo <= kCeilingTol) {
      for (Point* p : c) p->role = Role::Ceiling;
    } else if (hi - lo > kMinJambSpan) {
      jambs.push_back(jamb_from(c));
      for (Point* p : c) p->role = Role::Opening;
    }
    // anything else stays Unknown and is surfaced for the operator
  }

  std::vector<Pt> ring;
  for (const auto& p : room.points)
    if (p.role == Role::Floor) ring.push_back(xy(p));

  for (const auto& pr : pair_jambs(jambs, ring)) {
    Opening op;
    op.left = pr.first;
    op.right = pr.second;
    op.infer_kind(floor_z + 20.0);
    room.openings.push_back(op);
  }

  room.outline = sorted_by_index(room, Role::Floor);
  room.ceiling = sorted_by_index(room, Role::Ceiling);
  room.controls.clear();
  for (const auto& p : room.points)
    if (p.role == Role::Control) room.controls.push_back(p);
  validate(room);
}

}  // namespace

void validate(Room& room) {
  const size_t n = room.outline.size();
  if (n < 3) {
    room.issues.push_back({"error", "no-outline",
                           "Only " + std::to_string(n) +
                               " floor point(s) found. Cannot form a room outline.",
                           {}});
    return;
  }

  std::vector<Pt> ring;
  for (const auto& p : room.outline) ring.push_back(xy(p));

  const auto crossings = self_intersections(ring);
  if (!crossings.empty()) {
    std::set<std::string> names;
    for (const auto& pr : crossings) {
      names.insert(room.outline[pr.first].name);
      names.insert(room.outline[pr.second].name);
    }
    room.issues.push_back(
        {"error", "self-intersecting",
         "Outline crosses itself in " + std::to_string(crossings.size()) +
             " place(s). Usually a re-shoot appended after the loop was closed. "
             "Reorder or drop points in the plan view.",
         std::vector<std::string>(names.begin(), names.end())});
  }

  const double area = polygon_area(ring) / 10000.0;
  if (area < 0.5)
    room.issues.push_back(
        {"warning", "tiny-area", "Outline encloses only " + fmt(area, 2) + " m2.", {}});

  if (!room.ceiling_z)
    room.issues.push_back({"warning", "no-ceiling",
                           "No ceiling shots. A height must be supplied before this "
                           "room can be built.",
                           {}});

  std::vector<std::string> stray;
  for (const auto& p : room.points)
    if (p.role == Role::Unknown) stray.push_back(p.name);
  if (!stray.empty())
    room.issues.push_back({"info", "unclassified",
                           std::to_string(stray.size()) +
                               " point(s) could not be classified automatically.",
                           stray});
}

Room read_room(const std::string& path) {
  Room room;
  const fs::path file = fs::u8path(path);
  room.name = file.stem().u8string();
  room.source = path;

  const auto rows = read_csv(file, ';');
  for (size_t r = 1; r < rows.size(); ++r) {
    const auto& row = rows[r];
    if (row.empty() || trim(row[0]).empty()) continue;
    const std::string name = trim(row[0]);

    double x = 0, y = 0, z = 0;
    try {
      if (row.size() < 4) continue;
      x = parse_number(row[1]);
      y = parse_number(row[2]);
      z = parse_number(row[3]);
    } catch (const std::exception&) {
      continue;
    }
    const std::string layer = row.size() > 4 ? trim(row[4]) : "";

    if (is_station(name)) {
      const bool seen =
          std::any_of(room.stations.begin(), room.stations.end(),
                      [&](const Point& s) {
                        return std::hypot(std::hypot(s.x - x, s.y - y),
                                          s.z - z) < kStationMergeCm;
                      });
      if (!seen)
        room.stations.push_back(Point{name, x, y, z, layer, Role::Station, 0});
      continue;
    }
    room.points.push_back({name, x, y, z, layer, Role::Unknown, first_index(name)});
  }

  room.segments = read_segments(path);
  classify(room);
  return room;
}

Project read_project(const std::string& folder, const std::string& name) {
  Project proj;
  const fs::path dir = fs::u8path(folder);
  proj.name = name.empty() ? dir.filename().u8string() : name;

  std::vector<std::string> files;
  for (const auto& e : fs::directory_iterator(dir)) {
    if (!e.is_regular_file()) continue;
    const auto p = e.path();
    if (p.extension() != ".csv") continue;
    if (ascii_upper(p.stem().u8string()).find("FUKOKU") != std::string::npos) continue;
    files.push_back(p.u8string());
  }
  // Path ordering on Windows is case-insensitive, matching sorted(Path.glob).
  std::sort(files.begin(), files.end(),
            [](const std::string& a, const std::string& b) { return norm(a) < norm(b); });

  for (const auto& f : files) proj.rooms.push_back(read_room(f));
  return proj;
}

void rebuild(Room& room) {
  room.outline = sorted_by_index(room, Role::Floor);
  room.ceiling = sorted_by_index(room, Role::Ceiling);
  room.controls.clear();
  for (const auto& p : room.points)
    if (p.role == Role::Control) room.controls.push_back(p);

  room.openings.clear();
  std::vector<Point*> marked;
  for (auto& p : room.points)
    if (p.role == Role::Opening) marked.push_back(&p);

  if (marked.size() >= 4) {
    std::vector<Jamb> jambs;
    for (const auto& c : cluster_xy(marked)) {
      double lo = c.front()->z, hi = c.front()->z;
      for (const Point* p : c) {
        lo = std::min(lo, p->z);
        hi = std::max(hi, p->z);
      }
      if (c.size() >= 2 && hi - lo > kMinJambSpan) jambs.push_back(jamb_from(c));
    }
    const double floor_z = room.floor_z ? *room.floor_z : 0.0;
    std::vector<Pt> ring;
    for (const auto& p : room.outline) ring.push_back(xy(p));
    for (const auto& pr : pair_jambs(jambs, ring)) {
      Opening op;
      op.left = pr.first;
      op.right = pr.second;
      op.infer_kind(floor_z + 20.0);
      room.openings.push_back(op);
    }
  }

  room.issues.clear();
  validate(room);
}

void apply_roles(Room& room, const std::map<std::string, std::string>& roles) {
  static const std::set<std::string> assignable = {
      "floor", "ceiling", "opening", "socket", "plumbing", "control", "unknown"};
  for (auto& p : room.points) {
    const auto it = roles.find(p.name);
    if (it != roles.end() && assignable.count(it->second))
      p.role = role_from_string(it->second);
  }
  rebuild(room);
}

void reread_topology(Room& room) {
  for (auto& p : room.points) p.role = Role::Unknown;
  room.outline_source = "inferred";
  room.outline.clear();
  room.ceiling.clear();
  room.openings.clear();
  room.links.clear();
  room.issues.clear();
  if (!from_drawn_lines(room)) classify(room);
  else validate(room);
}

}  // namespace snapir
