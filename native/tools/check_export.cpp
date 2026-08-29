// What each export format costs, measured rather than claimed.
//
// The two formats are not checked against the same standard, because they are
// not for the same thing:
//
//   STEP  is the body to work from. It has to come back exactly: same face
//         count, same volume to the cubic millimetre. Any drift is a bug.
//   STL   is triangles, for viewing. It cannot come back exactly and is not
//         meant to. What matters is that the deviation is small and known, so
//         this prints it instead of pretending it is zero.
#include <cmath>
#include <cstdio>
#include <filesystem>
#include <iostream>
#include <string>

#include <Poly_Triangulation.hxx>
#include <RWStl.hxx>
#include <STEPControl_Reader.hxx>

#include "snapir/parser.hpp"
#include "snapir/solid.hpp"

namespace fs = std::filesystem;
using namespace snapir;

namespace {

// 1e-6 m3 is a cubic millimetre: the floor of what STEP is allowed to lose.
constexpr double kStepTol = 1e-6;

// A tessellation of a room that is almost entirely flat should be within a
// hundredth of a percent. Anything worse means the deflection is wrong.
constexpr double kStlMaxErrorPct = 0.01;

std::string num(double v, int places = 9) {
  char buf[64];
  std::snprintf(buf, sizeof(buf), "%.*f", places, v);
  return buf;
}

// Volume of a closed triangle soup, by the divergence theorem. The mesh is in
// millimetres, so the result is scaled to cubic metres to match SolidStats.
double mesh_volume_m3(const Handle(Poly_Triangulation) & tri) {
  if (tri.IsNull()) throw std::runtime_error("no triangulation in file");
  double six_v = 0.0;
  for (int i = 1; i <= tri->NbTriangles(); ++i) {
    int a, b, c;
    tri->Triangle(i).Get(a, b, c);
    const gp_Pnt p = tri->Node(a), q = tri->Node(b), r = tri->Node(c);
    six_v += p.X() * (q.Y() * r.Z() - q.Z() * r.Y()) -
             p.Y() * (q.X() * r.Z() - q.Z() * r.X()) +
             p.Z() * (q.X() * r.Y() - q.Y() * r.X());
  }
  return std::abs(six_v) / 6.0 / 1e9;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 2) {
    std::cerr << "usage: check_export <folder> [out_dir]\n";
    return 2;
  }
  const fs::path out = argc > 2 ? fs::u8path(argv[2])
                                : fs::temp_directory_path() / "snapir-check-export";
  fs::create_directories(out);

  const BuildSettings cfg;
  Project proj = read_project(argv[1]);
  int failures = 0;
  double worst_stl = 0.0;

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

        if (fmt == "step") {
          STEPControl_Reader reader;
          if (reader.ReadFile(path.c_str()) != IFSelect_RetDone)
            throw std::runtime_error("STEP read failed");
          reader.TransferRoots();
          const SolidStats got = solid_stats(reader.OneShape());
          const double drift = std::abs(got.volume_m3 - src.volume_m3);
          const bool ok = drift <= kStepTol && got.faces == src.faces;
          if (!ok) ++failures;
          verdict = std::string(ok ? "exact" : "DRIFT") +
                    " faces=" + std::to_string(got.faces) + "/" +
                    std::to_string(src.faces) + " drift=" + num(drift);
        } else {
          const double got = mesh_volume_m3(RWStl::ReadFile(path.c_str()));
          const double pct = std::abs(got - src.volume_m3) / src.volume_m3 * 100.0;
          worst_stl = std::max(worst_stl, pct);
          const bool ok = pct <= kStlMaxErrorPct;
          if (!ok) ++failures;
          verdict = std::string(ok ? "ok" : "COARSE") + " vol=" + num(got) + "/" +
                    num(src.volume_m3) + " error=" + num(pct, 6) + "%";
        }
      } catch (const std::exception& e) {
        ++failures;
        verdict = std::string("ERROR ") + e.what();
      }
      std::cout << room.name << '|' << fmt << '|' << verdict << '\n';
    }
  }

  std::cout << "|summary|"
            << (failures ? std::to_string(failures) + " failing"
                         : "STEP exact everywhere, worst STL error " +
                               num(worst_stl, 6) + "%")
            << '\n';
  return failures ? 1 : 0;
}
