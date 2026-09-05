// Putting the rooms of one survey into a single frame.
//
// Every room is measured from wherever the instrument happened to stand, so a
// survey is not one drawing: it is a dozen drawings each in its own coordinate
// system, and nothing in the file says how they sit relative to each other. A
// stairwell shot floor by floor is the case where that matters most - the
// flights are the same staircase, and until the floors are in one frame there
// is no staircase, only four unrelated boxes.
//
// Nothing here guesses. The operator says "this corner in this room is that
// corner in that one", and two of those are enough to fix a room: the rotation
// and the shift that carry one onto the other.
//
// The placement is the same rigid transform a door connection uses - rotate
// about the vertical, then translate - so a room placed here and a room placed
// by a connection land in the same place.
#pragma once
#include <array>
#include <map>
#include <string>
#include <utility>
#include <vector>

#include <TopoDS_Shape.hxx>

#include "snapir/model.hpp"
#include "snapir/settings.hpp"

namespace snapir {

// Where a room's own coordinates sit in the project's frame.
struct Placement {
  double dx = 0, dy = 0, dz = 0;
  double rotation_deg = 0;
  // How far the paired points ended up from each other, RMS, centimetres.
  // Zero for the anchor, which is the frame by definition.
  double residual = 0;
  // How the room got here: the room it was matched against, and on how many
  // pairs. The anchor names nothing.
  std::string via;
  int pairs = 0;

  std::array<double, 3> apply(double x, double y, double z) const;
};

// One point in one room said to be the same place as one in another.
struct MergePair {
  std::string room_a, point_a;
  std::string room_b, point_b;

  // Direction-independent identity, so the same pair is never made twice.
  std::array<std::string, 4> key() const;
};

struct MergeResult {
  std::map<std::string, Placement> placed;
  std::vector<std::string> unplaced;   // sorted
};

// The same placement, given a quarter turn about a point that stays put.
//
// Two matches on a short baseline fix a room's heading out of a few
// centimetres of difference between two readings, and a corner matched to the
// wrong corner fixes it out of nothing at all. Either way the room lands
// attached in the right place and facing the wrong way, and no amount of
// solving will say so, because by its own measure the answer is the best one
// there is. So this is the operator's, not the solver's: it turns about the
// match itself, which is the one place that must not move.
Placement turn_about(const Placement& place, int quarters,
                     double pivot_x, double pivot_y);

// Place every room the pairs can reach, and name the ones they cannot.
MergeResult solve_merge(const std::map<std::string, Room>& rooms,
                        const std::vector<MergePair>& pairs,
                        const std::string& anchor,
                        const std::map<std::string, int>& turns = {});

// Two pairs from two lines said to be the same wall. Which end answers to
// which is worked out here rather than asked for.
std::vector<MergePair> endpoints_for_lines(
    const Room& room_a, const std::pair<std::string, std::string>& line_a,
    const Room& room_b, const std::pair<std::string, std::string>& line_b,
    const Placement* place_a, const Placement* place_b);

struct MergedBody {
  TopoDS_Shape shape;
  std::vector<std::string> failed;
  std::string how;   // "fused" | "side by side"
};

// Every placed room, built and moved into the project frame.
MergedBody build_merged(const std::map<std::string, Room>& rooms,
                        const std::map<std::string, Placement>& placed,
                        const BuildSettings& cfg, bool fuse = true);

}  // namespace snapir
