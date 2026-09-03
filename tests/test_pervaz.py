"""Pervaz - skirting shot as a pair of floor points at one corner.

Two shots at one corner, a board's depth apart in plan and a board's height
apart in Z. Left unrecognised they both land in the outline and the ring
doubles, which validates cleanly and is wrong.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from snapir.geometry import polygon_area
from snapir.model import Role
from snapir.parser import apply_roles, read_room

CORNERS = [(0, 0), (400, 0), (400, 300), (0, 300)]
BACK = [(1, 1), (-1, 1), (-1, -1), (1, -1)]      # toward the wall behind


def _room(height: float = 10.0):
    rows = ["Kimlik;X (cm);Y (cm);Z (cm);Katman"]
    n = 1
    for (x, y), (bx, by) in zip(CORNERS, BACK):
        rows.append(f"P_{n:03d};{x:.2f};{y:.2f};0.00;Zemin")           # floor line
        n += 1
        rows.append(f"P_{n:03d};{x + bx * 2:.2f};{y + by * 2:.2f};{height:.2f};Zemin")
        n += 1
    for (x, y) in CORNERS:
        rows.append(f"P_{n:03d};{x:.2f};{y:.2f};280.00;")
        n += 1
    p = Path(tempfile.mkdtemp()) / "Pervaz.csv"
    p.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return read_room(p)


def test_a_skirting_pair_becomes_one_corner():
    room = _room()
    assert len(room.pervaz) == 4
    assert len(room.outline) == 4
    # The ring sits at floor level, not spread across two heights.
    assert {round(p.z, 1) for p in room.outline} == {0.0}
    assert polygon_area([p.xy for p in room.outline]) / 10_000 == pytest.approx(12.0)


def test_the_pair_records_the_board_it_measured():
    v = _room(height=12.0).pervaz[0]
    assert v.height == pytest.approx(12.0, abs=0.01)
    assert v.depth == pytest.approx(2.83, abs=0.05)     # 2 cm on each axis
    assert v.corner.z == pytest.approx(0.0)             # the floor-level shot


def test_detection_survives_a_rebuild():
    # It used to snap the wall shot down to floor level, destroying the height
    # difference the pair is recognised by. A second pass then found nothing
    # and every skirting record vanished on the operator's first correction.
    room = _room()
    assert len(room.pervaz) == 4

    from snapir.parser import rebuild
    rebuild(room)
    assert len(room.pervaz) == 4, "skirting lost on rebuild"
    assert len(room.outline) == 4


def test_nothing_is_moved():
    room = _room(height=10.0)
    wall_shots = [p for p in room.points if p.role is Role.PERVAZ]
    assert wall_shots, "the wall shot should leave the outline"
    # Every shot still reads exactly where the instrument put it.
    assert all(p.z == pytest.approx(10.0) for p in wall_shots)


def test_the_operator_can_overrule_the_detector_and_it_sticks():
    room = _room()
    victim = next(p for p in room.points if p.role is Role.PERVAZ)

    apply_roles(room, {victim.name: "floor"})
    assert victim.role is Role.FLOOR

    # And the rebuild that follows must not simply re-derive it back.
    from snapir.parser import rebuild
    rebuild(room)
    assert victim.role is Role.FLOOR, "inference overwrote the operator"
    assert len(room.pervaz) == 3
