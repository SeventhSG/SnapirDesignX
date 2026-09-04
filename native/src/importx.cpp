#include "snapir/importx.hpp"

#include <algorithm>
#include <cmath>
#include <filesystem>
#include <map>
#include <set>
#include <sstream>

#include <BRep_Tool.hxx>
#include <IFSelect_ReturnStatus.hxx>
#include <IGESControl_Reader.hxx>
#include <STEPControl_Reader.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopTools_IndexedDataMapOfShapeListOfShape.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Shape.hxx>
#include <gp_Pnt.hxx>

#include "snapir/geometry.hpp"
#include "snapir/solid.hpp"

namespace fs = std::filesystem;

namespace snapir {
namespace {

std::string lower(std::string s) {
  for (char& c : s) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
  return s;
}

double dist3(const std::array<double, 3>& a, const std::array<double, 3>& b) {
  const double dx = a[0] - b[0], dy = a[1] - b[1], dz = a[2] - b[2];
  return std::sqrt(dx * dx + dy * dy + dz * dz);
}

double ring_area(const std::vector<Pt>& ring) {
  double a = 0;
  const size_t n = ring.size();
  for (size_t i = 0; i < n; ++i) {
    const Pt& p = ring[i];
    const Pt& q = ring[(i + 1) % n];
    a += p.x * q.y - q.x * p.y;
  }
  return std::abs(a) / 2.0;
}

// Every closed loop where each corner joins exactly two lines. That is what a
// ring drawn as a ring looks like. A rectangle with its corners tied back to a
// second face - the box drawn around a fitting's measured depth - is not one,
// and is left alone.
std::vector<std::vector<int>> cycles(int n,
                                     const std::vector<std::pair<int, int>>& lines) {
  std::map<int, std::vector<int>> adj;
  for (const auto& l : lines) {
    adj[l.first].push_back(l.second);
    adj[l.second].push_back(l.first);
  }

  std::set<int> seen;
  std::vector<std::vector<int>> out;
  for (const auto& entry : adj) {
    const int start = entry.first;
    if (seen.count(start) || entry.second.size() != 2) continue;
    std::vector<int> loop;
    int node = start, prev = -1;
    while (true) {
      const auto it = adj.find(node);
      if (it == adj.end() || it->second.size() != 2) { loop.clear(); break; }
      loop.push_back(node);
      int nxt = -1;
      for (int q : it->second)
        if (q != prev) { nxt = q; break; }
      if (nxt < 0) { loop.clear(); break; }
      prev = node;
      node = nxt;
      if (node == start) break;
      if (static_cast<int>(loop.size()) > n) { loop.clear(); break; }
    }
    if (loop.size() >= 3) {
      seen.insert(loop.begin(), loop.end());
      out.push_back(loop);
    }
  }
  return out;
}

}  // namespace

Sketch read_sketch(const std::string& path) {
  const fs::path p = fs::u8path(path);
  if (!fs::is_regular_file(p)) throw BuildError("No such file: " + path);

  const std::string suffix = lower(p.extension().u8string());
  TopoDS_Shape shape;
  if (suffix == ".igs" || suffix == ".iges") {
    IGESControl_Reader reader;
    if (reader.ReadFile(p.u8string().c_str()) != IFSelect_RetDone)
      throw BuildError("Could not read " + p.filename().u8string());
    reader.TransferRoots();
    shape = reader.OneShape();
  } else if (suffix == ".stp" || suffix == ".step") {
    STEPControl_Reader reader;
    if (reader.ReadFile(p.u8string().c_str()) != IFSelect_RetDone)
      throw BuildError("Could not read " + p.filename().u8string());
    reader.TransferRoots();
    shape = reader.OneShape();
  } else {
    throw BuildError("Not a Design X sketch: " + p.filename().u8string());
  }
  if (shape.IsNull())
    throw BuildError(p.filename().u8string() + " holds no geometry");

  Sketch out;
  auto seat = [&](const TopoDS_Shape& v) {
    const gp_Pnt g = BRep_Tool::Pnt(TopoDS::Vertex(v));
    const std::array<double, 3> q = {g.X() / kCmToMm, g.Y() / kCmToMm,
                                     g.Z() / kCmToMm};
    for (size_t i = 0; i < out.points.size(); ++i) {
      const auto& r = out.points[i];
      if (std::abs(r[0] - q[0]) < kImportWeld && std::abs(r[1] - q[1]) < kImportWeld &&
          std::abs(r[2] - q[2]) < kImportWeld)
        return static_cast<int>(i);
    }
    out.points.push_back(q);
    return static_cast<int>(out.points.size()) - 1;
  };

  std::vector<std::pair<int, int>> lines;
  for (TopExp_Explorer exp(shape, TopAbs_EDGE); exp.More(); exp.Next()) {
    std::vector<int> idx;
    for (TopExp_Explorer ends(exp.Current(), TopAbs_VERTEX); ends.More(); ends.Next())
      idx.push_back(seat(ends.Current()));
    if (idx.size() >= 2 && idx.front() != idx.back())
      lines.emplace_back(idx.front(), idx.back());
  }

  // Vertices no edge uses: the single shots, written as points.
  std::set<int> free;
  TopTools_IndexedDataMapOfShapeListOfShape owners;
  TopExp::MapShapesAndAncestors(shape, TopAbs_VERTEX, TopAbs_EDGE, owners);
  for (TopExp_Explorer exp(shape, TopAbs_VERTEX); exp.More(); exp.Next())
    if (owners.Contains(exp.Current()) &&
        owners.FindFromKey(exp.Current()).Extent() == 0)
      free.insert(seat(exp.Current()));

  std::set<std::pair<int, int>> seen;
  std::vector<std::pair<int, int>> keep;
  for (const auto& l : lines) {
    if (dist3(out.points[l.first], out.points[l.second]) < kImportMinRun) continue;
    const auto key = l.first < l.second ? l : std::make_pair(l.second, l.first);
    if (seen.insert(key).second) keep.push_back(key);
  }

  // The ends of the runs that were dropped go with them. A cross through a
  // single shot is six of those, and left behind they would arrive as six
  // points nobody measured, clustered a few centimetres around one that was.
  std::set<int> used = free;
  for (const auto& l : keep) {
    used.insert(l.first);
    used.insert(l.second);
  }
  std::map<int, int> at;
  std::vector<std::array<double, 3>> kept;
  for (int i : used) {
    at[i] = static_cast<int>(kept.size());
    kept.push_back(out.points[i]);
  }
  out.points = std::move(kept);
  out.lines.clear();
  for (const auto& l : keep) out.lines.emplace_back(at[l.first], at[l.second]);
  return out;
}

std::vector<int> outline_loop(const Sketch& sketch) {
  const auto loops = cycles(static_cast<int>(sketch.points.size()), sketch.lines);
  if (loops.empty()) return {};

  std::vector<double> level;
  for (const auto& loop : loops) {
    double z = 0;
    for (int i : loop) z += sketch.points[i][2];
    level.push_back(z / static_cast<double>(loop.size()));
  }
  const double floor = *std::min_element(level.begin(), level.end());

  const std::vector<int>* best = nullptr;
  double best_area = -1;
  for (size_t i = 0; i < loops.size(); ++i) {
    if (level[i] - floor > 40.0) continue;
    std::vector<Pt> plan;
    for (int k : loops[i]) plan.push_back({sketch.points[k][0], sketch.points[k][1]});
    const double a = ring_area(plan);
    if (a > best_area) { best_area = a; best = &loops[i]; }
  }
  return best ? *best : std::vector<int>{};
}

ImportedSketch sketch_for(const Room& room, const std::string& path) {
  const Sketch sketch = read_sketch(path);
  if (sketch.points.empty())
    throw BuildError("That file has nothing in it to import.");

  // A point that lands on a surveyed shot is that shot, under its own name.
  // Everything the operator has already decided - a role they corrected, a wall
  // they took out, the kind of an opening - is keyed on these names, and all of
  // it survives the trip out and back because of this.
  std::set<std::string> taken;
  std::vector<std::string> names(sketch.points.size());
  // A point that only exists because the last import brought it in has to be
  // carried again, under the same name. Matching it and then leaving it out of
  // the record would delete it on the very next read, and every line drawn to
  // it would go with it.
  std::set<size_t> carry;
  int matched = 0;
  for (size_t i = 0; i < sketch.points.size(); ++i) {
    const Point* best = nullptr;
    double best_d = kImportMatch;
    for (const auto& p : room.points) {
      if (taken.count(p.name)) continue;
      const double d = dist3({p.x, p.y, p.z}, sketch.points[i]);
      if (d < best_d) { best = &p; best_d = d; }
    }
    if (best) {
      taken.insert(best->name);
      names[i] = best->name;
      ++matched;
      if (best->derived) carry.insert(i);
    }
  }

  const std::vector<int> loop = outline_loop(sketch);
  const std::set<int> on_ring(loop.begin(), loop.end());

  const fs::path file = fs::u8path(path);
  const std::string leaf = file.filename().u8string();

  ImportedSketch out;
  out.file = leaf;
  std::set<std::string> used(taken.begin(), taken.end());
  for (const auto& p : room.points) used.insert(p.name);
  out.matched = matched;
  int n = 1;
  for (size_t i = 0; i < names.size(); ++i) {
    if (!names[i].empty() && !carry.count(i)) continue;
    std::string name = names[i];
    if (name.empty()) {
      do {
        std::ostringstream os;
        os << "X_" << (n < 100 ? (n < 10 ? "00" : "0") : "") << n;
        name = os.str();
        ++n;
      } while (used.count(name));
      used.insert(name);
      names[i] = name;
    }
    // A corner of the floor loop is a floor corner; that much the drawing says
    // outright. Anything else the file brought is left unknown rather than
    // guessed at, so it shows up as a point waiting to be told what it is
    // instead of quietly joining the room as something it is not.
    out.points.push_back({name, sketch.points[i][0], sketch.points[i][1],
                          sketch.points[i][2],
                          on_ring.count(static_cast<int>(i)) ? "floor" : "unknown",
                          "Design X, " + leaf});
  }

  for (const auto& l : sketch.lines)
    out.segments.emplace_back(names[l.first], names[l.second]);
  for (int i : loop) out.outline.push_back(names[i]);
  return out;
}

}  // namespace snapir
