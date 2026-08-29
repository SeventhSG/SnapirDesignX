// Solid construction and STEP export, on Open CASCADE.
//
// Shape of a room body: the surveyed outline is the inner face of the walls.
// An outer ring is offset outward by the wall thickness, floor and ceiling
// planes are pushed out by their own slab thicknesses, and the inner volume is
// subtracted. What is left is walls, floor and ceiling as one closed solid with
// an empty room inside.
//
// Nothing is tessellated at any point. Faces are planes, edges are lines, and
// the body is watertight because the kernel refuses to build it otherwise.
#pragma once
#include <map>
#include <stdexcept>
#include <string>
#include <vector>

#include <TopoDS_Shape.hxx>

#include "snapir/geometry.hpp"
#include "snapir/model.hpp"
#include "snapir/planes.hpp"
#include "snapir/settings.hpp"

namespace snapir {

inline constexpr double kCmToMm = 10.0;

// Settings are millimetres; the survey and this module work in centimetres.
// One conversion, in one place.
inline double cm(double mm) { return mm / 10.0; }

class BuildError : public std::runtime_error {
 public:
  explicit BuildError(const std::string& what) : std::runtime_error(what) {}
};

// One building service, seated on the wall it belongs to.
struct Fixture {
  std::string name;
  std::string kind;  // "socket" | "pipe"
  std::string mode;  // "box" | "hole" | "stub"
  TopoDS_Shape solid;
  Pt seat;
  Pt normal;
  double reach = 0;  // cm the fixture stands out from the inner face
};

struct FixtureOverride {
  std::string mode;
};
using FixtureOverrides = std::map<std::string, FixtureOverride>;

struct SolidStats {
  int solids = 0;
  int shells = 0;
  int faces = 0;
  double volume_m3 = 0;
};

// The floor and ceiling planes this room will be built between.
std::pair<Plane, Plane> room_planes(const Room& room, const BuildSettings& cfg);

// Build one room shell.
TopoDS_Shape build_room(Room& room, const BuildSettings& cfg,
                        const std::vector<Opening>* openings = nullptr,
                        const FixtureOverrides* fixture_overrides = nullptr);

// Face and volume report, used to prove a body is what we think it is.
SolidStats solid_stats(const TopoDS_Shape& shape);

// Write a STEP file in millimetres.
std::string export_step(const TopoDS_Shape& shape, const std::string& path,
                        const std::string& schema = "AP214");

// The two ways a body leaves.
//
// STEP is the one to work from: exact B-rep, planes stay planes and the
// surveyed corner stays where the instrument put it. STL is triangles and is
// only for looking at the room in something that will not open a STEP file.
// Nothing downstream should be measured off the STL.
struct ExportFormat {
  const char* id;      // what the API and the UI call it
  const char* suffix;  // including the dot
};
const std::vector<ExportFormat>& export_formats();

// True if id names a format export_shape can write.
bool is_export_format(const std::string& id);

// The extension a format writes, ".step" for an unknown id.
std::string export_suffix(const std::string& fmt);

// Write one body in millimetres. base_path carries no extension; the one for
// the format is appended, and the written path is returned.
//
// schema applies to STEP only and is ignored by STL.
std::string export_shape(const TopoDS_Shape& shape, const std::string& base_path,
                         const std::string& fmt = "step",
                         const std::string& schema = "AP214");

// Which outline edge a point in the plan belongs to. Takes metres, because that
// is what the viewport reports for a picked face.
int wall_index_at(const Room& room, double x_m, double y_m);

struct WallBody {
  TopoDS_Shape shape;
  double length = 0;
  int solids = 0;
};

// One wall of the room as its own usable solid.
WallBody wall_body(Room& room, const BuildSettings& cfg, int edge,
                   const FixtureOverrides* fixture_overrides = nullptr);

// Every service fixture in the room, each carrying the point it came from.
std::vector<Fixture> fixtures(const Room& room, const std::vector<Pt>& ring,
                              const BuildSettings& cfg,
                              const FixtureOverrides* overrides = nullptr);

// Grow the outline outward, keeping sharp corners.
std::vector<Pt> offset_ring(const std::vector<Pt>& ring, double distance);

}  // namespace snapir
