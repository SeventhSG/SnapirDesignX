#include "snapir/model.hpp"
#include <algorithm>

namespace snapir {

const char* to_string(Role r) {
  switch (r) {
    case Role::Floor: return "floor";
    case Role::Ceiling: return "ceiling";
    case Role::Opening: return "opening";
    case Role::Socket: return "socket";
    case Role::Plumbing: return "plumbing";
    case Role::Control: return "control";
    case Role::Station: return "station";
    default: return "unknown";
  }
}

Role role_from_string(const std::string& s) {
  if (s == "floor") return Role::Floor;
  if (s == "ceiling") return Role::Ceiling;
  if (s == "opening") return Role::Opening;
  if (s == "socket") return Role::Socket;
  if (s == "plumbing") return Role::Plumbing;
  if (s == "control") return Role::Control;
  if (s == "station") return Role::Station;
  return Role::Unknown;
}

namespace {
std::string trim(const std::string& s) {
  const auto b = s.find_first_not_of(" \t\r\n");
  if (b == std::string::npos) return "";
  return s.substr(b, s.find_last_not_of(" \t\r\n") - b + 1);
}
}  // namespace

std::string Room::flat() const {
  const auto i = name.find(" - ");
  return i == std::string::npos ? "" : trim(name.substr(0, i));
}

std::string Room::label() const {
  const auto i = name.find(" - ");
  return i == std::string::npos ? name : trim(name.substr(i + 3));
}

std::vector<Point> Room::unresolved() const {
  std::vector<Point> out;
  for (const auto& p : points)
    if (p.role == Role::Unknown) out.push_back(p);
  return out;
}

bool Room::has_errors() const {
  return std::any_of(issues.begin(), issues.end(),
                     [](const Issue& i) { return i.severity == "error"; });
}

std::optional<double> Room::ceiling_height() const {
  if (ceiling_height_override) return ceiling_height_override;
  if (ceiling_z && floor_z) return *ceiling_z - *floor_z;
  if (ceiling.empty()) return std::nullopt;
  double s = 0.0;
  for (const auto& p : ceiling) s += p.z;
  return s / static_cast<double>(ceiling.size()) - (floor_z ? *floor_z : 0.0);
}

}  // namespace snapir
