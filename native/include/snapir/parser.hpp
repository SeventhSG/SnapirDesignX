// Reader for Leica iCON trades CSV exports (iCS50 and friends).
//
// The CSV is the authoritative source. The accompanying _2D.dxf / _3D.dxf hold
// only the segments the operator happened to draw on site, duplicated across
// three sheet frames, so they are deliberately ignored.
//
// File shape:
//     Kimlik;X (cm);Y (cm);Z (cm);Katman
//     LEICA_ICON_TOOL;166.86;-459.32;127.29
//     P_001;0.00;0.00;0.00;Zemin
#pragma once
#include <map>
#include <string>
#include "snapir/model.hpp"

namespace snapir {

// Tolerances, all in centimetres.
inline constexpr double kCeilingXyTol = 30.0;     // ceiling shot near a floor corner
inline constexpr double kMaxOpeningWidth = 320.0; // wider is two walls, not one opening
inline constexpr double kZBandTol = 8.0;          // Z readings sharing a plane
inline constexpr double kFloorTol = 12.0;         // a shot this near the datum is on the slab
inline constexpr double kCeilingTol = 18.0;       // ceilings are not flat; allow real sag
inline constexpr double kMinRoomHeight = 150.0;   // below this the high band is not a ceiling
inline constexpr double kMinJambSpan = 40.0;      // a jamb must be taller than this
inline constexpr double kJambXyTol = 12.0;        // two shots this close are one vertical
inline constexpr double kStationMergeCm = 5.0;    // re-levelled in place, not a new setup

// Parse one room CSV into a classified Room.
Room read_room(const std::string& path);

// Read every room CSV in a folder, skipping the _FUKOKU report variants.
Project read_project(const std::string& folder, const std::string& name = "");

// Re-derive the room from whatever roles its points currently carry.
void rebuild(Room& room);

// Set point roles by name, then rebuild everything derived from them.
void apply_roles(Room& room, const std::map<std::string, std::string>& roles);

// Re-derive the room after its lines were edited.
void reread_topology(Room& room);

void validate(Room& room);

}  // namespace snapir
