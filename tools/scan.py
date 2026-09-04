"""Batch report over a folder of Leica iCON room exports.

    python tools/scan.py "C:\path\to\survey"
"""
from __future__ import annotations

import sys
# The C++ side writes UTF-8. Windows hands Python a cp1252 stdout by default,
# which cannot encode a Turkish room name and kills the dump before it prints
# anything - so the two halves could not be compared at all on the machine the
# port is developed on.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from snapir.geometry import polygon_area          # noqa: E402
from snapir.parser import read_project            # noqa: E402

SEV = {"error": "ERR ", "warning": "WARN", "info": "note"}


def main(folder: str) -> int:
    proj = read_project(folder)
    if not proj.rooms:
        print(f"No room CSVs found in {folder}")
        return 1

    print(f"{proj.name}  ({len(proj.rooms)} rooms)\n")
    hdr = f"{'ROOM':<32}{'PTS':>4}{'AREA m2':>9}{'CEIL cm':>9}{'OPEN':>6}  STATUS"
    print(hdr)
    print("-" * len(hdr))

    blocked = 0
    for r in proj.rooms:
        area = polygon_area([p.xy for p in r.outline]) / 10_000 if len(r.outline) > 2 else 0.0
        h = r.ceiling_height()
        status = "ready" if not r.has_errors else "NEEDS REVIEW"
        if r.has_errors:
            blocked += 1
        print(f"{r.name:<32}{len(r.outline):>4}{area:>9.2f}"
              f"{(f'{h:.0f}' if h else '-'):>9}{len(r.openings):>6}  {status}")

    print()
    for r in proj.rooms:
        if not r.issues:
            continue
        print(f"  {r.name}")
        for i in r.issues:
            pts = f"  [{', '.join(i.points[:8])}{'...' if len(i.points) > 8 else ''}]" if i.points else ""
            print(f"    {SEV[i.severity]}  {i.message}{pts}")
        print()

    print(f"{len(proj.rooms) - blocked}/{len(proj.rooms)} rooms ready to build.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
