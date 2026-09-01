// What each export format costs, measured rather than claimed.
//
// The formats are not checked against the same standard, because they are
// not for the same thing:
//
//   STEP  is the body to work from. It has to come back exactly: same face
//         count, same volume to the cubic millimetre. Any drift is a bug.
//   STL   is triangles, for viewing. It cannot come back exactly and is not
//         meant to. What matters is that the deviation is small and known, so
//         this prints it instead of pretending it is zero.
//   DXF   is a plan section, not a volume, so there is no volume to compare.
//         What has to hold is that the file carries the same footprint as an
//         independent re-section of the body, computed here rather than
//         trusted from the writer.
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <string>

#include <Bnd_Box.hxx>
#include <BRepAlgoAPI_Section.hxx>
#include <BRepBndLib.hxx>
#include <Poly_Triangulation.hxx>
#include <RWStl.hxx>
#include <STEPControl_Reader.hxx>
#include <gp_Dir.hxx>
#include <gp_Pln.hxx>
#include <gp_Pnt.hxx>

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

// A hundredth of a millimetre: the file is a text rendering of the same
// section computed here, so anything past float and formatting noise means
// the writer dropped or misplaced geometry.
constexpr double kDxfTolMm = 0.01;

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

struct Extent {
  double xmin, ymin, xmax, ymax;
  int segments;
};

// The same horizontal cut write_dxf makes, redone here from the shape rather
// than trusting the file: mid-height of the body's own bounding box, sectioned,
// then measured. A tilted floor or ceiling makes the full body's bounding box
// a poor stand-in for this - the walls need not be perfectly plumb - so the
// check redoes the cut instead of comparing against that bigger box.
Extent section_xy_extent(const TopoDS_Shape& shape) {
  Bnd_Box full;
  BRepBndLib::Add(shape, full);
  double xmin, ymin, zmin, xmax, ymax, zmax;
  full.Get(xmin, ymin, zmin, xmax, ymax, zmax);
  const double mid_z = (zmin + zmax) / 2.0;

  BRepAlgoAPI_Section section(shape, gp_Pln(gp_Pnt(0, 0, mid_z), gp_Dir(0, 0, 1)),
                              Standard_False);
  section.Approximation(Standard_True);
  section.Build();
  if (!section.IsDone()) throw std::runtime_error("DXF section failed for check");

  Bnd_Box cut;
  BRepBndLib::Add(section.Shape(), cut);
  double cxmin, cymin, czmin, cxmax, cymax, czmax;
  cut.Get(cxmin, cymin, czmin, cxmax, cymax, czmax);
  (void)czmin;
  (void)czmax;
  return {cxmin, cymin, cxmax, cymax, 0};
}

// XY footprint of every LINE entity's endpoints in a DXF's ENTITIES section.
Extent dxf_xy_extent(const std::string& path) {
  std::ifstream in(path, std::ios::binary);
  if (!in) throw std::runtime_error("DXF read failed: " + path);

  double xmin = std::numeric_limits<double>::max();
  double ymin = std::numeric_limits<double>::max();
  double xmax = std::numeric_limits<double>::lowest();
  double ymax = std::numeric_limits<double>::lowest();
  int segments = 0;
  bool in_entities = false;
  double x = 0.0;
  bool have_x = false;

  std::string code_line, value_line;
  while (std::getline(in, code_line) && std::getline(in, value_line)) {
    const int code = std::stoi(code_line);
    if (code == 2 && value_line == "ENTITIES") { in_entities = true; continue; }
    if (!in_entities) continue;
    if (code == 10 || code == 11) {
      x = std::stod(value_line);
      have_x = true;
    } else if ((code == 20 || code == 21) && have_x) {
      const double y = std::stod(value_line);
      xmin = std::min(xmin, x);
      xmax = std::max(xmax, x);
      ymin = std::min(ymin, y);
      ymax = std::max(ymax, y);
      have_x = false;
      if (code == 21) ++segments;
    }
  }
  if (segments == 0) throw std::runtime_error("no LINE entities in " + path);
  return {xmin, ymin, xmax, ymax, segments};
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
        } else if (fmt == "dxf") {
          const Extent want = section_xy_extent(shape);
          const Extent got = dxf_xy_extent(path);
          const double drift =
              std::max({std::abs(got.xmin - want.xmin), std::abs(got.ymin - want.ymin),
                        std::abs(got.xmax - want.xmax), std::abs(got.ymax - want.ymax)});
          const bool ok = drift <= kDxfTolMm;
          if (!ok) ++failures;
          verdict = std::string(ok ? "exact" : "DRIFT") +
                    " segments=" + std::to_string(got.segments) + " drift=" + num(drift, 4);
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
                         : "STEP and DXF exact everywhere, worst STL error " +
                               num(worst_stl, 6) + "%")
            << '\n';
  return failures ? 1 : 0;
}
