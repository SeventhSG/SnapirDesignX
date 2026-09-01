#include "snapir/archive.hpp"

#include <cstdint>
#include <filesystem>
#include <fstream>
#include <stdexcept>

namespace fs = std::filesystem;

namespace snapir {
namespace {

constexpr int kFormatVersion = 1;

// ------------------------------------------------------------- zip: shared

void put_u16(std::string& out, uint16_t v) {
  out.push_back(static_cast<char>(v & 0xFF));
  out.push_back(static_cast<char>((v >> 8) & 0xFF));
}

void put_u32(std::string& out, uint32_t v) {
  out.push_back(static_cast<char>(v & 0xFF));
  out.push_back(static_cast<char>((v >> 8) & 0xFF));
  out.push_back(static_cast<char>((v >> 16) & 0xFF));
  out.push_back(static_cast<char>((v >> 24) & 0xFF));
}

uint16_t get_u16(const std::string& buf, size_t off) {
  return static_cast<uint16_t>(
      static_cast<unsigned char>(buf[off]) |
      (static_cast<unsigned char>(buf[off + 1]) << 8));
}

uint32_t get_u32(const std::string& buf, size_t off) {
  return static_cast<uint32_t>(static_cast<unsigned char>(buf[off])) |
         (static_cast<uint32_t>(static_cast<unsigned char>(buf[off + 1])) << 8) |
         (static_cast<uint32_t>(static_cast<unsigned char>(buf[off + 2])) << 16) |
         (static_cast<uint32_t>(static_cast<unsigned char>(buf[off + 3])) << 24);
}

// Bit-by-bit CRC32 (no lookup table). The archives here are, at most, a
// survey's worth of panorama JPEGs -- not enough traffic to justify a table.
uint32_t crc32(const std::string& data) {
  uint32_t crc = 0xFFFFFFFFu;
  for (unsigned char b : data) {
    crc ^= b;
    for (int k = 0; k < 8; ++k)
      crc = (crc & 1) ? (0xEDB88320u ^ (crc >> 1)) : (crc >> 1);
  }
  return crc ^ 0xFFFFFFFFu;
}

// ------------------------------------------------------------- zip: writer

struct ZipEntry {
  std::string name;  // forward-slash path inside the archive
  std::string data;
};

// A plain "stored" (uncompressed) zip. The payload is CSVs and JPEGs that are
// already compressed, so deflate would buy little -- and this way the format
// needs nothing beyond the standard library.
void write_zip(const std::string& out_path, const std::vector<ZipEntry>& entries) {
  if (entries.size() > 0xFFFF)
    throw std::runtime_error("Too many files to archive.");

  std::ofstream out(fs::u8path(out_path), std::ios::binary);
  if (!out) throw std::runtime_error("Could not create " + out_path);

  std::vector<std::string> central_dir;
  uint32_t offset = 0;

  for (const auto& e : entries) {
    const uint32_t crc = crc32(e.data);
    const uint32_t size = static_cast<uint32_t>(e.data.size());
    const uint16_t name_len = static_cast<uint16_t>(e.name.size());

    std::string lfh;
    put_u32(lfh, 0x04034b50);
    put_u16(lfh, 20);       // version needed
    put_u16(lfh, 0x0800);   // UTF-8 filenames
    put_u16(lfh, 0);        // stored, no compression
    put_u16(lfh, 0);        // mod time
    put_u16(lfh, 0x21);     // mod date: 1980-01-01, not user facing
    put_u32(lfh, crc);
    put_u32(lfh, size);
    put_u32(lfh, size);
    put_u16(lfh, name_len);
    put_u16(lfh, 0);
    lfh += e.name;

    out.write(lfh.data(), static_cast<std::streamsize>(lfh.size()));
    out.write(e.data.data(), static_cast<std::streamsize>(e.data.size()));

    std::string cdh;
    put_u32(cdh, 0x02014b50);
    put_u16(cdh, 20);
    put_u16(cdh, 20);
    put_u16(cdh, 0x0800);
    put_u16(cdh, 0);
    put_u16(cdh, 0);
    put_u16(cdh, 0x21);
    put_u32(cdh, crc);
    put_u32(cdh, size);
    put_u32(cdh, size);
    put_u16(cdh, name_len);
    put_u16(cdh, 0);
    put_u16(cdh, 0);
    put_u16(cdh, 0);
    put_u16(cdh, 0);
    put_u32(cdh, 0);
    put_u32(cdh, offset);
    cdh += e.name;
    central_dir.push_back(std::move(cdh));

    offset += static_cast<uint32_t>(lfh.size() + e.data.size());
  }

  const uint32_t cd_offset = offset;
  uint32_t cd_size = 0;
  for (const auto& cdh : central_dir) {
    out.write(cdh.data(), static_cast<std::streamsize>(cdh.size()));
    cd_size += static_cast<uint32_t>(cdh.size());
  }

  std::string eocd;
  put_u32(eocd, 0x06054b50);
  put_u16(eocd, 0);
  put_u16(eocd, 0);
  put_u16(eocd, static_cast<uint16_t>(entries.size()));
  put_u16(eocd, static_cast<uint16_t>(entries.size()));
  put_u32(eocd, cd_size);
  put_u32(eocd, cd_offset);
  put_u16(eocd, 0);
  out.write(eocd.data(), static_cast<std::streamsize>(eocd.size()));
}

// ------------------------------------------------------------- zip: reader

// Whole archive read into memory and handed back as name -> bytes. These
// archives are at most a survey folder's worth of data, read once on import,
// so this is simpler than streaming and costs nothing in practice.
std::map<std::string, std::string> read_zip(const std::string& path) {
  std::ifstream in(fs::u8path(path), std::ios::binary);
  if (!in) throw std::runtime_error("Could not open the file.");
  std::string data((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
  if (data.size() < 22) throw std::runtime_error("That file is not a .sdxp project.");

  const size_t max_back = std::min(data.size(), static_cast<size_t>(65557));
  const size_t lower = data.size() - max_back;
  size_t eocd_pos = std::string::npos;
  for (size_t i = data.size() - 22;; --i) {
    if (get_u32(data, i) == 0x06054b50u) { eocd_pos = i; break; }
    if (i <= lower) break;
  }
  if (eocd_pos == std::string::npos)
    throw std::runtime_error("That file is not a .sdxp project.");

  const uint16_t total_entries = get_u16(data, eocd_pos + 10);
  const uint32_t cd_offset = get_u32(data, eocd_pos + 16);

  std::map<std::string, std::string> out;
  size_t pos = cd_offset;
  for (uint16_t i = 0; i < total_entries; ++i) {
    if (pos + 46 > data.size() || get_u32(data, pos) != 0x02014b50u)
      throw std::runtime_error("That file is not a valid .sdxp project.");

    const uint16_t method = get_u16(data, pos + 10);
    const uint32_t size = get_u32(data, pos + 24);
    const uint16_t name_len = get_u16(data, pos + 28);
    const uint16_t extra_len = get_u16(data, pos + 30);
    const uint16_t comment_len = get_u16(data, pos + 32);
    const uint32_t local_offset = get_u32(data, pos + 42);
    const std::string name = data.substr(pos + 46, name_len);
    pos += 46 + name_len + extra_len + comment_len;

    if (method != 0)
      throw std::runtime_error("Unsupported entry in .sdxp project: " + name);
    if (local_offset + 30 > data.size())
      throw std::runtime_error("That file is not a valid .sdxp project.");

    const uint16_t lname_len = get_u16(data, local_offset + 26);
    const uint16_t lextra_len = get_u16(data, local_offset + 28);
    const size_t data_pos = local_offset + 30 + lname_len + lextra_len;
    if (data_pos + size > data.size())
      throw std::runtime_error("That .sdxp project file is truncated.");

    out[name] = data.substr(data_pos, size);
  }
  return out;
}

// --------------------------------------------------------------- manifest

Json manifest_json(const ProjectRecord& project) {
  Json j;
  j["format"] = "snapir-project";
  j["formatVersion"] = kFormatVersion;
  j["exportedAt"] = now_iso8601();
  j["name"] = project.name;
  j["createdAt"] = project.created_at;
  j["thickness"] = project.thickness;

  Json overrides = Json::object();
  for (const auto& kv : project.overrides) {
    Json ov = to_json(kv.second);
    // No built export travels with the archive, and a path from this machine
    // would be meaningless on the target.
    ov["built_at"] = nullptr;
    ov["step_path"] = nullptr;
    overrides[kv.first] = ov;
  }
  j["overrides"] = overrides;

  Json conns = Json::array();
  for (const auto& c : project.connections) conns.push_back(to_json(c));
  j["connections"] = conns;

  return j;
}

}  // namespace

void export_sdxp(const ProjectRecord& project, const std::string& out_path) {
  const fs::path survey_root = fs::u8path(project.folder);
  if (!fs::is_directory(survey_root))
    throw std::runtime_error(
        "The survey folder for this project is missing, so it can't be exported.");

  std::vector<ZipEntry> entries;
  entries.push_back({"manifest.json", manifest_json(project).dump(2)});

  for (const auto& e : fs::recursive_directory_iterator(survey_root)) {
    if (!e.is_regular_file()) continue;
    const fs::path rel = fs::relative(e.path(), survey_root);

    std::ifstream in(e.path(), std::ios::binary);
    if (!in) throw std::runtime_error("Could not read " + e.path().u8string());
    std::string bytes((std::istreambuf_iterator<char>(in)),
                       std::istreambuf_iterator<char>());
    entries.push_back({"survey/" + rel.generic_u8string(), std::move(bytes)});
  }

  const fs::path out = fs::u8path(out_path);
  if (out.has_parent_path()) fs::create_directories(out.parent_path());
  write_zip(out.u8string(), entries);
}

ImportedProject import_sdxp(const std::string& sdxp_path, const std::string& survey_dir) {
  const auto entries = read_zip(sdxp_path);

  const auto manifest_it = entries.find("manifest.json");
  if (manifest_it == entries.end())
    throw std::runtime_error("That file is not a Snapir Design X project.");

  Json manifest;
  try {
    manifest = Json::parse(manifest_it->second);
  } catch (const std::exception&) {
    throw std::runtime_error("That file is not a Snapir Design X project.");
  }

  if (manifest.value("format", std::string()) != "snapir-project")
    throw std::runtime_error("That file is not a Snapir Design X project.");
  if (manifest.value("formatVersion", 0) > kFormatVersion)
    throw std::runtime_error(
        "This project was saved by a newer version of Snapir Design X. "
        "Update the app to open it.");

  ImportedProject out;
  out.name = manifest.value("name", std::string("Imported project"));
  out.created_at = manifest.value("createdAt", std::string());
  out.thickness = manifest.value("thickness", 200.0);

  if (manifest.contains("overrides"))
    for (const auto& kv : manifest["overrides"].items())
      out.overrides[kv.key()] = override_from_json(kv.value());
  if (manifest.contains("connections"))
    for (const auto& c : manifest["connections"])
      out.connections.push_back(connection_from_json(c));

  const fs::path dest_root = fs::u8path(survey_dir);
  fs::create_directories(dest_root);
  static const std::string kPrefix = "survey/";
  bool any_file = false;
  for (const auto& kv : entries) {
    if (kv.first.rfind(kPrefix, 0) != 0) continue;
    const std::string rel = kv.first.substr(kPrefix.size());
    if (rel.empty()) continue;

    const fs::path dest = dest_root / fs::u8path(rel);
    if (dest.has_parent_path()) fs::create_directories(dest.parent_path());
    std::ofstream f(dest, std::ios::binary);
    if (!f) throw std::runtime_error("Could not write " + dest.u8string());
    f.write(kv.second.data(), static_cast<std::streamsize>(kv.second.size()));
    any_file = true;
  }
  if (!any_file)
    throw std::runtime_error("This project file has no survey data in it.");

  return out;
}

}  // namespace snapir
