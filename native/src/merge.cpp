#include "snapir/merge.hpp"

#include <algorithm>
#include <cmath>
#include <limits>

#include <BRepAlgoAPI_Fuse.hxx>
#include <BRepBuilderAPI_Transform.hxx>
#include <BRep_Builder.hxx>
#include <TopoDS_Compound.hxx>
#include <gp_Ax1.hxx>
#include <gp_Dir.hxx>
#include <gp_Pnt.hxx>
#include <gp_Trsf.hxx>
#include <gp_Vec.hxx>

#include "snapir/solid.hpp"

namespace snapir {
namespace {

constexpr double kDegToRad = 3.14159265358979323846 / 180.0;

using Triple = std::array<double, 3>;

double dist3(const Triple& a, const Triple& b) {
  const double dx = a[0] - b[0], dy = a[1] - b[1], dz = a[2] - b[2];
  return std::sqrt(dx * dx + dy * dy + dz * dz);
}

// The rotation and shift carrying src onto dst, in the plan.
//
// One pair can only give a shift - a single point says nothing about which way
// the room is turned - so the room keeps its own heading until a second pair is
// made. Two or more solve both at once, in the least-squares sense, which is
// what makes a third pair worth making: it does not overrule the first two, it
// averages with them.
Placement fit(const std::vector<Triple>& src, const std::vector<Triple>& dst) {
  const size_t n = src.size();
  Placement out;
  if (n == 0) return out;

  double sx = 0, sy = 0, sz = 0, dx = 0, dy = 0, dz = 0;
  for (size_t i = 0; i < n; ++i) {
    sx += src[i][0]; sy += src[i][1]; sz += src[i][2];
    dx += dst[i][0]; dy += dst[i][1]; dz += dst[i][2];
  }
  const double m = static_cast<double>(n);
  sx /= m; sy /= m; sz /= m; dx /= m; dy /= m; dz /= m;

  double rotation = 0.0;
  if (n >= 2) {
    double num = 0, den = 0;
    for (size_t i = 0; i < n; ++i) {
      const double a = src[i][0] - sx, b = src[i][1] - sy;
      const double c = dst[i][0] - dx, d = dst[i][1] - dy;
      num += a * d - b * c;
      den += a * c + b * d;
    }
    if (std::abs(num) > 1e-12 || std::abs(den) > 1e-12)
      rotation = std::atan2(num, den);
  }

  const double cos = std::cos(rotation), sin = std::sin(rotation);
  out.dx = dx - (sx * cos - sy * sin);
  out.dy = dy - (sx * sin + sy * cos);
  out.dz = dz - sz;
  out.rotation_deg = rotation / kDegToRad;

  double sum = 0;
  for (size_t i = 0; i < n; ++i) {
    const Triple at = out.apply(src[i][0], src[i][1], src[i][2]);
    const double d = dist3(at, dst[i]);
    sum += d * d;
  }
  out.residual = std::sqrt(sum / m);
  out.pairs = static_cast<int>(n);
  return out;
}

const Point* point_in(const Room& room, const std::string& name) {
  for (const auto& p : room.points)
    if (p.name == name) return &p;
  return nullptr;
}

}  // namespace

std::array<double, 3> Placement::apply(double x, double y, double z) const {
  const double rad = rotation_deg * kDegToRad;
  const double cos = std::cos(rad), sin = std::sin(rad);
  return {x * cos - y * sin + dx, x * sin + y * cos + dy, z + dz};
}

std::array<std::string, 4> MergePair::key() const {
  const std::pair<std::string, std::string> a{room_a, point_a};
  const std::pair<std::string, std::string> b{room_b, point_b};
  const auto& lo = a < b ? a : b;
  const auto& hi = a < b ? b : a;
  return {lo.first, lo.second, hi.first, hi.second};
}

MergeResult solve_merge(const std::map<std::string, Room>& rooms,
                        const std::vector<MergePair>& pairs,
                        const std::string& anchor_in) {
  MergeResult out;
  if (rooms.empty()) return out;

  std::string anchor = anchor_in;
  if (!rooms.count(anchor)) {
    // The room with the most pairs makes the steadiest frame; failing that,
    // the first one, so an empty merge still has somewhere to start.
    std::map<std::string, int> count;
    for (const auto& p : pairs) {
      ++count[p.room_a];
      ++count[p.room_b];
    }
    anchor = rooms.begin()->first;
    int best = -1;
    for (const auto& kv : rooms) {
      const int c = count.count(kv.first) ? count.at(kv.first) : 0;
      if (c > best) { best = c; anchor = kv.first; }
    }
  }
  out.placed[anchor] = Placement();

  // Rooms are placed outward from the anchor, each against whatever is already
  // placed, so a room matched only to a room matched only to the anchor still
  // lands - which is how a stairwell goes together, floor by floor, with nobody
  // ever having to see the top and the bottom at once.
  while (true) {
    std::string best_name;
    Placement best;
    bool found = false;

    for (const auto& kv : rooms) {
      const std::string& name = kv.first;
      if (out.placed.count(name)) continue;

      std::vector<Triple> src, dst;
      std::string via;
      for (const auto& pair : pairs) {
        for (int side = 0; side < 2; ++side) {
          const std::string& mine = side == 0 ? pair.room_a : pair.room_b;
          const std::string& theirs = side == 0 ? pair.room_b : pair.room_a;
          if (mine != name || !out.placed.count(theirs)) continue;
          const std::string& my_pt = side == 0 ? pair.point_a : pair.point_b;
          const std::string& their_pt = side == 0 ? pair.point_b : pair.point_a;
          const Point* a = point_in(kv.second, my_pt);
          const auto their_room = rooms.find(theirs);
          if (!a || their_room == rooms.end()) continue;
          const Point* b = point_in(their_room->second, their_pt);
          if (!b) continue;
          src.push_back({a->x, a->y, a->z});
          dst.push_back(out.placed.at(theirs).apply(b->x, b->y, b->z));
          via = via.empty() || via == theirs ? theirs : "several rooms";
          break;
        }
      }
      if (src.empty()) continue;

      Placement place = fit(src, dst);
      place.via = via;
      // The best-fitting room goes down first: placing a shaky one early makes
      // every room measured against it shaky too.
      if (!found || place.pairs > best.pairs ||
          (place.pairs == best.pairs && place.residual < best.residual)) {
        best_name = name;
        best = place;
        found = true;
      }
    }
    if (!found) break;
    out.placed[best_name] = best;
  }

  for (const auto& kv : rooms)
    if (!out.placed.count(kv.first)) out.unplaced.push_back(kv.first);
  std::sort(out.unplaced.begin(), out.unplaced.end());
  return out;
}

std::vector<MergePair> endpoints_for_lines(
    const Room& room_a, const std::pair<std::string, std::string>& line_a,
    const Room& room_b, const std::pair<std::string, std::string>& line_b,
    const Placement* place_a, const Placement* place_b) {
  const Point* a0 = point_in(room_a, line_a.first);
  const Point* a1 = point_in(room_a, line_a.second);
  const Point* b0 = point_in(room_b, line_b.first);
  const Point* b1 = point_in(room_b, line_b.second);
  if (!a0 || !a1 || !b0 || !b1) return {};

  const Placement identity;
  const Placement& A = place_a ? *place_a : identity;
  const Placement& B = place_b ? *place_b : identity;

  double straight, crossed;
  if (place_a && place_b) {
    // Already placed: the ends nearer each other are the ones that correspond.
    straight = dist3(A.apply(a0->x, a0->y, a0->z), B.apply(b0->x, b0->y, b0->z)) +
               dist3(A.apply(a1->x, a1->y, a1->z), B.apply(b1->x, b1->y, b1->z));
    crossed = dist3(A.apply(a0->x, a0->y, a0->z), B.apply(b1->x, b1->y, b1->z)) +
              dist3(A.apply(a1->x, a1->y, a1->z), B.apply(b0->x, b0->y, b0->z));
  } else {
    // No placement yet: agree on direction rather than on distance.
    const double dot = (a1->x - a0->x) * (b1->x - b0->x) +
                       (a1->y - a0->y) * (b1->y - b0->y);
    straight = dot >= 0 ? 0.0 : 1.0;
    crossed = dot >= 0 ? 1.0 : 0.0;
  }

  const std::string& first = straight <= crossed ? line_b.first : line_b.second;
  const std::string& second = straight <= crossed ? line_b.second : line_b.first;
  return {MergePair{room_a.name, line_a.first, room_b.name, first},
          MergePair{room_a.name, line_a.second, room_b.name, second}};
}

MergedBody build_merged(const std::map<std::string, Room>& rooms,
                        const std::map<std::string, Placement>& placed,
                        const BuildSettings& cfg, bool fuse) {
  MergedBody out;
  std::vector<TopoDS_Shape> bodies;

  for (const auto& kv : placed) {
    const auto it = rooms.find(kv.first);
    if (it == rooms.end()) continue;
    Room room = it->second;
    TopoDS_Shape shape;
    try {
      shape = build_room(room, cfg);
    } catch (const std::exception& e) {
      out.failed.push_back(kv.first + ": " + e.what());
      continue;
    }
    gp_Trsf turn;
    turn.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)),
                     kv.second.rotation_deg * kDegToRad);
    gp_Trsf shift;
    shift.SetTranslation(gp_Vec(kv.second.dx * kCmToMm, kv.second.dy * kCmToMm,
                                kv.second.dz * kCmToMm));
    bodies.push_back(
        BRepBuilderAPI_Transform(shape, shift.Multiplied(turn), true).Shape());
  }

  if (bodies.empty())
    throw BuildError("Nothing is placed yet, so there is nothing to merge.");

  // Fused where the kernel will have it, which is the honest answer for a
  // stairwell: the flights share their walls, and one body is what the building
  // is. Where a fuse fails the rooms are handed back side by side in one file
  // rather than not at all, and the caller is told which happened.
  if (fuse && bodies.size() > 1) {
    TopoDS_Shape whole = bodies.front();
    bool ok = true;
    for (size_t i = 1; i < bodies.size() && ok; ++i) {
      BRepAlgoAPI_Fuse run(whole, bodies[i]);
      run.Build();
      if (!run.IsDone()) ok = false;
      else whole = run.Shape();
    }
    if (ok) {
      out.shape = whole;
      out.how = "fused";
      return out;
    }
  }

  BRep_Builder builder;
  TopoDS_Compound compound;
  builder.MakeCompound(compound);
  for (const auto& b : bodies) builder.Add(compound, b);
  out.shape = compound;
  out.how = "side by side";
  return out;
}

}  // namespace snapir
