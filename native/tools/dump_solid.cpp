// Stage 2 verification, geometry half.
//
// Builds every room in the folder and prints the numbers the Python build is
// already trusted for: solid, shell and face counts, volume, and the wall
// tiling check where the exported walls have to add back up to the room.
#include <cstdio>
#include <iostream>
#include <string>

#include "snapir/parser.hpp"
#include "snapir/solid.hpp"
#include "snapir/tessellate.hpp"

using namespace snapir;

namespace {

void emit(const std::string& room, const std::string& key, const std::string& value) {
  std::cout << room << '|' << key << '|' << value << '\n';
}

std::string num(double v, int places = 9) {
  char buf[64];
  std::snprintf(buf, sizeof(buf), "%.*f", places, v);
  return buf;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 2) {
    std::cerr << "usage: dump_solid <folder>\n";
    return 2;
  }

  const BuildSettings cfg;
  Project proj = read_project(argv[1]);

  for (auto& room : proj.rooms) {
    const std::string& n = room.name;
    TopoDS_Shape shape;
    try {
      shape = build_room(room, cfg);
    } catch (const std::exception& e) {
      emit(n, "build", std::string("ERROR ") + e.what());
      continue;
    }

    const SolidStats s = solid_stats(shape);
    emit(n, "build", "ok");
    emit(n, "solids", std::to_string(s.solids));
    emit(n, "shells", std::to_string(s.shells));
    emit(n, "faces", std::to_string(s.faces));
    emit(n, "volume_m3", num(s.volume_m3));

    const Mesh mesh = tessellate(shape);
    emit(n, "triangles", std::to_string(mesh.triangle_count()));
    emit(n, "mesh_faces", std::to_string(mesh.faces.size()));

    // The wall tiling property: every wall of the room, cut out on its own,
    // has to add back up to the room's own volume.
    double total = 0.0;
    bool all_ok = true;
    for (size_t e = 0; e < room.outline.size(); ++e) {
      try {
        const WallBody w = wall_body(room, cfg, static_cast<int>(e));
        const SolidStats ws = solid_stats(w.shape);
        total += ws.volume_m3;
        emit(n, "wall[" + std::to_string(e) + "]",
             "len=" + num(w.length, 6) + " solids=" + std::to_string(w.solids) +
                 " vol=" + num(ws.volume_m3));
      } catch (const std::exception& e2) {
        all_ok = false;
        emit(n, "wall[" + std::to_string(e) + "]", std::string("ERROR ") + e2.what());
      }
    }
    if (all_ok) emit(n, "wall_sum_m3", num(total));
  }
  return 0;
}
