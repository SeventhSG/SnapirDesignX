#include "snapir/solid.hpp"

#include <algorithm>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <sstream>

#include <Bnd_Box.hxx>
#include <BRepAdaptor_Curve.hxx>
#include <BRepAlgoAPI_Common.hxx>
#include <BRepAlgoAPI_Cut.hxx>
#include <BRepAlgoAPI_Fuse.hxx>
#include <BRepAlgoAPI_Section.hxx>
#include <BRepBndLib.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakePolygon.hxx>
#include <BRepBuilderAPI_MakeSolid.hxx>
#include <BRepBuilderAPI_Sewing.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepGProp.hxx>
#include <BRepMesh_IncrementalMesh.hxx>
#include <BRepPrimAPI_MakeCylinder.hxx>
#include <GCPnts_TangentialDeflection.hxx>
#include <GProp_GProps.hxx>
#include <IFSelect_ReturnStatus.hxx>
#include <Interface_Static.hxx>
#include <STEPControl_Writer.hxx>
#include <StlAPI_Writer.hxx>
#include <TopAbs_ShapeEnum.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <gp_Ax2.hxx>
#include <gp_Dir.hxx>
#include <gp_Pln.hxx>
#include <gp_Pnt.hxx>

namespace snapir {
namespace {

int count_of(const TopoDS_Shape& shape, TopAbs_ShapeEnum kind) {
  int n = 0;
  for (TopExp_Explorer exp(shape, kind); exp.More(); exp.Next()) ++n;
  return n;
}

// A face forced onto a true plane, never a spline that happens to be flat.
//
// OCCT will happily hand back a BSpline surface for a face that is exactly
// planar. Downstream that is a worse file: no analytic plane to snap to, no
// clean face for a toolpath. Building the face plane-only keeps the B-rep
// honest.
TopoDS_Face planar_face(const std::vector<gp_Pnt>& pts) {
  BRepBuilderAPI_MakePolygon poly;
  for (const auto& p : pts) poly.Add(p);
  poly.Close();
  BRepBuilderAPI_MakeFace face(poly.Wire(), Standard_True);  // OnlyPlane
  if (!face.IsDone()) throw BuildError("face is not planar");
  return face.Face();
}

// A solid between two planes, with the given plan outline.
//
// Every face is built explicitly and forced planar. The caps sit on the fitted
// planes. Each side face is a quad whose two lower corners share a plan
// position with its two upper corners, so all four lie in the vertical plane
// through that plan edge: exactly coplanar, not approximately.
TopoDS_Shape prism(const std::vector<Pt>& raw_ring, const Plane& bottom,
                   const Plane& top) {
  const std::vector<Pt> ring = ensure_ccw(raw_ring);
  const size_t n = ring.size();

  std::vector<gp_Pnt> lower, upper;
  lower.reserve(n);
  upper.reserve(n);
  for (const auto& p : ring) {
    lower.emplace_back(p.x * kCmToMm, p.y * kCmToMm, bottom.z_at(p.x, p.y) * kCmToMm);
    upper.emplace_back(p.x * kCmToMm, p.y * kCmToMm, top.z_at(p.x, p.y) * kCmToMm);
  }

  std::vector<TopoDS_Face> faces;
  faces.push_back(planar_face(std::vector<gp_Pnt>(lower.rbegin(), lower.rend())));
  faces.push_back(planar_face(upper));
  for (size_t i = 0; i < n; ++i) {
    const size_t j = (i + 1) % n;
    faces.push_back(planar_face({lower[i], lower[j], upper[j], upper[i]}));
  }

  BRepBuilderAPI_Sewing sew(1.0e-6);
  for (const auto& f : faces) sew.Add(f);
  sew.Perform();

  TopExp_Explorer exp(sew.SewedShape(), TopAbs_SHELL);
  if (!exp.More()) throw BuildError("faces did not sew into a closed shell");
  BRepBuilderAPI_MakeSolid solid(TopoDS::Shell(exp.Current()));
  if (!solid.IsDone()) throw BuildError("shell did not close into a solid");
  return solid.Solid();
}

// A function giving the outward normal of any edge of the ring.
//
// Taken from the ring's winding rather than by testing each corner. A test per
// corner gets reflex corners backwards, and a room with a niche has several of
// those.
struct Frame { Pt normal, tangent; };

Frame outward(const std::vector<Pt>& ring, const Pt& a, const Pt& b) {
  const bool ccw = signed_area(ring) > 0;
  double dx = b.x - a.x, dy = b.y - a.y;
  double len = std::sqrt(dx * dx + dy * dy);
  if (len == 0.0) len = 1.0;
  const double tx = dx / len, ty = dy / len;
  return ccw ? Frame{{ty, -tx}, {tx, ty}} : Frame{{-ty, tx}, {tx, ty}};
}

// The outer corner where two offset wall faces meet.
//
// Solved as the intersection of the two offset edge lines, so neighbouring
// walls share exactly this point and tile back into the room with no overlap
// and no gap.
Pt mitre_vertex(const std::vector<Pt>& ring, size_t i, double dist) {
  const size_t n = ring.size();
  const Pt& prev = ring[(i + n - 1) % n];
  const Pt& here = ring[i];
  const Pt& nxt = ring[(i + 1) % n];

  const Frame f1 = outward(ring, prev, here);
  const Frame f2 = outward(ring, here, nxt);

  const Pt p1{here.x + f1.normal.x * dist, here.y + f1.normal.y * dist};
  const Pt p2{here.x + f2.normal.x * dist, here.y + f2.normal.y * dist};
  const double denom = f1.tangent.x * f2.tangent.y - f1.tangent.y * f2.tangent.x;
  if (std::abs(denom) < 1e-9) return p1;  // the two walls run straight through
  const double s = ((p2.x - p1.x) * f2.tangent.y - (p2.y - p1.y) * f2.tangent.x) / denom;
  return {p1.x + f1.tangent.x * s, p1.y + f1.tangent.y * s};
}

// Ray cast, replacing shapely's point-in-polygon. Orientation-independent, so
// it does not care which way the ring was wound.
bool point_in_polygon(const Pt& q, const std::vector<Pt>& ring) {
  bool inside = false;
  const size_t n = ring.size();
  for (size_t i = 0, j = n - 1; i < n; j = i++) {
    const Pt& a = ring[i];
    const Pt& b = ring[j];
    if ((a.y > q.y) != (b.y > q.y) &&
        q.x < (b.x - a.x) * (q.y - a.y) / (b.y - a.y) + a.x)
      inside = !inside;
  }
  return inside;
}

// Seat a surveyed point on its wall and return the inward normal.
//
// Service points are never shot on the surface. A socket reads a centimetre or
// two out at the faceplate, a pipe reads wherever its open end happens to be,
// up to ten centimetres into the room. Projecting onto the nearest wall is what
// puts the fixture where the building actually has it.
struct WallFrame { Pt seat, normal, tangent; double dist; };

WallFrame wall_frame(double x, double y, const std::vector<Pt>& ring) {
  const Projection pr = project_onto_edges({x, y}, ring);
  const Pt& a = ring[pr.edge];
  const Pt& b = ring[(pr.edge + 1) % ring.size()];
  double dx = b.x - a.x, dy = b.y - a.y;
  double len = std::sqrt(dx * dx + dy * dy);
  if (len == 0.0) len = 1.0;
  double nx = -dy / len, ny = dx / len;

  if (!point_in_polygon({pr.point.x + nx * 0.5, pr.point.y + ny * 0.5}, ring)) {
    nx = -nx;  // normal must point into the room
    ny = -ny;
  }
  return {pr.point, {nx, ny}, {dx / len, dy / len}, pr.distance};
}

// A box spanning the wall at an opening, overshooting both faces.
TopoDS_Shape opening_cutter(const Opening& op, const std::vector<Pt>& ring,
                            const BuildSettings& cfg) {
  const double reach = cm(cfg.wall_thickness) * 3.0;
  const double ax = op.left.x, ay = op.left.y;
  const double bx = op.right.x, by = op.right.y;
  const double dx = bx - ax, dy = by - ay;
  const double length = std::sqrt(dx * dx + dy * dy);
  if (length < 1.0) throw BuildError("opening jambs coincide");

  double nx = -dy / length, ny = dx / length;  // wall normal, direction TBD
  const double cx = (ax + bx) / 2, cy = (ay + by) / 2;
  const Projection pr = project_onto_edges({cx, cy}, ring);
  if ((pr.point.x - cx) * nx + (pr.point.y - cy) * ny < 0) {
    nx = -nx;
    ny = -ny;
  }

  const std::vector<Pt> corners = {
      {ax - nx * reach, ay - ny * reach},
      {bx - nx * reach, by - ny * reach},
      {bx + nx * reach, by + ny * reach},
      {ax + nx * reach, ay + ny * reach},
  };
  return prism(corners, level_plane(op.sill()), level_plane(op.head()));
}

struct FixtureBuild {
  TopoDS_Shape solid;
  Pt seat, normal;
  double reach;
};

// A back box standing proud of the wall, or a recess cut into it.
//
// Anchored on the seat rather than the reading, and always reaching into the
// wall by socket_embed, so it cannot end up floating in the room.
FixtureBuild socket_shape(const Point& pt, const std::vector<Pt>& ring,
                          const BuildSettings& cfg, const std::string& mode) {
  const WallFrame w = wall_frame(pt.x, pt.y, ring);
  const double hw = cm(cfg.socket_width) / 2;

  double near_off, far_off;
  if (mode == "hole") {
    near_off = 0.5;
    far_off = -cm(cfg.socket_recess);  // into the wall
  } else {
    near_off = std::max(w.dist, cm(cfg.socket_proud));  // out to the faceplate
    far_off = -cm(cfg.socket_embed);
  }
  const std::vector<Pt> corners = {
      {w.seat.x + w.tangent.x * hw + w.normal.x * far_off,
       w.seat.y + w.tangent.y * hw + w.normal.y * far_off},
      {w.seat.x - w.tangent.x * hw + w.normal.x * far_off,
       w.seat.y - w.tangent.y * hw + w.normal.y * far_off},
      {w.seat.x - w.tangent.x * hw + w.normal.x * near_off,
       w.seat.y - w.tangent.y * hw + w.normal.y * near_off},
      {w.seat.x + w.tangent.x * hw + w.normal.x * near_off,
       w.seat.y + w.tangent.y * hw + w.normal.y * near_off},
  };
  const double half = cm(cfg.socket_height) / 2;
  return {prism(corners, level_plane(pt.z - half), level_plane(pt.z + half)), w.seat,
          w.normal, near_off};
}

// A pipe stub reaching the surveyed point, or a sleeve through the wall.
//
// The surveyed reading is the open end of the pipe, so the stub is built to
// reach exactly that far and no further. Nothing is invented.
FixtureBuild pipe_shape(const Point& pt, const std::vector<Pt>& ring,
                        const BuildSettings& cfg, const std::string& mode) {
  const WallFrame w = wall_frame(pt.x, pt.y, ring);
  const double reach =
      cm(cfg.pipe_length) != 0.0 ? cm(cfg.pipe_length)
                                 : std::max(w.dist, cm(cfg.pipe_min_length));
  const double embed =
      mode == "hole" ? cm(cfg.wall_thickness) * 1.5 : cm(cfg.pipe_embed);

  const gp_Pnt origin((w.seat.x - w.normal.x * embed) * kCmToMm,
                      (w.seat.y - w.normal.y * embed) * kCmToMm, pt.z * kCmToMm);
  const gp_Ax2 axis(origin, gp_Dir(w.normal.x, w.normal.y, 0.0));
  const double height = (embed + (mode == "hole" ? 0.5 : reach)) * kCmToMm;
  TopoDS_Shape solid =
      BRepPrimAPI_MakeCylinder(axis, cm(cfg.pipe_diameter) / 2 * kCmToMm, height)
          .Shape();
  return {solid, w.seat, w.normal, reach};
}

// Group sockets that sit shoulder to shoulder into single runs.
//
// Two boxes 80 mm wide whose centres are 80 mm apart share a face. Left alone
// they fuse into one lumpy body with a seam down the middle; grouped, they
// become one clean outlet the length of the run, which is what a double or
// triple socket actually is.
std::vector<std::vector<const Point*>> merge_sockets(const Room& room,
                                                     const std::vector<Pt>& ring,
                                                     const BuildSettings& cfg) {
  std::vector<const Point*> sockets;
  for (const auto& p : room.points)
    if (p.role == Role::Socket) sockets.push_back(&p);

  std::map<std::string, std::pair<int, double>> seats;
  for (const Point* p : sockets) {
    const WallFrame w = wall_frame(p->x, p->y, ring);
    const Projection pr = project_onto_edges(w.seat, ring);
    // Distance along the wall, so neighbours can be ordered and measured.
    const double along = w.seat.x * w.tangent.x + w.seat.y * w.tangent.y;
    seats[p->name] = {pr.edge, along};
  }

  std::vector<const Point*> ordered = sockets;
  std::stable_sort(ordered.begin(), ordered.end(),
                   [&seats](const Point* a, const Point* b) {
                     return seats.at(a->name) < seats.at(b->name);
                   });

  const double half = cm(cfg.socket_width) / 2;
  const double gap = cm(cfg.sockets_merge_gap);
  std::vector<std::vector<const Point*>> groups;
  for (const Point* p : ordered) {
    const auto& s = seats.at(p->name);
    if (!groups.empty()) {
      const Point* last = groups.back().back();
      const auto& ls = seats.at(last->name);
      const bool same_wall = ls.first == s.first;
      const bool touching = std::abs(s.second - ls.second) - 2 * half <= gap;
      const bool level = std::abs(p->z - last->z) <= cm(cfg.socket_height);
      if (same_wall && touching && level) {
        groups.back().push_back(p);
        continue;
      }
    }
    groups.push_back({p});
  }
  return groups;
}

// One box spanning a whole run of touching sockets.
FixtureBuild socket_run(const std::vector<const Point*>& group,
                        const std::vector<Pt>& ring, const BuildSettings& cfg,
                        const std::string& mode) {
  if (group.size() == 1) return socket_shape(*group[0], ring, cfg, mode);

  double sx = 0, sy = 0;
  for (const Point* p : group) { sx += p->x; sy += p->y; }
  const WallFrame w = wall_frame(sx / static_cast<double>(group.size()),
                                 sy / static_cast<double>(group.size()), ring);

  // Span from the outer edge of the first box to the outer edge of the last.
  const double half = cm(cfg.socket_width) / 2;
  double lo = 0, hi = 0;
  bool first = true;
  for (const Point* p : group) {
    const double along =
        (p->x - w.seat.x) * w.tangent.x + (p->y - w.seat.y) * w.tangent.y;
    if (first) { lo = hi = along; first = false; }
    lo = std::min(lo, along);
    hi = std::max(hi, along);
  }
  lo -= half;
  hi += half;

  double near_off, far_off;
  if (mode == "hole") {
    near_off = 0.5;
    far_off = -cm(cfg.socket_recess);
  } else {
    near_off = std::max(w.dist, cm(cfg.socket_proud));
    far_off = -cm(cfg.socket_embed);
  }

  const std::vector<Pt> corners = {
      {w.seat.x + w.tangent.x * lo + w.normal.x * far_off,
       w.seat.y + w.tangent.y * lo + w.normal.y * far_off},
      {w.seat.x + w.tangent.x * hi + w.normal.x * far_off,
       w.seat.y + w.tangent.y * hi + w.normal.y * far_off},
      {w.seat.x + w.tangent.x * hi + w.normal.x * near_off,
       w.seat.y + w.tangent.y * hi + w.normal.y * near_off},
      {w.seat.x + w.tangent.x * lo + w.normal.x * near_off,
       w.seat.y + w.tangent.y * lo + w.normal.y * near_off},
  };
  double zc = 0;
  for (const Point* p : group) zc += p->z;
  zc /= static_cast<double>(group.size());
  const double h = cm(cfg.socket_height) / 2;
  return {prism(corners, level_plane(zc - h), level_plane(zc + h)), w.seat, w.normal,
          near_off};
}

std::string override_mode(const FixtureOverrides* overrides, const std::string& name,
                          const std::string& fallback) {
  if (!overrides) return fallback;
  const auto it = overrides->find(name);
  if (it == overrides->end() || it->second.mode.empty()) return fallback;
  return it->second.mode;
}

int solid_count(const TopoDS_Shape& shape) {
  return count_of(shape, TopAbs_SOLID);
}

// Fuse or cut every fixture, and report any that would not attach.
TopoDS_Shape add_fixtures(TopoDS_Shape shape, const Room& room,
                          const std::vector<Pt>& ring, const BuildSettings& cfg,
                          const FixtureOverrides* overrides,
                          std::vector<std::string>& stray) {
  for (const auto& f : fixtures(room, ring, cfg, overrides)) {
    TopoDS_Shape result;
    bool done = false;
    if (f.mode == "hole") {
      BRepAlgoAPI_Cut run(shape, f.solid);
      run.Build();
      done = run.IsDone();
      if (done) result = run.Shape();
    } else {
      BRepAlgoAPI_Fuse run(shape, f.solid);
      run.Build();
      done = run.IsDone();
      if (done) result = run.Shape();
    }
    if (!done) {
      stray.push_back(f.name);
      continue;
    }
    if (solid_count(result) != 1) {
      stray.push_back(f.name);  // it detached; keep the body whole
      continue;
    }
    shape = result;
  }
  return shape;
}

}  // namespace

std::vector<Pt> offset_ring(const std::vector<Pt>& raw_ring, double distance) {
  // Mitred joins matter here. A rounded join would put an arc where the
  // building has a corner, and the whole point is that corners stay exact.
  // This is the same solver wall_body uses for its own corners, so a wall and
  // the shell it came out of agree to the last decimal.
  const std::vector<Pt> ring = ensure_ccw(raw_ring);
  if (!self_intersections(ring).empty())
    throw BuildError("outline is not a simple polygon");

  std::vector<Pt> grown;
  grown.reserve(ring.size());
  for (size_t i = 0; i < ring.size(); ++i) grown.push_back(mitre_vertex(ring, i, distance));

  if (!self_intersections(grown).empty())
    throw BuildError("wall offset split the outline; thickness is too large");
  return grown;
}

std::pair<Plane, Plane> room_planes(const Room& room, const BuildSettings& cfg) {
  std::vector<Pt3> floor_pts;
  for (const auto& p : room.outline) floor_pts.push_back({p.x, p.y, p.z});
  const Plane floor = floor_pts.size() >= 3
                          ? fit_or_level(floor_pts, cfg.max_ceiling_tilt_deg)
                          : level_plane(room.floor_z ? *room.floor_z : 0.0);

  std::vector<Pt3> ceil_pts;
  for (const auto& p : room.ceiling) ceil_pts.push_back({p.x, p.y, p.z});

  Plane ceiling;
  if (ceil_pts.size() >= 3 && cfg.fit_ceiling_plane) {
    ceiling = fit_or_level(ceil_pts, cfg.max_ceiling_tilt_deg);
  } else if (room.ceiling_height_override) {
    ceiling = level_plane(floor.pz + *room.ceiling_height_override);
  } else if (room.ceiling_z) {
    ceiling = level_plane(*room.ceiling_z);
  } else {
    throw BuildError(room.name + ": no ceiling height. Supply one first.");
  }
  return {floor, ceiling};
}

std::vector<Fixture> fixtures(const Room& room, const std::vector<Pt>& ring,
                              const BuildSettings& cfg,
                              const FixtureOverrides* overrides) {
  std::vector<Fixture> out;

  // Sockets first, in runs, so neighbours arrive as one outlet.
  for (const auto& group : merge_sockets(room, ring, cfg)) {
    const std::string mode = override_mode(overrides, group.front()->name, cfg.socket_mode);
    FixtureBuild built;
    try {
      built = socket_run(group, ring, cfg, mode);
    } catch (const std::exception&) {
      continue;
    }
    const std::string name =
        group.size() == 1 ? group.front()->name
                          : group.front()->name + "+" + std::to_string(group.size() - 1);
    out.push_back({name, "socket", mode, built.solid, built.seat, built.normal,
                   built.reach});
  }

  for (const auto& p : room.points) {
    if (p.role != Role::Plumbing) continue;
    const std::string mode = override_mode(overrides, p.name, cfg.pipe_mode);
    FixtureBuild built;
    try {
      built = pipe_shape(p, ring, cfg, mode);
    } catch (const std::exception&) {
      continue;
    }
    out.push_back({p.name, "pipe", mode, built.solid, built.seat, built.normal,
                   built.reach});
  }
  return out;
}

TopoDS_Shape build_room(Room& room, const BuildSettings& cfg,
                        const std::vector<Opening>* openings,
                        const FixtureOverrides* fixture_overrides) {
  if (room.outline.size() < 3)
    throw BuildError(room.name + ": outline has fewer than three points");

  const auto planes = room_planes(room, cfg);
  const Plane& floor = planes.first;
  const Plane& ceiling = planes.second;

  std::vector<Pt> inner_ring;
  for (const auto& p : room.outline) inner_ring.push_back({p.x, p.y});

  const double thickness =
      cm(room.wall_thickness ? *room.wall_thickness : cfg.wall_thickness);
  const std::vector<Pt> outer_ring = offset_ring(inner_ring, thickness);

  const Plane outer_floor{floor.px, floor.py, floor.pz - cm(cfg.floor_thickness),
                          floor.nx, floor.ny, floor.nz};
  const Plane outer_ceiling{ceiling.px, ceiling.py,
                            ceiling.pz + cm(cfg.ceiling_thickness), ceiling.nx,
                            ceiling.ny, ceiling.nz};

  const TopoDS_Shape outer = prism(outer_ring, outer_floor, outer_ceiling);
  const TopoDS_Shape inner = prism(inner_ring, floor, ceiling);

  BRepAlgoAPI_Cut cut(outer, inner);
  cut.Build();
  if (!cut.IsDone()) throw BuildError(room.name + ": could not subtract the room volume");
  TopoDS_Shape shape = cut.Shape();

  if (cfg.cut_openings) {
    const std::vector<Opening>& list = openings ? *openings : room.openings;
    for (const auto& op : list) {
      BRepAlgoAPI_Cut c(shape, opening_cutter(op, inner_ring, cfg));
      c.Build();
      if (!c.IsDone()) throw BuildError(room.name + ": opening cut failed");
      shape = c.Shape();
    }
  }

  if (cfg.include_fixtures) {
    std::vector<std::string> stray;
    shape = add_fixtures(shape, room, inner_ring, cfg, fixture_overrides, stray);
    if (!stray.empty())
      room.issues.push_back({"info", "fixture-off-wall",
                             std::to_string(stray.size()) +
                                 " service point(s) did not meet any wall and were "
                                 "left out of the body.",
                             stray});
  }

  if (!BRepCheck_Analyzer(shape).IsValid())
    throw BuildError(room.name + ": resulting solid is not valid");
  return shape;
}

SolidStats solid_stats(const TopoDS_Shape& shape) {
  GProp_GProps props;
  BRepGProp::VolumeProperties(shape, props);
  return {count_of(shape, TopAbs_SOLID), count_of(shape, TopAbs_SHELL),
          count_of(shape, TopAbs_FACE), props.Mass() / 1.0e9};  // mm3 to m3
}

namespace {

// OCCT names its schemas by enum, not by the number a CAD user says out loud.
// Setting the integer is unambiguous where the string quietly falls back to the
// default when it is not one of the names OCCT knows.
int step_schema_code(const std::string& schema) {
  if (schema == "AP203") return 3;                        // AP203
  if (schema == "AP214" || schema == "AP214IS") return 4; // AP214IS
  if (schema == "AP242" || schema == "AP242DIS") return 5;// AP242DIS
  if (schema == "AP214CD") return 1;
  if (schema == "AP214DIS") return 2;
  throw BuildError("Unknown STEP schema: " + schema);
}

void ensure_parent(const std::filesystem::path& out) {
  if (out.has_parent_path()) std::filesystem::create_directories(out.parent_path());
}

// Binary STL, millimetres.
//
// The body is almost all planar faces, and a plane tessellates to two triangles
// whatever the deflection is asked for, so the tolerance below only ever bites
// on the pipe stubs. A tenth of a millimetre there is far finer than anything
// this file is meant to be used for, and costs nothing on the flat parts.
//
// Binary rather than ASCII: same triangles, a fifth of the size, and every
// viewer reads it.
constexpr double kStlDeflection = 0.1;   // mm
constexpr double kStlAngularDeg = 15.0;  // degrees between facets on a curve

std::string write_stl(const TopoDS_Shape& shape, const std::string& path) {
  // A shape carries no triangulation until it is asked for one, and the writer
  // will not make it. Meshing here also keeps the room's own display mesh out
  // of it, so what is written does not depend on whether the viewport ran.
  BRepMesh_IncrementalMesh mesher(shape, kStlDeflection, Standard_False,
                                  kStlAngularDeg * M_PI / 180.0, Standard_True);
  mesher.Perform();
  if (!mesher.IsDone()) throw BuildError("STL meshing failed: " + path);

  StlAPI_Writer writer;
  writer.ASCIIMode() = Standard_False;
  if (!writer.Write(shape, path.c_str())) throw BuildError("STL write failed: " + path);
  return path;
}

std::string dxf_num(double v) {
  std::ostringstream s;
  s.setf(std::ios::fixed);
  s.precision(6);
  s << v;
  return s.str();
}

// ASCII DXF (R12 entities), millimetres: a plan section through the solid,
// not a separate drawing. The cut is a horizontal plane through the shape's
// own mid-height, which lands inside the wall band for any room this builds
// (floor and ceiling slabs are thin next to a wall run), so what comes back
// is both wall faces at once: the surveyed inner ring and the grown outer
// one, each edge exactly where the B-rep puts it.
//
// Edges are written as individual LINE entities rather than chained into
// polylines - correct either way, and chaining wires back into loops through
// shared faces isn't worth the code for what is meant to be opened and
// traced over, not measured from.
std::string write_dxf(const TopoDS_Shape& shape, const std::string& path) {
  Bnd_Box box;
  BRepBndLib::Add(shape, box);
  if (box.IsVoid()) throw BuildError("DXF section failed: empty shape");
  double xmin, ymin, zmin, xmax, ymax, zmax;
  box.Get(xmin, ymin, zmin, xmax, ymax, zmax);
  const double mid_z = (zmin + zmax) / 2.0;

  const gp_Pln cut_plane(gp_Pnt(0, 0, mid_z), gp_Dir(0, 0, 1));
  BRepAlgoAPI_Section section(shape, cut_plane, Standard_False);
  section.Approximation(Standard_True);
  section.Build();
  if (!section.IsDone()) throw BuildError("DXF section failed: " + path);

  ensure_parent(std::filesystem::u8path(path));
  std::ofstream out(std::filesystem::u8path(path), std::ios::binary);
  if (!out) throw BuildError("DXF write failed: " + path);

  out << "0\nSECTION\n2\nHEADER\n9\n$INSUNITS\n70\n4\n0\nENDSEC\n"  // 4 = millimetres
      << "0\nSECTION\n2\nENTITIES\n";

  int segments = 0;
  for (TopExp_Explorer ex(section.Shape(), TopAbs_EDGE); ex.More(); ex.Next()) {
    BRepAdaptor_Curve curve(TopoDS::Edge(ex.Current()));
    GCPnts_TangentialDeflection pts(curve, kStlAngularDeg * M_PI / 180.0, kStlDeflection);
    for (int i = 1; i < pts.NbPoints(); ++i) {
      const gp_Pnt a = pts.Value(i), b = pts.Value(i + 1);
      out << "0\nLINE\n8\n0\n"
          << "10\n" << dxf_num(a.X()) << "\n20\n" << dxf_num(a.Y()) << "\n30\n"
          << dxf_num(a.Z()) << "\n"
          << "11\n" << dxf_num(b.X()) << "\n21\n" << dxf_num(b.Y()) << "\n31\n"
          << dxf_num(b.Z()) << "\n";
      ++segments;
    }
  }
  out << "0\nENDSEC\n0\nEOF\n";
  out.close();
  if (segments == 0) throw BuildError("DXF section carried no geometry: " + path);
  return path;
}

}  // namespace

const std::vector<ExportFormat>& export_formats() {
  // dwg is deliberately absent - see the comment on ExportFormat in the
  // header. Adding it later needs one row here and an export_dwg() beside
  // export_dxf(); export_shape already dispatches on fmt, nothing else to
  // redesign.
  static const std::vector<ExportFormat> v = {
      {"step", ".step"}, {"stl", ".stl"}, {"dxf", ".dxf"}};
  return v;
}

bool is_export_format(const std::string& id) {
  for (const auto& f : export_formats())
    if (id == f.id) return true;
  return false;
}

std::string export_suffix(const std::string& fmt) {
  for (const auto& f : export_formats())
    if (fmt == f.id) return f.suffix;
  return ".step";
}

std::string export_step(const TopoDS_Shape& shape, const std::string& path,
                        const std::string& schema) {
  ensure_parent(std::filesystem::u8path(path));

  Interface_Static::SetIVal("write.step.schema", step_schema_code(schema));
  Interface_Static::SetCVal("write.step.unit", "MM");
  STEPControl_Writer writer;
  writer.Transfer(shape, STEPControl_AsIs);
  if (writer.Write(path.c_str()) != IFSelect_RetDone)
    throw BuildError("STEP write failed: " + path);
  return path;
}

std::string export_shape(const TopoDS_Shape& shape, const std::string& base_path,
                         const std::string& fmt, const std::string& schema) {
  if (!is_export_format(fmt)) throw BuildError("Unknown export format: " + fmt);
  const std::string path = base_path + export_suffix(fmt);
  ensure_parent(std::filesystem::u8path(path));

  if (fmt == "step") return export_step(shape, path, schema);
  if (fmt == "dxf") return write_dxf(shape, path);
  return write_stl(shape, path);
}

int wall_index_at(const Room& room, double x_m, double y_m) {
  std::vector<Pt> ring;
  for (const auto& p : room.outline) ring.push_back({p.x, p.y});
  if (ring.size() < 2) throw BuildError("room has no outline");
  return project_onto_edges({x_m * 100.0, y_m * 100.0}, ring).edge;
}

WallBody wall_body(Room& room, const BuildSettings& cfg, int edge,
                   const FixtureOverrides* fixture_overrides) {
  std::vector<Pt> ring;
  for (const auto& p : room.outline) ring.push_back({p.x, p.y});
  const int n = static_cast<int>(ring.size());
  if (edge < 0 || edge >= n) throw BuildError(room.name + ": no wall " + std::to_string(edge));

  const Pt& a = ring[edge];
  const Pt& b = ring[(edge + 1) % n];
  const double dx = b.x - a.x, dy = b.y - a.y;
  const double length = std::sqrt(dx * dx + dy * dy);
  if (length < 1.0) throw BuildError("wall has no length");

  const double thickness =
      cm(room.wall_thickness ? *room.wall_thickness : cfg.wall_thickness);

  // Fixtures stand proud of the wall face, so they would be shaved off by a cut
  // that stops at the surface. The shell is built bare and this wall's own
  // fixtures are added back afterwards.
  BuildSettings bare_cfg = cfg;
  bare_cfg.include_fixtures = false;
  const TopoDS_Shape bare = build_room(room, bare_cfg);

  const auto planes = room_planes(room, cfg);
  const Frame f = outward(ring, a, b);
  const std::vector<Pt> footprint = {
      a, b,
      {b.x + f.normal.x * thickness, b.y + f.normal.y * thickness},
      {a.x + f.normal.x * thickness, a.y + f.normal.y * thickness}};
  const TopoDS_Shape box = prism(footprint, planes.first, planes.second);

  BRepAlgoAPI_Common common(bare, box);
  common.Build();
  if (!common.IsDone())
    throw BuildError(room.name + ": could not separate wall " + std::to_string(edge + 1));
  TopoDS_Shape body = common.Shape();

  if (cfg.include_fixtures) {
    for (const auto& fx : fixtures(room, ring, cfg, fixture_overrides)) {
      if (project_onto_edges(fx.seat, ring).edge != edge) continue;  // another wall
      if (fx.mode == "hole") {
        BRepAlgoAPI_Cut run(body, fx.solid);
        run.Build();
        if (run.IsDone()) body = run.Shape();
      } else {
        BRepAlgoAPI_Fuse run(body, fx.solid);
        run.Build();
        if (run.IsDone()) body = run.Shape();
      }
    }
  }

  const int count = solid_count(body);
  if (count == 0)
    throw BuildError(room.name + ": wall " + std::to_string(edge + 1) + " came out empty");
  // More than one solid is a real outcome, not a fault: an opening at the end of
  // a wall can leave the head and sill bands unconnected. STEP carries them as
  // separate bodies, which is still a usable part.
  if (!BRepCheck_Analyzer(body).IsValid())
    throw BuildError(room.name + ": wall " + std::to_string(edge + 1) +
                     " is not a valid solid");
  return {body, length, count};
}

}  // namespace snapir
