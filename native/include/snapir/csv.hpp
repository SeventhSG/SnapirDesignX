// Minimal CSV reading. The Leica export is semicolon-separated, UTF-8 with a
// BOM, and CRLF-terminated. Nothing here is general; it reads that file.
#pragma once
#include <filesystem>
#include <string>
#include <vector>

namespace snapir {

using CsvRow = std::vector<std::string>;

// Reads every row. Strips a leading UTF-8 BOM and trailing CR. Returns an
// empty vector when the file does not exist.
std::vector<CsvRow> read_csv(const std::filesystem::path& path, char delimiter = ';');
bool file_exists(const std::filesystem::path& path);
std::string trim(const std::string& s);

}  // namespace snapir
