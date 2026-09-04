"""Compare the Python reference dump against the C++ one.

Most fields must match exactly. Two do not, and the reason is worth stating:
the Python topology walk picks a starting direction out of a set, so the ring
it returns can come back either way round between runs of the same build. The
C++ walk is deterministic. A ring and its reverse describe the same room, so
outline and ceiling order are compared as cyclic sequences up to direction, and
signed area by magnitude. Everything else, including every coordinate, every
role, every opening and every issue, is compared exactly.
"""
from __future__ import annotations

import sys
# The C++ side writes UTF-8. Windows hands Python a cp1252 stdout by default,
# which cannot encode a Turkish room name and kills the dump before it prints
# anything - so the two halves could not be compared at all on the machine the
# port is developed on.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from collections import defaultdict


def load(path: str) -> dict[tuple[str, str], str]:
    out: dict[tuple[str, str], str] = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            room, key, value = line.rstrip("\n").split("|", 2)
            out[(room, key)] = value
    return out


def sequences(d: dict[tuple[str, str], str], prefix: str) -> dict[str, list[str]]:
    seqs: dict[str, dict[int, str]] = defaultdict(dict)
    for (room, key), value in d.items():
        if key.startswith(prefix + "["):
            seqs[room][int(key[len(prefix) + 1:-1])] = value
    return {room: [v for _, v in sorted(items.items())] for room, items in seqs.items()}


def canonical(seq: list[str]) -> tuple[str, ...]:
    """A ring, independent of where it starts and which way it runs."""
    if not seq:
        return ()
    rotations = [tuple(seq[i:] + seq[:i]) for i in range(len(seq))]
    back = list(reversed(seq))
    rotations += [tuple(back[i:] + back[:i]) for i in range(len(back))]
    return min(rotations)


def main(py_path: str, cpp_path: str) -> int:
    py, cpp = load(py_path), load(cpp_path)
    failures: list[str] = []

    only_py = set(py) - set(cpp)
    only_cpp = set(cpp) - set(py)
    for room, key in sorted(only_py):
        failures.append(f"missing in C++: {room}|{key} = {py[(room, key)]}")
    for room, key in sorted(only_cpp):
        failures.append(f"extra in C++:   {room}|{key} = {cpp[(room, key)]}")

    ring_prefixes = ("outline", "ceiling")
    checked_rings = 0
    for prefix in ring_prefixes:
        a, b = sequences(py, prefix), sequences(cpp, prefix)
        for room in sorted(set(a) | set(b)):
            if canonical(a.get(room, [])) != canonical(b.get(room, [])):
                failures.append(f"{room}: {prefix} ring differs beyond direction")
            else:
                checked_rings += 1

    exact = 0
    for key in sorted(set(py) & set(cpp)):
        room, field = key
        if field.startswith(ring_prefixes[0] + "[") or field.startswith(ring_prefixes[1] + "["):
            continue
        if field == "signed_area":
            if abs(float(py[key])) != abs(float(cpp[key])):
                failures.append(f"{room}: |signed_area| {py[key]} vs {cpp[key]}")
            else:
                exact += 1
            continue
        if py[key] != cpp[key]:
            failures.append(f"{room}|{field}: {py[key]!r} vs {cpp[key]!r}")
        else:
            exact += 1

    rooms = len({room for room, _ in py})
    print(f"rooms:          {rooms}")
    print(f"fields exact:   {exact}")
    print(f"rings matched:  {checked_rings}")
    if failures:
        print(f"MISMATCHES:     {len(failures)}")
        for f in failures[:40]:
            print("  " + f)
        return 1
    print("MISMATCHES:     0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
