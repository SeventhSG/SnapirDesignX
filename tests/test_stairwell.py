"""A stairwell is not a room, and its shots arrive tagged as floor.

Written against the Sofia villa survey, which is what taught us this: a
surveyor tags a tread `Zemin` because a tread is a floor surface, so a whole
flight arrives already claimed as outline corners.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from snapir.geometry import polygon_area, self_intersections
from snapir.model import Role
from snapir.parser import read_room


def _room(rows: list[str]):
    p = Path(tempfile.mkdtemp()) / "Merdiven.csv"
    p.write_text("Kimlik;X (cm);Y (cm);Z (cm);Katman\n" + "\n".join(rows) + "\n",
                 encoding="utf-8")
    return read_room(p)


def _zigzag(n: int, x0: float, y0: float, z0: float, start: int):
    """A flight traced corner by corner where the treads meet the wall, on the
    `Zemin` layer, exactly as the real survey writes it."""
    rows, y, z = [], y0, z0
    i = start
    for _ in range(n):
        rows.append(f"P_{i:03d};{x0:.2f};{y:.2f};{z:.2f};Zemin"); i += 1
        z += 16.0
        rows.append(f"P_{i:03d};{x0:.2f};{y:.2f};{z:.2f};Zemin"); i += 1
        y -= 29.5
    return rows


def test_a_flight_tagged_as_floor_is_still_a_flight():
    # The whole reason nothing fired on the real survey: the detector only
    # looked at unclassified shots, and every tread was tagged Zemin.
    rows = [f"P_{i:03d};{x:.2f};{y:.2f};0.00;Zemin" for i, (x, y) in
            enumerate([(0, 0), (400, 0), (400, 300), (0, 300)], 1)]
    rows += _zigzag(6, -280.0, 250.0, 0.0, start=20)
    room = _room(rows)

    assert len(room.stairs) == 1
    assert room.stairs[0].kind == "zigzag"
    assert room.stairs[0].steps >= 5
    # And the flight leaves the outline, which is the whole point.
    assert len(room.outline) == 4
    assert not any(p.role is Role.STAIRS for p in room.outline)


def test_the_flight_does_not_drag_the_ring_across_itself():
    rows = [f"P_{i:03d};{x:.2f};{y:.2f};0.00;Zemin" for i, (x, y) in
            enumerate([(0, 0), (400, 0), (400, 300), (0, 300)], 1)]
    rows += _zigzag(6, -280.0, 250.0, 0.0, start=20)
    room = _room(rows)
    assert self_intersections([p.xy for p in room.outline]) == []
    assert not room.has_errors


def test_risers_are_not_skirting():
    # A riser is two shots a centimetre apart and sixteen high, which is
    # exactly what a skirting pair looks like. The flight has to be claimed
    # first or every step becomes a board.
    rows = [f"P_{i:03d};{x:.2f};{y:.2f};0.00;Zemin" for i, (x, y) in
            enumerate([(0, 0), (400, 0), (400, 300), (0, 300)], 1)]
    rows += _zigzag(6, -280.0, 250.0, 0.0, start=20)
    room = _room(rows)
    assert room.pervaz == []


def test_the_floor_is_where_most_of_the_floor_shots_are():
    # Standing in a top-floor corridor, the lowest thing the instrument sees is
    # the landing a storey down. That is not this room's floor.
    rows = [f"P_{i:03d};{x:.2f};{y:.2f};0.00;Zemin" for i, (x, y) in
            enumerate([(0, 0), (400, 0), (400, 300), (0, 300)], 1)]
    rows += ["P_020;-160.00;500.00;-162.80;Zemin",     # the landing below
             "P_021;-280.00;500.00;-162.80;Zemin"]
    rows += [f"P_{i:03d};{x:.2f};{y:.2f};280.00;" for i, (x, y) in
             enumerate([(0, 0), (400, 0), (400, 300), (0, 300)], 30)]
    room = _room(rows)

    assert len(room.outline) == 4
    assert {round(p.z, 1) for p in room.outline} == {0.0}
    assert polygon_area([p.xy for p in room.outline]) / 10_000 == pytest.approx(12.0)


def test_a_corner_shot_twice_is_one_corner():
    # Where a flight arrives at a wall, the last tread and the wall corner are
    # the same place read a few millimetres apart. The stub between them used
    # to double the ring back and read as a self-intersection.
    rows = [
        "P_001;0.00;0.00;0.00;Zemin",
        "P_002;400.00;0.00;0.00;Zemin",
        "P_003;400.00;300.00;0.00;Zemin",
        "P_004;0.00;300.00;0.00;Zemin",
        "P_005;-0.60;0.40;0.00;Zemin",     # P_001 again, 0.7 cm away
    ]
    room = _room(rows)
    assert len(room.outline) == 4
    assert self_intersections([p.xy for p in room.outline]) == []
