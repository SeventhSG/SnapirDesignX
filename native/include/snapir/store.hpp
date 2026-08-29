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

struct ProjectRecord {
  std::string id;
  std::string name;
  std::string folder;
  std::string created_at;
  std::string opened_at;
  double thickness = 200.0;  // mm
  std::map<std::string, RoomOverride> overrides;

  void touch() { opened_at = now_iso8601(); }
};

class Store {
 public:
  explicit Store(const std::string& path = "");

  void load();
  void save() const;

  ProjectRecord& create(const std::string& name, const std::string& folder);
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

}  // namespace snapir
