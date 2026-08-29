// Best-fit planes through surveyed points.
//
// The Design X move: rather than average a set of readings into one number,
// fit a real plane to them and use that plane as the surface. A ceiling that
// runs 269.77 to 273.99 across a room is not noise, it is the building. The
// fitted plane keeps it, exactly, and still gives the kernel a true planar face.
#pragma once
#include <array>
#include <vector>

namespace snapir {

using Pt3 = std::array<double, 3>;

// A plane as a point on it plus a unit normal.
struct Plane {
  double px = 0, py = 0, pz = 0;
  double nx = 0, ny = 0, nz = 1;
  double rms = 0;      // fit residual, cm
  double max_dev = 0;  // worst point, cm

  // Height of the plane above a plan position. Only valid for planes that are
  // not vertical, which every floor and ceiling in this data is.
  double z_at(double x, double y) const;
  double tilt_deg() const;  // angle away from horizontal
};

// Least-squares plane through three or more points. Two points cannot define a
// plane, so a short list falls back to a level plane at the mean height. That
// is the honest answer, not a guess.
Plane fit_plane(const std::vector<Pt3>& pts);
Plane level_plane(double z);

// Fit a plane, but fall back to level if the result is implausible. A ceiling
// tilted more than a few degrees means the shots picked up a bulkhead or a beam
// rather than the ceiling itself.
Plane fit_or_level(const std::vector<Pt3>& pts, double max_tilt_deg = 3.0);

}  // namespace snapir
