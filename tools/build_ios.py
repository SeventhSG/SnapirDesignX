"""Build the iOS app: interface into the bundle, then CMake and Xcode.

    python3 tools/build_ios.py [simulator|device|both]

macOS only. The geometry kernel has to exist first; build it with
native/build-occt-ios.sh, which is a long cross-compile and is left as its own
step on purpose.

Simulator is the default because without a signing certificate it is the only
build that will ever actually run. The device build proves it compiles and
links, and nothing more.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPS = ROOT / ".deps"
WEB_SRC = ROOT / "app" / "dist"
IOS = ROOT / "ios"
WEB_DST = IOS / "Resources" / "web"
CATALOG = IOS / "Resources" / "Assets.xcassets"
LOGO = ROOT / "assets" / "Snapir Design BG - Logo.png"

SLICES = {
    # name        sysroot             OCCT prefix
    "simulator": ("iphonesimulator", DEPS / "occt-iossim"),
    "device": ("iphoneos", DEPS / "occt-ios"),
}


def stage_web() -> None:
    """The same built interface the desktop and the APK ship, unchanged."""
    if not (WEB_SRC / "index.html").is_file():
        raise SystemExit(f"No built interface at {WEB_SRC}. Run: cd app && npm run build")
    if WEB_DST.exists():
        shutil.rmtree(WEB_DST)
    shutil.copytree(WEB_SRC, WEB_DST)
    n = sum(1 for p in WEB_DST.rglob("*") if p.is_file())
    print(f"staged interface -> {WEB_DST.relative_to(ROOT)} ({n} files)")


def stage_icon() -> None:
    """A single 1024 icon, which Xcode 14 and later expand to every slot.

    Generated rather than committed: it is a resize of an asset already in the
    repository, and sips only exists on the machine that can build this anyway.
    """
    if CATALOG.exists():
        shutil.rmtree(CATALOG)
    appicon = CATALOG / "AppIcon.appiconset"
    appicon.mkdir(parents=True)

    (CATALOG / "Contents.json").write_text(
        json.dumps({"info": {"author": "snapir", "version": 1}}, indent=2)
    )
    (appicon / "Contents.json").write_text(
        json.dumps(
            {
                "images": [
                    {
                        "filename": "icon-1024.png",
                        "idiom": "universal",
                        "platform": "ios",
                        "size": "1024x1024",
                    }
                ],
                "info": {"author": "snapir", "version": 1},
            },
            indent=2,
        )
    )

    if not LOGO.is_file():
        raise SystemExit(f"No icon source at {LOGO}")

    # An app icon may not carry an alpha channel. sips has no flatten flag, so
    # the round trip through JPEG is the flatten: it cannot represent alpha, so
    # coming back out as PNG the channel is simply gone.
    flat = appicon / "icon-1024.jpg"
    subprocess.check_call(
        ["sips", "-s", "format", "jpeg", "-s", "formatOptions", "best",
         "-z", "1024", "1024", str(LOGO), "--out", str(flat)],
        stdout=subprocess.DEVNULL,
    )
    subprocess.check_call(
        ["sips", "-s", "format", "png", str(flat),
         "--out", str(appicon / "icon-1024.png")],
        stdout=subprocess.DEVNULL,
    )
    flat.unlink()
    print(f"staged icon -> {appicon.relative_to(ROOT)}")


def build(slice_name: str) -> int:
    sysroot, occt = SLICES[slice_name]
    if not (occt / "lib" / "libTKernel.a").is_file():
        raise SystemExit(
            f"No {slice_name} kernel at {occt}. Run native/build-occt-ios.sh first."
        )

    build_dir = ROOT / "out" / f"ios-{slice_name}"
    configure = [
        "cmake", "-S", str(IOS), "-B", str(build_dir), "-G", "Xcode",
        "-DCMAKE_SYSTEM_NAME=iOS",
        f"-DCMAKE_OSX_SYSROOT={sysroot}",
        "-DCMAKE_OSX_ARCHITECTURES=arm64",
        "-DCMAKE_OSX_DEPLOYMENT_TARGET=15.0",
        f"-DOCCT_IOS_ROOT={occt}",
    ]
    print(" ".join(configure))
    rc = subprocess.call(configure)
    if rc:
        return rc

    compile_cmd = ["cmake", "--build", str(build_dir), "--config", "Release"]
    print(" ".join(compile_cmd))
    rc = subprocess.call(compile_cmd)
    if rc:
        return rc

    app = build_dir / f"Release-{sysroot}" / "Snapir.app"
    if not app.is_dir():
        raise SystemExit(f"Build reported success but there is no bundle at {app}")
    print(f"built {app}")
    return 0


def main(which: str = "simulator") -> int:
    if sys.platform != "darwin":
        raise SystemExit("iOS builds are macOS only. This runs on the CI runner.")

    stage_web()
    stage_icon()

    targets = list(SLICES) if which == "both" else [which]
    for name in targets:
        if name not in SLICES:
            raise SystemExit(f"Unknown target {name}. One of: simulator, device, both")
        rc = build(name)
        if rc:
            return rc
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "simulator"))
