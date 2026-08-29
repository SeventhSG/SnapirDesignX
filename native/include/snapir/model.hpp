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
};

// One vertical edge of an opening: a cluster of points sharing an XY.
struct Jamb {
  double x = 0, y = 0;
  double z_bottom = 0, z_top = 0;
  std::vector<Point> points;
};

// A door or window, defined by two jambs on the same wall.
struct Opening {
  Jamb left, right;
  std::string kind = "unknown";  // "door" | "window", inferred or set by the user

  double sill() const { return std::min(left.z_bottom, right.z_bottom); }
  double head() const { return std::max(left.z_top, right.z_top); }
  double width() const {
    const double dx = left.x - right.x, dy = left.y - right.y;
    return std::sqrt(dx * dx + dy * dy);
  }
  const std::string& infer_kind(double door_sill_max = 20.0) {
    kind = sill() <= door_sill_max ? "door" : "window";
    return kind;
  }
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
  std::vector<Point> controls;
  std::optional<Point> station;
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
