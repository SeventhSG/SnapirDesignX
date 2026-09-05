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
    assert op.out_depth == pytest.approx(35.0, abs=0.01)
    assert op.depth_points == ["P_013"]

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
    assert not room.openings[0].measured


def test_a_depth_shot_means_an_object_not_a_hole():
    # Nobody measures how far a doorway sticks out of a wall. The shot itself
    # says this is a thing standing on the wall, so the wall behind it stays
    # whole - which is what the operator saw a hole punched through.
    room = _room_with_depth_shot()
    op = room.openings[0]
    assert op.kind == "object"
    assert not op.cuts


def test_the_box_stops_exactly_at_the_dot():
    from snapir.solid import _fitting_body, _occ
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    cfg = BuildSettings()
    occ = _occ()
    for off in (10.0, 35.0, 60.0):
        room = _room_with_depth_shot(off=off)
        ring = [p.xy for p in room.outline]
        body = _fitting_body(room.openings[0], ring, cfg, occ)
        box = Bnd_Box()
        BRepBndLib.Add_s(body, box)
        # The wall is at y = 0 and the room is on the +y side of it.
        assert box.CornerMax().Y() / 10.0 == pytest.approx(off, abs=0.01)
        # And it reaches a little way into the wall, so the fuse is clean.
        assert box.CornerMin().Y() / 10.0 < 0.0


def test_the_wall_is_not_cut_when_there_is_a_depth_shot():
    from snapir.solid import build_room, solid_stats

    cfg = BuildSettings()
    with_object = _room_with_depth_shot(off=35.0)
    volume = solid_stats(build_room(with_object, cfg))["volume_m3"]

    # Same room with the rectangle taken out of the survey entirely.
    plain = _room_with_depth_shot(off=35.0)
    plain.openings = []
    bare = solid_stats(build_room(plain, cfg))["volume_m3"]

    # Material added, never removed. A hole would have put this below `bare`.
    assert volume > bare


def test_a_dot_inside_the_wall_hollows_it_out():
    # The shot can sit behind the wall face as easily as in front of it. Behind
    # means the thing is set into the wall, so material comes away.
    room = _room_with_depth_shot(off=-8.0)
    op = room.openings[0]
    assert op.kind == "niche"
    assert op.in_depth == pytest.approx(8.0, abs=0.01)
    assert op.out_depth is None
    assert op.recesses and not op.cuts


def test_a_recess_stops_at_the_dot_instead_of_going_through():
    from snapir.solid import build_room, solid_stats

    cfg = BuildSettings()          # 200 mm walls, so 20 cm of wall to cut into
    bare = _room_with_depth_shot(off=-8.0)
    bare.openings = []
    plain = solid_stats(build_room(bare, cfg))["volume_m3"]

    recess = solid_stats(build_room(_room_with_depth_shot(off=-8.0), cfg))
    through = _room_with_depth_shot(off=-8.0)
    through.openings[0].kind = "window"
    hole = solid_stats(build_room(through, cfg))["volume_m3"]

    # Less material than a whole wall, but more than a hole clean through it.
    assert recess["volume_m3"] < plain
    assert recess["volume_m3"] > hole
    assert recess["solids"] == 1


def test_a_deeper_dot_takes_more_wall_away():
    from snapir.solid import build_room, solid_stats

    cfg = BuildSettings()
    shallow = solid_stats(build_room(_room_with_depth_shot(off=-3.0), cfg))["volume_m3"]
    deeper = solid_stats(build_room(_room_with_depth_shot(off=-12.0), cfg))["volume_m3"]
    assert deeper < shallow


def test_the_side_is_judged_per_wall_not_by_luck_of_the_winding():
    # The same room read twice must put the shot on the same side of the wall,
    # whichever way the ring happened to be wound.
    a = _room_with_depth_shot(off=-8.0)
    b = _room_with_depth_shot(off=-8.0)
    b.outline = list(reversed(b.outline))
    from snapir.parser import rebuild
    rebuild(b)
    assert a.openings[0].kind == b.openings[0].kind == "niche"


def test_the_depth_survives_a_rebuild():
    # It used to be found only while the shot was still unclassified, so the
    # first correction the operator made dropped the depth and turned the
    # object straight back into a hole.
    from snapir.parser import rebuild

    room = _room_with_depth_shot(off=35.0)
    assert room.openings[0].kind == "object"
    rebuild(room)
    assert room.openings[0].kind == "object", "the object reverted to a hole"
    assert room.openings[0].out_depth == pytest.approx(35.0, abs=0.01)


def _room_with_two_dots(out_off: float = 30.0, in_off: float = -7.0):
    """A rectangle let into the wall and standing out of it at once."""
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
    rows.append(f"P_{n:03d};180.00;{out_off:.2f};170.00;Katman 0")
    n += 1
    rows.append(f"P_{n:03d};180.00;{in_off:.2f};170.00;Katman 0")
    p = Path(tempfile.mkdtemp()) / "Both.csv"
    p.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return read_room(p)


def test_two_dots_are_kept_one_per_side():
    room = _room_with_two_dots(out_off=30.0, in_off=-7.0)
    op = room.openings[0]
    assert op.out_depth == pytest.approx(30.0, abs=0.01)
    assert op.in_depth == pytest.approx(7.0, abs=0.01)
    assert len(op.depth_points) == 2
    # Neither shot is left for the operator to rule on.
    assert not any(i.code == "unclassified" for i in room.issues)


def _inside(shape, x: float, y: float, z: float) -> bool:
    """Is there material at this spot, in survey centimetres?"""
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.gp import gp_Pnt
    from OCP.TopAbs import TopAbs_IN, TopAbs_ON

    from snapir.solid import CM_TO_MM

    cls = BRepClass3d_SolidClassifier(shape)
    cls.Perform(gp_Pnt(x * CM_TO_MM, y * CM_TO_MM, z * CM_TO_MM), 1e-6)
    return cls.State() in (TopAbs_IN, TopAbs_ON)


def test_two_dots_build_one_body_between_them():
    # Two shots are the two ends of one thing: the front of the boiler and the
    # back of it. Hollowing the wall out to the back shot and then standing a
    # box in the mouth was two half-answers, and left the boiler as a plate
    # with a void behind it.
    from snapir.solid import build_room, solid_stats

    cfg = BuildSettings()
    bare = _room_with_two_dots()
    bare.openings = []
    plain = solid_stats(build_room(bare, cfg))["volume_m3"]

    shape = build_room(_room_with_two_dots(30.0, -7.0), cfg)
    both = solid_stats(shape)
    assert both["solids"] == 1
    assert both["volume_m3"] > plain

    # Solid the whole way through: at the front shot, in the middle, and in the
    # wall behind it where the back shot reaches.
    for y in (28.0, 15.0, 1.0, -6.0):
        assert _inside(shape, 180.0, y, 170.0), f"hollow at y={y}"
    # And it stops at the shot rather than running on.
    assert not _inside(shape, 180.0, 34.0, 170.0)


def test_a_back_shot_alone_still_hollows_the_wall():
    # One shot behind the face and none in front is a recess, and has to stay
    # one: the wall is cut back to the depth measured and no further.
    from snapir.solid import build_room

    room = _room_with_two_dots(out_off=30.0, in_off=-7.0)
    op = room.openings[0]
    op.out_depth = None
    op.kind = "niche"
    shape = build_room(room, BuildSettings(), openings=[op])
    assert not _inside(shape, 180.0, -4.0, 170.0), "the recess was not cut"
    assert _inside(shape, 180.0, -12.0, 170.0), "it was cut past the shot"


def test_the_further_shot_on_a_side_wins():
    # Two shots on the same side describe one object; the far one is its face.
    room = _room_with_two_dots(out_off=30.0, in_off=-7.0)
    room2 = _room_with_two_dots(out_off=55.0, in_off=-7.0)
    assert room2.openings[0].out_depth > room.openings[0].out_depth
    assert room2.openings[0].in_depth == pytest.approx(7.0, abs=0.01)


def test_two_dots_survive_a_rebuild():
    from snapir.parser import rebuild

    room = _room_with_two_dots(30.0, -7.0)
    rebuild(room)
    op = room.openings[0]
    assert op.out_depth == pytest.approx(30.0, abs=0.01)
    assert op.in_depth == pytest.approx(7.0, abs=0.01)


def test_a_boiler_is_round_and_a_panel_is_not_unless_told():
    from snapir.model import Jamb, Opening

    j = Jamb(0, 0, 0, 100)
    assert Opening(left=j, right=j, kind="boiler").solid_shape == "round"
    assert Opening(left=j, right=j, kind="panel").solid_shape == "box"
    # And the operator overrules either way.
    assert Opening(left=j, right=j, kind="boiler", shape="box").solid_shape == "box"
    assert Opening(left=j, right=j, kind="lamp", shape="round").solid_shape == "round"


def test_a_round_fitting_reaches_the_dot_like_a_box_does():
    from snapir.solid import _fitting_body, _occ
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    cfg = BuildSettings()
    occ = _occ()
    for shape in ("box", "round"):
        room = _room_with_depth_shot(off=40.0)
        room.openings[0].shape = shape
        ring = [p.xy for p in room.outline]
        body = _fitting_body(room.openings[0], ring, cfg, occ)
        box = Bnd_Box()
        BRepBndLib.Add_s(body, box)
        assert box.CornerMax().Y() / 10.0 == pytest.approx(40.0, abs=0.01), shape


def test_round_and_square_are_different_bodies():
    from snapir.solid import build_room, solid_stats

    cfg = BuildSettings()
    square = _room_with_depth_shot(off=40.0)
    square.openings[0].shape = "box"
    round_ = _room_with_depth_shot(off=40.0)
    round_.openings[0].shape = "round"

    a = solid_stats(build_room(square, cfg))
    b = solid_stats(build_room(round_, cfg))
    assert a["solids"] == b["solids"] == 1
    # A cylinder inside the same rectangle carries less material than the box.
    assert b["volume_m3"] < a["volume_m3"]


def test_a_round_recess_bores_into_the_wall():
    from snapir.solid import build_room, solid_stats

    cfg = BuildSettings()
    bare = _room_with_depth_shot(off=-9.0)
    bare.openings = []
    plain = solid_stats(build_room(bare, cfg))["volume_m3"]

    room = _room_with_depth_shot(off=-9.0)
    room.openings[0].shape = "round"
    bored = solid_stats(build_room(room, cfg))
    assert bored["solids"] == 1
    assert bored["volume_m3"] < plain
