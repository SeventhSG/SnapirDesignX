// The .sdxp project file: a project's overrides and connections plus a
// verbatim copy of its survey folder, zipped together so it opens on another
// device with nothing else needed.
#pragma once
#include <map>
#include <string>
#include <vector>

#include "snapir/store.hpp"

namespace snapir {

// Writes out_path as a .sdxp: manifest.json (name, thickness, overrides,
// connections) plus every file under project.folder, under survey/. Throws
// std::runtime_error (message fit to show the user) if the survey folder is
// missing or a file can't be read.
//
// built_at and step_path are dropped from each override on the way out --
// built exports are not bundled, and a path from this machine would be
// meaningless on the target.
void export_sdxp(const ProjectRecord& project, const std::string& out_path);

// What a .sdxp carries, independent of the id or folder it lands under on
// this device.
struct ImportedProject {
  std::string name;
  std::string created_at;
  double thickness = 200.0;
  std::map<std::string, RoomOverride> overrides;
  std::vector<Connection> connections;
};

// Reads manifest.json and extracts survey/ into survey_dir. Throws
// std::runtime_error (message fit to show the user) if the file is not a
// .sdxp, is corrupt, or was written by a newer, incompatible version of the
// app.
ImportedProject import_sdxp(const std::string& sdxp_path,
                             const std::string& survey_dir);

}  // namespace snapir
