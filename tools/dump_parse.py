"""Reference numbers for the C++ port, parsing half.

Prints one line per field per room. native/tools/dump_parse.cpp prints the same
lines, so a plain diff decides whether the port is faithful.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# The C++ side writes UTF-8. Windows hands Python a cp1252 stdout by default,
# which cannot encode the dotted capital in the instrument's own name and kills
# the dump before it prints anything - so the two halves could not be compared
# at all on the machine the port is developed on.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

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
        emit("n_stations", len(r.stations))
        for i, s in enumerate(r.stations):
            emit(f"station[{i}]", f"{s.name} {num(s.x)} {num(s.y)} {num(s.z)}")

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
        # Flights and skirtings, spelled out rather than counted. Two cores can
        # tag the same points and still split them into different flights, and
        # a bare count would compare equal while the geometry differed.
        emit("n_stairs", len(r.stairs))
        for i, s in enumerate(r.stairs):
            emit(f"stair[{i}]",
                 f"{s.kind} steps={s.steps} rise={num(s.rise)} going={num(s.going)} "
                 f"pts={','.join(p.name for p in s.points)}")
        emit("n_pervaz", len(r.pervaz))
        for i, v in enumerate(r.pervaz):
            emit(f"pervaz[{i}]",
                 f"{v.corner.name}+{v.wall.name} h={num(v.height)} d={num(v.depth)}")
        for i, s in enumerate(r.issues):
            emit(f"issue[{i}]", f"{s.severity} {s.code}")
        for p in r.points:
            emit(f"role:{p.name}", p.role.value)

    sys.stdout.write("\n".join(out) + "\n")


if __name__ == "__main__":
    main(sys.argv[1])
