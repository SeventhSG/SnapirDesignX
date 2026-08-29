# A third shell: iOS

Status: **written, never run.** Every file is in place; nothing has been built,
because nothing here can build it. The first real result will come from CI.

The design this follows is
[`superpowers/specs/2026-08-29-ios-design.md`](superpowers/specs/2026-08-29-ios-design.md).

## The idea

The same move as Android, for the same reason. The geometry core is C++ behind
a narrow loopback HTTP API, and the interface is a React page that does not
care what is on the other end of it.

```
                  ┌─────────────────────────┐
                  │  snapir-core  (C++)     │
                  │  parse · topology ·     │
                  │  planes · solids · STEP │
                  └───────────┬─────────────┘
                              │  one service, three shells
         ┌────────────────────┼────────────────────┐
         │                    │                    │
   Electron + React    Android + WebView     iOS + WKWebView
    (sidecar proc)      (thread, JNI)       (thread, Obj-C++)
```

Not one line under `native/`, `app/` or `snapir/` changed. That was the
constraint, not a happy accident: the first time iOS needs its own parser or
its own I/O layer, the reason the core was written in C++ is gone.

## Build it

macOS only, and in practice that means the CI runner.

```bash
bash native/build-occt-ios.sh      # OCCT for device and simulator, static
cd app && npm ci && npm run build  # the interface
python3 tools/build_ios.py both    # bundle, then CMake and Xcode
```

The OCCT step is two cross-compiles of about an hour each and is left as its
own step on purpose. The simulator slice is built first: with no signing
certificate it is the only build that will ever actually run.

## Why there is no .xcodeproj

The person maintaining this cannot open Xcode. The project has to be a text
file that survives review in a diff, so CMake generates the real one with
`-G Xcode` and `ios/CMakeLists.txt` is what gets edited.

It is configured **once per SDK**, into `out/ios-simulator` and
`out/ios-device`. Xcode can express a per-SDK library path with an
`[sdk=iphoneos*]` conditional, but OCCT lands in a different prefix for each
slice, and getting that wrong fails at link time on a machine nobody can attach
a debugger to. Two configures, no conditionals.

## What is different from Android, and why

### The file model

The Android app reads survey folders where they lie: `MANAGE_EXTERNAL_STORAGE`,
plus `StoragePaths.toFilePath()` turning the picker's `content://` tree back
into a real absolute path.

iOS has no equivalent. There are no real paths outside the container, no
all-files access, and the App Store rejects the shape outright. So
`FolderImport.mm` **copies the chosen folder in**, once, to
`Documents/surveys/<name>/`, and everything downstream sees an ordinary
directory. The alternative — reading in place behind
`startAccessingSecurityScopedResource` — would put a platform seam through the
middle of the parser, which is the one file that most needs to stay shared.

The copy is cheap. The 28-room reference job is about 4 MB.

Exports land beside the input under `Documents/`. `UIFileSharingEnabled` and
`LSSupportsOpeningDocumentsInPlace` put the whole tree in Files.app, and
`reveal` opens a share sheet on the written STEP rather than the Android toast.

### The bridge, and the CSP

The built page carries `default-src 'self'`, which blocks inline script.
Android works around it by writing the shim out as a file and splicing a
`<script>` tag into `index.html` — which is why `WebAssets.java` has to unpack
the whole interface out of the APK to somewhere writable first.

A `WKUserScript` is injected by the host rather than loaded by the document, so
the page's policy does not apply to it. That deletes the entire problem: the
bundle stays read-only, nothing is copied, and `WebAssets`' 152 lines have no
iOS counterpart at all. The shim itself is identical in effect to Android's —
it defines the same `window.snapir` that `preload.cjs` exposes on the desktop.

### Two files that simply do not exist here

`WebAssets` and `StoragePaths` both exist to fight Android's storage model.
Neither has an iOS equivalent, which is most of why this shell is smaller than
the Android one.

| Android | iOS |
|---|---|
| `MainActivity` (206) | `SnapirViewController` |
| `NativeService.java` (55) + `jni_bridge.cpp` (56) | `NativeService.mm` |
| `WebAssets.java` (152) | — |
| `FolderPicker` (92) + `StoragePaths` (54) | `FolderImport.mm` |
| `WebBridge.java` (35) | `WebBridge.mm` |
| `network_security_config.xml` | — (ATS does not apply to loopback) |

### Three things the service needs on iOS

1. **`web_root` is the bundle's resource path.** Already unpacked, already
   readable. No install step, no version stamp, no cache directory.

2. **`HOME` is set explicitly** to `Library/Application Support` before
   `serve()`. `native/src/store.cpp:61` reads `APPDATA` and falls back to
   `HOME + "/.config"`. iOS *does* set `HOME` — to the container root — so
   without this the settings and the project list land in a hidden directory at
   the top of the container where nothing backs them up. Same `setenv` as
   `jni_bridge.cpp`, different reason.

3. **Port 8765 is not a free choice.** The built page pins it in its CSP.

No entitlement is required. `NSLocalNetworkUsageDescription` and the local
network prompt cover LAN discovery and mDNS; loopback is exempt, as is ATS.

**The app is foreground-only.** iOS suspends a backgrounded process and the
listening socket goes with it. For a tool used while standing in a room that is
an acceptable trade; the view controller re-checks the socket on
`applicationWillEnterForeground:` and restarts rather than showing a blank page.

### The link line

`android/app/src/main/cpp/CMakeLists.txt` wraps the OCCT archives in
`-Wl,--start-group ... -Wl,--end-group`. **Do not carry that across.** Apple's
`ld64` does not implement the GNU group flags and errors on them, and it does
not need them: it resolves circular references between static archives on its
own. The 22 toolkits are listed plainly, in the same order.
`find_library(log-lib log)` is dropped with it.

## CI

`.github/workflows/ios.yml`, on `macos-14`. The repository is public, so macOS
minutes are free; the Open CASCADE cache is there for iteration speed, not
cost.

Verification is **not** a smoke test. An iOS Simulator app shares the host's
network stack, so the service the app starts on `127.0.0.1:8765` inside the
simulator is the same `127.0.0.1:8765` the runner can reach.
`tools/verify_ios_sim.py` stages a survey into the app container where the
document picker would have put it, launches the app, and then drives the real
HTTP API — the same one `tools/compare_servers.py` drives against the desktop.

`Daire 53 - Salon` must come back **1 solid, 123 faces, 20.922131 m³** or the
job fails.

Screenshots are taken on an iPad Pro and an iPhone 15 and uploaded as
artifacts. From Windows they are the only way to see the app at all — the same
role `tools/shoot_layouts.js` plays for the interface.

## Layout

Universal, iPad-primary: this is a survey tool, not a phone tool. All four
orientations rather than the Android build's portrait lock. Deployment target
iOS 15. `tools/shoot_layouts.js` already exercises 800×1180 and 1440×900, so
the React side has tablet layouts under test; nothing in `app/` changed for
this.

## What this does not do

- No signing, no `.ipa`, no TestFlight, no App Store submission. There is no
  Apple Developer account. CI produces an unsigned simulator build that runs
  and an unsigned device build that only proves it compiles and links.
- **No hardware verification.** Same standing as the APK: never run on a real
  device.
- No iCloud, no document browser beyond Files.app visibility.
- No background execution, no multi-window on iPad.

## What we did

Nothing yet. This section gets written the way `ANDROID.md`'s did, once CI has
been green and the screenshots have been looked at.
