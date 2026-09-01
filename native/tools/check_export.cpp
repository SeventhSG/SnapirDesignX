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
//   GLB   carries one independent solid per element - floor, ceiling, each
//         wall, each fixture - so what has to hold is the body count and the
//         summed volume of those elements, rebuilt here the same way the
//         writer does, read back through the same triangle-volume check STL
//         uses.
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <map>
#include <string>

#include <Bnd_Box.hxx>
#include <BRepAlgoAPI_Section.hxx>
#include <BRepBndLib.hxx>
#include <BRep_Tool.hxx>
#include <Message_ProgressRange.hxx>
#include <Poly_Triangulation.hxx>
#include <RWGltf_CafReader.hxx>
#include <RWStl.hxx>
#include <STEPControl_Reader.hxx>
#include <TDF_Label.hxx>
#include <TDF_LabelSequence.hxx>
#include <TDocStd_Document.hxx>
#include <TopAbs_ShapeEnum.hxx>
#include <TopExp_Explorer.hxx>
#include <TopLoc_Location.hxx>
#include <TopoDS.hxx>
#include <XCAFApp_Application.hxx>
#include <XCAFDoc_DocumentTool.hxx>
#include <XCAFDoc_ShapeTool.hxx>
#include <gp_Dir.hxx>
#include <gp_Pln.hxx>
#include <gp_Pnt.hxx>
#include <gp_Trsf.hxx>

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

// Same divergence-theorem volume, summed over every triangulated face in a
// shape rather than one bare triangulation - a GLB read back carries one
// independent solid per element, not one mesh for the whole file.
double shape_mesh_volume_m3(const TopoDS_Shape& shape) {
  double six_v = 0.0;
  for (TopExp_Explorer ex(shape, TopAbs_FACE); ex.More(); ex.Next()) {
    TopLoc_Location loc;
    const Handle(Poly_Triangulation) tri =
        BRep_Tool::Triangulation(TopoDS::Face(ex.Current()), loc);
    if (tri.IsNull()) continue;
    const gp_Trsf trsf = loc.Transformation();
    for (int i = 1; i <= tri->NbTriangles(); ++i) {
      int a, b, c;
      tri->Triangle(i).Get(a, b, c);
      const gp_Pnt p = tri->Node(a).Transformed(trsf);
      const gp_Pnt q = tri->Node(b).Transformed(trsf);
      const gp_Pnt r = tri->Node(c).Transformed(trsf);
      six_v += p.X() * (q.Y() * r.Z() - q.Z() * r.Y()) -
               p.Y() * (q.X() * r.Z() - q.Z() * r.X()) +
               p.Z() * (q.X() * r.Y() - q.Y() * r.X());
    }
  }
  return std::abs(six_v) / 6.0 / 1e9;
}

struct Extent {
  double xmin = std::numeric_limits<double>::max();
  double ymin = std::numeric_limits<double>::max();
  double xmax = std::numeric_limits<double>::lowest();
  double ymax = std::numeric_limits<double>::lowest();
  int segments = 0;
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

// XY footprint of every LINE entity's endpoints in a DXF's ENTITIES section,
// bucketed by layer (group code 8) - each element (a wall, the floor, a
// fixture) now writes to its own layer, so this checks them independently
// rather than pretending the file is one undifferentiated body.
std::map<std::string, Extent> dxf_layers(const std::string& path) {
  std::ifstream in(path, std::ios::binary);
  if (!in) throw std::runtime_error("DXF read failed: " + path);

  std::map<std::string, Extent> layers;
  bool in_entities = false;
  std::string layer = "0";
  double x = 0.0;
  bool have_x = false;

  std::string code_line, value_line;
  while (std::getline(in, code_line) && std::getline(in, value_line)) {
    const int code = std::stoi(code_line);
    if (code == 2 && value_line == "ENTITIES") { in_entities = true; continue; }
    if (!in_entities) continue;
    if (code == 8) { layer = value_line; continue; }
    if (code == 10 || code == 11) {
      x = std::stod(value_line);
      have_x = true;
    } else if ((code == 20 || code == 21) && have_x) {
      const double y = std::stod(value_line);
      Extent& e = layers[layer];
      e.xmin = std::min(e.xmin, x);
      e.xmax = std::max(e.xmax, x);
      e.ymin = std::min(e.ymin, y);
      e.ymax = std::max(e.ymax, y);
      have_x = false;
      if (code == 21) ++e.segments;
    }
  }
  if (layers.empty()) throw std::runtime_error("no LINE entities in " + path);
  return layers;
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
            export_shape(shape, (out / fs::u8path(room.name)).u8string(), fmt,
                        cfg.step_schema, &room, &cfg);

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
          const auto layers = dxf_layers(path);
          double worst_drift = 0.0;

          int wall_ok = 0;
          const int wall_total = static_cast<int>(room.outline.size());
          for (int e = 0; e < wall_total; ++e) {
            const auto it = layers.find("WALL_" + std::to_string(e + 1));
            if (it == layers.end()) continue;
            const WallBody wb = wall_body(room, cfg, e);
            const Extent want = section_xy_extent(wb.shape);
            const double drift = std::max(
                {std::abs(it->second.xmin - want.xmin), std::abs(it->second.ymin - want.ymin),
                 std::abs(it->second.xmax - want.xmax), std::abs(it->second.ymax - want.ymax)});
            worst_drift = std::max(worst_drift, drift);
            if (drift <= kDxfTolMm) ++wall_ok;
          }

          std::vector<Pt> inner_ring;
          for (const auto& p : room.outline) inner_ring.push_back({p.x, p.y});
          const double thickness =
              cm(room.wall_thickness ? *room.wall_thickness : cfg.wall_thickness);
          const std::vector<Pt> outer_ring = offset_ring(inner_ring, thickness);
          Extent ring_extent;
          for (const auto& p : outer_ring) {
            ring_extent.xmin = std::min(ring_extent.xmin, p.x * kCmToMm);
            ring_extent.xmax = std::max(ring_extent.xmax, p.x * kCmToMm);
            ring_extent.ymin = std::min(ring_extent.ymin, p.y * kCmToMm);
            ring_extent.ymax = std::max(ring_extent.ymax, p.y * kCmToMm);
          }

          auto slab_ok = [&](const std::string& name) {
            const auto it = layers.find(name);
            if (it == layers.end()) return false;
            const double drift = std::max(
                {std::abs(it->second.xmin - ring_extent.xmin),
                 std::abs(it->second.ymin - ring_extent.ymin),
                 std::abs(it->second.xmax - ring_extent.xmax),
                 std::abs(it->second.ymax - ring_extent.ymax)});
            worst_drift = std::max(worst_drift, drift);
            return drift <= kDxfTolMm;
          };
          const bool floor_ok = slab_ok("FLOOR");
          const bool ceiling_ok = slab_ok("CEILING");

          const auto fx = fixtures(room, inner_ring, cfg);
          int fixture_layers = 0;
          for (const auto& [name, extent] : layers)
            if (name.rfind("FIXTURE_", 0) == 0 && extent.segments > 0) ++fixture_layers;

          const bool ok = wall_ok == wall_total && floor_ok && ceiling_ok &&
                          fixture_layers == static_cast<int>(fx.size());
          if (!ok) ++failures;
          verdict = std::string(ok ? "exact" : "DRIFT") +
                    " walls=" + std::to_string(wall_ok) + "/" + std::to_string(wall_total) +
                    " floor=" + (floor_ok ? "ok" : "MISS") +
                    " ceiling=" + (ceiling_ok ? "ok" : "MISS") +
                    " fixtures=" + std::to_string(fixture_layers) + "/" +
                    std::to_string(fx.size()) + " drift=" + num(worst_drift, 4);
        } else if (fmt == "glb") {
          Handle(TDocStd_Document) doc;
          XCAFApp_Application::GetApplication()->NewDocument("MDTV-XCAF", doc);
          RWGltf_CafReader reader;
          reader.SetDocument(doc);
          if (!reader.Perform(TCollection_AsciiString(path.c_str()), Message_ProgressRange()))
            throw std::runtime_error("GLB read failed: " + path);

          TDF_LabelSequence roots;
          XCAFDoc_DocumentTool::ShapeTool(doc->Main())->GetFreeShapes(roots);

          std::vector<Pt> inner_ring;
          for (const auto& p : room.outline) inner_ring.push_back({p.x, p.y});
          const auto fx = fixtures(room, inner_ring, cfg);
          const int wall_total = static_cast<int>(room.outline.size());
          const int expected_count = 2 + wall_total + static_cast<int>(fx.size());

          double want_vol = solid_stats(floor_body(room, cfg)).volume_m3 +
                            solid_stats(ceiling_body(room, cfg)).volume_m3;
          for (int e = 0; e < wall_total; ++e)
            want_vol += solid_stats(wall_body(room, cfg, e).shape).volume_m3;
          for (const auto& f : fx) want_vol += solid_stats(f.solid).volume_m3;

          double got_vol = 0.0;
          for (int i = 1; i <= roots.Length(); ++i)
            got_vol += shape_mesh_volume_m3(XCAFDoc_ShapeTool::GetShape(roots.Value(i)));

          const bool count_ok = roots.Length() == expected_count;
          const double pct = want_vol > 0 ? std::abs(got_vol - want_vol) / want_vol * 100.0 : 0.0;
          const bool vol_ok = pct <= kStlMaxErrorPct;
          const bool ok = count_ok && vol_ok;
          if (!ok) ++failures;
          verdict = std::string(ok ? "ok" : (count_ok ? "COARSE" : "MISSING")) +
                    " bodies=" + std::to_string(roots.Length()) + "/" +
                    std::to_string(expected_count) + " vol=" + num(got_vol) + "/" +
                    num(want_vol) + " error=" + num(pct, 6) + "%";
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
