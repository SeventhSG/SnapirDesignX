"""Regression tests pinned to the reference survey.

Set SNAPIR_SAMPLES to a folder of Leica iCON room CSVs to run these.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from snapir.geometry import polygon_area, self_intersections
from snapir.parser import read_room

SAMPLES = Path(os.environ.get("SNAPIR_SAMPLES", ""))
needs_samples = pytest.mark.skipif(
    not SAMPLES.is_dir(), reason="SNAPIR_SAMPLES not set"
)


@needs_samples
def test_tagged_room_matches_survey():
    r = read_room(SAMPLES / "Daire 53 - Salon.csv")
    assert r.outline_source == "surveyed layer"
    assert len(r.outline) == 11
    assert polygon_area([p.xy for p in r.outline]) / 10_000 == pytest.approx(23.41, abs=0.05)
    assert 265 <= r.ceiling_height() <= 280
    assert not r.has_errors


@needs_samples
def test_floor_datum_is_not_assumed_zero():
    """This room was surveyed with the origin at instrument height."""
    r = read_room(SAMPLES / "Daire 51 - Koridor.csv")
    assert r.floor_z == pytest.approx(-126.66, abs=0.5)
    assert r.ceiling_height() == pytest.approx(272, abs=5)


@needs_samples
def test_openings_are_split_into_doors_and_windows():
    r = read_room(SAMPLES / "Daire 53 - Salon.csv")
    kinds = {o.kind for o in r.openings}
    assert "door" in kinds
    assert all(o.width > 50 for o in r.openings)


@needs_samples
def test_reshoot_is_flagged_not_guessed():
    r = read_room(SAMPLES / "Daire 56 - Oda.csv")
    assert any(i.code == "self-intersecting" for i in r.issues)
    assert r.has_errors


def test_self_intersection_detection():
    square = [(0, 0), (10, 0), (10, 10), (0, 10)]
    bowtie = [(0, 0), (10, 10), (10, 0), (0, 10)]
    assert self_intersections(square) == []
    assert self_intersections(bowtie)
