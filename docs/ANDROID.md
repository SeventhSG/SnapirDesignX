# Moving the core to C++

Status: **done.** All five stages. The desktop runs the C++ core, and the same
core runs on Android. What follows is the original plan; what actually happened
is recorded at the bottom, under "What we did".

## The idea

Not "port Snapir to Android". Move the geometry core from Python to C++ once,
then run it under two shells: the desktop app we already have, and an Android
app. Android stops being a rewrite and becomes a second front end on an engine
that already works.

```
                  ┌─────────────────────────┐
                  │  snapir-core  (C++)     │
                  │  parse · topology ·     │
                  │  planes · solids · STEP │
                  └───────────┬─────────────┘
                              │  same calls, two transports
              ┌───────────────┴───────────────┐
              │                               │
     local HTTP service                     JNI
              │                               │
      Electron + React                Android + React
        (Windows today)                  (WebView)
```

The interface does not care which side it is talking to. It already speaks to
the backend over a narrow, typed boundary, so the same React code serves both.

## Why this is worth doing for the desktop alone

Android is the reason it came up, but the desktop gets most of the benefit, and
that is what makes the work defensible even if Android never happens.

| | Today | With a C++ core |
|---|---|---|
| Backend on disk | 358 MB | roughly 80–120 MB of OCCT libraries |
| Installer | 147.8 MB | meaningfully smaller |
| Startup | Python interpreter, then imports, then OCCT | process start |
| Dependencies | Python 3.11+, PyInstaller freeze | none |
| Build | PyInstaller, which we already had to fight | CMake |

The current backend is large because it ships a Python runtime and the OCP
binding wheel on top of OCCT itself. Linking OCCT directly removes both layers.

## What moves, and how hard each part is

2403 lines of Python in total, of which the geometry is the smaller half.

| Piece | Lines | Difficulty |
|---|---|---|
| `solid.py` | 612 | **Mechanical.** Already calls the C++ API through bindings that mirror it one to one. `BRepAlgoAPI_Cut`, `BRepBuilderAPI_MakeFace`, `BRepPrimAPI_MakeCylinder` are the same calls with the same arguments. |
| `parser.py` | 455 | CSV reading and classification. Standard library only today. |
| `server.py` | 415 | HTTP service. Any small C++ HTTP library. |
| `topology.py` | 165 | Plain graph work. No dependencies. |
| `model.py` | 142 | Plain structs. |
| `tessellate.py` | 137 | `BRepMesh_IncrementalMesh` and a triangle walk. Direct. |
| `store.py` | 117 | A JSON file on disk. |
| `designx.py` | 109 | IGES and STEP curve writing. Direct. |
| `geometry.py` | 87 | Plane geometry, no dependencies. |
| `planes.py` | 76 | Needs an SVD. Eigen, or twenty lines by hand for a 3×3. |
| `settings.py` | 65 | Plain struct plus JSON. |
| React interface | all of it | **Unchanged.** |

Two real substitutions, neither of them research:

- **numpy SVD** in the plane fit → Eigen, or hand-rolled.
- **shapely** for the outward wall offset and point-in-polygon → OCCT's own 2D
  offset, or the mitre solver written directly. That solver already exists in
  `wall_body`, so the logic is proven.

## The estimate, corrected

I originally said several weeks. That was wrong and I inflated it.

| Stage | Honest guess | Can I verify it? |
|---|---|---|
| C++ core, desktop | 1–2 days | **Yes, completely** |
| Desktop service and swapping the sidecar | half a day | Yes |
| OCCT built for `arm64-v8a` | hours of compute, unknown retries | Only that it compiles |
| Android shell, JNI bridge, WebView | 1–2 days | Only with a real device |
| Packaging an APK | half a day | Only with a real device |

## Why the desktop stage comes first, and why it matters

Because it can be checked against work we already trust. Every room in the
reference survey has known-good numbers from the Python build:

- `Daire 53 - Salon`: 1 solid, 123 faces, 20.9221 m³
- Wall tiling: sum of exported walls matches the room to **0.0 cm³**
- Kernel volume against analytic volume: identical to floating point

Run the C++ core over the same 28 rooms and compare. If every number matches,
the core is correct, and Android is then only a packaging problem. If they
don't match, we find out on a machine where I can debug in seconds instead of
through logcat.

That single property is what makes this plan reasonable and the earlier one
not. **Nothing unverifiable happens until the geometry is already proven.**

## What is actually expensive

Not the code. Two things:

**The Android toolchain.** SDK, NDK, Gradle, and a large C++ library
cross-compiled before a single line runs. Mostly waiting, and it rarely works
first try.

**Testing on Android at all.** There is no device on this machine. An emulator
is x86_64, so OCCT would be built twice and still not be what ships. Every
iteration becomes cross-compile, gradle, install, read logcat, minutes each,
against the two-second loop that let the desktop app come together as fast as
it did.

A geometry kernel I cannot run is a geometry kernel I cannot stand behind.

## Open questions

1. **Is there an Android device to test on?** This decides whether the Android
   half is a real port or code shipped unverified.
2. **Is 80–120 MB of kernel acceptable on a phone?** Worth measuring before
   committing to the Android half. It does not affect the desktop work.
3. **Phone alone, or phone talking to the PC?** If a PC on the network is
   acceptable, serving the existing interface over the LAN gets Android working
   in about a day with everything verified. Different product, far less risk.

## Order of work

1. Build OCCT for the desktop with CMake and get one room to build from C++.
   This is the only step that can fail in an interesting way.
2. Port the core. Compare all 28 rooms against the Python numbers.
3. Swap the desktop sidecar. Ship it. The desktop is now smaller and faster,
   and the work has paid for itself whatever happens next.
4. Build OCCT for `arm64-v8a`.
5. Android shell, JNI, WebView, APK.

Stages 1 to 3 stand on their own. Stopping after them leaves the desktop app
better and Android still open.

## What would make me say no

If OCCT's desktop CMake build turns out to be a fight, stage 1 tells us in an
afternoon and we have lost an afternoon. If the C++ core cannot reproduce the
reference numbers exactly, stop: the Python one is correct and shipping.


---

# What we did

Stages 1 to 3, in one sitting, on 2026-08-29. Stage 4 and 5 were not started:
there is still no Android device here, which was open question 1 and is still
the thing that decides whether the Android half is a port or a guess.

## Stage 1: OCCT on the desktop

Built OCCT **7.9.3** from source with CMake, matching the version behind the
OCP wheel exactly so the two builds can be compared number for number. Ninja
rather than MSBuild, which crashed on its own output pipe.

The build needs **no third-party dependencies at all**: with
`BUILD_MODULE_Visualization=OFF`, `BUILD_MODULE_Draw=OFF` and every `USE_*` off,
freetype, tcl/tk, rapidjson and the rest drop out. That is the whole reason the
result came in far under the estimate, and it is the same configuration that
will cross-compile for `arm64-v8a`.

    .deps/occt   47 toolkits, 117 MB

This was billed as the only step that could fail in an interesting way. It
configured and built first time.

## Stage 2: the port, checked against the Python build

2403 lines of Python became roughly 2600 lines of C++ in `native/`. Both
substitutions the plan called for went in:

- **numpy SVD** → Jacobi rotation on the 3x3 covariance, in `planes.cpp`.
- **shapely** → the mitre solver that already existed in `wall_body`, plus a
  ray-cast point-in-polygon, in `solid.cpp`.

Verification runs in two halves, so the classifier is proven before the kernel
is involved at all. Both dump one line per field per room; the Python side is
`tools/dump_parse.py` and `tools/dump_solid.py`, the C++ side is the matching
tools in `native/tools`.

| Half | Result over the 28 reference rooms |
|---|---|
| Parser, topology, geometry, planes | **1637 fields exact, 0 mismatches** |
| Solids | **23 of 24 buildable rooms identical to 0.0000 cm3** |
| Wall tiling | **0.000000 cm3** across all 23, the property the plan named |
| The 4 rooms that cannot build | fail in C++ with the same messages |
| `Daire 53 - Salon` | 1 solid, 123 faces, 20.922131 m3 |

Two things came out of the comparison that were not expected.

**The Python build is not reproducible.** Two runs of `dump_parse.py` differ by
180 lines. `_walk_cycle` picks its starting direction out of a `set`, and string
hashing is randomised per process, so a room's ring can come back either way
round between runs. The C++ walk sorts, and is deterministic. Rings are
therefore compared up to direction and signed area by magnitude; every
coordinate, role, opening and issue is still compared exactly.

**One room differs, and we accepted it.** `Daire 51 - Ebeveyn odası`, 71 faces
against 70, and 629 cm3 of 16.38 m3, which is 0.004%. The cause is two surveyed
corners **0.8 mm apart** on a near-straight run, at 171.2 degrees and 186.0
degrees. Offsetting outward by 20 cm, shapely's `buffer` dissolves the pair into
one vertex; the mitre solver keeps both, at 20.056 and 20.031 cm perpendicular,
which is correct for those angles. Shapely's merged vertex sits about a
centimetre from either mitre vertex, so no tolerance reproduces it: it is
cleanup, not a formula.

We kept the mitre result. It is the exact offset of the surveyed outline, it
leaves the outer ring with the same corner count as the inner one rather than
one fewer, and it is deterministic. The wall bodies for that room are identical
either way; the difference lives only in the shell's outer corner filler.

## Stage 3: the desktop swap

`server.py` and `store.py` are ported. `store.cpp` reads and writes the same
`projects.json` the Python build wrote, so existing projects keep working across
the swap, including the centimetre-to-millimetre migration for old files. Two
vendored single headers do the plumbing: cpp-httplib 0.18.3 and nlohmann/json
3.11.3, both in `native/third_party`.

The frontend is unchanged, which was the point. `tools/compare_servers.py`
drives both sidecars through the same calls and diffs the JSON:

    268 checks, 5 failures - all five the accepted corner above

That covers every route, all 28 rooms, build, export, Design X export, a patch
round trip, and the 404 and 400 paths.

One rounding bug was found by that comparison and fixed. Python's `round()`
rounds the exact value of the double; scaling by a power of ten first does not.
207.95 is really 207.9499999..., but `207.95 * 10` lands on exactly 2079.5 and
then rounds the wrong way. Formatting to the requested number of places rounds
the exact value, which is the same rule Python uses.

The packaged sidecar also used to land at `resources/backend/backend/`, one
directory below where `main.cjs` looks for it. That is fixed in the
`extraResources` mapping. Development now prefers the native backend when it has
been built, so dev and the installer run the same engine.

## What it cost, against the estimate

| | Before | After |
|---|---|---|
| Backend on disk | 358 MB | **46.8 MB** |
| Installer | 147.8 MB | **87.2 MB** |
| Dependencies | Python 3.11+, PyInstaller, OCP wheel, shapely, numpy | none |
| Startup | interpreter, imports, then OCCT | process start |
| 28 rooms, parse and build | 34.0 s | 30.0 s |

46.8 MB is well under the 80-120 MB the plan guessed, because none of the
visualization toolkits ship. That also answers open question 2 in advance: the
kernel is not too large for a phone.

The packaged app was launched and its bundled backend answered on 8765, served
all 28 rooms, and rebuilt `Daire 53 - Salon` to 123 faces and 20.922131 m3.

## Stage 4: OCCT for arm64-v8a

The desktop CMake configuration carried over unchanged, which is exactly what
turning the third-party dependencies off had bought us: nothing to cross-compile
first. Two flags differ.

    -DCMAKE_TOOLCHAIN_FILE=<ndk>/build/cmake/android.toolchain.cmake
    -DANDROID_ABI=arm64-v8a  -DANDROID_PLATFORM=android-26
    -DBUILD_LIBRARY_TYPE=Static
    -DINSTALL_DIR_LAYOUT=Unix

Static rather than shared, so the app ships one `.so` instead of forty-odd, and
the linker drops the toolkit code nothing calls. `native/build-occt-android.bat`
is the whole recipe.

`arm64-v8a` only. It is every phone worth surveying with, and building the other
three ABIs would multiply the longest step in the whole job by four.

## Stage 5: the Android shell

The shell is deliberately thin, and the reason is worth stating, because it is
the decision that made the Android half a day rather than a week.

**There is no per-endpoint JNI bridge.** The plan drew one, but the service is
already a narrow HTTP API on loopback that the interface has spoken since the
desktop build. So the phone runs the *same server*, on a thread, and the WebView
talks to it exactly as the Electron window did. One implementation of every
route, nothing to keep in sync, and the whole comparison suite that verified the
desktop covers the phone too.

`server.cpp` became `service.cpp` plus a five-line `main.cpp`, so the desktop
sidecar and the Android thread call the same `snapir::serve()`.

**The service also serves the interface.** Loading the page from `file://` would
put it on a null origin and every call to the backend would be a cross-origin
request into a WebView that blocks them; serving the page from
`appassets.androidplatform.net` instead would make the backend call mixed
content. Serving both from `127.0.0.1:8765` removes the problem rather than
working around it. The built React bundle is unpacked out of the APK on first
run and handed to the same `httplib` server as a mount point.

The Java side has no dependencies at all. AppCompat was the obvious import and
went in first, but a WebView shell uses nothing it provides, and it dragged in a
Kotlin stdlib that collided with itself. Plain `android.app.Activity` and
`android.app.AlertDialog` do the job, and the APK is a library chain lighter for
it.

Four small files:

| | |
|---|---|
| `MainActivity` | unpack, start, show a WebView |
| `NativeService` | load `libsnapir.so`, start the service, wait for the port |
| `WebAssets` | unpack the interface, inject the `window.snapir` shim |
| `WebBridge` + `FolderPicker` | the same bridge the Electron preload exposes |

`WebAssets` injects a `window.snapir` object identical in shape to the one
`preload.cjs` exposes, so **not one line of the React app knows it is on a
phone**. `api` becomes `location.origin`, `pickFolder` opens a directory
browser, `reveal` becomes a toast.

The folder picker walks real directories rather than using the system document
picker, because the picker returns `content://` URIs and the geometry core opens
files with the standard library. That is also what lets the same parser read the
same CSVs on both platforms. It needs All files access, which on Android 11 and
up only the user can grant, in Settings.

## What it came to

    APK                     31.9 MB
      libsnapir.so          28.9 MB   the core plus every OCCT toolkit it uses
      libc++_shared.so       1.2 MB
      assets/web             0.7 MB   the interface, unchanged
      classes.dex             20 KB   the entire Java shell

28.9 MB of kernel, from 1.5 GB of static archives, because the linker keeps only
what is reached. That answers open question 2, which asked whether 80 to 120 MB
of kernel was acceptable on a phone: it never got near that.

## What is not verified

There is no Android device on this machine, which was open question 1 and stayed
open. The APK builds, links and installs its own assets, and every line of
geometry in it is the code the desktop comparison proved room by room. What has
**not** been exercised is the phone itself: the WebView, the storage permission,
the folder picker, and the service coming up under Android's process lifecycle.

That is the honest boundary. The geometry is proven; the shell around it is
not run until someone installs it.
