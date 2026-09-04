// Data model. Everything is in centimetres, matching the Leica iCON export.
// Conversion to millimetres happens only at STEP export time.
#pragma once
#include <cmath>
#include <optional>
#include <string>
#include <vector>

namespace snapir {

enum class Role {
  Floor,     // room outline corner, on the slab
  Ceiling,   // ceiling height shot above a floor corner
  Opening,   // door / window jamb, sill or head
  Socket,    // Kontak
  Plumbing,  // Su tesisat
  Control,   // VTARGET ArUco reference marker
  Station,   // instrument position
  Stairs,    // one shot of a climbed flight
  Pervaz,    // the wall shot of a skirting pair
  Depth,     // the middle shot giving a wall fitting its depth
  Unknown,   // needs a human decision
};

const char* to_string(Role r);
Role role_from_string(const std::string& s);

struct Point {
  std::string name;
  double x = 0, y = 0, z = 0;
  std::string layer;
  Role role = Role::Unknown;
  int index = 0;  // shot order, parsed from P_nnn
  // Constructed by the operator - a line run out to where it should reach, or
  // the crossing of two runs - rather than measured by the instrument. Never
  // written back to the survey, and never silently mistaken for a shot.
  bool derived = false;
  std::string source;  // how it was constructed, for the provenance list
  // The operator said what this point is. Inference must leave it alone -
  // otherwise the next rebuild quietly re-derives the very thing they just
  // corrected, and their decision looks like it never took.
  bool pinned = false;
};

// One vertical edge of an opening: a cluster of points sharing an XY.
struct Jamb {
  double x = 0, y = 0;
  double z_bottom = 0, z_top = 0;
  std::vector<Point> points;
};

// What a rectangle surveyed on a wall turns out to be.
//
// The survey cannot tell these apart: a boiler, a window and a switch panel
// are all four corners on a wall. Only the operator knows, so the classifier
// guesses a door or a window from the sill height and the rest are theirs to
// set. Doors and windows are cut through the wall; the others are fittings
// that hang on it and stand out into the room.
bool kind_cuts(const std::string& kind);
// A niche is neither hole nor fitting: the wall is cut back to the depth
// that was measured and no further, so the wall behind it survives.
bool kind_recesses(const std::string& kind);
const std::vector<std::string>& opening_kinds();
std::string kind_label(const std::string& kind);

// A rectangle on a wall: two jambs, a sill and a head.
//
// Doors and windows are holes. A boiler, a socket panel or a wall lamp is the
// same rectangle in the survey and a solid standing in the room, so what gets
// built is decided by `kind`, not by the shape.
struct Opening {
  Jamb left, right;
  std::string kind = "unknown";  // one of opening_kinds(), inferred or set by the user
  // Shots in the middle of the rectangle, off the wall: how far the thing
  // actually reaches. Measured, so they beat any setting. A rectangle can carry
  // one on each side - a thing let into the wall and standing out of it at the
  // same time - so they are kept apart rather than as one signed number. Unset
  // on a side means no shot there, and then the settings' depth is used.
  std::optional<double> out_depth;  // cm it stands into the room
  std::optional<double> in_depth;   // cm it is let back into the wall
  std::vector<std::string> depth_points;

  // True when the surveyor measured either side of this rectangle.
  bool measured() const { return out_depth.has_value() || in_depth.has_value(); }

  double sill() const { return std::min(left.z_bottom, right.z_bottom); }
  double head() const { return std::max(left.z_top, right.z_top); }
  double height() const { return head() - sill(); }
  // True when this rectangle is a hole rather than a fitting.
  bool cuts() const { return kind_cuts(kind); }
  // True when the wall is cut back to the depth, but not through.
  bool recesses() const { return kind_recesses(kind); }
  double width() const {
    const double dx = left.x - right.x, dy = left.y - right.y;
    return std::sqrt(dx * dx + dy * dy);
  }
  const std::string& infer_kind(double door_sill_max = 20.0) {
    kind = sill() <= door_sill_max ? "door" : "window";
    return kind;
  }
};

// A flight climbed in survey order.
//
// Nothing pairs left and right edges here the way a jamb does - the surveyor
// walks up shooting one line, so a flight is just that line, in order. It is
// traced either at the nosings, one shot per step, or as the zigzag where the
// steps meet the wall, corner by corner. Two shots make up one step in the
// second case, so the step count cannot be read off the point count.
struct Stair {
  std::vector<Point> points;
  std::string kind = "nosings";  // "nosings" | "zigzag"
  int steps = 0;                 // risers climbed

  double rise() const {
    return points.size() >= 2
               ? std::fabs(points.back().z - points.front().z)
               : 0.0;
  }
  double going() const {
    double total = 0.0;
    for (size_t i = 0; i + 1 < points.size(); ++i) {
      const double dx = points[i + 1].x - points[i].x;
      const double dy = points[i + 1].y - points[i].y;
      total += std::sqrt(dx * dx + dy * dy);
    }
    return total;
  }
};

// Skirting, shot as a pair at one corner.
//
// The surveyor puts one shot on the wall just above the board and one at floor
// level on its outer face. The diagonal between them is the whole measurement:
// the rise is the board's height, the plan offset is how far it stands proud of
// the wall behind it. The floor-level shot keeps the corner, since that is the
// one that measured the floor. Neither shot is moved.
struct Pervaz {
  Point corner;   // the floor-level shot: this is the outline corner
  Point wall;     // the shot on the wall above the board
  double height = 0;  // cm
  double depth = 0;   // cm the board stands proud of the wall
};

// Something the app cannot decide on its own.
struct Issue {
  std::string severity;  // "error" | "warning" | "info"
  std::string code;
  std::string message;
  std::vector<std::string> points;
};

struct Room {
  std::string name;
  std::string source;  // path of the .csv it came from
  std::vector<Point> points;
  std::vector<Point> outline;  // floor polygon, shot order
  std::vector<Point> ceiling;
  std::vector<Opening> openings;
  std::vector<Stair> stairs;
  std::vector<Pervaz> pervaz;
  std::vector<Point> controls;
  // A room can be surveyed from several setups, each with its own panorama.
  // Distinct positions only: the instrument is written out again every time it
  // is re-levelled without being moved.
  std::vector<Point> stations;
  std::vector<Issue> issues;

  // Set by the user or by app settings, not present in the survey data.
  // "drawn" when the surveyor's own lines describe the ring, which is the
  // only source that needs no guessing at all.
  std::string outline_source = "inferred";  // "drawn" | "surveyed layer" | "inferred"
  std::vector<std::pair<std::string, std::string>> segments;
  std::vector<std::pair<std::string, std::string>> links;
  std::optional<double> floor_z;
  std::optional<double> ceiling_z;
  std::optional<double> wall_thickness;
  std::optional<double> ceiling_height_override;

  std::string flat() const;   // "Daire 53 - Salon" -> "Daire 53"
  std::string label() const;
  std::vector<Point> unresolved() const;
  bool has_errors() const;
  std::optional<double> ceiling_height() const;
};

struct Project {
  std::string name = "Untitled";
  std::vector<Room> rooms;
};

}  // namespace snapir
