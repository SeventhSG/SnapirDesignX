"""Build the Android app: interface into assets, then Gradle.

    python tools/build_android.py [debug|release]

The geometry kernel has to exist first; build it with
native/build-occt-android.bat, which is a long cross-compile and is left as
its own step on purpose.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPS = ROOT / ".deps" / "android"
JDK = DEPS / "jdk-17.0.13+11"
SDK = DEPS / "sdk"
GRADLE = DEPS / "gradle-8.7" / "bin" / "gradle.bat"
WEB_SRC = ROOT / "app" / "dist"
WEB_DST = ROOT / "android" / "app" / "src" / "main" / "assets" / "web"


def stage_web() -> None:
    """The same built interface the desktop ships, unchanged."""
    if not (WEB_SRC / "index.html").is_file():
        raise SystemExit(f"No built interface at {WEB_SRC}. Run: cd app && npm run build")
    if WEB_DST.exists():
        shutil.rmtree(WEB_DST)
    shutil.copytree(WEB_SRC, WEB_DST)
    n = sum(1 for _ in WEB_DST.rglob("*") if _.is_file())
    print(f"staged interface -> {WEB_DST.relative_to(ROOT)} ({n} files)")


def main(variant: str = "release") -> int:
    if not (ROOT / ".deps" / "occt-android").is_dir():
        raise SystemExit("No arm64 kernel. Run native/build-occt-android.bat first.")

    stage_web()

    env = dict(os.environ)
    env["JAVA_HOME"] = str(JDK)
    env["ANDROID_HOME"] = str(SDK)
    env["ANDROID_SDK_ROOT"] = str(SDK)

    task = "assembleRelease" if variant == "release" else "assembleDebug"
    cmd = [str(GRADLE), "--no-daemon", "-p", str(ROOT / "android"), task]
    print(" ".join(cmd))
    return subprocess.call(cmd, env=env)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "release"))
