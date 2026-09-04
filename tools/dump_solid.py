"""Reference numbers for the C++ port, geometry half.

Builds every room and prints the numbers the Python build is already trusted
for. native/tools/dump_solid.cpp prints the same lines.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# The C++ side writes UTF-8. Windows hands Python a cp1252 stdout by default,
# which cannot encode a Turkish room name and kills the dump before it prints
# anything - so the two halves could not be compared at all on the machine the
# port is developed on.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


from snapir.parser import read_project
from snapir.settings import BuildSettings
from snapir.solid import build_room, solid_stats, wall_body
from snapir.tessellate import tessellate


def num(v: float, places: int = 9) -> str:
    return f"{v:.{places}f}"


def main(folder: str) -> None:
    cfg = BuildSettings()
    out: list[str] = []

    for room in read_project(folder).rooms:
        n = room.name

        def emit(key, value):
            out.append(f"{n}|{key}|{value}")

        try:
            shape = build_room(room, cfg)
        except Exception as exc:  # noqa: BLE001 - the message is the datum
            emit("build", f"ERROR {exc}")
            continue

        s = solid_stats(shape)
        emit("build", "ok")
        emit("solids", s["solids"])
        emit("shells", s["shells"])
        emit("faces", s["faces"])
        emit("volume_m3", num(s["volume_m3"]))

        mesh = tessellate(shape)
        emit("triangles", mesh.triangle_count)
        emit("mesh_faces", len(mesh.faces))

        total = 0.0
        all_ok = True
        for e in range(len(room.outline)):
            try:
                body, length, count = wall_body(room, cfg, e)
                ws = solid_stats(body)
                total += ws["volume_m3"]
                emit(f"wall[{e}]",
                     f"len={num(length, 6)} solids={count} vol={num(ws['volume_m3'])}")
            except Exception as exc:  # noqa: BLE001
                all_ok = False
                emit(f"wall[{e}]", f"ERROR {exc}")
        if all_ok:
            emit("wall_sum_m3", num(total))

    sys.stdout.write("\n".join(out) + "\n")


if __name__ == "__main__":
    main(sys.argv[1])
