# Moving the core to C++

Status: **not now.** v1.0 ships as it is. This is the plan for when we pick it
up, and the reasoning behind it, so neither of us has to reconstruct it later.

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

| Piece | Lines | Difficulty |
|---|---|---|
| `solid.py` | ~480 | **Mechanical.** Already calls the C++ API through bindings that mirror it one to one. `BRepAlgoAPI_Cut`, `BRepBuilderAPI_MakeFace`, `BRepPrimAPI_MakeCylinder` are the same calls with the same arguments. |
| `topology.py` | ~180 | Plain graph work. No dependencies. |
| `parser.py` | ~330 | CSV reading and classification. Standard library only today. |
| `planes.py` | ~70 | Needs an SVD. Eigen, or twenty lines by hand for a 3×3. |
| `geometry.py` | ~110 | Plane geometry, no dependencies. |
| `tessellate.py` | ~120 | `BRepMesh_IncrementalMesh` and a triangle walk. Direct. |
| `server.py`, `store.py` | ~340 | HTTP service and a JSON file. Any small C++ HTTP library. |
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
