"""Stage the C++ geometry backend for the Electron installer.

    cd app && npm run backend

Replaces the PyInstaller freeze. The backend is now one executable plus the
Open CASCADE toolkits it links, so there is no Python runtime, no OCP wheel and
no frozen import graph to ship.

Everything lands in app/resources/backend, which electron-builder copies to
resources/backend inside the installed app, exactly where main.cjs looks.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "native"
BUILD = NATIVE / "build"
OCCT_BIN = ROOT / ".deps" / "occt" / "win64" / "vc14" / "bin"
STAGE = ROOT / "app" / "resources" / "backend"


def mb(n: int) -> str:
    return f"{n / 1_048_576:.1f} MB"


def tree_size(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def main() -> int:
    exe = BUILD / "snapir-server.exe"
    if not exe.exists():
        print(f"No {exe}.\nBuild it first:  native\\build-full.bat")
        return 1
    if not OCCT_BIN.is_dir():
        print(f"No OCCT runtime at {OCCT_BIN}.")
        return 1

    was = tree_size(STAGE) if STAGE.exists() else 0
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)

    shutil.copy2(exe, STAGE / exe.name)
    dlls = sorted(OCCT_BIN.glob("*.dll"))
    for d in dlls:
        shutil.copy2(d, STAGE / d.name)

    now = tree_size(STAGE)
    print(f"staged {STAGE.relative_to(ROOT)}")
    print(f"  snapir-server.exe + {len(dlls)} OCCT toolkits")
    print(f"  {mb(was)} -> {mb(now)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
