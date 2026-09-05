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
NL = chr(10)
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


def test_a_shot_no_line_touches_still_goes_over():
    # A point the classifier could not place is exactly the one that still
    # needs a decision, and it was the one being left behind: no polyline
    # carries it, so without a point of its own it simply did not arrive.
    room = _room()
    stray = (77.0, 155.0, 42.0)
    room.points.append(
        __import__("snapir.model", fromlist=["Point"]).Point(
            name="P_099", x=stray[0], y=stray[1], z=stray[2], layer=""))

    pts, _lines = read_sketch(_out(room))
    assert any(abs(p[0] - stray[0]) < 0.01 and abs(p[1] - stray[1]) < 0.01
               and abs(p[2] - stray[2]) < 0.01 for p in pts), "the loose shot was dropped"


def test_a_corner_the_outline_already_draws_is_not_sent_twice():
    # Only what no curve carries. A ring corner is on the ring; sending it as a
    # loose point as well would put a cross through every corner of the room.
    from snapir.designx import _rings
    from snapir.settings import BuildSettings

    room = _room()
    _polylines, loose, _circles = _rings(room, BuildSettings())
    for p in room.outline:
        assert not any(abs(q[0] - p.x) < 0.01 and abs(q[1] - p.y) < 0.01
                       and abs(q[2] - p.z) < 0.01 for q in loose)


def _room_with_services():
    """A room with a socket and a water pipe on the same wall."""
    rows, n = ["Kimlik;X (cm);Y (cm);Z (cm);Katman"], 1

    def add(x, y, z, layer):
        nonlocal n
        rows.append(f"P_{n:03d};{x:.2f};{y:.2f};{z:.2f};{layer}")
        n += 1

    for x, y in CORNERS:
        add(x, y, 0.0, "Zemin")
    for x, y in CORNERS:
        add(x, y, CEIL, "")
    add(120.0, 2.0, 30.0, "Kontak")
    add(200.0, 3.0, 60.0, "Su tesisat")

    p = Path(tempfile.mkdtemp()) / "Services.csv"
    p.write_text(NL.join(rows) + NL, encoding="utf-8")
    return read_room(p)


def test_a_socket_leaves_as_a_square_and_a_pipe_as_a_circle():
    # Both arrive as one reading, and as one reading they left as two identical
    # dots - which says where a service is and nothing about what it is.
    from snapir.designx import _rings
    from snapir.settings import BuildSettings

    cfg = BuildSettings()
    room = _room_with_services()
    assert [p.role for p in room.points if p.role is Role.SOCKET]
    assert [p.role for p in room.points if p.role is Role.PLUMBING]

    rings, _loose, circles = _rings(room, cfg)
    assert len(circles) == 1
    (_c, _axis, radius) = circles[0]
    assert radius == pytest.approx(cfg.pipe_diameter / 10.0 / 2)

    # The square sits on the wall, at the socket's own height, the size the
    # settings give a faceplate.
    side = cfg.socket_width / 10.0
    squares = [r for r in rings
               if len(r) == 5 and all(abs(q[1]) < 1.0 for q in r)
               and abs(max(q[2] for q in r) - min(q[2] for q in r)
                       - cfg.socket_height / 10.0) < 0.01]
    assert squares, "no faceplate drawn"
    q = squares[0]
    assert abs(max(v[0] for v in q) - min(v[0] for v in q) - side) < 0.01


def test_a_service_is_not_marked_twice():
    # It has a shape of its own now, so the cross through it is one mark more
    # than the drawing needs.
    from snapir.designx import MARK, _rings
    from snapir.settings import BuildSettings

    room = _room_with_services()
    rings, _loose, _circles = _rings(room, BuildSettings())
    arms = [r for r in rings
            if len(r) == 2 and abs(r[0][2] - r[1][2]) == pytest.approx(2 * MARK)]
    assert not arms, "a service was crossed as well as drawn"
