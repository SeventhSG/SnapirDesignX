"""Create the GitHub release for a tag and upload the installer.

Uses the credential already stored for github.com, so no token is handled here
beyond asking git for it.

    python tools/publish_release.py v1.0.0 app/release/SnapirDesignX-1.0.0-setup.exe
"""
from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = "SeventhSG/SnapirDesignX"
API = "https://api.github.com"

NOTES = """\
First release of Snapir Design X.

Turns Leica iCON room surveys into solid bodies. The surveyor's own drawn lines
describe the room, so the outline, the ceiling ring, the openings and the
floor-to-ceiling links are read rather than guessed.

**What it does**

- Reads a folder of Leica iCON room exports and classifies every point
- Builds each room as one watertight B-rep solid: walls, floor and ceiling,
  with the room empty inside
- Fits a real plane through the measured ceiling corners instead of averaging
- Cuts doors and windows through the wall with their reveals
- Builds sockets as back boxes or recesses, plumbing as pipe stubs or sleeves,
  and joins sockets that sit shoulder to shoulder into one outlet
- Exports STEP AP214 in millimetres, per room or per wall
- Exports IGES or STEP curves for Geomagic Design X when you would rather
  finish there

**Editing**

Plan and 3D sketch views, a line tool, layer reassignment, point and line
deletion, and an outline editor for the rooms the survey left open.

**Interface**

English and Turkish, light and dark, an inside camera and a see-through mode.

**Installing**

Download `SnapirDesignX-1.0.0-setup.exe` and run it. The installer is not code
signed, so Windows SmartScreen will ask you to confirm: choose More info, then
Run anyway.
"""


def credential() -> str:
    """The GitHub token git already has for this remote."""
    out = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n",
        capture_output=True, text=True, check=True).stdout
    for line in out.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1]
    raise SystemExit("No stored GitHub credential found.")


def call(url: str, token: str, data=None, method=None, ctype=None):
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "snapir-release")
    if ctype:
        req.add_header("Content-Type", ctype)
    with urllib.request.urlopen(req) as r:
        body = r.read()
    return json.loads(body) if body else {}


def main(tag: str, asset: str) -> int:
    token = credential()
    path = Path(asset)
    if not path.is_file():
        raise SystemExit(f"Installer not found: {path}")

    try:
        rel = call(f"{API}/repos/{REPO}/releases/tags/{tag}", token)
        print(f"release {tag} already exists (id {rel['id']})")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        rel = call(
            f"{API}/repos/{REPO}/releases", token,
            data=json.dumps({
                "tag_name": tag, "name": f"Snapir Design X {tag}",
                "body": NOTES, "draft": False, "prerelease": False,
            }).encode(), method="POST", ctype="application/json")
        print(f"created release {tag} (id {rel['id']})")

    # Replace the asset if a previous attempt left one behind.
    for a in rel.get("assets", []):
        if a["name"] == path.name:
            call(f"{API}/repos/{REPO}/releases/assets/{a['id']}", token,
                 method="DELETE")
            print(f"removed previous {a['name']}")

    upload = rel["upload_url"].split("{")[0] + f"?name={path.name}"
    size = path.stat().st_size
    print(f"uploading {path.name} ({size / 1e6:.1f} MB)...")
    out = call(upload, token, data=path.read_bytes(), method="POST",
               ctype="application/octet-stream")
    print(f"uploaded: {out['browser_download_url']}")
    print(f"release:  {rel['html_url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
