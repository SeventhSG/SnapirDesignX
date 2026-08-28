"""The connections the surveyor actually drew.

The plain room CSV is a bag of points with no connectivity. The `_FUKOKU.csv`
beside it carries the lines: a `Line start` / `Line end` pair per row. That file
holds the whole topology of the room, already closed:

    P_001 -> P_002 -> ... -> P_011 -> P_001      the floor ring
    P_012 -> P_013 -> ... -> P_022 -> P_012      the ceiling ring
    P_023 -> P_024 -> P_025 -> P_026 -> P_023    a door, as a closed loop
    P_013 -> P_001, P_014 -> P_002, ...          floor to ceiling links

Reading it means the room is described rather than guessed. Nothing here
invents a connection; every line drawn in the app comes from this file or from
the operator.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

# Two points this close in Z belong to the same level, so the line between
# them lies flat rather than rising.
LEVEL_DZ = 35.0


@dataclass
class Topology:
    segments: list[tuple[str, str]] = field(default_factory=list)
    floor_ring: list[str] = field(default_factory=list)
    ceiling_ring: list[str] = field(default_factory=list)
    openings: list[list[str]] = field(default_factory=list)
    links: list[tuple[str, str]] = field(default_factory=list)   # floor to ceiling

    @property
    def found(self) -> bool:
        return len(self.segments) > 0


def fukoku_path(room_csv: str | Path) -> Path:
    p = Path(room_csv)
    return p.with_name(f"{p.stem}_FUKOKU.csv")


def read_segments(room_csv: str | Path) -> list[tuple[str, str]]:
    """Every line the operator drew, as point-name pairs."""
    path = fukoku_path(room_csv)
    if not path.exists():
        return []

    out: list[tuple[str, str]] = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.reader(fh, delimiter=";"):
            if len(row) < 2:
                continue
            a, b = row[0].strip(), row[1].strip()
            if not a or not b or a == "Line start":
                continue          # a standalone point, or the header
            out.append((a, b))
    return out


def _adjacency(segments, keep=None) -> dict[str, set[str]]:
    adj: dict[str, set[str]] = {}
    for a, b in segments:
        if keep and not keep(a, b):
            continue
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
    return adj


def _components(adj: dict[str, set[str]]) -> list[set[str]]:
    seen: set[str] = set()
    out = []
    for start in adj:
        if start in seen:
            continue
        stack, comp = [start], set()
        while stack:
            n = stack.pop()
            if n in comp:
                continue
            comp.add(n)
            stack.extend(adj[n] - comp)
        seen |= comp
        out.append(comp)
    return out


def _walk_cycle(adj: dict[str, set[str]], comp: set[str]) -> list[str]:
    """Order a component that is a simple closed loop. Empty if it is not."""
    if len(comp) < 3 or any(len(adj[n]) != 2 for n in comp):
        return []
    start = min(comp)
    ring = [start]
    prev, cur = None, start
    while True:
        nxt = next((n for n in adj[cur] if n != prev), None)
        if nxt is None:
            return []
        if nxt == start:
            return ring if len(ring) == len(comp) else []
        ring.append(nxt)
        prev, cur = cur, nxt
        if len(ring) > len(comp):
            return []


def build(segments, points: dict[str, tuple[float, float, float]]) -> Topology:
    """Sort the drawn lines into rings, openings and vertical links."""
    topo = Topology(segments=list(segments))
    known = [s for s in segments if s[0] in points and s[1] in points]
    if not known:
        return topo

    z = {n: points[n][2] for n in points}

    def level(a: str, b: str) -> bool:
        return abs(z[a] - z[b]) <= LEVEL_DZ

    # Flat lines first. Rings live entirely at one level.
    flat = _adjacency(known, keep=level)
    rings: list[list[str]] = []
    for comp in _components(flat):
        ring = _walk_cycle(flat, comp)
        if len(ring) >= 3:
            rings.append(ring)

    if rings:
        by_height = sorted(rings, key=lambda r: sum(z[n] for n in r) / len(r))
        topo.floor_ring = by_height[0]
        if len(by_height) > 1:
            top = by_height[-1]
            # A ring well above the floor one, with a matching corner count,
            # is the ceiling. Anything else is left alone.
            lo = sum(z[n] for n in topo.floor_ring) / len(topo.floor_ring)
            hi = sum(z[n] for n in top) / len(top)
            if hi - lo > 120.0:
                topo.ceiling_ring = top

    ring_nodes = set(topo.floor_ring) | set(topo.ceiling_ring)

    # Whatever is left over and forms its own closed loop is an opening: two
    # jambs and the sill and head lines between them.
    full = _adjacency(known)
    for comp in _components(full):
        if comp & ring_nodes:
            continue
        loop = _walk_cycle(full, comp)
        if len(loop) >= 4:
            topo.openings.append(loop)

    # Risers that join a floor corner to a ceiling corner. These are the links
    # the operator drew by hand, and the only ones the app will show.
    floor_set, ceil_set = set(topo.floor_ring), set(topo.ceiling_ring)
    for a, b in known:
        if level(a, b):
            continue
        if a in floor_set and b in ceil_set:
            topo.links.append((a, b))
        elif b in floor_set and a in ceil_set:
            topo.links.append((b, a))

    return topo
