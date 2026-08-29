#include "snapir/designx.hpp"

#include <array>
#include <cctype>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <map>
#include <sstream>
#include <vector>

#include <BRepBuilderAPI_MakePolygon.hxx>
#include <BRep_Builder.hxx>
#include <IFSelect_ReturnStatus.hxx>
#include <IGESControl_Controller.hxx>
#include <IGESControl_Writer.hxx>
#include <Interface_Static.hxx>
#include <STEPControl_Writer.hxx>
#include <TopoDS_Compound.hxx>
#include <gp_Pnt.hxx>

#include "snapir/planes.hpp"
#include "snapir/solid.hpp"

namespace fs = std::filesystem;

namespace snapir {
namespace {

const std::map<std::string, std::string>& suffixes() {
  static const std::map<std::string, std::string> m = {
      {"iges", ".igs"}, {"step", ".stp"}, {"asc", ".asc"}};
  return m;
}

using Ring = std::vector<std::array<double, 3>>;

// Every closed or open polyline worth handing over.
std::vector<Ring> rings_of(const Room& room) {
  std::vector<Ring> rings;

  Ring ring;
  for (const auto& p : room.outline) ring.push_back({p.x, p.y, p.z});
  rings.push_back(ring);

  std::vector<Pt3> ceil_pts;
  for (const auto& p : room.ceiling) ceil_pts.push_back({p.x, p.y, p.z});

  bool have_plane = false;
  Plane plane;
  if (ceil_pts.size() >= 3) {
    plane = fit_or_level(ceil_pts);
    have_plane = true;
  } else if (room.ceiling_height_override) {
    plane = level_plane((room.floor_z ? *room.floor_z : 0.0) +
                        *room.ceiling_height_override);
    have_plane = true;
  }
  if (have_plane) {
    Ring up;
    for (const auto& p : ring) up.push_back({p[0], p[1], plane.z_at(p[0], p[1])});
    rings.push_back(up);
  }

  for (const auto& op : room.openings) {
    const double ax = op.left.x, ay = op.left.y;
    const double bx = op.right.x, by = op.right.y;
    const double sill = op.sill(), head = op.head();
    rings.push_back({{ax, ay, sill},
                     {bx, by, sill},
                     {bx, by, head},
                     {ax, ay, head},
                     {ax, ay, sill}});
  }
  return rings;
}

std::string write_curves(const Room& room, const fs::path& path,
                         const std::string& fmt) {
  BRep_Builder builder;
  TopoDS_Compound compound;
  builder.MakeCompound(compound);

  for (const auto& ring : rings_of(room)) {
    BRepBuilderAPI_MakePolygon poly;
    for (const auto& p : ring)
      poly.Add(gp_Pnt(p[0] * kCmToMm, p[1] * kCmToMm, p[2] * kCmToMm));
    if (!(ring.front() == ring.back())) poly.Close();
    builder.Add(compound, poly.Wire());
  }

  const std::string out = path.u8string();
  if (fmt == "iges") {
    IGESControl_Controller::Init();
    // Mode 0, surfaces. These are wires, not a body: brepmode has nothing to
    // stitch and would only wrap each polyline in a shell it does not need.
    IGESControl_Writer writer("MM", 0);
    writer.AddShape(compound);
    writer.ComputeModel();
    if (!writer.Write(out.c_str())) throw BuildError("IGES write failed: " + out);
  } else {
    Interface_Static::SetCVal("write.step.unit", "MM");
    STEPControl_Writer writer;
    writer.Transfer(compound, STEPControl_AsIs);
    if (writer.Write(out.c_str()) != IFSelect_RetDone)
      throw BuildError("STEP write failed: " + out);
  }
  return out;
}

// Plain XYZ, millimetres, one point per line.
std::string write_asc(const Room& room, const fs::path& path) {
  std::ostringstream os;
  os.setf(std::ios::fixed);
  os.precision(4);
  for (const auto& p : room.points)
    os << p.x * kCmToMm << ' ' << p.y * kCmToMm << ' ' << p.z * kCmToMm << '\n';

  std::ofstream fh(path, std::ios::binary);
  const std::string text = os.str();
  fh.write(text.data(), static_cast<std::streamsize>(text.size()));
  return path.u8string();
}

}  // namespace

std::string export_curves(const Room& room, const std::string& out_dir,
                          const std::string& fmt_in) {
  std::string fmt;
  for (char c : fmt_in) fmt += static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
  const auto it = suffixes().find(fmt);
  if (it == suffixes().end()) throw BuildError("Unknown format: " + fmt);

  const fs::path dir = fs::u8path(out_dir);
  fs::create_directories(dir);
  const fs::path path = dir / fs::u8path(room.name + it->second);

  if (fmt == "asc") return write_asc(room, path);
  if (room.outline.size() < 3)
    throw BuildError(room.name + ": outline has fewer than three points");
  return write_curves(room, path, fmt);
}

}  // namespace snapir
