"""Not every building is closed.

A stairwell is open at the top, a landing has no ceiling of its own, and a
survey says so by having nothing shot up there. That is a measurement, not a
gap: reading it as a gap is what puts a wall and a slab across an opening the
building has not got.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from snapir.parser import read_room
from snapir.settings import BuildSettings
from snapir.solid import (CM_TO_MM, build_room, open_corners, open_edges,
                          solid_stats)

CORNERS = [(0, 0), (400, 0), (400, 300), (0, 300)]
CEIL = 260.0


def _room(ceiling_over):
    """A plain room with a ceiling shot over only the corners named."""
    rows, n = ["Kimlik;X (cm);Y (cm);Z (cm);Katman"], 1

    def add(x, y, z, layer):
        nonlocal n
        rows.append(f"P_{n:03d};{x:.2f};{y:.2f};{z:.2f};{layer}")
        n += 1

    for x, y in CORNERS:
        add(x, y, 0.0, "Zemin")
    for i, (x, y) in enumerate(CORNERS):
        if i in ceiling_over:
            add(x, y, CEIL, "")
    # Two shots in the middle of the room regardless, so there is a ceiling
    # level to speak of at all. Both are 250 cm from the nearest corner, so
    # they cover none of them.
    add(180.0, 150.0, CEIL, "")
    add(220.0, 150.0, CEIL, "")

    p = Path(tempfile.mkdtemp()) / "Open.csv"
    p.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return read_room(p)


def _inside(shape, x, y, z) -> bool:
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.gp import gp_Pnt
    from OCP.TopAbs import TopAbs_IN, TopAbs_ON

    cls = BRepClass3d_SolidClassifier(shape)
    cls.Perform(gp_Pnt(x * CM_TO_MM, y * CM_TO_MM, z * CM_TO_MM), 1e-6)
    return cls.State() in (TopAbs_IN, TopAbs_ON)


def test_a_room_shot_all_round_keeps_every_wall():
    room = _room({0, 1, 2, 3})
    assert open_corners(room) == set()
    assert open_edges(room) == set()


def test_a_side_with_no_ceiling_over_it_is_not_a_wall():
    # Neither end of the far edge has anything above it, so the building is
    # open there. One end would be enough to keep the wall.
    room = _room({0, 1})
    assert open_corners(room) == {2, 3}
    assert open_edges(room) == {2}

    cfg = BuildSettings()
    thick = cfg.wall_thickness / 10.0
    shape = build_room(room, cfg)
    # The open side is gone...
    assert not _inside(shape, 200.0, 300 + thick / 2, CEIL / 2)
    # ...and the two beside it, each with one end covered, are still there.
    assert _inside(shape, -thick / 2, 150.0, CEIL / 2)
    assert _inside(shape, 400 + thick / 2, 150.0, CEIL / 2)


def test_nothing_over_it_at_all_means_no_roof_either():
    # A landing between two flights. Under three corners with anything above
    # them there is no ceiling to build, and a slab there is invention.
    room = _room(set())
    assert open_corners(room) == {0, 1, 2, 3}

    plain = solid_stats(build_room(_room({0, 1, 2, 3}), BuildSettings()))
    open_top = solid_stats(build_room(room, BuildSettings()))
    assert open_top["volume_m3"] < plain["volume_m3"]

    shape = build_room(room, BuildSettings())
    # No slab overhead, and no walls: what is left is the floor it stands on.
    assert not _inside(shape, 200.0, 150.0, CEIL + 10.0)
    assert _inside(shape, 200.0, 150.0, -10.0)


def test_one_end_covered_is_enough_to_keep_a_wall():
    room = _room({0})
    assert open_corners(room) == {1, 2, 3}
    # Edges 1 and 2 have both ends open; 0 and 3 each touch corner 0.
    assert open_edges(room) == {1, 2}
