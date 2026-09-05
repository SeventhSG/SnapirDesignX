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

#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakePolygon.hxx>
#include <BRepBuilderAPI_MakeVertex.hxx>
#include <BRep_Builder.hxx>
#include <IFSelect_ReturnStatus.hxx>
#include <IGESControl_Controller.hxx>
#include <IGESControl_Writer.hxx>
#include <Interface_Static.hxx>
#include <STEPControl_Writer.hxx>
#include <TopoDS_Compound.hxx>
#include <gp_Ax2.hxx>
#include <gp_Circ.hxx>
#include <gp_Dir.hxx>
#include <gp_Pnt.hxx>

#include "snapir/geometry.hpp"
#include "snapir/planes.hpp"
#include "snapir/settings.hpp"
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

// Sockets and pipes as the shapes they are, drawn on their own wall.
//
// Both arrive as a single reading, and as a single reading they leave as two
// identical dots - which tells you where a service is and nothing about what it
// is. A socket is a faceplate and a pipe is a bore, so one goes over as the
// square it measures and the other as a real circle, seated on the wall face
// the way the body seats them.
struct Circle {
  std::array<double, 3> centre;
  Pt axis;
  double radius;
};

void fixtures_of(const Room& room, const BuildSettings& cfg,
                 const std::vector<Pt>& ring, std::vector<Ring>& squares,
                 std::vector<Circle>& circles) {
  if (!cfg.include_fixtures || ring.size() < 3) return;

  for (const auto& p : room.points) {
    if (p.role != Role::Socket && p.role != Role::Plumbing) continue;
    const Projection pr = project_onto_edges({p.x, p.y}, ring);
    const Pt& a = ring[pr.edge];
    const Pt& b = ring[(pr.edge + 1) % ring.size()];
    double ex = b.x - a.x, ey = b.y - a.y;
    double len = std::sqrt(ex * ex + ey * ey);
    if (len == 0.0) len = 1.0;
    const double tx = ex / len, ty = ey / len;
    double nx = -ey / len, ny = ex / len;
    if (!point_in_polygon({pr.point.x + nx * 0.5, pr.point.y + ny * 0.5}, ring)) {
      nx = -nx;
      ny = -ny;
    }

    if (p.role == Role::Plumbing) {
      circles.push_back({{pr.point.x, pr.point.y, p.z}, {nx, ny},
                         cm(cfg.pipe_diameter) / 2});
      continue;
    }
    const double hw = cm(cfg.socket_width) / 2, hh = cm(cfg.socket_height) / 2;
    const std::array<std::array<double, 3>, 4> face = {{
        {pr.point.x + tx * hw, pr.point.y + ty * hw, p.z - hh},
        {pr.point.x - tx * hw, pr.point.y - ty * hw, p.z - hh},
        {pr.point.x - tx * hw, pr.point.y - ty * hw, p.z + hh},
        {pr.point.x + tx * hw, pr.point.y + ty * hw, p.z + hh},
    }};
    Ring loop(face.begin(), face.end());
    loop.push_back(face[0]);
    squares.push_back(loop);
  }
}

// Every polyline worth handing over, and every shot none of them carries.
//
// The two come back together because the second is worked out from the first:
// a shot is loose exactly when no curve already passes through it.
struct Handover {
  std::vector<Ring> rings;
  std::vector<std::array<double, 3>> loose;
  std::vector<Circle> circles;
};

Handover rings_of(const Room& room, const BuildSettings& cfg) {
  std::vector<Ring> rings;

  Ring ring;
  std::vector<Pt> plan;
  for (const auto& p : room.outline) {
    ring.push_back({p.x, p.y, p.z});
    plan.push_back({p.x, p.y});
  }
  if (ring.empty()) {
    // A merged room has no ring of its own - a stairwell is not one ring - so
    // its drawing is the lines it is made of, every one of them.
    std::map<std::string, const Point*> by;
    for (const auto& p : room.points) by[p.name] = &p;
    for (const auto& s : room.segments) {
      const auto a = by.find(s.first), b = by.find(s.second);
      if (a == by.end() || b == by.end()) continue;
      rings.push_back({{a->second->x, a->second->y, a->second->z},
                       {b->second->x, b->second->y, b->second->z}});
    }
    const auto loose = vertices_of(room, rings);
    for (const auto& v : loose) {
      rings.push_back({{v[0] - kMark, v[1], v[2]}, {v[0] + kMark, v[1], v[2]}});
      rings.push_back({{v[0], v[1] - kMark, v[2]}, {v[0], v[1] + kMark, v[2]}});
      rings.push_back({{v[0], v[1], v[2] - kMark}, {v[0], v[1], v[2] + kMark}});
    }
    return {rings, loose, {}};
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
  std::vector<Ring> squares;
  std::vector<Circle> circles;
  fixtures_of(room, cfg, plan, squares, circles);
  for (const auto& s : squares) rings.push_back(s);

  const auto loose = vertices_of(room, rings);
  // A service already has a shape of its own, so it gets no cross: two marks
  // on one reading is one more than the drawing needs.
  std::set<std::array<long long, 3>> marked;
  for (const auto& p : room.points)
    if (p.role == Role::Socket || p.role == Role::Plumbing)
      marked.insert(key_of(p.x, p.y, p.z));

  for (const auto& v : loose) {
    if (marked.count(key_of(v[0], v[1], v[2]))) continue;
    rings.push_back({{v[0] - kMark, v[1], v[2]}, {v[0] + kMark, v[1], v[2]}});
    rings.push_back({{v[0], v[1] - kMark, v[2]}, {v[0], v[1] + kMark, v[2]}});
    rings.push_back({{v[0], v[1], v[2] - kMark}, {v[0], v[1], v[2] + kMark}});
  }
  return {rings, loose, circles};
}

std::string write_curves(const Room& room, const fs::path& path,
                         const std::string& fmt, const BuildSettings& cfg) {
  BRep_Builder builder;
  TopoDS_Compound compound;
  builder.MakeCompound(compound);

  const Handover handover = rings_of(room, cfg);
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

  // A real circle, not a polygon pretending to be one: Design X reads the arc
  // and gives back a diameter you can dimension off.
  for (const auto& c : handover.circles) {
    const gp_Ax2 axis(
        gp_Pnt(c.centre[0] * kCmToMm, c.centre[1] * kCmToMm, c.centre[2] * kCmToMm),
        gp_Dir(c.axis.x, c.axis.y, 0.0));
    builder.Add(compound,
                BRepBuilderAPI_MakeEdge(gp_Circ(axis, c.radius * kCmToMm)).Edge());
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
                          const std::string& fmt_in, const BuildSettings& cfg) {
  std::string fmt;
  for (char c : fmt_in) fmt += static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
  const auto it = suffixes().find(fmt);
  if (it == suffixes().end()) throw BuildError("Unknown format: " + fmt);

  const fs::path dir = fs::u8path(out_dir);
  fs::create_directories(dir);
  const fs::path path = dir / fs::u8path(room.name + it->second);

  if (fmt == "asc") return write_asc(room, path);
  if (room.outline.size() < 3 && room.segments.empty())
    throw BuildError(room.name + ": outline has fewer than three points");
  return write_curves(room, path, fmt, cfg);
}

}  // namespace snapir
