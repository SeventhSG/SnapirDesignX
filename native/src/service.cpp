// Local API for the desktop frontend.
//
// Runs as a private sidecar process on a loopback port the user never sees.
// Everything heavy (parsing, plane fitting, the kernel) stays on this side.
//
// The routes, the JSON field names and the error shape are the ones the React
// client already speaks, so the frontend is unchanged across the swap.
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <sstream>
#include <thread>

// httplib has to see windows.h before OCCT's headers reach it, or the Win32
// text helpers it uses are not declared yet.
#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <process.h>
#else
#include <unistd.h>
#endif
#include "../third_party/httplib.h"

#include <Message.hxx>
#include <Message_Messenger.hxx>
#include <Message_PrinterOStream.hxx>
#include "snapir/archive.hpp"
#include "snapir/designx.hpp"
#include "snapir/elements.hpp"
#include "snapir/service.hpp"
#include "snapir/geometry.hpp"
#include "snapir/parser.hpp"
#include "snapir/settings.hpp"
#include "snapir/solid.hpp"
#include "snapir/store.hpp"
#include "snapir/tessellate.hpp"

namespace fs = std::filesystem;
using namespace snapir;

namespace {

constexpr const char* kVersion = "1.3.10";

std::mutex g_lock;
Store* g_store = nullptr;
// project id -> room name -> Room, as parsed. Overrides are layered on a copy.
std::map<std::string, std::map<std::string, Room>> g_rooms;

// Python's round() rounds the exact value of the double, not an approximation
// of it. Scaling by a power of ten first would not do that: 207.95 is really
// 207.9499999..., but 207.95 * 10 lands on exactly 2079.5 and then rounds the
// wrong way. Formatting rounds the exact value, which is the same rule, so the
// numbers the UI sees do not shift across the swap.
double round_to(double v, int places) {
  char buf[64];
  std::snprintf(buf, sizeof(buf), "%.*f", places, v);
  return std::strtod(buf, nullptr);
}

void fail(httplib::Response& res, int status, const std::string& detail) {
  Json j;
  j["detail"] = detail;
  res.status = status;
  res.set_content(j.dump(), "application/json");
}

void ok_json(httplib::Response& res, const Json& j) {
  res.set_content(j.dump(), "application/json");
}

std::string ascii_upper(const std::string& v) {
  std::string s = v;
  for (char& c : s) {
    const auto u = static_cast<unsigned char>(c);
    if (u < 128) c = static_cast<char>(std::toupper(u));
  }
  return s;
}

// A project name is free text the operator typed; a filename built from it
// is not, so anything a filesystem would choke on becomes an underscore.
std::string safe_filename(const std::string& name) {
  std::string s = name.empty() ? "project" : name;
  for (char& c : s)
    if (std::strchr("\\/:*?\"<>|", c)) c = '_';
  return s;
}

bool is_room_csv(const fs::path& p) {
  if (p.extension() != ".csv") return false;
  return ascii_upper(p.stem().u8string()).find("FUKOKU") == std::string::npos;
}

// Panoramas sit in "<room name>_Panorama" beside the room CSV, straight off
// the survey camera. The folder is only ever read, never written.
std::vector<fs::path> panorama_files(const std::string& folder,
                                     const std::string& room) {
  std::vector<fs::path> out;
  if (folder.empty()) return out;
  const fs::path root = fs::u8path(folder);
  if (!fs::is_directory(root)) return out;

  fs::path dir = root / fs::u8path(room + "_Panorama");
  if (!fs::is_directory(dir)) {
    // Fall back to a case-insensitive match: the camera and the total station
    // do not always agree on how a room name is capitalised.
    const std::string want = ascii_upper(room + "_Panorama");
    dir.clear();
    for (const auto& e : fs::directory_iterator(root))
      if (e.is_directory() && ascii_upper(e.path().filename().u8string()) == want) {
        dir = e.path();
        break;
      }
    if (dir.empty()) return out;
  }

  for (const auto& e : fs::directory_iterator(dir)) {
    if (!e.is_regular_file()) continue;
    const std::string ext = ascii_upper(e.path().extension().u8string());
    if (ext == ".JPG" || ext == ".JPEG" || ext == ".PNG") out.push_back(e.path());
  }
  std::sort(out.begin(), out.end());
  return out;
}

int count_room_csvs(const std::string& folder) {
  const fs::path f = fs::u8path(folder);
  if (!fs::is_directory(f)) return 0;
  int n = 0;
  for (const auto& e : fs::directory_iterator(f))
    if (e.is_regular_file() && is_room_csv(e.path())) ++n;
  return n;
}

// ------------------------------------------------------------------ settings

fs::path settings_path() { return fs::u8path(app_dir()) / "settings.json"; }

Json settings_to_json(const BuildSettings& c) {
  return Json{{"wall_thickness", c.wall_thickness},
              {"floor_thickness", c.floor_thickness},
              {"ceiling_thickness", c.ceiling_thickness},
              {"fit_ceiling_plane", c.fit_ceiling_plane},
              {"max_ceiling_tilt_deg", c.max_ceiling_tilt_deg},
              {"sockets_merge_gap", c.sockets_merge_gap},
              {"cut_openings", c.cut_openings},
              {"confirm_openings_per_room", c.confirm_openings_per_room},
              {"door_sill_max", c.door_sill_max},
              {"include_fixtures", c.include_fixtures},
              {"include_stairs", c.include_stairs},
              {"stair_width", c.stair_width},
              {"include_fittings", c.include_fittings},
              {"boiler_depth", c.boiler_depth},
              {"lamp_depth", c.lamp_depth},
              {"panel_depth", c.panel_depth},
              {"socket_mode", c.socket_mode},
              {"socket_width", c.socket_width},
              {"socket_height", c.socket_height},
              {"socket_proud", c.socket_proud},
              {"socket_embed", c.socket_embed},
              {"socket_recess", c.socket_recess},
              {"pipe_mode", c.pipe_mode},
              {"pipe_diameter", c.pipe_diameter},
              {"pipe_length", c.pipe_length},
              {"pipe_min_length", c.pipe_min_length},
              {"pipe_embed", c.pipe_embed},
              {"units", c.units},
              {"export_format", c.export_format},
              {"step_schema", c.step_schema},
              {"output_dir", c.output_dir}};
}

void apply_settings_json(BuildSettings& c, const Json& j) {
  const auto num = [&j](const char* k, double& dst) {
    if (j.contains(k) && j.at(k).is_number()) dst = j.at(k).get<double>();
  };
  const auto flag = [&j](const char* k, bool& dst) {
    if (j.contains(k) && j.at(k).is_boolean()) dst = j.at(k).get<bool>();
  };
  const auto str = [&j](const char* k, std::string& dst) {
    if (j.contains(k) && j.at(k).is_string()) dst = j.at(k).get<std::string>();
  };
  num("wall_thickness", c.wall_thickness);
  num("floor_thickness", c.floor_thickness);
  num("ceiling_thickness", c.ceiling_thickness);
  flag("fit_ceiling_plane", c.fit_ceiling_plane);
  num("max_ceiling_tilt_deg", c.max_ceiling_tilt_deg);
  num("sockets_merge_gap", c.sockets_merge_gap);
  flag("cut_openings", c.cut_openings);
  flag("confirm_openings_per_room", c.confirm_openings_per_room);
  num("door_sill_max", c.door_sill_max);
  flag("include_fixtures", c.include_fixtures);
  flag("include_stairs", c.include_stairs);
  num("stair_width", c.stair_width);
  flag("include_fittings", c.include_fittings);
  num("boiler_depth", c.boiler_depth);
  num("lamp_depth", c.lamp_depth);
  num("panel_depth", c.panel_depth);
  str("socket_mode", c.socket_mode);
  num("socket_width", c.socket_width);
  num("socket_height", c.socket_height);
  num("socket_proud", c.socket_proud);
  num("socket_embed", c.socket_embed);
  num("socket_recess", c.socket_recess);
  str("pipe_mode", c.pipe_mode);
  num("pipe_diameter", c.pipe_diameter);
  num("pipe_length", c.pipe_length);
  num("pipe_min_length", c.pipe_min_length);
  num("pipe_embed", c.pipe_embed);
  str("units", c.units);
  str("export_format", c.export_format);
  str("step_schema", c.step_schema);
  str("output_dir", c.output_dir);
}

void write_settings(const BuildSettings& c) {
  const fs::path p = settings_path();
  fs::create_directories(p.parent_path());
  std::ofstream fh(p, std::ios::binary);
  const std::string text = settings_to_json(c).dump(2);
  fh.write(text.data(), static_cast<std::streamsize>(text.size()));
}

BuildSettings global_settings() {
  BuildSettings cfg;
  std::ifstream fh(settings_path(), std::ios::binary);
  if (fh) {
    try {
      Json j;
      fh >> j;
      apply_settings_json(cfg, j);
    } catch (const std::exception&) {
      return BuildSettings();
    }
  }
  // Settings written before the move to millimetres held centimetres.
  if (cfg.wall_thickness < 50.0) {
    for (double* f : {&cfg.wall_thickness, &cfg.floor_thickness, &cfg.ceiling_thickness,
                      &cfg.socket_width, &cfg.socket_height, &cfg.socket_proud,
                      &cfg.socket_embed, &cfg.socket_recess, &cfg.pipe_diameter,
                      &cfg.pipe_length, &cfg.pipe_min_length, &cfg.pipe_embed})
      *f *= 10.0;
    write_settings(cfg);
  }
  return cfg;
}

// Global settings, with the project's own thickness layered on top.
BuildSettings settings_for(const std::string& pid) {
  BuildSettings cfg = global_settings();
  const double t = g_store->get(pid).thickness;
  cfg.wall_thickness = cfg.floor_thickness = cfg.ceiling_thickness = t;
  return cfg;
}

// ------------------------------------------------------------------- rooms

std::map<std::string, Room>& load_rooms(const std::string& pid) {
  const auto it = g_rooms.find(pid);
  if (it != g_rooms.end()) return it->second;
  const ProjectRecord& proj = g_store->get(pid);
  auto& slot = g_rooms[pid];
  for (auto& r : read_project(proj.folder, proj.name).rooms) slot[r.name] = std::move(r);
  return slot;
}

FixtureOverrides to_fixture_overrides(const RoomOverride* ov) {
  FixtureOverrides out;
  if (!ov) return out;
  for (const auto& kv : ov->fixture_overrides) {
    if (kv.second.is_object() && kv.second.contains("mode") &&
        kv.second.at("mode").is_string())
      out[kv.first] = FixtureOverride{kv.second.at("mode").get<std::string>()};
  }
  return out;
}

// The walls this room is not to build, or nothing at all. Returned by pointer
// so every endpoint builds the same body: a wall removed in the preview has to
// be removed in the export and in the single-wall export too.
const std::vector<std::string>* removed_walls_for(Store& store,
                                                  const std::string& pid,
                                                  const std::string& name) {
  const RoomOverride* ov = store.override_if_any(pid, name);
  if (!ov || ov->removed_walls.empty()) return nullptr;
  return &ov->removed_walls;
}

// Layer the operator's decisions over the parsed survey.
Room apply_overrides(const std::string& pid, const Room& parsed) {
  Room room = parsed;
  const RoomOverride* ov = g_store->override_if_any(pid, room.name);
  if (!ov) return room;

  if (!ov->derived_points.empty()) {
    // Constructed points join the room before anything else is layered on, so a
    // ring, a line or an opening can be built through them. They are flagged,
    // so nothing downstream mistakes one for a measurement, and they are placed
    // by the same outline_order / role_overrides the operator uses for any
    // other point rather than by re-classifying.
    std::set<std::string> have;
    for (const auto& p : room.points) have.insert(p.name);
    for (size_t i = 0; i < ov->derived_points.size(); ++i) {
      const Json& d = ov->derived_points[i];
      if (!d.is_object()) continue;
      const std::string name = d.value("name", std::string());
      if (name.empty() || have.count(name)) continue;
      Point p;
      p.name = name;
      p.x = d.value("x", 0.0);
      p.y = d.value("y", 0.0);
      p.z = d.value("z", room.floor_z ? *room.floor_z : 0.0);
      const std::string role = d.value("role", std::string());
      p.role = role.empty() ? Role::Floor : role_from_string(role);
      p.index = 10000 + static_cast<int>(i);
      p.derived = true;
      p.source = d.value("from", std::string("constructed"));
      room.points.push_back(p);
    }
  }

  if (!ov->dropped_points.empty()) {
    // A deleted point leaves the room entirely, and every line that touched it
    // goes with it. Nothing on disk is changed.
    const std::set<std::string> gone(ov->dropped_points.begin(),
                                     ov->dropped_points.end());
    std::vector<Point> kept;
    for (const auto& p : room.points)
      if (!gone.count(p.name)) kept.push_back(p);
    room.points = std::move(kept);

    std::vector<std::pair<std::string, std::string>> segs;
    for (const auto& s : room.segments)
      if (!gone.count(s.first) && !gone.count(s.second)) segs.push_back(s);
    room.segments = std::move(segs);
    reread_topology(room);
  }

  if (!ov->added_segments.empty() || !ov->removed_segments.empty()) {
    // Operator edits sit on top of the surveyed lines, and the room is re-read
    // from the combined set so the outline follows.
    std::set<std::pair<std::string, std::string>> gone;
    for (const auto& x : ov->removed_segments) {
      if (x.size() < 2) continue;
      gone.insert(std::minmax(x[0], x[1]));
    }
    std::vector<std::pair<std::string, std::string>> segs;
    for (const auto& s : room.segments)
      if (!gone.count(std::minmax(s.first, s.second))) segs.push_back(s);
    for (const auto& x : ov->added_segments)
      if (x.size() >= 2) segs.emplace_back(x[0], x[1]);
    room.segments = std::move(segs);
    reread_topology(room);
  }

  if (!ov->role_overrides.empty()) {
    // A relabelled point changes what the room is, so everything derived from
    // the old reading is worked out again.
    apply_roles(room, ov->role_overrides);
  }

  if (ov->outline_order) {
    // The operator can pull in any surveyed point, not just the ones the
    // classifier called a floor corner. Their ring wins outright.
    std::map<std::string, const Point*> by_name;
    for (const auto& p : room.points) by_name[p.name] = &p;
    room.outline.clear();
    for (const auto& n : *ov->outline_order) {
      const auto it = by_name.find(n);
      if (it != by_name.end()) room.outline.push_back(*it->second);
    }
    std::vector<Issue> keep;
    for (const auto& i : room.issues)
      if (i.code != "self-intersecting" && i.code != "no-outline") keep.push_back(i);
    room.issues = std::move(keep);

    if (room.outline.size() >= 3) {
      std::vector<Pt> ring;
      for (const auto& p : room.outline) ring.push_back({p.x, p.y});
      if (!self_intersections(ring).empty())
        room.issues.push_back({"error", "self-intersecting",
                               "The ring you drew still crosses itself.", {}});
    }
  }

  if (ov->ceiling_height) {
    room.ceiling_height_override = ov->ceiling_height;
    std::vector<Issue> keep;
    for (const auto& i : room.issues)
      if (i.code != "no-ceiling") keep.push_back(i);
    room.issues = std::move(keep);
  }

  if (ov->wall_thickness) room.wall_thickness = ov->wall_thickness;

  if (!ov->opening_kind_overrides.empty()) {
    // Correcting a door read as a window, or a boiler read as either. Matched
    // on the jamb points the opening was built from, so the correction follows
    // the opening rather than its position in the list. Runs before the
    // disabled filter, so both are indexed against the same list.
    const auto& allowed = opening_kinds();
    for (auto& o : room.openings) {
      const auto it = ov->opening_kind_overrides.find(opening_key(o));
      if (it == ov->opening_kind_overrides.end()) continue;
      if (std::find(allowed.begin(), allowed.end(), it->second) != allowed.end())
        o.kind = it->second;
    }
  }

  if (!ov->opening_shape_overrides.empty()) {
    // Round or square is the operator's call: four corners on a wall look the
    // same either way.
    for (auto& o : room.openings) {
      const auto it = ov->opening_shape_overrides.find(opening_key(o));
      if (it == ov->opening_shape_overrides.end()) continue;
      if (it->second == "box" || it->second == "round") o.shape = it->second;
    }
  }

  if (!ov->disabled_openings.empty()) {
    const std::set<int> off(ov->disabled_openings.begin(), ov->disabled_openings.end());
    std::vector<Opening> keep;
    for (size_t i = 0; i < room.openings.size(); ++i)
      if (!off.count(static_cast<int>(i))) keep.push_back(room.openings[i]);
    room.openings = std::move(keep);
  }
  return room;
}

Room room_or_throw(const std::string& pid, const std::string& name) {
  auto& rooms = load_rooms(pid);
  const auto it = rooms.find(name);
  if (it == rooms.end()) throw std::out_of_range("No room named " + name);
  return apply_overrides(pid, it->second);
}

Json room_json(const Room& room, const RoomOverride* ov,
               const std::string& folder) {
  double area = 0.0;
  if (room.outline.size() > 2) {
    std::vector<Pt> ring;
    for (const auto& p : room.outline) ring.push_back({p.x, p.y});
    area = polygon_area(ring) / 10000.0;
  }

  Json j;
  j["name"] = room.name;
  j["flat"] = room.flat();
  j["panoramas"] = static_cast<int>(panorama_files(folder, room.name).size());
  j["label"] = room.label();
  j["outlineSource"] = room.outline_source;
  j["area"] = round_to(area, 3);

  const auto h = room.ceiling_height();
  if (h && *h != 0.0) j["ceilingHeight"] = round_to(*h, 1);
  else j["ceilingHeight"] = nullptr;

  Json names = Json::array();
  for (const auto& p : room.outline) names.push_back(p.name);
  j["outline"] = names;

  if (room.floor_z) j["floorZ"] = *room.floor_z;
  else j["floorZ"] = nullptr;

  // Set only when this room departs from the job thickness.
  if (room.wall_thickness) j["wallThickness"] = *room.wall_thickness;
  else j["wallThickness"] = nullptr;

  // Every line the surveyor drew, plus anything the operator added.
  Json segs = Json::array();
  for (const auto& s : room.segments) segs.push_back(Json::array({s.first, s.second}));
  j["segments"] = segs;

  Json links = Json::array();
  for (const auto& l : room.links) links.push_back(Json::array({l.first, l.second}));
  j["links"] = links;

  Json points = Json::array();
  for (const auto& p : room.points)
    points.push_back(Json{{"name", p.name},
                          {"x", p.x},
                          {"y", p.y},
                          {"z", p.z},
                          {"role", to_string(p.role)},
                          {"layer", p.layer},
                          {"derived", p.derived},
                          {"source", p.source}});
  j["points"] = points;

  // Where the instrument stood. One setup per panorama, so this is also where
  // each panorama was shot from.
  Json stations = Json::array();
  for (const auto& s : room.stations)
    stations.push_back(
        Json{{"name", s.name}, {"x", s.x}, {"y", s.y}, {"z", s.z}});
  j["stations"] = stations;

  Json openings = Json::array();
  for (size_t i = 0; i < room.openings.size(); ++i) {
    const auto& o = room.openings[i];
    openings.push_back(Json{{"index", static_cast<int>(i)},
                            {"kind", o.kind},
                            {"width", round_to(o.width(), 1)},
                            {"sill", round_to(o.sill(), 1)},
                            {"head", round_to(o.head(), 1)},
                            {"left", Json::array({o.left.x, o.left.y})},
                            {"right", Json::array({o.right.x, o.right.y})},
                            // What this rectangle is keyed on, so the
                            // operator's choice of what it really is survives a
                            // rebuild.
                            {"key", opening_key(o)},
                            {"cuts", o.cuts()},
                            // Measured off the middle shots, when there are
                            // any. A rectangle can carry one on each side.
                            {"outDepth",
                             o.out_depth ? Json(round_to(*o.out_depth, 1)) : Json()},
                            {"inDepth",
                             o.in_depth ? Json(round_to(*o.in_depth, 1)) : Json()},
                            {"depthPoints", o.depth_points},
                            {"shape", o.solid_shape()}});
  }
  j["openings"] = openings;

  // Everything a wall rectangle is allowed to be. The survey cannot tell a
  // boiler from a window, so the picker is the answer, not a better guess.
  Json kinds = Json::array();
  for (const auto& k : opening_kinds())
    kinds.push_back(Json{{"kind", k}, {"label", kind_label(k)}});
  j["openingKinds"] = kinds;
  j["shapes"] = shapes();

  Json stairs = Json::array();
  for (const auto& s : room.stairs) {
    std::vector<std::string> names;
    for (const auto& p : s.points) names.push_back(p.name);
    stairs.push_back(Json{{"points", names},
                          {"steps", s.steps},
                          {"rise", round_to(s.rise(), 1)},
                          {"going", round_to(s.going(), 1)}});
  }
  j["stairs"] = stairs;

  // Everything in this room that can be clicked, named by the survey points it
  // was built from. These keys outlive a rebuild; face ids do not, so a
  // remembered decision is keyed on these.
  Json els = Json::array();
  for (const auto& e : elements(room)) {
    Json one{{"kind", e.kind}, {"key", e.key}, {"label", e.label},
             {"points", e.points}};
    if (e.index) one["index"] = *e.index;
    else one["index"] = nullptr;
    els.push_back(one);
  }
  j["elements"] = els;

  // Where two drawn lines cross. The sketch offers each one as a corner the
  // operator can adopt; nothing is created behind their back.
  std::map<std::string, const Point*> by_name;
  for (const auto& p : room.points) by_name[p.name] = &p;
  std::vector<std::pair<Pt, Pt>> segs_xy;
  std::vector<std::pair<std::string, std::string>> seg_names;
  for (const auto& s : room.segments) {
    const auto a = by_name.find(s.first), b = by_name.find(s.second);
    if (a == by_name.end() || b == by_name.end()) continue;
    segs_xy.push_back({{a->second->x, a->second->y}, {b->second->x, b->second->y}});
    seg_names.push_back(s);
  }
  Json cross = Json::array();
  for (const auto& c : crossings(segs_xy))
    cross.push_back(
        Json{{"at", Json::array({round_to(c.at.x, 2), round_to(c.at.y, 2)})},
             {"lines", Json::array({Json::array({seg_names[c.i].first,
                                                 seg_names[c.i].second}),
                                    Json::array({seg_names[c.j].first,
                                                 seg_names[c.j].second})})}});
  j["crossings"] = cross;

  Json issues = Json::array();
  for (const auto& i : room.issues)
    issues.push_back(Json{{"severity", i.severity},
                          {"code", i.code},
                          {"message", i.message},
                          {"points", i.points}});
  j["issues"] = issues;

  const bool built = ov && ov->built_at.has_value();
  j["status"] = room.has_errors() ? "needs-you" : (built ? "built" : "ready");
  if (built) j["builtAt"] = *ov->built_at;
  else j["builtAt"] = nullptr;
  if (ov && ov->step_path) j["stepPath"] = *ov->step_path;
  else j["stepPath"] = nullptr;
  return j;
}

Json mesh_json(const Mesh& mesh) {
  Json faces = Json::array();
  for (const auto& f : mesh.faces)
    faces.push_back(
        Json{{"id", f.id},
             {"kind", f.kind},
             {"area", round_to(f.area_m2, 4)},
             {"normal", Json::array({round_to(f.normal[0], 6), round_to(f.normal[1], 6),
                                     round_to(f.normal[2], 6)})},
             {"centroid",
              Json::array({round_to(f.centroid[0], 4), round_to(f.centroid[1], 4),
                           round_to(f.centroid[2], 4)})},
             {"role", f.role},
             // Which element this face belongs to. `id` is an OCCT ordinal and
             // only means anything for this one build; `element` survives a
             // rebuild, so it is what the UI keys a decision on.
             {"element", f.element},
             {"elementKind", f.element_kind},
             {"label", f.label}});
  return Json{{"positions", mesh.positions},
              {"normals", mesh.normals},
              {"faceIds", mesh.face_ids},
              {"faces", faces},
              {"triangleCount", mesh.triangle_count()}};
}

Json stats_json(const SolidStats& s) {
  return Json{{"solids", s.solids},
              {"shells", s.shells},
              {"faces", s.faces},
              {"volume_m3", round_to(s.volume_m3, 6)}};
}

std::string url_param(const httplib::Request& req, const char* key,
                      const std::string& fallback) {
  return req.has_param(key) ? req.get_param_value(key) : fallback;
}

long long file_size_of(const std::string& path) {
  std::error_code ec;
  const auto n = fs::file_size(fs::u8path(path), ec);
  return ec ? 0 : static_cast<long long>(n);
}

}  // namespace

namespace snapir {

int serve(const std::string& host, int port, const std::string& web_root) {
  // OCCT writes progress banners to stdout. Keep them out of the API.
  Message::DefaultMessenger()->RemovePrinters(STANDARD_TYPE(Message_PrinterOStream));

  Store store;
  g_store = &store;

  httplib::Server svr;
  svr.set_default_headers({{"Access-Control-Allow-Origin", "*"},
                           {"Access-Control-Allow-Methods", "*"},
                           {"Access-Control-Allow-Headers", "*"}});
  svr.Options(".*", [](const httplib::Request&, httplib::Response& res) {
    res.status = 204;
  });

  // Anything a route did not catch itself. Without this the client is handed a
  // bare "Internal Server Error" with the reason thrown away, which on a tablet
  // in a stairwell is the difference between a fixable problem and a dead end.
  svr.set_exception_handler([](const httplib::Request& req, httplib::Response& res,
                               std::exception_ptr ep) {
    std::string what = "unknown error";
    try {
      std::rethrow_exception(ep);
    } catch (const std::exception& e) {
      what = e.what();
    } catch (...) {
      // OCCT and a few other libraries still throw types of their own.
    }
    Json j;
    j["detail"] = req.method + " " + req.path + ": " + what;
    res.status = 500;
    res.set_content(j.dump(), "application/json");
  });

  // -------------------------------------------------------------- lifecycle

  svr.Get("/health", [&](const httplib::Request&, httplib::Response& res) {
    ok_json(res, Json{{"ok", true},
                      {"version", kVersion},
                      {"pid", static_cast<long long>(
#ifdef _WIN32
                                  _getpid()
#else
                                  getpid()
#endif
                                  )}});
  });

  // Stand down so a newer instance can take the port. Only ever called by the
  // desktop app, which asks an orphaned backend to exit before starting its own.
  svr.Post("/shutdown", [&](const httplib::Request&, httplib::Response& res) {
    ok_json(res, Json{{"ok", true}});
    std::thread([] {
      std::this_thread::sleep_for(std::chrono::milliseconds(250));
      std::_Exit(0);
    }).detach();
  });

  // --------------------------------------------------------------- projects

  svr.Get("/projects", [&](const httplib::Request&, httplib::Response& res) {
    std::lock_guard<std::mutex> guard(g_lock);
    Json out = Json::array();
    for (const ProjectRecord* p : store.recent()) {
      const bool exists = fs::is_directory(fs::u8path(p->folder));
      out.push_back(Json{{"id", p->id},
                         {"name", p->name},
                         {"folder", p->folder},
                         {"rooms", exists ? count_room_csvs(p->folder) : 0},
                         {"openedAt", p->opened_at},
                         {"missing", !exists},
                         {"thickness", p->thickness}});
    }
    ok_json(res, out);
  });

  svr.Post("/projects", [&](const httplib::Request& req, httplib::Response& res) {
    std::lock_guard<std::mutex> guard(g_lock);
    try {
      const Json body = Json::parse(req.body);
      const std::string name = body.value("name", "");
      const std::string folder = body.value("folder", "");
      const ProjectRecord& p = store.create(name, folder);
      ok_json(res, Json{{"id", p.id}, {"name", p.name}, {"folder", p.folder}});
    } catch (const std::invalid_argument& e) {
      fail(res, 400, e.what());
    } catch (const std::exception& e) {
      fail(res, 400, e.what());
    }
  });

  svr.Delete(R"(/projects/([^/]+))", [&](const httplib::Request& req,
                                         httplib::Response& res) {
    std::lock_guard<std::mutex> guard(g_lock);
    const std::string pid = req.matches[1];
    store.remove(pid);
    g_rooms.erase(pid);
    ok_json(res, Json{{"ok", true}});
  });

  // A .sdxp already picked and sitting at a local path -- the shell resolves
  // whatever the platform's picker hands back (a save dialog, a document
  // picker) into a plain path before this is ever called, the same way it
  // already does for a survey folder.
  svr.Post("/projects/import-sdxp", [&](const httplib::Request& req,
                                        httplib::Response& res) {
    std::lock_guard<std::mutex> guard(g_lock);
    try {
      const Json body = Json::parse(req.body);
      const std::string src = body.at("path").get<std::string>();
      const std::string survey_dir =
          (fs::u8path(app_dir()) / "imported" / new_id()).u8string();

      const ImportedProject imported = import_sdxp(src, survey_dir);
      ProjectRecord rec;
      rec.name = imported.name;
      rec.folder = survey_dir;
      rec.created_at = imported.created_at;
      rec.thickness = imported.thickness;
      rec.overrides = imported.overrides;
      rec.connections = imported.connections;

      const ProjectRecord& p = store.adopt(std::move(rec));
      ok_json(res, Json{{"id", p.id}, {"name", p.name}, {"folder", p.folder}});
    } catch (const std::exception& e) {
      fail(res, 422, e.what());
    }
  });

  svr.Patch(R"(/projects/([^/]+))", [&](const httplib::Request& req,
                                        httplib::Response& res) {
    std::lock_guard<std::mutex> guard(g_lock);
    try {
      ProjectRecord& p = store.get(req.matches[1]);
      const Json body = Json::parse(req.body);
      if (body.contains("thickness") && body["thickness"].is_number())
        p.thickness = body["thickness"].get<double>();
      if (body.contains("name") && body["name"].is_string() &&
          !body["name"].get<std::string>().empty())
        p.name = body["name"].get<std::string>();
      store.save();
      ok_json(res, Json{{"id", p.id}, {"name", p.name}, {"thickness", p.thickness}});
    } catch (const std::out_of_range&) {
      fail(res, 404, "No such project");
    } catch (const std::exception& e) {
      fail(res, 400, e.what());
    }
  });

  // Writes the .sdxp into this device's app data, same as a STEP export
  // writes into the survey folder. The shell then moves it wherever the
  // operator picked, since only the shell knows how to show that dialog.
  svr.Post(R"(/projects/([^/]+)/export-sdxp)", [&](const httplib::Request& req,
                                                    httplib::Response& res) {
    std::lock_guard<std::mutex> guard(g_lock);
    try {
      const ProjectRecord& p = store.get(req.matches[1]);
      const fs::path out =
          fs::u8path(app_dir()) / "exports" / fs::u8path(safe_filename(p.name) + ".sdxp");
      export_sdxp(p, out.u8string());
      ok_json(res, Json{{"path", out.u8string()},
                        {"bytes", static_cast<long long>(fs::file_size(out))}});
    } catch (const std::out_of_range&) {
      fail(res, 404, "No such project");
    } catch (const std::exception& e) {
      fail(res, 422, e.what());
    }
  });

  svr.Get(R"(/projects/([^/]+)/rooms)", [&](const httplib::Request& req,
                                            httplib::Response& res) {
    std::lock_guard<std::mutex> guard(g_lock);
    const std::string pid = req.matches[1];
    try {
      ProjectRecord& proj = store.get(pid);
      proj.touch();
      store.save();

      Json rooms = Json::array();
      for (const auto& kv : load_rooms(pid))
        rooms.push_back(room_json(apply_overrides(pid, kv.second),
                                  store.override_if_any(pid, kv.first),
                                  proj.folder));

      ok_json(res, Json{{"id", proj.id},
                        {"name", proj.name},
                        {"folder", proj.folder},
                        {"thickness", proj.thickness},
                        {"rooms", rooms}});
    } catch (const std::out_of_range&) {
      fail(res, 404, "No such project");
    } catch (const std::exception& e) {
      fail(res, 422, e.what());
    }
  });

  svr.Get(R"(/projects/([^/]+)/rooms/([^/]+))",
          [&](const httplib::Request& req, httplib::Response& res) {
            std::lock_guard<std::mutex> guard(g_lock);
            const std::string pid = req.matches[1], name = req.matches[2];
            try {
              ok_json(res, room_json(room_or_throw(pid, name),
                                     store.override_if_any(pid, name),
                                     store.get(pid).folder));
            } catch (const std::out_of_range& e) {
              fail(res, 404, e.what());
            } catch (const std::exception& e) {
              fail(res, 422, e.what());
            }
          });

  // One panorama out of the room's folder, by index. The card grid asks for
  // 0; the viewer walks the rest. Bytes are handed over as they sit on disk --
  // there is no image library on this side and none is wanted.
  svr.Get(R"(/projects/([^/]+)/rooms/([^/]+)/panorama/(\d+))",
          [&](const httplib::Request& req, httplib::Response& res) {
            std::lock_guard<std::mutex> guard(g_lock);
            const std::string pid = req.matches[1], name = req.matches[2];
            const size_t index = std::stoul(req.matches[3]);
            try {
              const auto shots = panorama_files(store.get(pid).folder, name);
              if (index >= shots.size()) {
                fail(res, 404, "No panorama " + std::to_string(index) +
                                   " for " + name);
                return;
              }
              std::ifstream in(shots[index], std::ios::binary);
              if (!in) {
                fail(res, 404, "Could not read the panorama");
                return;
              }
              std::string bytes((std::istreambuf_iterator<char>(in)),
                                std::istreambuf_iterator<char>());
              const std::string ext = ascii_upper(shots[index].extension().u8string());
              // The survey folder is read-only to us, so a shot never changes
              // under a client that has already cached it.
              res.set_header("Cache-Control", "public, max-age=31536000, immutable");
              res.set_content(std::move(bytes),
                              ext == ".PNG" ? "image/png" : "image/jpeg");
            } catch (const std::out_of_range&) {
              fail(res, 404, "No such project");
            } catch (const std::exception& e) {
              fail(res, 422, e.what());
            }
          });

  // -------------------------------------------------------------- decisions

  svr.Patch(R"(/projects/([^/]+)/rooms/([^/]+))",
            [&](const httplib::Request& req, httplib::Response& res) {
              std::lock_guard<std::mutex> guard(g_lock);
              const std::string pid = req.matches[1], name = req.matches[2];
              try {
                store.get(pid);  // 404 before we create an override
                RoomOverride& ov = store.override_for(pid, name);
                const Json b = Json::parse(req.body);

                if (b.contains("outlineOrder") && !b["outlineOrder"].is_null())
                  ov.outline_order = b["outlineOrder"].get<std::vector<std::string>>();
                if (b.contains("droppedPoints") && !b["droppedPoints"].is_null())
                  ov.dropped_points = b["droppedPoints"].get<std::vector<std::string>>();
                if (b.contains("ceilingHeight") && !b["ceilingHeight"].is_null())
                  ov.ceiling_height = b["ceilingHeight"].get<double>();
                if (b.contains("wallThickness")) {
                  // An explicit null hands the room back to the job default,
                  // which is a different thing from not mentioning it at all.
                  if (b["wallThickness"].is_null()) ov.wall_thickness.reset();
                  else ov.wall_thickness = b["wallThickness"].get<double>();
                }
                if (b.contains("disabledOpenings") && !b["disabledOpenings"].is_null())
                  ov.disabled_openings = b["disabledOpenings"].get<std::vector<int>>();
                if (b.contains("fixtureOverrides") && !b["fixtureOverrides"].is_null())
                  ov.fixture_overrides =
                      b["fixtureOverrides"].get<std::map<std::string, Json>>();
                if (b.contains("roleOverrides") && !b["roleOverrides"].is_null())
                  for (const auto& kv : b["roleOverrides"].items())
                    ov.role_overrides[kv.key()] = kv.value().get<std::string>();
                if (b.contains("addedSegments") && !b["addedSegments"].is_null())
                  ov.added_segments =
                      b["addedSegments"].get<std::vector<std::vector<std::string>>>();
                if (b.contains("removedSegments") && !b["removedSegments"].is_null())
                  ov.removed_segments =
                      b["removedSegments"].get<std::vector<std::vector<std::string>>>();
                if (b.contains("faceThickness") && !b["faceThickness"].is_null())
                  for (const auto& kv : b["faceThickness"].items())
                    ov.face_thickness[kv.key()] = kv.value().get<double>();
                // Merged, not replaced - the UI sends one rectangle at a time,
                // the same way it sends one role at a time.
                if (b.contains("openingKindOverrides") &&
                    !b["openingKindOverrides"].is_null())
                  for (const auto& kv : b["openingKindOverrides"].items())
                    ov.opening_kind_overrides[kv.key()] = kv.value().get<std::string>();
                if (b.contains("openingShapeOverrides") &&
                    !b["openingShapeOverrides"].is_null())
                  for (const auto& kv : b["openingShapeOverrides"].items())
                    ov.opening_shape_overrides[kv.key()] = kv.value().get<std::string>();
                if (b.contains("removedWalls") && !b["removedWalls"].is_null())
                  ov.removed_walls = b["removedWalls"].get<std::vector<std::string>>();
                if (b.contains("derivedPoints") && !b["derivedPoints"].is_null())
                  ov.derived_points = b["derivedPoints"].get<std::vector<Json>>();

                store.save();
                g_rooms.erase(pid);  // force a clean re-parse
                ok_json(res, room_json(room_or_throw(pid, name),
                                       store.override_if_any(pid, name),
                                       store.get(pid).folder));
              } catch (const std::out_of_range& e) {
                fail(res, 404, e.what());
              } catch (const std::exception& e) {
                fail(res, 422, e.what());
              }
            });

  // ------------------------------------------------------------ connections
  //
  // A door hooked to another door, so a walkthrough can cross from the room
  // on one side to the room on the other. Rooms keep their own independent
  // survey coordinates always; the alignment (dx, dy, rotationDeg) is
  // computed by the caller (the plan view, from the two openings' own
  // geometry) and just persisted here, the same way fixture overrides are.

  svr.Get(R"(/projects/([^/]+)/connections)",
          [&](const httplib::Request& req, httplib::Response& res) {
            std::lock_guard<std::mutex> guard(g_lock);
            try {
              const ProjectRecord& p = store.get(req.matches[1]);
              Json out = Json::array();
              for (const auto& c : p.connections) out.push_back(to_json(c));
              ok_json(res, Json{{"connections", out}});
            } catch (const std::out_of_range&) {
              fail(res, 404, "No such project");
            }
          });

  svr.Post(R"(/projects/([^/]+)/connections)",
           [&](const httplib::Request& req, httplib::Response& res) {
             std::lock_guard<std::mutex> guard(g_lock);
             try {
               ProjectRecord& p = store.get(req.matches[1]);
               const Json b = Json::parse(req.body);

               Connection c;
               c.id = new_id();
               c.room_a = b.at("roomA").get<std::string>();
               c.opening_a = b.at("openingA").get<int>();
               c.room_b = b.at("roomB").get<std::string>();
               c.opening_b = b.at("openingB").get<int>();
               c.dx = b.value("dx", 0.0);
               c.dy = b.value("dy", 0.0);
               c.rotation_deg = b.value("rotationDeg", 0.0);
               c.enabled = b.value("enabled", true);

               p.connections.push_back(c);
               store.save();
               ok_json(res, to_json(c));
             } catch (const std::out_of_range&) {
               fail(res, 404, "No such project");
             } catch (const std::exception& e) {
               fail(res, 422, e.what());
             }
           });

  svr.Patch(R"(/projects/([^/]+)/connections/([^/]+))",
            [&](const httplib::Request& req, httplib::Response& res) {
              std::lock_guard<std::mutex> guard(g_lock);
              const std::string pid = req.matches[1], cid = req.matches[2];
              try {
                ProjectRecord& p = store.get(pid);
                const auto it = std::find_if(p.connections.begin(), p.connections.end(),
                                             [&](const Connection& c) { return c.id == cid; });
                if (it == p.connections.end()) { fail(res, 404, "No such connection"); return; }

                const Json b = Json::parse(req.body);
                if (b.contains("dx")) it->dx = b["dx"].get<double>();
                if (b.contains("dy")) it->dy = b["dy"].get<double>();
                if (b.contains("rotationDeg")) it->rotation_deg = b["rotationDeg"].get<double>();
                if (b.contains("enabled")) it->enabled = b["enabled"].get<bool>();

                store.save();
                ok_json(res, to_json(*it));
              } catch (const std::out_of_range&) {
                fail(res, 404, "No such project");
              } catch (const std::exception& e) {
                fail(res, 422, e.what());
              }
            });

  svr.Delete(R"(/projects/([^/]+)/connections/([^/]+))",
             [&](const httplib::Request& req, httplib::Response& res) {
               std::lock_guard<std::mutex> guard(g_lock);
               const std::string pid = req.matches[1], cid = req.matches[2];
               try {
                 ProjectRecord& p = store.get(pid);
                 auto& v = p.connections;
                 v.erase(std::remove_if(v.begin(), v.end(),
                                        [&](const Connection& c) { return c.id == cid; }),
                        v.end());
                 store.save();
                 ok_json(res, Json{{"ok", true}});
               } catch (const std::out_of_range&) {
                 fail(res, 404, "No such project");
               }
             });

  // --------------------------------------------------------------- settings

  svr.Get("/settings", [&](const httplib::Request&, httplib::Response& res) {
    std::lock_guard<std::mutex> guard(g_lock);
    ok_json(res, settings_to_json(global_settings()));
  });

  svr.Patch("/settings", [&](const httplib::Request& req, httplib::Response& res) {
    std::lock_guard<std::mutex> guard(g_lock);
    try {
      BuildSettings cfg = global_settings();
      apply_settings_json(cfg, Json::parse(req.body));
      write_settings(cfg);
      ok_json(res, settings_to_json(cfg));
    } catch (const std::exception& e) {
      fail(res, 400, e.what());
    }
  });

  // ------------------------------------------------------------------ build

  svr.Post(R"(/projects/([^/]+)/rooms/([^/]+)/build)",
           [&](const httplib::Request& req, httplib::Response& res) {
             std::lock_guard<std::mutex> guard(g_lock);
             const std::string pid = req.matches[1], name = req.matches[2];
             try {
               Room room = room_or_throw(pid, name);
               const BuildSettings cfg = settings_for(pid);
               const FixtureOverrides fx =
                   to_fixture_overrides(store.override_if_any(pid, name));

               const std::vector<std::string>* rm = removed_walls_for(store, pid, name);
               const TopoDS_Shape shape = build_room(room, cfg, nullptr, &fx, rm);
               Mesh mesh = tessellate(shape);
               name_faces(mesh, room, cfg);
               const SolidStats stats = solid_stats(shape);
               const auto planes = room_planes(room, cfg);

               ok_json(res,
                       Json{{"mesh", mesh_json(mesh)},
                            {"stats", stats_json(stats)},
                            {"planes",
                             Json{{"floorTilt", round_to(planes.first.tilt_deg(), 3)},
                                  {"floorRms", round_to(planes.first.rms, 3)},
                                  {"ceilingTilt", round_to(planes.second.tilt_deg(), 3)},
                                  {"ceilingRms", round_to(planes.second.rms, 3)},
                                  {"height",
                                   round_to(planes.second.pz - planes.first.pz, 1)}}}});
             } catch (const std::out_of_range& e) {
               fail(res, 404, e.what());
             } catch (const std::exception& e) {
               fail(res, 422, e.what());
             }
           });

  svr.Post(R"(/projects/([^/]+)/rooms/([^/]+)/export)",
           [&](const httplib::Request& req, httplib::Response& res) {
             std::lock_guard<std::mutex> guard(g_lock);
             const std::string pid = req.matches[1], name = req.matches[2];
             try {
               const ProjectRecord& proj = store.get(pid);
               Room room = room_or_throw(pid, name);
               const BuildSettings cfg = settings_for(pid);
               const std::string fmt = url_param(req, "fmt", cfg.export_format);
               const std::string schema = url_param(req, "schema", cfg.step_schema);
               const fs::path out = fs::u8path(proj.folder) / "Snapir STEP";

               // Same fixture decisions the preview was built with, so the file
               // on disk is the body that was approved on screen.
               const FixtureOverrides fx =
                   to_fixture_overrides(store.override_if_any(pid, name));
               const TopoDS_Shape shape = build_room(
                   room, cfg, nullptr, &fx, removed_walls_for(store, pid, name));
               const std::string path = export_shape(
                   shape, (out / fs::u8path(name)).u8string(), fmt, schema,
                   &room, &cfg, &fx);

               RoomOverride& ov = store.override_for(pid, name);
               ov.step_path = path;
               ov.built_at = now_iso8601();
               store.save();
               ok_json(res, Json{{"path", path},
                                 {"bytes", file_size_of(path)},
                                 {"format", fmt}});
             } catch (const std::out_of_range& e) {
               fail(res, 404, e.what());
             } catch (const std::exception& e) {
               fail(res, 422, e.what());
             }
           });

  // Export the wall under a picked face as its own STEP body.
  svr.Post(R"(/projects/([^/]+)/rooms/([^/]+)/export-wall)",
           [&](const httplib::Request& req, httplib::Response& res) {
             std::lock_guard<std::mutex> guard(g_lock);
             const std::string pid = req.matches[1], name = req.matches[2];
             const int face_id = std::atoi(url_param(req, "faceId", "-1").c_str());
             try {
               const ProjectRecord& proj = store.get(pid);
               Room room = room_or_throw(pid, name);
               const BuildSettings cfg = settings_for(pid);
               const std::string fmt = url_param(req, "fmt", cfg.export_format);
               const std::string schema = url_param(req, "schema", cfg.step_schema);
               const FixtureOverrides fx =
                   to_fixture_overrides(store.override_if_any(pid, name));

               const TopoDS_Shape shape = build_room(
                   room, cfg, nullptr, &fx, removed_walls_for(store, pid, name));
               Mesh mesh = tessellate(shape);
               name_faces(mesh, room, cfg);
               const FaceInfo* face = nullptr;
               for (const auto& f : mesh.faces)
                 if (f.id == face_id) { face = &f; break; }
               if (!face) {
                 fail(res, 404, "No face " + std::to_string(face_id));
                 return;
               }
               if (face->role != "wall") {
                 fail(res, 400, "That face is a floor or ceiling, not a wall.");
                 return;
               }

               const int edge = wall_index_at(room, face->centroid[0], face->centroid[1]);
               const WallBody wb = wall_body(room, cfg, edge, &fx);
               const SolidStats stats = solid_stats(wb.shape);
               const fs::path out =
                   fs::u8path(proj.folder) / "Snapir STEP" / "Walls";
               const std::string path = export_shape(
                   wb.shape,
                   (out / fs::u8path(name + " - wall " + std::to_string(edge + 1)))
                       .u8string(),
                   fmt, schema);

               ok_json(res, Json{{"path", path},
                                 {"bytes", file_size_of(path)},
                                 {"format", fmt},
                                 {"wall", edge + 1},
                                 {"length", round_to(wb.length, 1)},
                                 {"pieces", wb.solids},
                                 {"stats", stats_json(stats)}});
             } catch (const std::out_of_range& e) {
               fail(res, 404, e.what());
             } catch (const std::exception& e) {
               fail(res, 422, e.what());
             }
           });

  // Exact wireframe for Geomagic Design X. Never a mesh.
  svr.Post(R"(/projects/([^/]+)/rooms/([^/]+)/export-designx)",
           [&](const httplib::Request& req, httplib::Response& res) {
             std::lock_guard<std::mutex> guard(g_lock);
             const std::string pid = req.matches[1], name = req.matches[2];
             const std::string fmt = url_param(req, "fmt", "iges");
             try {
               const ProjectRecord& proj = store.get(pid);
               const Room room = room_or_throw(pid, name);
               const fs::path out = fs::u8path(proj.folder) / "For Design X";
               const std::string path = export_curves(room, out.u8string(), fmt);
               ok_json(res, Json{{"path", path},
                                 {"bytes", file_size_of(path)},
                                 {"format", fmt}});
             } catch (const std::out_of_range& e) {
               fail(res, 404, e.what());
             } catch (const std::exception& e) {
               fail(res, 422, e.what());
             }
           });

  // On Android the same service also serves the interface, so the page and the
  // API share an origin and there is no file:// or mixed-content problem to
  // work around. On the desktop, Electron loads the interface itself and this
  // is left empty.
  if (!web_root.empty()) {
    svr.set_mount_point("/", web_root.c_str());
    svr.Get("/", [web_root](const httplib::Request&, httplib::Response& res) {
      std::ifstream fh(fs::u8path(web_root) / "index.html", std::ios::binary);
      std::stringstream ss;
      ss << fh.rdbuf();
      res.set_content(ss.str(), "text/html");
    });
  }

  if (!svr.listen(host.c_str(), port)) {
    std::fprintf(stderr, "snapir-server: could not bind %s:%d\n", host.c_str(), port);
    return 1;
  }
  return 0;
}

}  // namespace snapir
