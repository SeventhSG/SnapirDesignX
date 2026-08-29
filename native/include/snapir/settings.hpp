// Job settings. Everything the survey cannot tell us lives here.
//
// Every length here is in millimetres, the same unit the STEP files are
// written in. The survey itself arrives in centimetres; the conversion happens
// once, where the geometry is built.
#pragma once
#include <string>

namespace snapir {

struct BuildSettings {
  // Shell dimensions, millimetres. The surveyed surface is always the INNER
  // face, so every offset grows outward and never disturbs the measurement.
  double wall_thickness = 200.0;
  double floor_thickness = 200.0;
  double ceiling_thickness = 200.0;

  // Ceiling handling
  bool fit_ceiling_plane = true;      // false levels it at the mean height
  double max_ceiling_tilt_deg = 3.0;  // degrees
  double sockets_merge_gap = 5.0;     // mm; closer than this, sockets join

  // Openings
  bool cut_openings = true;
  bool confirm_openings_per_room = true;
  double door_sill_max = 80.0;  // sill at or under this reads as a door

  // Fixtures. Single surveyed points on the Kontak and Su tesisat layers are
  // real building services, so they become real geometry. Every fixture is
  // anchored to the wall it belongs to, never left floating.
  bool include_fixtures = true;

  // "box" adds a back box standing proud of the wall.
  // "hole" cuts a recess into the wall instead.
  std::string socket_mode = "box";
  double socket_width = 80.0;   // mm, along the wall
  double socket_height = 80.0;  // mm
  double socket_proud = 12.0;   // mm the box stands out from the inner face
  double socket_embed = 50.0;   // mm the box reaches into the wall
  double socket_recess = 50.0;  // mm deep when the mode is "hole"

  // "stub" adds a pipe coming out of the wall, reaching the surveyed point.
  // "hole" cuts a sleeve through the wall instead.
  std::string pipe_mode = "stub";
  double pipe_diameter = 25.0;   // mm
  double pipe_length = 0.0;      // 0 means reach the surveyed point
  double pipe_min_length = 40.0; // mm, floor for a point shot on the wall
  double pipe_embed = 50.0;      // mm the stub reaches into the wall

  // Export. Exact B-rep only: "step", "iges" or "brep". A mesh format would
  // trade the surveyed corner for a triangle and a tolerance, so none is
  // offered.
  std::string units = "mm";  // every length above, and every file written
  std::string export_format = "step";
  std::string step_schema = "AP214";  // AP203 | AP214 | AP242
  std::string output_dir = "out";
};

}  // namespace snapir
