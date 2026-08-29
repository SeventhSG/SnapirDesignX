# Snapir Design X 1.1.0

The geometry core now runs on Android. Same C++, same Open CASCADE, same
numbers as the desktop.

## Android

`SnapirDesignX-1.1.0.apk`, `arm64-v8a`, Android 8.0 or newer.

The phone runs the identical geometry core the desktop does, compiled for
64-bit ARM. There is no cut-down mobile version of the maths: the same parser,
the same plane fitting, the same Open CASCADE 7.9.3 kernel, the same STEP and
IGES writers.

The app is deliberately thin around it. The core already spoke a small HTTP API
to the desktop interface, so the phone runs that same service on loopback and
shows the same React interface in a WebView. Nothing in the interface knows it
is on a phone.

On first launch Android will ask for **All files access**. Surveys arrive as
ordinary folders copied off the instrument, and the app reads them where they
are rather than in its own sandbox. Only Settings can grant it.

**Not yet verified on hardware.** The APK builds, links and installs its
assets, and every line of geometry in it is the code the desktop comparison
proved room by room against the previous Python build. What has not been
exercised is the phone itself: the WebView, the storage permission, the folder
picker, and the service under Android's process lifecycle.

## Desktop

`SnapirDesignX-1.1.0-setup.exe`, Windows 10/11, 64-bit.

Unchanged in behaviour from 1.0.0. The backend was reorganised so the desktop
sidecar and the Android service are one implementation rather than two, and the
version it reports moved to 1.1.0.

| | 0.x | 1.1.0 |
|---|---|---|
| Backend on disk | 358 MB | 46.8 MB |
| Installer | 147.8 MB | 87.2 MB |
| Dependencies | Python, PyInstaller, OCP, shapely, numpy | none |

## Verification

Both engines are still checked against each other over the 28-room reference
survey on every change:

- 1638 parser fields exact, 0 mismatches
- 23 of 24 buildable rooms identical to 0.0000 cm3
- wall tiling 0.000000 cm3
- 268 API checks across every route, 5 differences, all in one room

The one room, `Daire 51 - Ebeveyn odasi`, differs by 629 cm3 of 16.38 m3
(0.004%) where two surveyed corners sit 0.8 mm apart. The mitre solver keeps
both corners at the exact offset instead of dissolving them, which is the
correct offset of the surveyed outline. It is written up in `docs/ANDROID.md`.

The installer is unsigned, and so is the APK, so both will ask once before
installing.
