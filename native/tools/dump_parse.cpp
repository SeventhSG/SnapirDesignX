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
    emit(n, "station", r.station ? r.station->name : "None");

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
    for (size_t i = 0; i < r.issues.size(); ++i)
      emit(n, "issue[" + std::to_string(i) + "]",
           r.issues[i].severity + " " + r.issues[i].code);
    for (const auto& p : r.points)
      emit(n, "role:" + p.name, to_string(p.role));
  }
  return 0;
}
