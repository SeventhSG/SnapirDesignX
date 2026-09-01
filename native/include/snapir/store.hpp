// Project store. Survey folders in, room overrides remembered.
//
// A project is a survey folder plus whatever the operator has told us that the
// survey could not: a corrected outline order, a ceiling height nobody shot, a
// thickness for one particular wall. The CSVs are never modified.
//
// The file format is the one the Python build wrote, read and written
// unchanged, so an existing projects.json keeps working across the swap.
#pragma once
#include <map>
#include <optional>
#include <string>
#include <vector>

#include "../../third_party/json.hpp"

namespace snapir {

using Json = nlohmann::json;

std::string app_dir();
std::string now_iso8601();
std::string new_id();  // 12 random hex characters, the same shape as a project id

// Operator decisions for one room. Absent means nothing was overridden.
struct RoomOverride {
  std::optional<std::vector<std::string>> outline_order;  // point names, ring order
  std::vector<std::string> dropped_points;
  std::optional<double> ceiling_height;   // cm above the floor plane
  std::optional<double> wall_thickness;   // whole-room override
  std::map<std::string, double> face_thickness;  // edge -> cm
  std::vector<int> disabled_openings;
  std::map<std::string, Json> fixture_overrides;
  std::map<std::string, std::string> role_overrides;  // point -> role
  std::vector<std::vector<std::string>> added_segments;
  std::vector<std::vector<std::string>> removed_segments;
  std::vector<Json> added_openings;
  std::optional<std::string> built_at;
  std::optional<std::string> step_path;
};

// One door hooked to another, so a walkthrough can cross from the room on
// one side to the room on the other. Each room keeps its own independent
// survey coordinates always - there is no shared building frame - so this
// carries a small rigid transform of its own: where room_b sits, and how it
// is turned, if its coordinates were dropped into room_a's local frame.
// Computed once (aligning the two openings) and adjustable afterward.
struct Connection {
  std::string id;
  std::string room_a;
  int opening_a = -1;
  std::string room_b;
  int opening_b = -1;
  double dx = 0, dy = 0;        // cm, room_b's origin in room_a's frame
  double rotation_deg = 0;      // room_b's turn about its origin
  bool enabled = true;
};

struct ProjectRecord {
  std::string id;
  std::string name;
  std::string folder;
  std::string created_at;
  std::string opened_at;
  double thickness = 200.0;  // mm
  std::map<std::string, RoomOverride> overrides;
  std::vector<Connection> connections;

  void touch() { opened_at = now_iso8601(); }
};

class Store {
 public:
  explicit Store(const std::string& path = "");

  void load();
  void save() const;

  ProjectRecord& create(const std::string& name, const std::string& folder);
  // Inserts an already-built record (an imported .sdxp), assigning a fresh id
  // so it never collides with the one it was exported from.
  ProjectRecord& adopt(ProjectRecord rec);
  ProjectRecord& get(const std::string& pid);              // throws std::out_of_range
  const ProjectRecord* find(const std::string& pid) const;
  void remove(const std::string& pid);
  RoomOverride& override_for(const std::string& pid, const std::string& room);
  const RoomOverride* override_if_any(const std::string& pid,
                                      const std::string& room) const;
  std::vector<const ProjectRecord*> recent() const;

 private:
  std::string path_;
  std::map<std::string, ProjectRecord> projects_;
};

Json to_json(const RoomOverride& ov);
RoomOverride override_from_json(const Json& j);

Json to_json(const Connection& c);
Connection connection_from_json(const Json& j);

}  // namespace snapir
