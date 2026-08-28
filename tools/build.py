"""Batch build: survey folder in, STEP solids out.

    python tools/build.py "C:/path/to/survey" [out_dir]
"""
from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from snapir.parser import read_project
from snapir.settings import BuildSettings
from snapir.solid import BuildError, build_room, export_step, solid_stats


def main(folder: str, out: str = "out") -> int:
    cfg = BuildSettings(output_dir=out)
    proj = read_project(folder)
    built = skipped = failed = 0

    print(f"{proj.name}: {len(proj.rooms)} rooms -> {out}\n")
    for r in proj.rooms:
        if r.has_errors:
            print(f"  skip   {r.name:<30} {r.issues[0].message[:52]}")
            skipped += 1
            continue
        try:
            sink = io.StringIO()
            with contextlib.redirect_stdout(sink):
                shape = build_room(r, cfg)
                stats = solid_stats(shape)
                path = export_step(shape, Path(out) / f"{r.name}.step", cfg.step_schema)
            print(f"  built  {r.name:<30} {stats['faces']:>3} faces  "
                  f"{stats['volume_m3']:>6.2f} m3  {len(r.openings)} openings")
            built += 1
        except BuildError as e:
            print(f"  FAIL   {r.name:<30} {e}")
            failed += 1

    print(f"\n{built} built, {skipped} need review, {failed} failed.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "out"))
