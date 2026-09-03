// Stage 2 verification, parsing half.
//
// Prints one deterministic line per field per room. The Python build prints the
// same lines from tools/dump_parse.py, so a plain diff decides whether the port
// is faithful. Nothing here is a test framework; it is the reference numbers.
#include <cstdio>
#include <iostream>
#include <string>

#include "snapir/geometry.hpp"
#include "snapir/parser.hpp"

using namespace snapir;

namespace {

void emit(const std::string& room, const std::string& key, const std::string& value) {
  std::cout << room << '|' << key << '|' << value << '\n';
}

std::string num(double v) {
  char buf[64];
  std::snprintf(buf, sizeof(buf), "%.6f", v);
  return buf;
}

std::string opt(const std::optional<double>& v) { return v ? num(*v) : "None"; }

}  // namespace

int main(int argc, char** argv) {
  if (argc < 2) {
    std::cerr << "usage: dump_parse <folder>\n";
    return 2;
  }

  const Project proj = read_project(argv[1]);
  for (const auto& r : proj.rooms) {
    const std::string& n = r.name;
    emit(n, "outline_source", r.outline_source);
    emit(n, "floor_z", opt(r.floor_z));
    emit(n, "ceiling_z", opt(r.ceiling_z));
    emit(n, "ceiling_height", opt(r.ceiling_height()));
    emit(n, "n_points", std::to_string(r.points.size()));
    emit(n, "n_outline", std::to_string(r.outline.size()));
    emit(n, "n_ceiling", std::to_string(r.ceiling.size()));
    emit(n, "n_openings", std::to_string(r.openings.size()));
    emit(n, "n_controls", std::to_string(r.controls.size()));
    emit(n, "n_segments", std::to_string(r.segments.size()));
    emit(n, "n_links", std::to_string(r.links.size()));
    emit(n, "n_stations", std::to_string(r.stations.size()));
    for (size_t i = 0; i < r.stations.size(); ++i) {
      const auto& s = r.stations[i];
      emit(n, "station[" + std::to_string(i) + "]",
           s.name + " " + num(s.x) + " " + num(s.y) + " " + num(s.z));
    }

    std::vector<Pt> ring;
    for (const auto& p : r.outline) ring.push_back({p.x, p.y});
    emit(n, "area", num(polygon_area(ring)));
    emit(n, "signed_area", num(signed_area(ring)));
    emit(n, "perimeter", num(perimeter(ring)));

    for (size_t i = 0; i < r.outline.size(); ++i) {
      const auto& p = r.outline[i];
      emit(n, "outline[" + std::to_string(i) + "]",
           p.name + " " + num(p.x) + " " + num(p.y) + " " + num(p.z) + " " +
               std::to_string(p.index));
    }
    for (size_t i = 0; i < r.ceiling.size(); ++i) {
      const auto& p = r.ceiling[i];
      emit(n, "ceiling[" + std::to_string(i) + "]", p.name + " " + num(p.z));
    }
    for (size_t i = 0; i < r.openings.size(); ++i) {
      const auto& o = r.openings[i];
      emit(n, "opening[" + std::to_string(i) + "]",
           o.kind + " w=" + num(o.width()) + " sill=" + num(o.sill()) +
               " head=" + num(o.head()) + " L=" + num(o.left.x) + "," + num(o.left.y) +
               " R=" + num(o.right.x) + "," + num(o.right.y));
    }
    // Flights and skirtings, spelled out rather than counted. Two cores can tag
    // the same points and still split them into different flights, and a bare
    // count would compare equal while the geometry differed.
    emit(n, "n_stairs", std::to_string(r.stairs.size()));
    for (size_t i = 0; i < r.stairs.size(); ++i) {
      const auto& s = r.stairs[i];
      std::string names;
      for (size_t k = 0; k < s.points.size(); ++k)
        names += (k ? "," : "") + s.points[k].name;
      emit(n, "stair[" + std::to_string(i) + "]",
           s.kind + " steps=" + std::to_string(s.steps) + " rise=" + num(s.rise()) +
               " going=" + num(s.going()) + " pts=" + names);
    }
    emit(n, "n_pervaz", std::to_string(r.pervaz.size()));
    for (size_t i = 0; i < r.pervaz.size(); ++i) {
      const auto& v = r.pervaz[i];
      emit(n, "pervaz[" + std::to_string(i) + "]",
           v.corner.name + "+" + v.wall.name + " h=" + num(v.height) +
               " d=" + num(v.depth));
    }
    for (size_t i = 0; i < r.issues.size(); ++i)
      emit(n, "issue[" + std::to_string(i) + "]",
           r.issues[i].severity + " " + r.issues[i].code);
    for (const auto& p : r.points)
      emit(n, "role:" + p.name, to_string(p.role));
  }
  return 0;
}
