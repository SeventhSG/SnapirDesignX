// The connections the surveyor actually drew.
//
// The plain room CSV is a bag of points with no connectivity. The `_FUKOKU.csv`
// beside it carries the lines: a `Line start` / `Line end` pair per row. That
// file holds the whole topology of the room, already closed:
//
//     P_001 -> P_002 -> ... -> P_011 -> P_001      the floor ring
//     P_012 -> P_013 -> ... -> P_022 -> P_012      the ceiling ring
//     P_023 -> P_024 -> P_025 -> P_026 -> P_023    a door, as a closed loop
//     P_013 -> P_001, P_014 -> P_002, ...          floor to ceiling links
//
// Reading it means the room is described rather than guessed. Nothing here
// invents a connection; every line drawn in the app comes from this file or
// from the operator.
#pragma once
#include <array>
#include <filesystem>
#include <map>
#include <string>
#include <utility>
#include <vector>

namespace snapir {

// Two points this close in Z belong to the same level, so the line between
// them lies flat rather than rising.
inline constexpr double kLevelDz = 35.0;

using Segment = std::pair<std::string, std::string>;

struct Topology {
  std::vector<Segment> segments;
  std::vector<std::string> floor_ring;
  std::vector<std::string> ceiling_ring;
  std::vector<std::vector<std::string>> openings;
  std::vector<Segment> links;  // floor to ceiling

  bool found() const { return !segments.empty(); }
};

std::filesystem::path fukoku_path(const std::string& room_csv);

// Every line the operator drew, as point-name pairs.
std::vector<Segment> read_segments(const std::string& room_csv);

// Sort the drawn lines into rings, openings and vertical links.
Topology build_topology(const std::vector<Segment>& segments,
                        const std::map<std::string, std::array<double, 3>>& points);

}  // namespace snapir
