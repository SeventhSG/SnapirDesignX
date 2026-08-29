// The local API, as a callable service.
//
// The desktop spawns this as its own process; Android starts it on a thread
// inside the app. Same routes, same JSON, one implementation.
#pragma once
#include <string>

namespace snapir {

// Blocks until the server stops. `web_root`, when set, also serves the built
// interface from that directory, so the page and the API share an origin.
int serve(const std::string& host = "127.0.0.1", int port = 8765,
          const std::string& web_root = "");

}  // namespace snapir
