"""Offsetting a room that has a niche narrower than its own walls.

Both cores mitre the outline outward. Where a feature is narrower than twice
the wall, its two sides each move toward the other and the ring folds back on
itself. That fold is not an error - it is the niche filling with wall, which
is what the building does.
"""
from __future__ import annotations

import pytest

from snapir.geometry import polygon_area, self_intersections
from snapir.solid import _offset_ring, cm

# Daire 56 - Salon, cut down to the alcove that used to refuse to build: a
# niche 37 cm wide in a room with 20 cm walls.
NICHE_ROOM = [
    (0.0, 0.0), (-342.5, 0.0), (-342.5, -36.2),
    (-341.0, -111.7), (-303.9, -109.3), (-304.0, -151.4), (-340.1, -152.1),
    (-340.0, -600.0), (0.0, -600.0),
]


def test_a_niche_narrower_than_the_walls_still_builds():
    ring = NICHE_ROOM
    out = _offset_ring(ring, cm(200.0))          # 20 cm walls
    assert self_intersections(out) == []
    # Grown, not shrunk, and the niche has filled rather than folded.
    assert polygon_area(out) > polygon_area(ring)


def test_the_fold_is_dissolved_not_kept():
    thin = _offset_ring(NICHE_ROOM, cm(50.0))    # 5 cm: niche survives
    thick = _offset_ring(NICHE_ROOM, cm(200.0))  # 20 cm: niche fills in
    assert self_intersections(thin) == []
    assert self_intersections(thick) == []
    # Filling the niche costs corners.
    assert len(thick) < len(thin)


def test_a_plain_room_is_untouched():
    square = [(0.0, 0.0), (400.0, 0.0), (400.0, 300.0), (0.0, 300.0)]
    out = _offset_ring(square, cm(200.0))
    assert len(out) == 4
    assert polygon_area(out) / 10_000 == pytest.approx(4.4 * 3.4, abs=0.01)
