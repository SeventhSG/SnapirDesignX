"""Element identity: what a picked face is, and whether the answer survives.

The point of this layer is that a decision the operator makes about "this
wall" still means that wall after the body is rebuilt. Face ids do not survive
a rebuild; these keys have to.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from snapir.elements import (Element, elements, face_element, opening_key,
                             wall_edge_for_key, wall_key)
from snapir.model import Point, Role, Stair
from snapir.parser import read_room
from snapir.settings import BuildSettings

FIXTURE = Path(__file__).parent / "fixtures" / "survey" / "Daire 53 - Salon.csv"


@pytest.fixture
def room():
    return read_room(FIXTURE)


def test_wall_key_does_not_depend_on_ring_direction():
    # The topology walk's direction is not deterministic between the Python
    # and C++ cores, so a key that flipped with it would not survive the port.
    assert wall_key("P_004", "P_003") == wall_key("P_003", "P_004")


def test_every_wall_of_the_room_is_named_after_its_corners(room):
    walls = [e for e in elements(room) if e.kind == "wall"]
    assert len(walls) == len(room.outline)
    assert walls[0].key == wall_key(room.outline[0].name, room.outline[1].name)
    assert all(len(w.points) == 2 for w in walls)
    assert len({w.key for w in walls}) == len(walls)      # keys are unique


def test_keys_survive_a_rebuild_where_face_ids_do_not(room):
    from snapir.solid import build_room
    from snapir.tessellate import tessellate

    cfg = BuildSettings()
    before = tessellate(build_room(room, cfg), room=room, cfg=cfg)
    picked = next(f for f in before.faces if f.element_kind == "wall")

    # Rebuild with one wall taken out - exactly the kind of correction that
    # renumbers OCCT's faces underneath a stored selection.
    other = next(f.element for f in before.faces
                 if f.element_kind == "wall" and f.element != picked.element)
    after = tessellate(build_room(room, cfg, removed_walls=[other]),
                       room=room, cfg=cfg)

    assert any(f.element == picked.element for f in after.faces), \
        "the picked wall lost its identity across a rebuild"

    # And show why this layer has to exist: on the reference room this single
    # correction leaves most face ids pointing at a different element than
    # they did before, so anything keyed on an id is now keyed on the wrong
    # thing - silently.
    was = {f.id: f.element for f in before.faces}
    now = {f.id: f.element for f in after.faces}
    moved = sum(1 for i in set(was) & set(now) if was[i] != now[i])
    assert moved > 50, f"expected face ids to churn on rebuild, only {moved} moved"


def test_a_stair_tread_is_not_reported_as_ceiling(room):
    # A tread points straight up, so naming faces by their normal called it
    # the ceiling and export-wall then exported whichever wall was nearest.
    cfg = BuildSettings()
    room.stairs = [Stair(points=[
        Point(f"S_{i}", 100.0 + i * 30.0, -300.0, room.floor_z + 20.0 + i * 17.0,
              "", role=Role.STAIRS) for i in range(5)])]

    tread = (110.0 / 100.0, -300.0 / 100.0, (room.floor_z + 20.0) / 100.0)
    el = face_element(room, cfg, tread, (0.0, 0.0, 1.0))
    assert el is not None
    assert el.kind == "stairs"
    assert el.key.startswith("stairs:S_0")


def test_a_face_in_the_middle_of_the_floor_is_the_floor(room):
    cfg = BuildSettings()
    el = face_element(room, cfg, (2.0, -3.0, room.floor_z / 100.0), (0.0, 0.0, -1.0))
    assert el is not None and el.kind == "floor"


def test_openings_are_keyed_by_their_jamb_points(room):
    assert room.openings, "reference room should have openings"
    for o in room.openings:
        key = opening_key(o)
        assert key.startswith("opening:")
        assert key == opening_key(o)          # stable across calls
    keys = {opening_key(o) for o in room.openings}
    assert len(keys) == len(room.openings)    # and unique per opening


def test_a_removed_wall_key_that_no_longer_exists_is_dropped_not_misapplied(room):
    # The whole reason for names over indices: a stale decision must do
    # nothing, rather than quietly take out a different wall.
    assert wall_edge_for_key(room, "wall:P_999|P_998") is None

    from snapir.solid import build_room, solid_stats
    cfg = BuildSettings()
    plain = solid_stats(build_room(room, cfg))
    stale = solid_stats(build_room(room, cfg, removed_walls=["wall:P_999|P_998"]))
    assert stale["volume_m3"] == pytest.approx(plain["volume_m3"], abs=1e-9)


def test_every_meshed_face_gets_named(room):
    from snapir.solid import build_room
    from snapir.tessellate import tessellate

    cfg = BuildSettings()
    mesh = tessellate(build_room(room, cfg), room=room, cfg=cfg)
    unnamed = [f.id for f in mesh.faces if not f.element]
    assert not unnamed, f"{len(unnamed)} face(s) could not be attributed"
    assert {f.element_kind for f in mesh.faces} <= {
        "wall", "floor", "ceiling", "opening", "fitting", "fixture",
        "stairs", "pervaz"}
