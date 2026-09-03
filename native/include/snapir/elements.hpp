// What each piece of the built body actually is.
//
// A face in the solid is an OCCT ordinal. It changes the moment the body is
// rebuilt, and the body is rebuilt every time the operator corrects anything.
// That makes a face id useless as the key for a decision meant to be
// remembered: remove wall 3, correct something else, and wall 3 is now a
// different wall.
//
// Survey point names do not move. `P_007` is `P_007` in this build, in the CSV
// on disk, and in a re-survey next year. So every element of the body is named
// after the points it was built from, and a picked face is attributed back to
// one of those names geometrically - the projection wall_index_at already does
// for walls, generalised to openings, fixtures and stairs.
//
// Face roles used to be decided by which way a face pointed, which cannot tell
// a door reveal from a wall, or a stair tread from the ceiling. This can.
//
// No CAD kernel here, on purpose: attribution is plane geometry and stays
// testable without OCCT.
#pragma once
#include <array>
#include <optional>
#include <string>
#include <vector>

#include "snapir/model.hpp"
#include "snapir/settings.hpp"

namespace snapir {

// One addressable piece of the built body.
struct Element {
  std::string kind;   // wall|floor|ceiling|opening|fitting|fixture|stairs|pervaz
  std::string key;    // stable, built from point names
  std::string label;  // what the inspector shows
  std::optional<int> index;         // ordinal, where one exists
  std::vector<std::string> points;  // the survey points behind it
};

// A wall is named by its two corners, in a fixed order. Sorted rather than ring
// order on purpose: the topology walk's direction is not deterministic between
// the two implementations, and a wall is the same wall whichever way the ring
// was walked.
std::string wall_key(const std::string& a, const std::string& b);

// An opening is named by the lowest-ordered point of each of its jambs.
std::string opening_key(const Opening& op);

// Every addressable element of the body this room would build.
std::vector<Element> elements(const Room& room);

// Name the element a picked face belongs to.
//
// Most specific first: a stair tread also points up, and a door reveal is also
// vertical, so testing the normal first is exactly how the old role-by-normal
// guess got both of them wrong. `centroid_m` arrives in metres from the
// tessellator; everything else here is survey centimetres.
std::optional<Element> face_element(const Room& room, const BuildSettings& cfg,
                                    const std::array<double, 3>& centroid_m,
                                    const std::array<double, 3>& normal,
                                    const std::vector<Element>& table);

// Resolve a stored wall key back to this build's ring edge index. Empty when
// the corner it names is no longer in the outline - the operator dropped the
// point, or redrew the ring. A decision that no longer has anything to apply to
// is dropped, not applied to the wrong wall.
std::optional<int> wall_edge_for_key(const Room& room, const std::string& key);

}  // namespace snapir
