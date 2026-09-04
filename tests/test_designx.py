"""The trip out to Geomagic Design X and back.

Out is a wireframe: exact curves, plus a point for every single shot and a box
around every rectangle whose depth was measured - the two things the plain
outline cannot say. Back is the same drawing with something changed, and the
room has to become it without losing what the survey knows.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from snapir.designx import export_curves
from snapir.importx import outline_loop, read_sketch, sketch_for
from snapir.model import Role
from snapir.parser import read_room

CORNERS = [(0, 0), (400, 0), (400, 300), (0, 300)]
CEIL = 260.0


def _room(depth_shot: tuple[float, float, float] | None = None):
    rows, n = ["Kimlik;X (cm);Y (cm);Z (cm);Katman"], 1

    def add(x, y, z, layer):
        nonlocal n
        rows.append(f"P_{n:03d};{x:.2f};{y:.2f};{z:.2f};{layer}")
        n += 1

    for x, y in CORNERS:
        add(x, y, 0.0, "Zemin")
    for x, y in CORNERS:
        add(x, y, CEIL, "")
    # A rectangle on the back wall, with a shot in the middle of it saying how
    # far the thing standing there reaches into the room.
    for x in (150.0, 250.0):
        add(x, 300.0, 100.0, "Katman 0")
        add(x, 300.0, 200.0, "Katman 0")
    if depth_shot:
        add(*depth_shot, "Katman 0")

    p = Path(tempfile.mkdtemp()) / "Trip.csv"
    p.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return read_room(p)


def _out(room, fmt="iges") -> Path:
    return Path(export_curves(room, Path(tempfile.mkdtemp()), fmt))


def test_a_measured_depth_leaves_with_the_room():
    # The rectangle looks the same whether the boiler is 8 cm deep or 40. Sent
    # as four corners on a wall and nothing else, the one number the survey
    # actually measured never arrives.
    room = _room((200.0, 288.5, 150.0))
    op = room.openings[0]
    assert op.out_depth == pytest.approx(11.5, abs=0.2)

    pts, lines = read_sketch(_out(room))
    front = [p for p in pts if abs(p[1] - 288.5) < 0.5]
    assert front, "nothing at the depth that was measured"
    # And the shot itself, as a point in its own right.
    assert any(abs(p[0] - 200.0) < 0.01 and abs(p[1] - 288.5) < 0.01
               and abs(p[2] - 150.0) < 0.01 for p in pts)


@pytest.mark.parametrize("fmt", ["iges", "step"])
def test_the_room_comes_back_as_the_room(fmt):
    room = _room()
    pts, lines = read_sketch(_out(room, fmt))
    loop = outline_loop(pts, lines)
    assert len(loop) == 4
    ring = sorted((round(pts[i][0]), round(pts[i][1])) for i in loop)
    assert ring == sorted((round(x), round(y)) for x, y in CORNERS)


def test_every_corner_keeps_the_name_the_instrument_gave_it():
    # This is the whole point of the round trip: an opening the operator
    # relabelled, a wall they removed, a role they corrected are all keyed on
    # point names. A ring of freshly invented names would silently drop the lot.
    room = _room()
    sketch = sketch_for(room, _out(room))
    assert sketch["outline"] == [p.name for p in room.outline] or \
           set(sketch["outline"]) == {p.name for p in room.outline}
    assert all(not n.startswith("X_") for n in sketch["outline"])


def test_a_corner_moved_in_design_x_moves_the_room():
    room = _room()
    # The same room with one corner dragged 50 cm, which is what comes back
    # from an afternoon of tidying the plan up in Design X.
    edited = _room()
    edited.outline[1].x = 450.0
    sketch = sketch_for(room, _out(edited))
    assert len(sketch["outline"]) == 4
    # Three corners still answer to their surveyed names; the moved one is new.
    fresh = [d for d in sketch["points"] if d["name"] in sketch["outline"]]
    assert len(fresh) == 1
    assert fresh[0]["x"] == pytest.approx(450.0)
    assert fresh[0]["role"] == "floor"


def test_importing_twice_changes_nothing_the_second_time():
    room = _room()
    path = _out(room)
    first = sketch_for(room, path)
    second = sketch_for(room, path)
    assert first == second


def test_a_point_the_file_does_not_explain_is_left_unknown():
    # Design X will happily hand back geometry the survey never had. Guessing
    # it is a floor corner would put it in the ring behind the operator's back.
    room = _room()
    sketch = sketch_for(room, _out(room))
    strays = [d for d in sketch["points"] if d["name"] not in sketch["outline"]]
    assert all(d["role"] == "unknown" for d in strays)


def test_a_file_that_is_not_a_sketch_is_refused():
    from snapir.solid import BuildError

    junk = Path(tempfile.mkdtemp()) / "notes.txt"
    junk.write_text("nothing to see", encoding="utf-8")
    with pytest.raises(BuildError):
        read_sketch(junk)


def test_a_point_the_last_import_brought_in_survives_the_next_one():
    # It matched the point it had itself created, called that "already in the
    # room", and left it out of the new record - so the point vanished on the
    # next read and every line drawn to it went with it.
    from dataclasses import replace

    from snapir.model import Point, Role

    room = _room()
    edited = _room()
    edited.outline[1].x = 450.0
    first = sketch_for(room, _out(edited))
    assert first["points"], "the moved corner should be new"

    # The room as the app rebuilds it: the survey, plus what the import added.
    with_import = replace(room, points=list(room.points) + [
        Point(name=d["name"], x=d["x"], y=d["y"], z=d["z"], layer="",
              role=Role(d["role"]), derived=True, source=d["from"])
        for d in first["points"]])

    second = sketch_for(with_import, _out(edited))
    assert [d["name"] for d in second["points"]] == [d["name"] for d in first["points"]]
    assert second["outline"] == first["outline"]
