"""The store is shared ground: the C++ core and this implementation read and
write the same projects.json, and the C++ side owns fields this one does not.

These pin the contract that neither side may destroy the other's decisions.
"""
from __future__ import annotations

import json

from snapir.store import ProjectRecord, RoomOverride, Store

CPP_WRITTEN = {
    "version": 1,
    "projects": {
        "abc123456789": {
            "id": "abc123456789",
            "name": "PB Mustafa",
            "folder": ".",
            "created_at": "2026-01-01T00:00:00+00:00",
            "opened_at": "2026-01-02T00:00:00+00:00",
            "thickness": 200.0,
            # Written unconditionally by the C++ store; no field for it here
            # until it was added.
            "connections": [{"id": "c1", "a": "Salon", "b": "Koridor", "enabled": True}],
            "overrides": {"Salon": {"ceiling_height": 268.0, "removed_walls": [2]}},
        }
    },
}


def _store_at(tmp_path, payload):
    path = tmp_path / "projects.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return Store(path)


def test_loads_a_store_the_shipped_app_wrote(tmp_path):
    # Before this was fixed, ProjectRecord(**p) raised TypeError on the
    # connections key - and because server.py builds its Store at import time,
    # that took the entire reference implementation down with it.
    store = _store_at(tmp_path, CPP_WRITTEN)
    proj = store.get("abc123456789")
    assert proj.name == "PB Mustafa"
    assert len(proj.connections) == 1
    assert proj.overrides["Salon"].removed_walls == [2]


def test_saving_does_not_destroy_the_other_core_s_fields(tmp_path):
    store = _store_at(tmp_path, CPP_WRITTEN)
    store.save()

    back = json.loads((tmp_path / "projects.json").read_text(encoding="utf-8"))
    proj = back["projects"]["abc123456789"]
    assert proj["connections"][0]["id"] == "c1"
    assert proj["overrides"]["Salon"]["removed_walls"] == [2]
    assert "extra" not in proj          # the passthrough is not itself a field


def test_unknown_fields_from_a_newer_core_survive_a_round_trip(tmp_path):
    # The same hazard as connections, for whatever the C++ side adds next.
    payload = json.loads(json.dumps(CPP_WRITTEN))
    payload["projects"]["abc123456789"]["someFutureField"] = {"keep": "me"}
    payload["projects"]["abc123456789"]["overrides"]["Salon"]["future_override"] = 7

    store = _store_at(tmp_path, payload)
    store.save()

    proj = json.loads((tmp_path / "projects.json").read_text(encoding="utf-8"))
    proj = proj["projects"]["abc123456789"]
    assert proj["someFutureField"] == {"keep": "me"}
    assert proj["overrides"]["Salon"]["future_override"] == 7


def test_centimetre_thickness_is_still_migrated(tmp_path):
    payload = json.loads(json.dumps(CPP_WRITTEN))
    payload["projects"]["abc123456789"]["thickness"] = 20.0
    store = _store_at(tmp_path, payload)
    assert store.get("abc123456789").thickness == 200.0
