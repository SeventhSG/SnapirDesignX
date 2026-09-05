#include "snapir/designx.hpp"

#include <array>
#include <cctype>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <cmath>
#include <map>
#include <set>
#include <sstream>
#include <vector>

#include <BRepBuilderAPI_MakePolygon.hxx>
#include <BRepBuilderAPI_MakeVertex.hxx>
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

// Half-arm of the cross drawn through a single shot, centimetres.
constexpr double kMark = 5.0;

// Every shot no curve carries.
//
// A depth shot, a socket, a point the classifier could not place, a corner the
// surveyor took and never joined to anything - none of them are on a polyline,
// so a room exported without them arrives in Design X missing exactly the
// readings that still need a decision. Whatever the drawing already says is
// left to the drawing; the rest go over as points.
//
// The instrument's own stations go too: they are where the panoramas were
// taken from.
std::array<long long, 3> key_of(double x, double y, double z) {
  return {std::llround(x * 1000), std::llround(y * 1000), std::llround(z * 1000)};
}

std::vector<std::array<double, 3>> vertices_of(const Room& room,
                                               const std::vector<Ring>& carried) {
  std::set<std::array<long long, 3>> seen;
  for (const auto& ring : carried)
    for (const auto& p : ring) seen.insert(key_of(p[0], p[1], p[2]));

  std::vector<std::array<double, 3>> out;
  for (const auto& p : room.points)
    if (!seen.count(key_of(p.x, p.y, p.z))) out.push_back({p.x, p.y, p.z});
  for (const auto& p : room.stations) out.push_back({p.x, p.y, p.z});
  return out;
}

// The wireframe of what a measured rectangle actually becomes.
//
// A shot in the middle of a rectangle says how far the thing standing on the
// wall reaches, and that is the one number the drawing cannot show on its own:
// the rectangle looks identical whether the boiler is 8 cm deep or 40. So the
// far face is drawn where the shot put it, joined back to the rectangle corner
// by corner - a box, in the round, at the measured depth.
void depth_box(const Opening& op, const std::vector<Pt>& ring,
               std::vector<Ring>& out) {
  if (!op.measured() || ring.size() < 3) return;
  const double cx = (op.left.x + op.right.x) / 2;
  const double cy = (op.left.y + op.right.y) / 2;

  // The inward normal of the wall this rectangle sits on. Same derivation the
  // builder uses to stand the fitting up, so the wireframe lands on the body.
  const Projection pr = project_onto_edges({cx, cy}, ring);
  const Pt& a = ring[pr.edge];
  const Pt& b = ring[(pr.edge + 1) % ring.size()];
  double ex = b.x - a.x, ey = b.y - a.y;
  double len = std::sqrt(ex * ex + ey * ey);
  if (len == 0.0) len = 1.0;
  double nx = -ey / len, ny = ex / len;
  if (!point_in_polygon({pr.point.x + nx * 0.5, pr.point.y + ny * 0.5}, ring)) {
    nx = -nx;
    ny = -ny;
  }

  const double sides[2] = {op.out_depth ? *op.out_depth : 0.0,
                           op.in_depth ? -*op.in_depth : 0.0};
  for (double depth : sides) {
    if (depth == 0.0) continue;
    const double dx = nx * depth, dy = ny * depth;
    const std::array<std::array<double, 3>, 4> face = {{
        {op.left.x + dx, op.left.y + dy, op.sill()},
        {op.right.x + dx, op.right.y + dy, op.sill()},
        {op.right.x + dx, op.right.y + dy, op.head()},
        {op.left.x + dx, op.left.y + dy, op.head()},
    }};
    Ring loop(face.begin(), face.end());
    loop.push_back(face[0]);
    out.push_back(loop);
    const std::array<std::array<double, 2>, 4> back = {{
        {op.left.x, op.left.y}, {op.right.x, op.right.y},
        {op.right.x, op.right.y}, {op.left.x, op.left.y},
    }};
    for (size_t i = 0; i < 4; ++i)
      out.push_back({{back[i][0], back[i][1], face[i][2]}, face[i]});
  }
}

// Every polyline worth handing over, and every shot none of them carries.
//
// The two come back together because the second is worked out from the first:
// a shot is loose exactly when no curve already passes through it.
struct Handover {
  std::vector<Ring> rings;
  std::vector<std::array<double, 3>> loose;
};

Handover rings_of(const Room& room) {
  std::vector<Ring> rings;

  Ring ring;
  std::vector<Pt> plan;
  for (const auto& p : room.outline) {
    ring.push_back({p.x, p.y, p.z});
    plan.push_back({p.x, p.y});
  }
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
    depth_box(op, plan, rings);
  }

  // A flight is the line the surveyor walked up, nosing by nosing. Handing
  // over the room without it leaves the stairs to be drawn again from the
  // loose points, which is the work the survey already did.
  for (const auto& flight : room.stairs) {
    if (flight.points.size() < 2) continue;
    Ring run;
    for (const auto& p : flight.points) run.push_back({p.x, p.y, p.z});
    rings.push_back(run);
  }

  // Skirting: the pair that measured one board, as the diagonal it was shot
  // as. Two points, so it reads as the depth and height it is.
  for (const auto& v : room.pervaz)
    rings.push_back({{v.corner.x, v.corner.y, v.corner.z},
                     {v.wall.x, v.wall.y, v.wall.z}});

  // A single shot is written as an IGES point as well, which is the exact
  // thing. The cross is for STEP, whose writer drops a loose vertex on the
  // floor: three short lines through the shot, so it arrives either way.
  const auto loose = vertices_of(room, rings);
  for (const auto& v : loose) {
    rings.push_back({{v[0] - kMark, v[1], v[2]}, {v[0] + kMark, v[1], v[2]}});
    rings.push_back({{v[0], v[1] - kMark, v[2]}, {v[0], v[1] + kMark, v[2]}});
    rings.push_back({{v[0], v[1], v[2] - kMark}, {v[0], v[1], v[2] + kMark}});
  }
  return {rings, loose};
}

std::string write_curves(const Room& room, const fs::path& path,
                         const std::string& fmt) {
  BRep_Builder builder;
  TopoDS_Compound compound;
  builder.MakeCompound(compound);

  const Handover handover = rings_of(room);
  for (const auto& ring : handover.rings) {
    if (ring.size() < 2) continue;
    BRepBuilderAPI_MakePolygon poly;
    for (const auto& p : ring)
      poly.Add(gp_Pnt(p[0] * kCmToMm, p[1] * kCmToMm, p[2] * kCmToMm));
    // An open run - a flight of stairs, a skirting pair - is a line, not a
    // loop. Closing it would draw a wall that was never measured.
    if (ring.size() > 2 && !(ring.front() == ring.back())) poly.Close();
    builder.Add(compound, poly.Wire());
  }

  // Single shots, as points. Design X shows a vertex where the instrument
  // stood; a wire cannot carry one.
  for (const auto& v : handover.loose)
    builder.Add(compound, BRepBuilderAPI_MakeVertex(
                              gp_Pnt(v[0] * kCmToMm, v[1] * kCmToMm, v[2] * kCmToMm))
                              .Vertex());

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
