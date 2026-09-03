"""Stairs: detection from a survey, manual correction, and the built body.

Synthetic CSVs here (not the reference dataset, which has no staircase in it)
cover the classifier. The OCCT-level tests build on the real reference room
in fixtures/survey, just with a stair run bolted onto it - the geometry code
only cares about room.stairs and the floor plane, not where the points came
from.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from snapir.model import Point, Role, Stair
from snapir.parser import apply_roles, read_room

HEADER = "Kimlik;X (cm);Y (cm);Z (cm);Katman\n"

# A plain rectangular room: floor tagged, ceiling left for the classifier to
# find, plus five nosings climbing at a consistent 17 cm riser / 30 cm tread.
BASE_ROWS = [
    "P_001;0.00;0.00;0.00;Zemin",
    "P_002;500.00;0.00;0.00;Zemin",
    "P_003;500.00;400.00;0.00;Zemin",
    "P_004;0.00;400.00;0.00;Zemin",
    "P_005;0.00;0.00;270.00;",
    "P_006;500.00;0.00;270.00;",
    "P_007;500.00;400.00;270.00;",
    "P_008;0.00;400.00;270.00;",
]
STAIR_ROWS = [
    "P_009;100.00;100.00;20.00;",
    "P_010;130.00;100.00;37.00;",
    "P_011;160.00;100.00;54.00;",
    "P_012;190.00;100.00;71.00;",
    "P_013;220.00;100.00;88.00;",
]


def _write(tmp_path: Path, name: str, rows: list[str]) -> Path:
    path = tmp_path / f"{name}.csv"
    path.write_text(HEADER + "\n".join(rows) + "\n", encoding="utf-8")
    return path


def test_detect_stairs_tags_a_consistent_run(tmp_path):
    path = _write(tmp_path, "room", BASE_ROWS + STAIR_ROWS)
    room = read_room(path)

    assert len(room.stairs) == 1
    stair = room.stairs[0]
    assert stair.steps == 4
    assert stair.rise == pytest.approx(68.0, abs=0.1)     # 20 -> 88
    assert stair.going == pytest.approx(120.0, abs=0.1)    # 4 * 30 cm
    assert all(p.role is Role.STAIRS for p in stair.points)
    assert not any(i.code == "unclassified" for i in room.issues)


def test_short_run_is_left_unclassified(tmp_path):
    # Only one interval: below STAIR_MIN_STEPS, so it must not read as stairs.
    path = _write(tmp_path, "room", BASE_ROWS + STAIR_ROWS[:2])
    room = read_room(path)

    assert room.stairs == []
    stray = {p.name for p in room.points if p.role is Role.UNKNOWN}
    assert stray == {"P_009", "P_010"}


def test_operator_can_promote_and_demote_stairs(tmp_path):
    # Two points alone don't trip the detector (see above); the operator can
    # still call them a flight by hand, and can just as easily undo it.
    path = _write(tmp_path, "room", BASE_ROWS + STAIR_ROWS[:2])
    room = read_room(path)
    assert room.stairs == []

    apply_roles(room, {"P_009": "stairs", "P_010": "stairs"})
    assert len(room.stairs) == 1
    assert {p.name for p in room.stairs[0].points} == {"P_009", "P_010"}

    apply_roles(room, {"P_009": "unknown", "P_010": "unknown"})
    assert room.stairs == []


def test_two_flights_with_a_landing_gap_stay_separate(tmp_path):
    # A break in survey order bigger than STAIR_RUN_GAP reads as two flights,
    # not one - e.g. a run shot, then something else, then the run resumed.
    rows = BASE_ROWS + STAIR_ROWS + [
        "P_020;250.00;100.00;20.00;",
        "P_021;280.00;100.00;37.00;",
        "P_022;310.00;100.00;54.00;",
        "P_023;340.00;100.00;71.00;",
    ]
    room = read_room(_write(tmp_path, "room", rows))
    assert len(room.stairs) == 2
    assert room.stairs[0].points[0].name == "P_009"
    assert room.stairs[1].points[0].name == "P_020"


FIXTURE = Path(__file__).parent / "fixtures" / "survey" / "Daire 53 - Salon.csv"


def _stair_in(room, n=5) -> Stair:
    """A synthetic flight placed well inside the reference room's outline."""
    pts = [Point(f"S_{i}", 100.0 + i * 30.0, -300.0, room.floor_z + 20.0 + i * 17.0,
                "", role=Role.STAIRS) for i in range(n)]
    return Stair(points=pts)


def test_stairs_add_volume_to_the_built_shell():
    from snapir.settings import BuildSettings
    from snapir.solid import build_room, solid_stats

    room = read_room(FIXTURE)
    cfg = BuildSettings()

    plain = solid_stats(build_room(room, cfg))

    room.stairs = [_stair_in(room)]
    with_stairs = solid_stats(build_room(room, cfg))

    assert with_stairs["volume_m3"] > plain["volume_m3"] + 0.05


def test_removed_wall_opens_the_shell():
    from snapir.elements import wall_key
    from snapir.settings import BuildSettings
    from snapir.solid import build_room, solid_stats

    room = read_room(FIXTURE)
    cfg = BuildSettings()
    gone = wall_key(room.outline[0].name, room.outline[1].name)

    plain = solid_stats(build_room(room, cfg))
    opened = solid_stats(build_room(room, cfg, removed_walls=[gone]))

    assert opened["volume_m3"] < plain["volume_m3"]
