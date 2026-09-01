// What a .sdxp round trip costs, measured rather than claimed.
//
// Export builds the archive from a live project - survey folder plus
// whatever overrides and connections were on it; import unpacks it into a
// fresh folder as a new project. What has to hold: every override and
// connection value comes back identical, and every survey file comes back
// byte-identical, in both directions - a file the export dropped and a file
// the import invented are both a failure.
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <random>
#include <string>

#include "snapir/archive.hpp"
#include "snapir/parser.hpp"
#include "snapir/store.hpp"

namespace fs = std::filesystem;
using namespace snapir;

namespace {

int failures = 0;

void check(bool ok, const std::string& what) {
  std::cout << (ok ? "ok   " : "FAIL ") << what << '\n';
  if (!ok) ++failures;
}

std::string read_file(const fs::path& p) {
  std::ifstream in(p, std::ios::binary);
  return std::string((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
}

// Every file that exists on one side exists, same bytes, on the other - both
// directions, so a dropped file and an invented one are both caught.
void check_survey_identical(const fs::path& original, const fs::path& copy) {
  size_t original_count = 0, copy_count = 0;
  for (const auto& e : fs::recursive_directory_iterator(original)) {
    if (!e.is_regular_file()) continue;
    ++original_count;
    const fs::path rel = fs::relative(e.path(), original);
    const fs::path other = copy / rel;
    if (!fs::exists(other)) {
      check(false, "missing after import: " + rel.u8string());
      continue;
    }
    check(read_file(e.path()) == read_file(other), "survey file identical: " + rel.u8string());
  }
  for (const auto& e : fs::recursive_directory_iterator(copy))
    if (e.is_regular_file()) ++copy_count;
  check(original_count == copy_count,
        "survey file count " + std::to_string(copy_count) + "/" + std::to_string(original_count));
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 2) {
    std::cerr << "usage: check_roundtrip <survey folder>\n";
    return 2;
  }

  const fs::path work = fs::temp_directory_path() /
      fs::u8path("snapir-check-roundtrip-" + std::to_string(std::random_device{}()));
  fs::create_directories(work);

  Store store((work / "projects.json").u8string());
  ProjectRecord& src = store.create("Roundtrip check", argv[1]);
  src.thickness = 180.0;

  const Project parsed = read_project(argv[1]);
  if (parsed.rooms.empty()) {
    std::cerr << "no rooms in " << argv[1] << '\n';
    return 2;
  }

  // Exercise real override and connection fields, not just defaults.
  const std::string room_name = parsed.rooms.front().name;
  RoomOverride& ov = src.overrides[room_name];
  ov.ceiling_height = 240.0;
  ov.wall_thickness = 150.0;
  ov.disabled_openings = {0};
  ov.role_overrides["P1"] = "socket";
  ov.built_at = now_iso8601();  // should NOT survive the round trip
  ov.step_path = "C:/somewhere/on/this/machine.step";  // should NOT survive it

  if (parsed.rooms.size() > 1) {
    Connection c;
    c.id = new_id();
    c.room_a = room_name;
    c.opening_a = 0;
    c.room_b = parsed.rooms[1].name;
    c.opening_b = 0;
    c.dx = 12.5;
    c.dy = -3.0;
    c.rotation_deg = 90.0;
    src.connections.push_back(c);
  }
  store.save();

  const fs::path sdxp = work / "export.sdxp";
  export_sdxp(src, sdxp.u8string());
  check(fs::exists(sdxp) && fs::file_size(sdxp) > 0, "archive written");

  const fs::path imported_survey = work / "imported-survey";
  const ImportedProject imported = import_sdxp(sdxp.u8string(), imported_survey.u8string());

  check(imported.name == src.name, "name preserved");
  check(imported.thickness == src.thickness, "thickness preserved");
  check(imported.overrides.count(room_name) == 1, "room override present");
  if (imported.overrides.count(room_name)) {
    const RoomOverride& iov = imported.overrides.at(room_name);
    check(iov.ceiling_height == ov.ceiling_height, "ceilingHeight preserved");
    check(iov.wall_thickness == ov.wall_thickness, "wallThickness preserved");
    check(iov.disabled_openings == ov.disabled_openings, "disabledOpenings preserved");
    check(iov.role_overrides == ov.role_overrides, "roleOverrides preserved");
    check(!iov.built_at.has_value(), "built_at dropped (no built export is bundled)");
    check(!iov.step_path.has_value(), "step_path dropped (no built export is bundled)");
  }
  check(imported.connections.size() == src.connections.size(), "connection count preserved");
  if (!imported.connections.empty() && !src.connections.empty())
    check(imported.connections[0].room_a == src.connections[0].room_a &&
              imported.connections[0].room_b == src.connections[0].room_b &&
              imported.connections[0].dx == src.connections[0].dx &&
              imported.connections[0].rotation_deg == src.connections[0].rotation_deg,
          "connection fields preserved");

  check_survey_identical(fs::u8path(argv[1]), imported_survey);

  fs::remove_all(work);
  std::cout << "|summary|"
            << (failures ? std::to_string(failures) + " failing" : "round trip exact") << '\n';
  return failures ? 1 : 0;
}
