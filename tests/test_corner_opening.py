"""A window that turns the corner of a room.

Both jambs are on different walls, so everything between them - the two
returns and the pier where the walls meet - is glass. Cut as one box between
the jambs it comes out as a diagonal slice with the corner still standing
behind it, which is not a window anyone has ever fitted.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from snapir.model import Role
from snapir.parser import read_room
from snapir.settings import BuildSettings
from snapir.solid import CM_TO_MM, build_room, solid_stats

CORNERS = [(0, 0), (400, 0), (400, 300), (0, 300)]
SILL, HEAD = 90.0, 210.0
CEIL = 260.0


def _room(left: tuple[float, float], right: tuple[float, float]):
    """A plain room with one window between the two given jambs."""
    rows, n = ["Kimlik;X (cm);Y (cm);Z (cm);Katman"], 1

    def add(x, y, z, layer):
        nonlocal n
        rows.append(f"P_{n:03d};{x:.2f};{y:.2f};{z:.2f};{layer}")
        n += 1

    for x, y in CORNERS:
        add(x, y, 0.0, "Zemin")
    for x, y in CORNERS:
        add(x, y, CEIL, "")
    for x, y in (left, right):
        add(x, y, SILL, "Katman 0")
        add(x, y, HEAD, "Katman 0")

    p = Path(tempfile.mkdtemp()) / "Corner.csv"
    p.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return read_room(p)


def _inside(shape, x: float, y: float, z: float) -> bool:
    """Is there material at this spot, in survey centimetres?"""
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.gp import gp_Pnt
    from OCP.TopAbs import TopAbs_IN, TopAbs_ON

    cls = BRepClass3d_SolidClassifier(shape)
    cls.Perform(gp_Pnt(x * CM_TO_MM, y * CM_TO_MM, z * CM_TO_MM), 1e-6)
    return cls.State() in (TopAbs_IN, TopAbs_ON)


def test_the_window_is_read_as_one_rectangle_across_the_corner():
    room = _room((300.0, 0.0), (400.0, 100.0))
    assert len(room.openings) == 1
    assert room.openings[0].kind == "window"
    assert len(room.outline) == 4


def test_the_pier_between_the_two_returns_is_taken_out():
    cfg = BuildSettings()
    thick = cfg.wall_thickness / 10.0        # cm
    shape = build_room(_room((300.0, 0.0), (400.0, 100.0)), cfg)
    mid = (SILL + HEAD) / 2

    # The corner itself: the block of wall behind the outside corner. At window
    # height it is glass, and nothing may be left standing there.
    assert not _inside(shape, 400 + thick / 2, -thick / 2, mid), "corner pier still there"
    # And both returns, which are the window proper.
    assert not _inside(shape, 350.0, -thick / 2, mid)
    assert not _inside(shape, 400 + thick / 2, 50.0, mid)


def test_the_wall_beyond_each_jamb_survives():
    cfg = BuildSettings()
    thick = cfg.wall_thickness / 10.0
    shape = build_room(_room((300.0, 0.0), (400.0, 100.0)), cfg)
    mid = (SILL + HEAD) / 2

    # Past the left jamb, and past the right one. A cut on the diagonal
    # overshoots both of these, because its reach is measured off the chord
    # rather than off the wall it is cutting.
    assert _inside(shape, 240.0, -thick / 2, mid), "wall past the left jamb was eaten"
    assert _inside(shape, 400 + thick / 2, 170.0, mid), "wall past the right jamb was eaten"
    # And the sill and the head are still there.
    assert _inside(shape, 350.0, -thick / 2, SILL - 20.0)
    assert _inside(shape, 350.0, -thick / 2, HEAD + 20.0)


def test_it_is_still_one_watertight_body():
    stats = solid_stats(build_room(_room((300.0, 0.0), (400.0, 100.0)), BuildSettings()))
    assert stats["solids"] == 1
    assert stats["volume_m3"] > 0


def test_a_window_on_one_wall_is_untouched():
    # The wrapped path must not reach for an ordinary opening: same room, both
    # jambs on the same wall, and the body has to come out exactly as before.
    plain = solid_stats(build_room(_room((150.0, 0.0), (250.0, 0.0)), BuildSettings()))
    assert plain["solids"] == 1
    shape = build_room(_room((150.0, 0.0), (250.0, 0.0)), BuildSettings())
    thick = BuildSettings().wall_thickness / 10.0
    assert not _inside(shape, 200.0, -thick / 2, (SILL + HEAD) / 2)
    assert _inside(shape, 350.0, -thick / 2, (SILL + HEAD) / 2)


def _room_three_verticals():
    """A corner window as it is actually shot: one vertical at each end and
    one on the corner itself, where the two panes meet."""
    rows, n = ["Kimlik;X (cm);Y (cm);Z (cm);Katman"], 1

    def add(x, y, z, layer):
        nonlocal n
        rows.append(f"P_{n:03d};{x:.2f};{y:.2f};{z:.2f};{layer}")
        n += 1

    for x, y in CORNERS:
        add(x, y, 0.0, "Zemin")
    for x, y in CORNERS:
        add(x, y, CEIL, "")
    # Left jamb, the mullion standing on the corner, right jamb.
    for x, y in ((300.0, 0.0), (400.0, 0.0), (400.0, 100.0)):
        add(x, y, SILL, "Katman 0")
        add(x, y, HEAD, "Katman 0")

    p = Path(tempfile.mkdtemp()) / "Mullion.csv"
    p.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return read_room(p)


def test_three_verticals_make_one_window_not_one_and_a_half():
    # Pairing takes jambs two at a time, so the third was always left over -
    # and with it half the window, which simply never got cut. The room came
    # back with glass on one wall and masonry where the rest of it is.
    room = _room_three_verticals()
    assert len(room.openings) == 1
    op = room.openings[0]
    ends = sorted([(round(op.left.x), round(op.left.y)),
                   (round(op.right.x), round(op.right.y))])
    assert ends == [(300, 0), (400, 100)], "the window stops at the corner"


def test_the_far_half_of_a_corner_window_is_cut_too():
    cfg = BuildSettings()
    thick = cfg.wall_thickness / 10.0
    shape = build_room(_room_three_verticals(), cfg)
    mid = (SILL + HEAD) / 2

    assert not _inside(shape, 350.0, -thick / 2, mid), "the near half is solid"
    assert not _inside(shape, 400 + thick / 2, 50.0, mid), "the far half is solid"
    assert not _inside(shape, 400 + thick / 2, -thick / 2, mid), "the pier is still there"
    # And the walls beyond it are untouched.
    assert _inside(shape, 240.0, -thick / 2, mid)
    assert _inside(shape, 400 + thick / 2, 170.0, mid)


def test_a_jamb_near_a_corner_with_nothing_beyond_it_is_still_a_jamb():
    # The rule only fires where there is a vertical on each of the two walls
    # that meet at the corner. An ordinary door that happens to start at a
    # corner must keep both its sides.
    room = _room((400.0, 0.0), (400.0, 100.0))
    assert len(room.openings) == 1
    op = room.openings[0]
    assert op.width == pytest.approx(100.0, abs=1.0)
