"""Constructing the corner nobody stood in.

Where a survey stops short - only one side of a stairwell shot, a wall run
that ends before the corner - the operator extends the lines until they meet.
The crossing is a derived point: constructed, never measured, and it has to
stay obviously different from a shot.
"""
from __future__ import annotations

import pytest

from snapir.geometry import crossings, extend, line_intersection


def test_two_wall_runs_meet_at_the_corner_neither_reached():
    # One run along y=0, another along x=400, both stopping well short.
    a, b = (0.0, 0.0), (300.0, 0.0)
    c, d = (400.0, 200.0), (400.0, 500.0)
    assert line_intersection(a, b, c, d) == pytest.approx((400.0, 0.0))


def test_parallel_walls_never_meet():
    assert line_intersection((0, 0), (100, 0), (0, 50), (100, 50)) is None


def test_near_parallel_is_treated_as_parallel():
    # A hair of survey noise must not throw a corner a kilometre away.
    assert line_intersection((0, 0), (100, 0), (0, 50), (100, 50 + 1e-12)) is None


def test_extending_a_line_keeps_its_direction():
    assert extend((0.0, 0.0), (100.0, 0.0), 50.0) == pytest.approx((150.0, 0.0))
    got = extend((0.0, 0.0), (30.0, 40.0), 50.0)      # 3-4-5, length 50
    assert got == pytest.approx((60.0, 80.0))


def test_a_crossing_is_found_and_located():
    segs = [((0.0, 0.0), (100.0, 0.0)), ((50.0, -50.0), (50.0, 50.0))]
    hits = crossings(segs)
    assert len(hits) == 1
    i, j, at = hits[0]
    assert (i, j) == (0, 1)
    assert at == pytest.approx((50.0, 0.0))


def test_walls_meeting_at_a_surveyed_corner_are_not_a_crossing():
    # Two walls of a room share a corner. That is a corner, not a discovery.
    segs = [((0.0, 0.0), (100.0, 0.0)), ((100.0, 0.0), (100.0, 80.0))]
    assert crossings(segs) == []


def test_lines_that_only_would_cross_if_extended_do_not_count_yet():
    # crossings() reports real crossings; reaching the corner is the
    # operator's decision to extend, not something inferred behind their back.
    segs = [((0.0, 0.0), (40.0, 0.0)), ((100.0, -50.0), (100.0, 50.0))]
    assert crossings(segs) == []
    assert line_intersection(*segs[0], *segs[1]) == pytest.approx((100.0, 0.0))
