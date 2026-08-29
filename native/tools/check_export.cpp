// Proof that every offered format is exact.
//
// The reason mesh formats are refused is that they cannot carry the surveyed
// corner back. So the claim has to be checked, not asserted: every room is
// built once, written in each format, read back through the same kernel, and
// the face count and volume of the file are compared against the body it came
// from. A format that drifts here does not belong in the menu.
#include <cstdio>
#include <filesystem>
#include <iostream>
#include <string>

#include <BRepTools.hxx>
#include <BRep_Builder.hxx>
#include <IGESControl_Reader.hxx>
#include <STEPControl_Reader.hxx>

#include "snapir/parser.hpp"
#include "snapir/solid.hpp"

namespace fs = std::filesystem;
using namespace snapir;

namespace {

// A face may be split on the way through a file without the body changing, so
// volume is the number that has to hold exactly. 1e-6 m3 is a cubic millimetre.
constexpr double kVolumeTol = 1e-6;

std::string num(double v, int places = 9) {
  char buf[64];
  std::snprintf(buf, sizeof(buf), "%.*f", places, v);
  return buf;
}

TopoDS_Shape read_back(const std::string& path, const std::string& fmt) {
  if (fmt == "step") {
    STEPControl_Reader reader;
    if (reader.ReadFile(path.c_str()) != IFSelect_RetDone)
      throw std::runtime_error("STEP read failed");
    reader.TransferRoots();
    return reader.OneShape();
  }
  if (fmt == "iges") {
    IGESControl_Reader reader;
    if (reader.ReadFile(path.c_str()) != IFSelect_RetDone)
      throw std::runtime_error("IGES read failed");
    reader.TransferRoots();
    return reader.OneShape();
  }
  TopoDS_Shape shape;
  BRep_Builder builder;
  if (!BRepTools::Read(shape, path.c_str(), builder))
    throw std::runtime_error("BREP read failed");
  return shape;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 2) {
    std::cerr << "usage: check_export <folder> [out_dir]\n";
    return 2;
  }
  const fs::path out = argc > 2 ? fs::u8path(argv[2]) : fs::temp_directory_path() /
                                                            "snapir-check-export";
  fs::create_directories(out);

  const BuildSettings cfg;
  Project proj = read_project(argv[1]);
  int failures = 0;

  for (auto& room : proj.rooms) {
    TopoDS_Shape shape;
    try {
      shape = build_room(room, cfg);
    } catch (const std::exception&) {
      continue;  // Rooms the survey cannot carry are dump_solid's business.
    }
    const SolidStats src = solid_stats(shape);

    for (const auto& f : export_formats()) {
      const std::string fmt = f.id;
      std::string verdict;
      try {
        const std::string path =
            export_shape(shape, (out / fs::u8path(room.name)).u8string(), fmt);
        const SolidStats got = solid_stats(read_back(path, fmt));
        const double drift = std::abs(got.volume_m3 - src.volume_m3);
        const bool ok = drift <= kVolumeTol && got.faces == src.faces;
        if (!ok) ++failures;
        verdict = std::string(ok ? "ok" : "DRIFT") +
                  " faces=" + std::to_string(got.faces) + "/" +
                  std::to_string(src.faces) + " vol=" + num(got.volume_m3) + "/" +
                  num(src.volume_m3) + " drift=" + num(drift);
      } catch (const std::exception& e) {
        ++failures;
        verdict = std::string("ERROR ") + e.what();
      }
      std::cout << room.name << '|' << fmt << '|' << verdict << '\n';
    }
  }

  std::cout << "|summary|" << (failures ? std::to_string(failures) + " failing"
                                        : "all formats exact")
            << '\n';
  return failures ? 1 : 0;
}
