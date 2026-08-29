// The whole Android native surface: start the service, and say where it lives.
//
// There is no per-endpoint JNI bridge, and deliberately so. The service already
// speaks a narrow HTTP API that the interface has used since the desktop build,
// so the phone runs the same server on loopback and the WebView talks to it the
// way the Electron window always did. One implementation, one set of routes,
// nothing to keep in sync.
#include <jni.h>

#include <atomic>
#include <cstdlib>
#include <string>
#include <thread>

#include <android/log.h>

#include "snapir/service.hpp"

namespace {

std::atomic<bool> g_started{false};

std::string to_utf8(JNIEnv* env, jstring s) {
  if (!s) return {};
  const char* raw = env->GetStringUTFChars(s, nullptr);
  std::string out(raw ? raw : "");
  if (raw) env->ReleaseStringUTFChars(s, raw);
  return out;
}

}  // namespace

extern "C" JNIEXPORT void JNICALL
Java_com_snapirdesign_designx_NativeService_nativeStart(JNIEnv* env, jclass,
                                                        jstring j_files_dir,
                                                        jstring j_web_root,
                                                        jint port) {
  if (g_started.exchange(true)) return;  // one service per process

  const std::string files_dir = to_utf8(env, j_files_dir);
  const std::string web_root = to_utf8(env, j_web_root);

  // store.cpp finds its settings and project list through APPDATA, then HOME.
  // Android sets neither, and the working directory of an app is "/", which is
  // not writable, so point HOME at the app's own private storage.
  setenv("HOME", files_dir.c_str(), 1);

  const int p = static_cast<int>(port);
  std::thread([files_dir, web_root, p] {
    __android_log_print(ANDROID_LOG_INFO, "snapir",
                        "serving %s on 127.0.0.1:%d (home %s)", web_root.c_str(), p,
                        files_dir.c_str());
    const int rc = snapir::serve("127.0.0.1", p, web_root);
    __android_log_print(ANDROID_LOG_ERROR, "snapir", "service stopped, rc=%d", rc);
  }).detach();
}
