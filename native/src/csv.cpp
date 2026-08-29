#include "snapir/csv.hpp"
#include <fstream>

namespace snapir {

bool file_exists(const std::filesystem::path& path) {
  std::ifstream fh(path, std::ios::binary);
  return fh.good();
}

std::string trim(const std::string& s) {
  const auto b = s.find_first_not_of(" \t\r\n");
  if (b == std::string::npos) return "";
  return s.substr(b, s.find_last_not_of(" \t\r\n") - b + 1);
}

std::vector<CsvRow> read_csv(const std::filesystem::path& path, char delimiter) {
  std::vector<CsvRow> rows;
  std::ifstream fh(path, std::ios::binary);
  if (!fh) return rows;

  std::string line;
  bool first = true;
  while (std::getline(fh, line)) {
    if (first) {
      first = false;
      if (line.size() >= 3 && static_cast<unsigned char>(line[0]) == 0xEF &&
          static_cast<unsigned char>(line[1]) == 0xBB &&
          static_cast<unsigned char>(line[2]) == 0xBF)
        line.erase(0, 3);
    }
    if (!line.empty() && line.back() == '\r') line.pop_back();

    CsvRow row;
    std::string cell;
    bool quoted = false;
    for (size_t i = 0; i < line.size(); ++i) {
      const char c = line[i];
      if (quoted) {
        if (c == '"') {
          if (i + 1 < line.size() && line[i + 1] == '"') { cell += '"'; ++i; }
          else quoted = false;
        } else cell += c;
      } else if (c == '"') {
        quoted = true;
      } else if (c == delimiter) {
        row.push_back(cell);
        cell.clear();
      } else {
        cell += c;
      }
    }
    row.push_back(cell);
    rows.push_back(std::move(row));
  }
  return rows;
}

}  // namespace snapir
