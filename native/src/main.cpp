// The desktop sidecar: a process whose whole job is to run the service.
#include <cstdlib>
#include <string>

#include "snapir/service.hpp"

int main(int argc, char** argv) {
  std::string host = "127.0.0.1";
  int port = 8765;
  std::string web_root;
  for (int i = 1; i < argc; ++i) {
    const std::string a = argv[i];
    if (a == "--host" && i + 1 < argc) host = argv[++i];
    else if (a == "--port" && i + 1 < argc) port = std::atoi(argv[++i]);
    else if (a == "--web" && i + 1 < argc) web_root = argv[++i];
  }
  return snapir::serve(host, port, web_root);
}
