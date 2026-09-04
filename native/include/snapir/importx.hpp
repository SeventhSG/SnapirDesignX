// The way back: a sketch edited in Geomagic Design X, read into the room.
//
// The room goes out as exact curves; if the corner of a wall was in the wrong
// place, that is where it gets fixed, with the tools that are good at it. What
// comes back is the same drawing with something changed - a corner moved, a
// wall added, a point put in - and the room has to become that drawing without
// losing what the survey knows.
//
// So an imported point that lands on a surveyed one keeps that point's name.
// That is the whole trick: identity survives the trip, the operator's earlier
// decisions still find the points they were made about, and only what actually
// moved actually moves.
#pragma once
#include <array>
#include <string>
#include <utility>
#include <vector>

#include "snapir/model.hpp"

namespace snapir {

// Two shots this close are the same corner. The survey is exact and so is the
// file, so this only has to swallow the millimetre rounding in between.
inline constexpr double kImportMatch = 2.0;   // cm
inline constexpr double kImportWeld = 0.2;    // cm; two ends this close are one
// Below this a run is a marker, not a wall: the cross drawn through a single
// shot on the way out has arms of exactly this order.
inline constexpr double kImportMinRun = 12.0; // cm

struct Sketch {
  std::vector<std::array<double, 3>> points;   // survey centimetres
  std::vector<std::pair<int, int>> lines;      // indices into points
};

// Points and lines out of an IGES or STEP file, in survey centimetres.
//
// A curve that is not a straight line arrives as its two ends. Design X writes
// sketch lines as lines, so that costs nothing in practice, and guessing at a
// spline would put corners where the drawing has none.
Sketch read_sketch(const std::string& path);

// The loop that is the floor of the room, as indices into the sketch's points.
//
// A room exported for editing carries at least two rings of the same plan
// shape, the floor and the ceiling above it, plus a rectangle for every
// opening. The floor is the big one down at the bottom.
std::vector<int> outline_loop(const Sketch& sketch);

// One imported point, named.
struct ImportedPoint {
  std::string name;
  double x = 0, y = 0, z = 0;
  std::string role;    // "floor" on the ring, "unknown" everywhere else
  std::string from;
};

struct ImportedSketch {
  std::vector<ImportedPoint> points;                    // the new ones only
  std::vector<std::pair<std::string, std::string>> segments;
  std::vector<std::string> outline;
  std::string file;
  int matched = 0;     // how many landed on a shot the survey already had
};

// Read the edited file and say what the room becomes.
ImportedSketch sketch_for(const Room& room, const std::string& path);

}  // namespace snapir
