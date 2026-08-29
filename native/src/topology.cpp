#include "snapir/topology.hpp"
#include "snapir/csv.hpp"
#include <algorithm>
#include <cmath>
#include <set>
#include <unordered_map>

namespace snapir {
namespace {

// Adjacency that remembers the order names were first seen, so component and
// opening ordering is reproducible rather than hash-dependent.
struct Adjacency {
  std::vector<std::string> order;
  std::unordered_map<std::string, std::set<std::string>> map;

  void add(const std::string& a, const std::string& b) {
    if (map.find(a) == map.end()) order.push_back(a);
    map[a].insert(b);
    if (map.find(b) == map.end()) order.push_back(b);
    map[b].insert(a);
  }
  const std::set<std::string>& at(const std::string& n) const { return map.at(n); }
};

std::vector<std::set<std::string>> components(const Adjacency& adj) {
  std::set<std::string> seen;
  std::vector<std::set<std::string>> out;
  for (const auto& start : adj.order) {
    if (seen.count(start)) continue;
    std::vector<std::string> stack{start};
    std::set<std::string> comp;
    while (!stack.empty()) {
      const std::string n = stack.back();
      stack.pop_back();
      if (comp.count(n)) continue;
      comp.insert(n);
      for (const auto& m : adj.at(n))
        if (!comp.count(m)) stack.push_back(m);
    }
    seen.insert(comp.begin(), comp.end());
    out.push_back(std::move(comp));
  }
  return out;
}

// Order a component that is a simple closed loop. Empty if it is not.
std::vector<std::string> walk_cycle(const Adjacency& adj,
                                    const std::set<std::string>& comp) {
  if (comp.size() < 3) return {};
  for (const auto& n : comp)
    if (adj.at(n).size() != 2) return {};

  const std::string start = *comp.begin();  // std::set is sorted: min(comp)
  std::vector<std::string> ring{start};
  std::string prev, cur = start;
  bool has_prev = false;
  while (true) {
    std::string nxt;
    bool found = false;
    for (const auto& n : adj.at(cur)) {
      if (has_prev && n == prev) continue;
      nxt = n;
      found = true;
      break;
    }
    if (!found) return {};
    if (nxt == start) return ring.size() == comp.size() ? ring : std::vector<std::string>{};
    ring.push_back(nxt);
    prev = cur;
    has_prev = true;
    cur = nxt;
    if (ring.size() > comp.size()) return {};
  }
}

double mean_z(const std::vector<std::string>& ring,
              const std::unordered_map<std::string, double>& z) {
  double s = 0.0;
  for (const auto& n : ring) s += z.at(n);
  return s / static_cast<double>(ring.size());
}

}  // namespace

std::filesystem::path fukoku_path(const std::string& room_csv) {
  // The room path arrives as UTF-8; u8path keeps the Turkish room names intact
  // rather than losing them through the console codepage.
  const std::filesystem::path p = std::filesystem::u8path(room_csv);
  // operator/ would read a narrow string back as the ANSI codepage, which
  // loses the Turkish room names, so the joined name goes through u8path too.
  return p.parent_path() / std::filesystem::u8path(p.stem().u8string() + "_FUKOKU.csv");
}

std::vector<Segment> read_segments(const std::string& room_csv) {
  const std::filesystem::path path = fukoku_path(room_csv);
  std::vector<Segment> out;
  if (!file_exists(path)) return out;

  for (const auto& row : read_csv(path, ';')) {
    if (row.size() < 2) continue;
    const std::string a = trim(row[0]), b = trim(row[1]);
    if (a.empty() || b.empty() || a == "Line start") continue;  // point, or header
    out.emplace_back(a, b);
  }
  return out;
}

Topology build_topology(const std::vector<Segment>& segments,
                        const std::map<std::string, std::array<double, 3>>& points) {
  Topology topo;
  topo.segments = segments;

  std::vector<Segment> known;
  for (const auto& s : segments)
    if (points.count(s.first) && points.count(s.second)) known.push_back(s);
  if (known.empty()) return topo;

  std::unordered_map<std::string, double> z;
  for (const auto& kv : points) z[kv.first] = kv.second[2];

  const auto level = [&z](const std::string& a, const std::string& b) {
    return std::abs(z.at(a) - z.at(b)) <= kLevelDz;
  };

  // Flat lines first. Rings live entirely at one level.
  Adjacency flat;
  for (const auto& s : known)
    if (level(s.first, s.second)) flat.add(s.first, s.second);

  std::vector<std::vector<std::string>> rings;
  for (const auto& comp : components(flat)) {
    const auto ring = walk_cycle(flat, comp);
    if (ring.size() >= 3) rings.push_back(ring);
  }

  if (!rings.empty()) {
    std::stable_sort(rings.begin(), rings.end(),
                     [&z](const std::vector<std::string>& a,
                          const std::vector<std::string>& b) {
                       return mean_z(a, z) < mean_z(b, z);
                     });
    topo.floor_ring = rings.front();
    if (rings.size() > 1) {
      // A ring well above the floor one, with a matching corner count, is the
      // ceiling. Anything else is left alone.
      const double lo = mean_z(topo.floor_ring, z);
      const double hi = mean_z(rings.back(), z);
      if (hi - lo > 120.0) topo.ceiling_ring = rings.back();
    }
  }

  std::set<std::string> ring_nodes(topo.floor_ring.begin(), topo.floor_ring.end());
  ring_nodes.insert(topo.ceiling_ring.begin(), topo.ceiling_ring.end());

  // Whatever is left over and forms its own closed loop is an opening: two
  // jambs and the sill and head lines between them.
  Adjacency full;
  for (const auto& s : known) full.add(s.first, s.second);
  for (const auto& comp : components(full)) {
    bool touches_ring = false;
    for (const auto& n : comp)
      if (ring_nodes.count(n)) { touches_ring = true; break; }
    if (touches_ring) continue;
    const auto loop = walk_cycle(full, comp);
    if (loop.size() >= 4) topo.openings.push_back(loop);
  }

  // Risers that join a floor corner to a ceiling corner. These are the links
  // the operator drew by hand, and the only ones the app will show.
  const std::set<std::string> floor_set(topo.floor_ring.begin(), topo.floor_ring.end());
  const std::set<std::string> ceil_set(topo.ceiling_ring.begin(), topo.ceiling_ring.end());
  for (const auto& s : known) {
    if (level(s.first, s.second)) continue;
    if (floor_set.count(s.first) && ceil_set.count(s.second))
      topo.links.emplace_back(s.first, s.second);
    else if (floor_set.count(s.second) && ceil_set.count(s.first))
      topo.links.emplace_back(s.second, s.first);
  }

  return topo;
}

}  // namespace snapir
