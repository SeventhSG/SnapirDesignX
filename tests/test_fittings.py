"""Rectangles on a wall that are not holes.

A boiler, a socket panel and a wall lamp are each four corners on a wall -
exactly what a window looks like in the survey. The classifier cannot tell
them apart and must not pretend to: it guesses a door or a window, and the
operator says what it really is. What must never happen is a boiler being cut
through the wall.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from snapir.elements import elements, opening_key
from snapir.parser import read_room
from snapir.settings import BuildSettings
from snapir.solid import build_room, solid_stats


def _room_with_rectangle():
    """A 4x3 m room with one 60x100 cm rectangle on the north wall."""
    rows = ["Kimlik;X (cm);Y (cm);Z (cm);Katman"]
    for i, (x, y) in enumerate([(0, 0), (400, 0), (400, 300), (0, 300)], 1):
        rows.append(f"P_{i:03d};{x:.2f};{y:.2f};0.00;Zemin")
    for i, (x, y) in enumerate([(0, 0), (400, 0), (400, 300), (0, 300)], 5):
        rows.append(f"P_{i:03d};{x:.2f};{y:.2f};280.00;")
    n = 9
    for x in (150.0, 210.0):
        for z in (120.0, 220.0):
            rows.append(f"P_{n:03d};{x:.2f};0.00;{z:.2f};Katman 0")
            n += 1
    p = Path(tempfile.mkdtemp()) / "Fitting.csv"
    p.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return read_room(p)


def test_the_classifier_still_guesses_a_window():
    # It has nothing else to go on, and guessing is better than refusing.
    room = _room_with_rectangle()
    assert len(room.openings) == 1
    assert room.openings[0].kind == "window"
    assert room.openings[0].cuts


def test_a_boiler_is_added_to_the_room_not_cut_out_of_it():
    room = _room_with_rectangle()
    cfg = BuildSettings()
    as_window = solid_stats(build_room(room, cfg))["volume_m3"]

    room.openings[0].kind = "boiler"
    assert not room.openings[0].cuts
    as_boiler = solid_stats(build_room(room, cfg))["volume_m3"]

    # The window removes material; the boiler adds it. Anything else means a
    # boiler is being punched through the wall.
    assert as_boiler > as_window


def test_every_fitting_kind_builds_a_valid_solid():
    cfg = BuildSettings()
    for kind in ("boiler", "socket", "lamp", "panel"):
        room = _room_with_rectangle()
        room.openings[0].kind = kind
        stats = solid_stats(build_room(room, cfg))
        assert stats["solids"] == 1, f"{kind} did not build one solid"
        assert stats["volume_m3"] > 0


def test_empty_builds_nothing_at_all():
    room = _room_with_rectangle()
    cfg = BuildSettings()
    room.openings[0].kind = "empty"
    empty = solid_stats(build_room(room, cfg))

    # "Nothing here" means the wall is left whole: no hole, no fitting.
    plain = _room_with_rectangle()
    plain.openings = []
    assert empty["volume_m3"] == pytest.approx(
        solid_stats(build_room(plain, cfg))["volume_m3"], abs=1e-9)


def test_a_fitting_is_clickable_and_keeps_its_name():
    room = _room_with_rectangle()
    room.openings[0].kind = "boiler"
    key = opening_key(room.openings[0])

    el = next(e for e in elements(room) if e.key == key)
    assert el.kind == "fitting"
    assert el.label == "Boiler"

    # The same rectangle, re-read, is the same element - which is what makes
    # "this one is a boiler" stick.
    again = _room_with_rectangle()
    assert opening_key(again.openings[0]) == key


def _room_with_depth_shot(off: float = 35.0):
    """The same rectangle, plus the middle shot that measures how far it
    stands out of the wall."""
    rows = ["Kimlik;X (cm);Y (cm);Z (cm);Katman"]
    for i, (x, y) in enumerate([(0, 0), (400, 0), (400, 300), (0, 300)], 1):
        rows.append(f"P_{i:03d};{x:.2f};{y:.2f};0.00;Zemin")
    for i, (x, y) in enumerate([(0, 0), (400, 0), (400, 300), (0, 300)], 5):
        rows.append(f"P_{i:03d};{x:.2f};{y:.2f};280.00;")
    n = 9
    for x in (150.0, 210.0):
        for z in (120.0, 220.0):
            rows.append(f"P_{n:03d};{x:.2f};0.00;{z:.2f};Katman 0")
            n += 1
    # In the middle of the rectangle, standing `off` cm into the room.
    rows.append(f"P_{n:03d};180.00;{off:.2f};170.00;Katman 0")
    p = Path(tempfile.mkdtemp()) / "Depth.csv"
    p.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return read_room(p)


def test_the_middle_shot_measures_the_depth():
    room = _room_with_depth_shot(off=35.0)
    assert len(room.openings) == 1
    op = room.openings[0]
    assert op.depth == pytest.approx(35.0, abs=0.01)
    assert op.depth_point == "P_013"

    # And it stops being an unresolved shot the operator has to look at.
    assert not any(i.code == "unclassified" for i in room.issues)


def test_a_measured_depth_beats_the_setting():
    from snapir.solid import build_room, solid_stats

    cfg = BuildSettings()
    shallow = _room_with_depth_shot(off=10.0)
    deep = _room_with_depth_shot(off=60.0)
    for r in (shallow, deep):
        r.openings[0].kind = "panel"

    a = solid_stats(build_room(shallow, cfg))["volume_m3"]
    b = solid_stats(build_room(deep, cfg))["volume_m3"]
    # Same rectangle, same kind, same settings - only the measurement differs.
    assert b > a


def test_without_a_middle_shot_the_setting_is_used():
    room = _room_with_rectangle()
    assert room.openings[0].depth is None
