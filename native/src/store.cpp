#include "snapir/store.hpp"

#include <algorithm>
#include <cctype>
#include <chrono>
#include <cstdlib>
#include <ctime>
#include <filesystem>
#include <fstream>
#include <random>
#include <sstream>
#include <stdexcept>

#include "snapir/csv.hpp"

namespace fs = std::filesystem;

namespace snapir {
namespace {

std::string env_or(const char* key, const std::string& fallback) {
#ifdef _WIN32
  char* buf = nullptr;
  size_t len = 0;
  if (_dupenv_s(&buf, &len, key) == 0 && buf) {
    const std::string v(buf);
    std::free(buf);
    if (!v.empty()) return v;
  }
#else
  if (const char* v = std::getenv(key)) {
    if (*v) return v;
  }
#endif
  return fallback;
}

// Optional fields are written as JSON null, the way Python's asdict did, so a
// file written by either build reads back the same in both.
template <typename T>
void put_opt(Json& j, const char* key, const std::optional<T>& v) {
  if (v) j[key] = *v;
  else j[key] = nullptr;
}

template <typename T>
std::optional<T> get_opt(const Json& j, const char* key) {
  if (!j.contains(key) || j.at(key).is_null()) return std::nullopt;
  return j.at(key).get<T>();
}

template <typename T>
T get_or(const Json& j, const char* key, T fallback) {
  if (!j.contains(key) || j.at(key).is_null()) return fallback;
  return j.at(key).get<T>();
}

}  // namespace

std::string app_dir() {
  std::string base = env_or("APPDATA", "");
  if (base.empty()) base = env_or("HOME", ".") + "/.config";
  const fs::path d = fs::u8path(base) / "SnapirDesignX";
  fs::create_directories(d);
  return d.u8string();
}

std::string new_id() {
  static std::mt19937_64 rng{std::random_device{}()};
  std::ostringstream id;
  for (int i = 0; i < 12; ++i) id << "0123456789abcdef"[rng() & 0xF];
  return id.str();
}

std::string now_iso8601() {
  const auto now = std::chrono::system_clock::now();
  const std::time_t t = std::chrono::system_clock::to_time_t(now);
  std::tm tm{};
#ifdef _WIN32
  gmtime_s(&tm, &t);
#else
  gmtime_r(&t, &tm);
#endif
  char buf[32];
  std::strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%S", &tm);
  return std::string(buf) + "+00:00";
}

Json to_json(const RoomOverride& ov) {
  Json j = Json::object();
  if (ov.outline_order) j["outline_order"] = *ov.outline_order;
  else j["outline_order"] = nullptr;
  j["dropped_points"] = ov.dropped_points;
  put_opt(j, "ceiling_height", ov.ceiling_height);
  put_opt(j, "wall_thickness", ov.wall_thickness);
  j["face_thickness"] = ov.face_thickness;
  j["disabled_openings"] = ov.disabled_openings;
  j["opening_kind_overrides"] = ov.opening_kind_overrides;
  j["opening_shape_overrides"] = ov.opening_shape_overrides;
  j["fixture_overrides"] = ov.fixture_overrides;
  j["role_overrides"] = ov.role_overrides;
  j["added_segments"] = ov.added_segments;
  j["removed_segments"] = ov.removed_segments;
  j["added_openings"] = ov.added_openings;
  j["derived_points"] = ov.derived_points;
  j["moved_points"] = ov.moved_points;
  if (ov.imported_sketch) j["imported_sketch"] = *ov.imported_sketch;
  else j["imported_sketch"] = nullptr;
  j["removed_walls"] = ov.removed_walls;
  put_opt(j, "built_at", ov.built_at);
  put_opt(j, "step_path", ov.step_path);
  return j;
}

RoomOverride override_from_json(const Json& j) {
  RoomOverride ov;
  ov.outline_order = get_opt<std::vector<std::string>>(j, "outline_order");
  ov.dropped_points = get_or(j, "dropped_points", std::vector<std::string>{});
  ov.ceiling_height = get_opt<double>(j, "ceiling_height");
  ov.wall_thickness = get_opt<double>(j, "wall_thickness");
  ov.face_thickness = get_or(j, "face_thickness", std::map<std::string, double>{});
  ov.disabled_openings = get_or(j, "disabled_openings", std::vector<int>{});
  ov.opening_kind_overrides =
      get_or(j, "opening_kind_overrides", std::map<std::string, std::string>{});
  ov.opening_shape_overrides =
      get_or(j, "opening_shape_overrides", std::map<std::string, std::string>{});
  ov.fixture_overrides = get_or(j, "fixture_overrides", std::map<std::string, Json>{});
  ov.role_overrides = get_or(j, "role_overrides", std::map<std::string, std::string>{});
  ov.added_segments =
      get_or(j, "added_segments", std::vector<std::vector<std::string>>{});
  ov.removed_segments =
      get_or(j, "removed_segments", std::vector<std::vector<std::string>>{});
  ov.added_openings = get_or(j, "added_openings", std::vector<Json>{});
  ov.derived_points = get_or(j, "derived_points", std::vector<Json>{});
  ov.moved_points =
      get_or(j, "moved_points", std::map<std::string, std::vector<double>>{});
  ov.imported_sketch = get_opt<Json>(j, "imported_sketch");
  ov.removed_walls = get_or(j, "removed_walls", std::vector<std::string>{});
  ov.built_at = get_opt<std::string>(j, "built_at");
  ov.step_path = get_opt<std::string>(j, "step_path");
  return ov;
}

Json to_json(const Connection& c) {
  Json j = Json::object();
  j["id"] = c.id;
  j["roomA"] = c.room_a;
  j["openingA"] = c.opening_a;
  j["roomB"] = c.room_b;
  j["openingB"] = c.opening_b;
  j["dx"] = c.dx;
  j["dy"] = c.dy;
  j["rotationDeg"] = c.rotation_deg;
  j["enabled"] = c.enabled;
  return j;
}

Connection connection_from_json(const Json& j) {
  Connection c;
  c.id = get_or(j, "id", std::string{});
  c.room_a = get_or(j, "roomA", std::string{});
  c.opening_a = get_or(j, "openingA", -1);
  c.room_b = get_or(j, "roomB", std::string{});
  c.opening_b = get_or(j, "openingB", -1);
  c.dx = get_or(j, "dx", 0.0);
  c.dy = get_or(j, "dy", 0.0);
  c.rotation_deg = get_or(j, "rotationDeg", 0.0);
  c.enabled = get_or(j, "enabled", true);
  return c;
}

Store::Store(const std::string& path) {
  path_ = path.empty() ? (fs::u8path(app_dir()) / "projects.json").u8string() : path;
  load();
}

void Store::load() {
  const fs::path p = fs::u8path(path_);
  if (!fs::exists(p)) return;

  std::ifstream fh(p, std::ios::binary);
  Json raw;
  try {
    fh >> raw;
  } catch (const std::exception&) {
    return;  // a corrupt file is not a reason to refuse to start
  }
  if (!raw.contains("projects")) return;

  for (const auto& item : raw["projects"].items()) {
    const Json& p_json = item.value();
    ProjectRecord rec;
    rec.id = get_or(p_json, "id", item.key());
    rec.name = get_or(p_json, "name", std::string{});
    rec.folder = get_or(p_json, "folder", std::string{});
    rec.created_at = get_or(p_json, "created_at", std::string{});
    rec.opened_at = get_or(p_json, "opened_at", std::string{});
    rec.thickness = get_or(p_json, "thickness", 200.0);
    // Thicknesses used to be stored in centimetres. Anything that small is an
    // old file, not a 2 cm wall.
    if (rec.thickness < 50.0) rec.thickness *= 10.0;

    if (p_json.contains("overrides"))
      for (const auto& ov : p_json["overrides"].items())
        rec.overrides[ov.key()] = override_from_json(ov.value());

    if (p_json.contains("connections"))
      for (const auto& c : p_json["connections"])
        rec.connections.push_back(connection_from_json(c));

    projects_[rec.id] = std::move(rec);
  }
}

void Store::save() const {
  Json payload;
  payload["version"] = 1;
  payload["projects"] = Json::object();
  for (const auto& kv : projects_) {
    const ProjectRecord& p = kv.second;
    Json j;
    j["id"] = p.id;
    j["name"] = p.name;
    j["folder"] = p.folder;
    j["created_at"] = p.created_at;
    j["opened_at"] = p.opened_at;
    j["thickness"] = p.thickness;
    j["overrides"] = Json::object();
    for (const auto& ov : p.overrides) j["overrides"][ov.first] = to_json(ov.second);
    j["connections"] = Json::array();
    for (const auto& c : p.connections) j["connections"].push_back(to_json(c));
    payload["projects"][kv.first] = j;
  }

  const fs::path p = fs::u8path(path_);
  if (p.has_parent_path()) fs::create_directories(p.parent_path());
  std::ofstream fh(p, std::ios::binary);
  const std::string text = payload.dump(2);
  fh.write(text.data(), static_cast<std::streamsize>(text.size()));
}

ProjectRecord& Store::create(const std::string& name, const std::string& folder) {
  const fs::path f = fs::u8path(folder);
  if (!fs::is_directory(f)) throw std::invalid_argument("No such folder: " + folder);

  bool any = false;
  for (const auto& e : fs::directory_iterator(f)) {
    if (!e.is_regular_file() || e.path().extension() != ".csv") continue;
    std::string stem = e.path().stem().u8string();
    for (char& c : stem)
      if (static_cast<unsigned char>(c) < 128) c = static_cast<char>(std::toupper(c));
    if (stem.find("FUKOKU") == std::string::npos) { any = true; break; }
  }
  if (!any) throw std::invalid_argument("No Leica room CSVs found in that folder.");

  ProjectRecord rec;
  rec.id = new_id();
  rec.name = name.empty() ? f.filename().u8string() : name;
  rec.folder = f.u8string();
  rec.created_at = now_iso8601();
  rec.opened_at = rec.created_at;
  const std::string id = rec.id;
  projects_[rec.id] = std::move(rec);
  save();
  return projects_[id];
}

ProjectRecord& Store::adopt(ProjectRecord rec) {
  rec.id = new_id();
  rec.created_at = rec.created_at.empty() ? now_iso8601() : rec.created_at;
  rec.opened_at = now_iso8601();
  const std::string id = rec.id;
  projects_[rec.id] = std::move(rec);
  save();
  return projects_[id];
}

ProjectRecord& Store::get(const std::string& pid) {
  const auto it = projects_.find(pid);
  if (it == projects_.end()) throw std::out_of_range(pid);
  return it->second;
}

const ProjectRecord* Store::find(const std::string& pid) const {
  const auto it = projects_.find(pid);
  return it == projects_.end() ? nullptr : &it->second;
}

void Store::remove(const std::string& pid) {
  projects_.erase(pid);
  save();
}

RoomOverride& Store::override_for(const std::string& pid, const std::string& room) {
  return get(pid).overrides[room];
}

const RoomOverride* Store::override_if_any(const std::string& pid,
                                           const std::string& room) const {
  const ProjectRecord* p = find(pid);
  if (!p) return nullptr;
  const auto it = p->overrides.find(room);
  return it == p->overrides.end() ? nullptr : &it->second;
}

std::vector<const ProjectRecord*> Store::recent() const {
  std::vector<const ProjectRecord*> out;
  for (const auto& kv : projects_) out.push_back(&kv.second);
  std::stable_sort(out.begin(), out.end(),
                   [](const ProjectRecord* a, const ProjectRecord* b) {
                     return a->opened_at > b->opened_at;
                   });
  return out;
}

}  // namespace snapir
