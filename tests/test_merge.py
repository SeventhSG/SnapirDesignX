"""Putting the rooms of one survey into a single frame.

Every room is measured from wherever the instrument stood, so a survey is a
dozen drawings each in its own coordinate system. The operator says which
corner in one room is which corner in another; these are the sums that turn
that into a placement, and the properties they have to keep.
"""
from __future__ import annotations

import copy
import math
import tempfile
from pathlib import Path

import pytest

from snapir.merge import Pair, Placement, endpoints_for_lines, solve
from snapir.parser import read_room

CORNERS = [(0, 0), (400, 0), (400, 300), (0, 300)]
CEIL = 260.0


def _room(name: str, corners=CORNERS):
    rows, n = ["Kimlik;X (cm);Y (cm);Z (cm);Katman"], 1
    for x, y in corners:
        rows.append(f"P_{n:03d};{x:.2f};{y:.2f};0.00;Zemin")
        n += 1
    for x, y in corners:
        rows.append(f"P_{n:03d};{x:.2f};{y:.2f};{CEIL:.2f};")
        n += 1
    p = Path(tempfile.mkdtemp()) / f"{name}.csv"
    p.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return read_room(p)


def _moved(room, name: str, place: Placement):
    """The same room as another instrument would have measured it."""
    out = copy.deepcopy(room)
    out.name = name
    for p in out.points:
        p.x, p.y, p.z = place.apply(p.x, p.y, p.z)
    for p in out.outline:
        pass  # outline holds the same Point objects
    return out


def test_two_pairs_recover_the_transform_exactly():
    a = _room("A")
    truth = Placement(dx=317.0, dy=-88.5, dz=290.0, rotation_deg=37.0)
    b = _moved(a, "B", truth)

    names = [p.name for p in a.points[:2]]
    placed, loose = solve({"A": a, "B": b},
                          [Pair("A", n, "B", n) for n in names], anchor="A")
    assert not loose
    got = placed["B"]
    # B is carried back onto A, so the placement is the inverse of the move.
    assert got.rotation_deg == pytest.approx(-truth.rotation_deg, abs=1e-6)
    assert got.dz == pytest.approx(-truth.dz, abs=1e-6)
    assert got.residual == pytest.approx(0.0, abs=1e-6)
    # And it actually lands: every point of B falls on its twin in A.
    for p, q in zip(a.points, b.points):
        x, y, z = got.apply(q.x, q.y, q.z)
        assert (x, y, z) == pytest.approx((p.x, p.y, p.z), abs=1e-6)


def test_the_anchor_is_the_frame():
    a, b = _room("A"), _moved(_room("A"), "B", Placement(dx=50, dy=50))
    placed, _ = solve({"A": a, "B": b}, [Pair("A", "P_001", "B", "P_001")], anchor="A")
    assert placed["A"] == Placement()
    assert placed["A"].via == ""


def test_one_pair_shifts_but_does_not_turn():
    # A single point says where a room is, not which way round it is. Guessing
    # a rotation off one point would spin the room on its own corner.
    a = _room("A")
    b = _moved(a, "B", Placement(dx=120.0, dy=-40.0, rotation_deg=25.0))
    placed, _ = solve({"A": a, "B": b}, [Pair("A", "P_001", "B", "P_001")], anchor="A")
    assert placed["B"].rotation_deg == 0.0
    x, y, _z = placed["B"].apply(b.points[0].x, b.points[0].y, b.points[0].z)
    assert (x, y) == pytest.approx((a.points[0].x, a.points[0].y), abs=1e-6)


def test_a_room_reaches_the_frame_through_another_room():
    # Nobody can see the top of a stairwell and the bottom at once. C is
    # matched only to B, and B only to A, and C still has to land in A's frame.
    a = _room("A")
    b = _moved(a, "B", Placement(dx=500.0, dy=0.0, dz=300.0, rotation_deg=90.0))
    c = _moved(a, "C", Placement(dx=-220.0, dy=610.0, dz=600.0, rotation_deg=-45.0))

    pairs = [Pair("A", "P_001", "B", "P_001"), Pair("A", "P_002", "B", "P_002"),
             Pair("B", "P_003", "C", "P_003"), Pair("B", "P_004", "C", "P_004")]
    placed, loose = solve({"A": a, "B": b, "C": c}, pairs, anchor="A")
    assert not loose
    assert placed["C"].via == "B"
    for p, q in zip(a.points, c.points):
        assert placed["C"].apply(q.x, q.y, q.z) == pytest.approx((p.x, p.y, p.z), abs=1e-6)


def test_a_room_nobody_matched_is_named_rather_than_guessed():
    a, b = _room("A"), _room("B")
    placed, loose = solve({"A": a, "B": b}, [], anchor="A")
    assert loose == ["B"]
    assert "B" not in placed


def test_a_third_pair_averages_rather_than_overrules():
    # Real readings disagree by a centimetre or two. Three pairs must land
    # between them, not on the last one, and must say how far apart they were.
    a = _room("A")
    b = _moved(a, "B", Placement(dx=100.0, dy=20.0, rotation_deg=15.0))
    b.points[2].x += 3.0            # one corner read 3 cm out
    names = [p.name for p in a.points[:3]]
    placed, _ = solve({"A": a, "B": b},
                      [Pair("A", n, "B", n) for n in names], anchor="A")
    assert 0.1 < placed["B"].residual < 3.0
    assert placed["B"].pairs == 3


def test_two_lines_pair_their_ends_the_right_way_round():
    a = _room("A")
    b = _moved(a, "B", Placement(dx=90.0, dy=15.0, rotation_deg=12.0))
    # The same wall, traced the other way in the second room.
    made = endpoints_for_lines(a, ("P_001", "P_002"), b, ("P_002", "P_001"))
    assert {(p.point_a, p.point_b) for p in made} == {("P_001", "P_001"),
                                                      ("P_002", "P_002")}
    # And traced the same way, it stays the same way.
    made = endpoints_for_lines(a, ("P_001", "P_002"), b, ("P_001", "P_002"))
    assert {(p.point_a, p.point_b) for p in made} == {("P_001", "P_001"),
                                                      ("P_002", "P_002")}


def test_a_pair_is_the_same_pair_read_either_way():
    one = Pair("A", "P_001", "B", "P_004")
    other = Pair("B", "P_004", "A", "P_001")
    assert one.key == other.key


def test_the_whole_thing_builds_as_one_body():
    from snapir.merge import build_merged
    from snapir.settings import BuildSettings
    from snapir.solid import solid_stats

    a = _room("A")
    # Side by side, sharing a wall line, the way two rooms of a flat do.
    b = _moved(a, "B", Placement(dx=400.0, dy=0.0))
    placed, _ = solve({"A": a, "B": b},
                      [Pair("A", "P_002", "B", "P_001"),
                       Pair("A", "P_003", "B", "P_004")], anchor="A")
    shape, failed, how = build_merged({"A": a, "B": b}, placed, BuildSettings())
    assert not failed
    stats = solid_stats(shape)
    assert stats["volume_m3"] > 0
    assert how in ("fused", "side by side")


def test_a_quarter_turn_swings_the_room_round_its_match():
    # Two matches on a short baseline fix a heading out of a couple of
    # centimetres, and a corner matched to the wrong corner fixes it out of
    # nothing. Either way the room lands attached and facing the wrong way, and
    # the solver cannot say so: by its own measure it is the best answer there
    # is. The turn is the operator's, and it has to leave the match where it is.
    a = _room("A")
    b = _moved(a, "B", Placement(dx=500.0, dy=0.0))
    pairs = [Pair("A", "P_001", "B", "P_001"), Pair("A", "P_002", "B", "P_002")]

    plain, _ = solve({"A": a, "B": b}, pairs, anchor="A")
    turned, _ = solve({"A": a, "B": b}, pairs, anchor="A", turns={"B": 1})

    assert turned["B"].rotation_deg == pytest.approx(
        plain["B"].rotation_deg + 90.0, abs=1e-9)
    # The match itself has not moved: the room turns about the middle of the
    # corners it was pinned by, so the pinning stays as good as it was.
    pins = [q for q in b.points if q.name in ("P_001", "P_002")]
    def mid(place):
        at = [place.apply(q.x, q.y, q.z) for q in pins]
        return (sum(p[0] for p in at) / 2, sum(p[1] for p in at) / 2)
    assert mid(turned["B"]) == pytest.approx(mid(plain["B"]), abs=1e-6)
    # And a corner away from the match has.
    far = next(p for p in b.points if p.name == "P_003")
    assert turned["B"].apply(far.x, far.y, far.z)[:2] != pytest.approx(
        plain["B"].apply(far.x, far.y, far.z)[:2], abs=1.0)


def test_four_quarter_turns_are_none():
    a = _room("A")
    b = _moved(a, "B", Placement(dx=500.0, dy=0.0))
    pairs = [Pair("A", "P_001", "B", "P_001"), Pair("A", "P_002", "B", "P_002")]
    plain, _ = solve({"A": a, "B": b}, pairs, anchor="A")
    round_trip, _ = solve({"A": a, "B": b}, pairs, anchor="A", turns={"B": 4})
    for p in b.points:
        assert round_trip["B"].apply(p.x, p.y, p.z) == pytest.approx(
            plain["B"].apply(p.x, p.y, p.z), abs=1e-6)


def test_a_room_placed_through_a_turned_room_follows_it():
    # C is measured against B. Turning B has to carry C with it, or the two
    # come apart the moment the operator fixes B's heading.
    a = _room("A")
    b = _moved(a, "B", Placement(dx=500.0, dy=0.0))
    c = _moved(a, "C", Placement(dx=-220.0, dy=610.0, rotation_deg=-45.0))
    pairs = [Pair("A", "P_001", "B", "P_001"), Pair("A", "P_002", "B", "P_002"),
             Pair("B", "P_003", "C", "P_003"), Pair("B", "P_004", "C", "P_004")]

    plain, _ = solve({"A": a, "B": b, "C": c}, pairs, anchor="A")
    turned, _ = solve({"A": a, "B": b, "C": c}, pairs, anchor="A", turns={"B": 1})
    assert turned["C"].via == "B"
    # B's own corner and C's twin of it still coincide after the turn.
    bp = next(p for p in b.points if p.name == "P_003")
    cp = next(p for p in c.points if p.name == "P_003")
    assert turned["C"].apply(cp.x, cp.y, cp.z) == pytest.approx(
        turned["B"].apply(bp.x, bp.y, bp.z), abs=1e-6)
    # And C has actually moved with it.
    assert turned["C"].apply(cp.x, cp.y, cp.z)[:2] != pytest.approx(
        plain["C"].apply(cp.x, cp.y, cp.z)[:2], abs=1.0)


def test_the_merge_is_a_room_of_its_own():
    # An export is a file. A room is a thing you can open, look at, build and
    # export - which is what the merged whole has to be.
    from snapir.merge import MERGED_ROOM, assemble

    a = _room("A")
    b = _moved(a, "B", Placement(dx=400.0, dy=0.0, dz=280.0))
    placed, _ = solve({"A": a, "B": b},
                      [Pair("A", "P_002", "B", "P_001"),
                       Pair("A", "P_003", "B", "P_004")], anchor="A")
    merged = assemble({"A": a, "B": b}, placed)

    assert merged.name == MERGED_ROOM
    assert merged.outline_source == "merged"
    assert len(merged.points) == len(a.points) + len(b.points)
    assert len(merged.segments) == len(a.segments) + len(b.segments)
    # A corner says which survey it came from and which shot it was.
    assert merged.points[0].name.startswith("A/")
    assert any(p.name.startswith("B/") for p in merged.points)
    # Roles survive: each room was classified on its own, correctly.
    assert {p.role for p in merged.points} == (
        {p.role for p in a.points} | {p.role for p in b.points})
    # No ring, because four floors are not one ring.
    assert merged.outline == []
    # It reaches from the lowest thing in it to the highest, whatever they are.
    assert merged.floor_z == pytest.approx(min(p.z for p in merged.points))
    assert merged.ceiling_z == pytest.approx(max(p.z for p in merged.points))


def test_the_merged_room_follows_the_rooms_it_is_made_of():
    # It is derived, never stored. Correct a wall in one of its parts and the
    # merged room has that correction, without anything being rebuilt by hand.
    from snapir.merge import assemble

    a = _room("A")
    b = _moved(a, "B", Placement(dx=400.0, dy=0.0))
    pairs = [Pair("A", "P_002", "B", "P_001"), Pair("A", "P_003", "B", "P_004")]
    placed, _ = solve({"A": a, "B": b}, pairs, anchor="A")

    was = assemble({"A": a, "B": b}, placed).points[0].x
    a.points[0].x -= 25.0
    placed, _ = solve({"A": a, "B": b}, pairs, anchor="A")
    assert assemble({"A": a, "B": b}, placed).points[0].x == pytest.approx(was - 25.0)
