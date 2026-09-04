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


def _room_with_drawn_lines(tmp_path):
    """Skirting as the surveyor actually traces it: the outer line down at the
    real floor, then the same way back along the top of the board. With a
    _FUKOKU beside it, so the room is read from the drawn lines."""
    corners = [(0, 0), (-431, 0), (-431, -266), (0, -281)]
    rows, n = [], 1
    for (x, y) in corners:                       # the outer line, on the floor
        rows.append(f"P_{n:03d};{x:.2f};{y:.2f};0.00;Zemin"); n += 1
    for (x, y) in reversed(corners):             # back along the top of it
        rows.append(f"P_{n:03d};{x + 2.2:.2f};{y + 2.2:.2f};6.40;Zemin"); n += 1
    for (x, y) in corners:
        rows.append(f"P_{n:03d};{x:.2f};{y:.2f};253.00;")
        n += 1

    csv = tmp_path / "Oda.csv"
    csv.write_text("Kimlik;X (cm);Y (cm);Z (cm);Katman\n" + "\n".join(rows) + "\n",
                   encoding="utf-8")
    # The drawn ring: the outer line only, closed.
    lines = ["Line start;Line end"]
    for i in range(4):
        lines.append(f"P_{i + 1:03d};P_{(i + 1) % 4 + 1:03d}")
    (tmp_path / "Oda_FUKOKU.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return read_room(csv)


def test_skirting_is_found_when_the_ring_came_from_drawn_lines(tmp_path):
    # The drawn-lines path skipped skirting detection entirely, so on every
    # room the surveyor had drawn - which is most of them - the board's upper
    # run stayed tagged as floor and no skirting was ever reported.
    room = _room_with_drawn_lines(tmp_path)
    assert room.outline_source == "drawn"
    assert len(room.pervaz) == 4
    for v in room.pervaz:
        assert v.height == pytest.approx(6.4, abs=0.1)
        assert v.depth == pytest.approx(3.1, abs=0.2)
    # And the ring is still the outer line, not doubled by the upper one.
    assert len(room.outline) == 4


def test_the_board_is_actually_built():
    # Detection was reported for weeks while nothing was ever built: `pervaz`
    # appeared nowhere in the solid builder, so every room came back with a
    # plain wall meeting a plain floor.
    from snapir.settings import BuildSettings
    from snapir.solid import build_room, solid_stats

    room = _room()
    assert len(room.pervaz) == 4
    plain = solid_stats(build_room(room, BuildSettings(include_pervaz=False)))
    board = solid_stats(build_room(room, BuildSettings()))

    # The wall steps back above the board, so there is less material, not more.
    assert board["volume_m3"] < plain["volume_m3"]
    assert board["solids"] == 1
    # And not by much: a couple of centimetres off one storey of wall.
    taken = plain["volume_m3"] - board["volume_m3"]
    assert 0.0 < taken < plain["volume_m3"] * 0.15


def test_the_ceiling_survives_the_skirting():
    # The band once ran past the ceiling and took the slab with it - three
    # cubic metres and half the faces of the room.
    from snapir.settings import BuildSettings
    from snapir.solid import build_room, solid_stats

    room = _room()
    plain = solid_stats(build_room(room, BuildSettings(include_pervaz=False)))
    board = solid_stats(build_room(room, BuildSettings()))
    assert board["faces"] >= plain["faces"] * 0.5
