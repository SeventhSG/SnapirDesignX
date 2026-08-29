"""Run the reference survey inside a booted simulator and check the numbers.

    python3 tools/verify_ios_sim.py <Snapir.app> <fixture-dir> [--shot out.png]

macOS only, and the app must already be built for the simulator.

This is not a smoke test. An iOS Simulator app shares the host's network
stack, so the geometry service the app starts on 127.0.0.1:8765 inside the
simulator is the same 127.0.0.1:8765 the runner can reach. That means CI drives
the real HTTP API -- the one tools/compare_servers.py drives against the
desktop -- rather than looking at a screenshot and hoping.

A room whose volume moved is a failed build, not a warning.
"""
from __future__ import annotations

import argparse
import json
import plistlib
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8765"

# The known-good room, from docs and from every desktop run since the port.
# Numbers are the C++ core's, which match the Python reference exactly.
EXPECTED = {
    "name": "Daire 53 - Salon",
    "solids": 1,
    "faces": 123,
    "volume_m3": 20.922131,
}
VOLUME_TOLERANCE = 1e-6


def sh(*args: str, check: bool = True) -> str:
    p = subprocess.run(args, capture_output=True, text=True)
    if check and p.returncode:
        raise SystemExit(f"{' '.join(args)}\n{p.stdout}{p.stderr}")
    return p.stdout.strip()


def call(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def wait_for_service(timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(BASE + "/health", timeout=2):
                return True
        except Exception:
            time.sleep(0.5)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("app")
    ap.add_argument("fixture")
    ap.add_argument("--shot")
    args = ap.parse_args()

    app = Path(args.app).resolve()
    fixture = Path(args.fixture).resolve()
    if not app.is_dir():
        raise SystemExit(f"No app bundle at {app}")
    if not fixture.is_dir():
        raise SystemExit(f"No fixture at {fixture}")

    bundle_id = plistlib.loads((app / "Info.plist").read_bytes())["CFBundleIdentifier"]

    print(f"==> installing {app.name} ({bundle_id})")
    sh("xcrun", "simctl", "install", "booted", str(app))

    # The survey has to be inside the container, because that is the only place
    # the sandboxed core can read. On a device the document picker copies it in;
    # here we put it where the picker would have.
    container = Path(sh("xcrun", "simctl", "get_app_container", "booted",
                        bundle_id, "data"))
    surveys = container / "Documents" / "surveys" / fixture.name
    if surveys.exists():
        shutil.rmtree(surveys)
    surveys.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(fixture, surveys)
    n = sum(1 for p in surveys.rglob("*") if p.is_file())
    print(f"==> staged {n} files at {surveys}")

    print("==> launching")
    sh("xcrun", "simctl", "launch", "booted", bundle_id)

    if not wait_for_service(90):
        sh("xcrun", "simctl", "spawn", "booted", "log", "show", "--last", "2m",
           "--predicate", 'process == "Snapir"', check=False)
        raise SystemExit(f"The geometry service never answered on {BASE}")
    print(f"==> service up on {BASE}")

    status, project = call(
        "POST", "/projects", {"name": fixture.name, "folder": str(surveys)}
    )
    if status != 200:
        raise SystemExit(f"POST /projects -> {status} {project}")
    pid = project.get("id")
    if not pid:
        raise SystemExit(f"No project id in {project}")

    status, rooms = call("GET", f"/projects/{pid}/rooms")
    if status != 200:
        raise SystemExit(f"GET rooms -> {status} {rooms}")
    names = [r["name"] for r in rooms["rooms"]]
    print(f"==> {len(names)} rooms: {', '.join(names)}")

    target = EXPECTED["name"]
    if target not in names:
        raise SystemExit(f"The fixture has no room called {target!r}. Found: {names}")

    q = urllib.parse.quote(target)
    status, built = call("POST", f"/projects/{pid}/rooms/{q}/build")
    if status != 200:
        raise SystemExit(f"build {target} -> {status} {built}")

    # stats is {solids, shells, faces, volume_m3}, the volume already rounded to
    # six places by the service, which is the precision the reference is quoted
    # at. The mesh is checked too: a solid that tessellates to a different face
    # count is a different solid, whatever the volume says.
    stats = built["stats"]
    mesh_faces = len(built["mesh"]["faces"])

    problems = []
    if stats.get("solids") != EXPECTED["solids"]:
        problems.append(f"solids {stats.get('solids')} != {EXPECTED['solids']}")
    if stats.get("faces") != EXPECTED["faces"]:
        problems.append(f"faces {stats.get('faces')} != {EXPECTED['faces']}")
    if mesh_faces != EXPECTED["faces"]:
        problems.append(f"mesh faces {mesh_faces} != {EXPECTED['faces']}")
    volume = stats.get("volume_m3")
    if volume is None:
        problems.append(f"no volume_m3 in stats: {stats}")
    elif abs(volume - EXPECTED["volume_m3"]) > VOLUME_TOLERANCE:
        problems.append(f"volume {volume:.6f} != {EXPECTED['volume_m3']:.6f}")

    print(f"==> {target}: {stats.get('solids')} solid(s), "
          f"{stats.get('faces')} faces, {volume} m3")

    if args.shot:
        Path(args.shot).parent.mkdir(parents=True, exist_ok=True)
        sh("xcrun", "simctl", "io", "booted", "screenshot", args.shot)
        print(f"==> screenshot {args.shot}")

    if problems:
        print("FAILURES:")
        for p in problems:
            print(f"  {p}")
        return 1
    print("FAILURES: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
