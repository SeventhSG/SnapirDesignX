"""Reference numbers for the C++ port, parsing half.

Prints one line per field per room. native/tools/dump_parse.cpp prints the same
lines, so a plain diff decides whether the port is faithful.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from snapir.geometry import perimeter, polygon_area, signed_area
from snapir.parser import read_project


def num(v: float) -> str:
    return f"{v:.6f}"


def opt(v) -> str:
    return "None" if v is None else num(v)


def main(folder: str) -> None:
    out = []
    for r in read_project(folder).rooms:
        n = r.name
        def emit(key, value):
            out.append(f"{n}|{key}|{value}")

        emit("outline_source", r.outline_source)
        emit("floor_z", opt(r.floor_z))
        emit("ceiling_z", opt(r.ceiling_z))
        emit("ceiling_height", opt(r.ceiling_height()))
        emit("n_points", len(r.points))
        emit("n_outline", len(r.outline))
        emit("n_ceiling", len(r.ceiling))
        emit("n_openings", len(r.openings))
        emit("n_controls", len(r.controls))
        emit("n_segments", len(r.segments))
        emit("n_links", len(r.links))
        emit("station", r.station.name if r.station else "None")

        ring = [p.xy for p in r.outline]
        emit("area", num(polygon_area(ring)))
        emit("signed_area", num(signed_area(ring)))
        emit("perimeter", num(perimeter(ring)))

        for i, p in enumerate(r.outline):
            emit(f"outline[{i}]",
                 f"{p.name} {num(p.x)} {num(p.y)} {num(p.z)} {p.index}")
        for i, p in enumerate(r.ceiling):
            emit(f"ceiling[{i}]", f"{p.name} {num(p.z)}")
        for i, o in enumerate(r.openings):
            emit(f"opening[{i}]",
                 f"{o.kind} w={num(o.width)} sill={num(o.sill)} head={num(o.head)} "
                 f"L={num(o.left.x)},{num(o.left.y)} R={num(o.right.x)},{num(o.right.y)}")
        for i, s in enumerate(r.issues):
            emit(f"issue[{i}]", f"{s.severity} {s.code}")
        for p in r.points:
            emit(f"role:{p.name}", p.role.value)

    sys.stdout.write("\n".join(out) + "\n")


if __name__ == "__main__":
    main(sys.argv[1])
