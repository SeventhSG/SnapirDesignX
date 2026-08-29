// Which openings actually carve, and which quietly do nothing.
//
// Builds each room twice, once with the opening cuts and once without, then
// again cutting one opening at a time. An opening that removes no volume was
// detected but never made a hole, which is the failure this tool exists to find.
#include <cstdio>
#include <iostream>
#include <string>
#include <vector>

#include "snapir/parser.hpp"
#include "snapir/solid.hpp"

using namespace snapir;

namespace {
std::string num(double v, int p = 6) {
  char buf[64];
  std::snprintf(buf, sizeof(buf), "%.*f", p, v);
  return buf;
}
}  // namespace

int main(int argc, char** argv) {
  if (argc < 2) {
    std::cerr << "usage: check_openings <folder>\n";
    return 2;
  }

  BuildSettings cfg;
  Project proj = read_project(argv[1]);

  for (auto& room : proj.rooms) {
    if (room.openings.empty()) continue;

    BuildSettings bare = cfg;
    bare.cut_openings = false;
    bare.include_fixtures = false;

    double v_bare = 0;
    try {
      v_bare = solid_stats(build_room(room, bare)).volume_m3;
    } catch (const std::exception& e) {
      std::cout << room.name << " | BUILD FAILED | " << e.what() << "\n";
      continue;
    }

    const double floor_z = room.floor_z ? *room.floor_z : 0.0;
    const double ceil_z = room.ceiling_z ? *room.ceiling_z : 0.0;

    for (size_t i = 0; i < room.openings.size(); ++i) {
      const Opening& op = room.openings[i];
      BuildSettings one = bare;
      one.cut_openings = true;
      const std::vector<Opening> just{op};

      double v_one = v_bare;
      std::string note = "ok";
      try {
        v_one = solid_stats(build_room(room, one, &just)).volume_m3;
      } catch (const std::exception& e) {
        note = std::string("cut threw: ") + e.what();
      }
      const double removed = (v_bare - v_one) * 1e6;  // m3 -> cm3
      if (note == "ok" && removed < 1.0) note = "CARVED NOTHING";

      std::cout << room.name << " | opening " << i << " | " << op.kind
                << " w=" << num(op.width(), 1) << " sill=" << num(op.sill(), 1)
                << " head=" << num(op.head(), 1) << " | floor=" << num(floor_z, 1)
                << " ceil=" << num(ceil_z, 1) << " | removed=" << num(removed, 1)
                << " cm3 | " << note << "\n";
    }
  }
  return 0;
}
