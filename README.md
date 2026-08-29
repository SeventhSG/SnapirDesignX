# Snapir Design X

Leica iCON room surveys to solid bodies. Interior volumes, exact B-rep out, no
mesh anywhere in the chain.

## Status

Working end to end on real survey data: parse, classify, fit planes, build the
shell, export. 24 of the 28 rooms in the reference job build with no human
input; the other four have real problems in the data and say so.

## Export formats

Every format on offer is exact B-rep. Planes stay planes and the surveyed
corner stays where the instrument put it.

| Format | Extension | Opens in |
|---|---|---|
| STEP, schema AP203 / AP214 / AP242 | `.step` | SolidWorks, Geomagic Design X, Rhino, Revit, Inventor, Fusion, CATIA |
| IGES 5.3 solids | `.igs` | SolidWorks, Geomagic Design X, Rhino, older CAD |
| BREP | `.brep` | Open CASCADE tools, and Snapir itself |

`native/build/check_export` proves the claim rather than repeating it: every
room is built, written in each format, read back through the same kernel, and
the face count and volume are compared with the body it came from. On the
28-room reference survey STEP and BREP round-trip at zero volume drift; IGES
loses about 1e-9 m3 to its own ASCII precision, roughly a thousandth of a cubic
millimetre.

**No mesh format is offered.** STL, OBJ, PLY and glTF all replace the surveyed
corner with a triangle and a tolerance, which is the one thing this tool exists
not to do.

**`.sldprt` cannot be written**, by Snapir or by anything else outside
SolidWorks: the format is closed and undocumented. The same is true of
Parasolid `.x_t` and ACIS `.sat`, which additionally need a paid licence.
SolidWorks imports STEP and IGES natively, so AP242 is the route in.

The geometry core is C++ linked against Open CASCADE. It runs behind the
Windows desktop app and, unchanged, inside the Android app and the iOS app.

## What runs where

| | |
|---|---|
| `native/` | the geometry core and the local HTTP service, C++ |
| `app/` | the interface, React, and the Electron shell around it |
| `android/` | the Android shell: the same service on a thread, in a WebView |
| `ios/` | the iOS shell: the same again, in a WKWebView |
| `snapir/` | the original Python implementation, kept as the reference |

The Python package is not dead code. It is what every change to the C++ core is
checked against, room by room, by the three tools in `tools/`.

## Build the desktop app

```bash
native\build-full.bat           # OCCT for Windows, then the core and sidecar
python tools/bundle_backend.py  # stage the sidecar for the installer
cd app && npm install && npm run dist
```

The first run of `build-full.bat` clones and builds Open CASCADE 7.9.3, which
takes a while. Everything after it is quick.

## Build the Android app

```bash
native\build-occt-android.bat   # OCCT for arm64-v8a, static
cd app && npm run build         # the interface
python tools/build_android.py   # assets, then Gradle
```

Needs a JDK, the Android SDK and NDK r27. `arm64-v8a` only.

## Build the iOS app

macOS only, so in practice this happens on the CI runner
(`.github/workflows/ios.yml`) rather than anywhere local.

```bash
bash native/build-occt-ios.sh      # OCCT for device and simulator, static
cd app && npm ci && npm run build  # the interface
python3 tools/build_ios.py both    # bundle, then CMake and Xcode
```

Universal, iPad first, `arm64` only. Unsigned: there is no Apple Developer
account, so the simulator build is the one that runs and the device build only
proves it links.

## Check a change

Nothing in the geometry core is trusted until it reproduces the Python build
over the reference survey:

```bash
python tools/dump_parse.py "C:/path/to/survey" > py.txt
native\build\dump_parse.exe "C:/path/to/survey" > cpp.txt
python tools/compare_dumps.py py.txt cpp.txt

python tools/compare_servers.py http://127.0.0.1:8767 http://127.0.0.1:8766 "C:/path/to/survey"
```

`tools/dump_solid.py` and `native\build\dump_solid.exe` do the same for solids,
volumes and the wall tiling. `native\build\check_openings.exe` reports any door
or window that was found but carved nothing.

## Command line

```bash
python tools/scan.py "C:/path/to/survey/folder"    # per-room report
python tools/build.py "C:/path/to/survey/folder" out   # one STEP body per room
```

## Requirements

Python 3.11 or newer for the reference implementation and the tools:

```bash
pip install -r requirements.txt
```

The parser and geometry layer need nothing but the standard library.

See [SPEC.md](SPEC.md) for the data format and the classification rules,
[docs/ANDROID.md](docs/ANDROID.md) for why the core moved to C++ and how the
Android app is put together, and [docs/IOS.md](docs/IOS.md) for what iOS does
differently and why.
