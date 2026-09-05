// Escape hatch: hand a room to Geomagic Design X instead.
//
// Exact wireframe, not a point cloud. Design X reads IGES and STEP curves
// natively, and a curve carries the surveyed corner exactly where the
// instrument put it. Sampling the same lines into points would throw that away
// and then charge you the labour of fitting it back.
//
// ASC points are offered too, for the cases where a cloud really is wanted.
#pragma once
#include <string>
#include "snapir/model.hpp"
#include "snapir/settings.hpp"

namespace snapir {

// Write the room outline, ceiling ring and openings as exact curves.
// fmt is "iges", "step" or "asc".
std::string export_curves(const Room& room, const std::string& out_dir,
                          const std::string& fmt = "iges",
                          const BuildSettings& cfg = BuildSettings());

}  // namespace snapir
