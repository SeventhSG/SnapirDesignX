"""Drive the Python and C++ sidecars through the same calls and diff the JSON.

Both are given their own empty store, pointed at the same survey folder, and
asked the questions the React client asks. Anything the frontend can see has to
come back the same from both.
"""
from __future__ import annotations

import json
import sys
# The C++ side writes UTF-8. Windows hands Python a cp1252 stdout by default,
# which cannot encode a Turkish room name and kills the dump before it prints
# anything - so the two halves could not be compared at all on the machine the
# port is developed on.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import urllib.error
import urllib.request

TIMEOUT = 300


def call(base: str, method: str, path: str, body=None):
    req = urllib.request.Request(
        base + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"} if body is not None else {})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def canon(v, path=""):
    """Strip the fields that are legitimately per-instance, not per-engine."""
    drop = {"id", "pid", "folder", "openedAt", "path", "builtAt", "stepPath", "version"}
    if isinstance(v, dict):
        return {k: canon(x, f"{path}.{k}") for k, x in sorted(v.items()) if k not in drop}
    if isinstance(v, list):
        return [canon(x, path) for x in v]
    if isinstance(v, float):
        return round(v, 6)
    return v


def ring_free(room: dict) -> dict:
    """The outline ring's direction is arbitrary in the Python build."""
    r = dict(room)
    for key in ("outline", "segments", "links", "points", "issues"):
        if key in r and isinstance(r[key], list):
            r[key] = sorted(r[key], key=lambda x: json.dumps(x, sort_keys=True))
    return r


def main(py_base: str, cpp_base: str, folder: str) -> int:
    fails: list[str] = []
    checks = 0

    def compare(label, a, b, normalise=canon):
        nonlocal checks
        checks += 1
        if normalise(a) != normalise(b):
            fails.append(label)
            sa, sb = json.dumps(normalise(a), sort_keys=True), json.dumps(normalise(b), sort_keys=True)
            for i in range(min(len(sa), len(sb))):
                if sa[i] != sb[i]:
                    fails.append(f"    py : ...{sa[max(0,i-70):i+70]}...")
                    fails.append(f"    cpp: ...{sb[max(0,i-70):i+70]}...")
                    break
            else:
                fails.append(f"    py len={len(sa)} cpp len={len(sb)}")

    sp, hp = call(py_base, "GET", "/health")
    sc, hc = call(cpp_base, "GET", "/health")
    compare("health status", sp, sc)
    compare("health ok", hp.get("ok"), hc.get("ok"))

    sp, pp = call(py_base, "POST", "/projects", {"name": "cmp", "folder": folder})
    sc, pc = call(cpp_base, "POST", "/projects", {"name": "cmp", "folder": folder})
    compare("create status", sp, sc)
    compare("create body", pp, pc)
    pid_py, pid_cpp = pp["id"], pc["id"]

    # A folder that is not there has to fail the same way.
    sp, ep = call(py_base, "POST", "/projects", {"name": "x", "folder": folder + "_nope"})
    sc, ec = call(cpp_base, "POST", "/projects", {"name": "x", "folder": folder + "_nope"})
    compare("missing folder status", sp, sc)

    sp, lp = call(py_base, "GET", "/projects")
    sc, lc = call(cpp_base, "GET", "/projects")
    compare("projects status", sp, sc)
    compare("projects list", lp, lc)

    sp, gs_p = call(py_base, "GET", "/settings")
    sc, gs_c = call(cpp_base, "GET", "/settings")
    compare("settings status", sp, sc)
    compare("settings body", gs_p, gs_c)

    sp, rp = call(py_base, "GET", f"/projects/{pid_py}/rooms")
    sc, rc = call(cpp_base, "GET", f"/projects/{pid_cpp}/rooms")
    compare("rooms status", sp, sc)
    compare("rooms count", len(rp["rooms"]), len(rc["rooms"]))
    compare("rooms thickness", rp["thickness"], rc["thickness"])

    by_py = {r["name"]: r for r in rp["rooms"]}
    by_cpp = {r["name"]: r for r in rc["rooms"]}
    compare("room names", sorted(by_py), sorted(by_cpp))

    for name in sorted(by_py):
        compare(f"room {name}", ring_free(by_py[name]), ring_free(by_cpp.get(name, {})))

    # Build, export and wireframe on every room that the survey can carry.
    for name in sorted(by_py):
        q = urllib.parse.quote(name)
        sp, bp = call(py_base, "POST", f"/projects/{pid_py}/rooms/{q}/build")
        sc, bc = call(cpp_base, "POST", f"/projects/{pid_cpp}/rooms/{q}/build")
        compare(f"build status {name}", sp, sc)
        if sp != 200:
            compare(f"build error {name}", bp.get("detail"), bc.get("detail"))
            continue
        compare(f"build stats {name}", bp["stats"], bc["stats"])
        compare(f"build planes {name}", bp["planes"], bc["planes"])
        compare(f"build triangles {name}", bp["mesh"]["triangleCount"],
                bc["mesh"]["triangleCount"])
        compare(f"build faces {name}", len(bp["mesh"]["faces"]), len(bc["mesh"]["faces"]))
        compare(f"build face roles {name}",
                sorted(f["role"] for f in bp["mesh"]["faces"]),
                sorted(f["role"] for f in bc["mesh"]["faces"]))
        compare(f"build face areas {name}",
                sorted(round(f["area"], 4) for f in bp["mesh"]["faces"]),
                sorted(round(f["area"], 4) for f in bc["mesh"]["faces"]))

        sp, xp = call(py_base, "POST", f"/projects/{pid_py}/rooms/{q}/export")
        sc, xc = call(cpp_base, "POST", f"/projects/{pid_cpp}/rooms/{q}/export")
        compare(f"export status {name}", sp, sc)

        sp, dp = call(py_base, "POST", f"/projects/{pid_py}/rooms/{q}/export-designx?fmt=iges")
        sc, dc = call(cpp_base, "POST", f"/projects/{pid_cpp}/rooms/{q}/export-designx?fmt=iges")
        compare(f"designx status {name}", sp, sc)

    # A patch has to land the same way and re-derive the same room.
    target = sorted(by_py)[0]
    q = urllib.parse.quote(target)
    patch = {"ceilingHeight": 260.0, "wallThickness": 15.0}
    sp, mp = call(py_base, "PATCH", f"/projects/{pid_py}/rooms/{q}", patch)
    sc, mc = call(cpp_base, "PATCH", f"/projects/{pid_cpp}/rooms/{q}", patch)
    compare("patch status", sp, sc)
    compare("patch room", ring_free(mp), ring_free(mc))

    sp, np_ = call(py_base, "GET", f"/projects/{pid_py}/rooms/xxx-no-such-room")
    sc, nc_ = call(cpp_base, "GET", f"/projects/{pid_cpp}/rooms/xxx-no-such-room")
    compare("missing room status", sp, sc)

    print(f"checks: {checks}")
    if fails:
        print(f"FAILURES: {sum(1 for f in fails if not f.startswith(' '))}")
        for f in fails[:60]:
            print(("  " + f) if not f.startswith(" ") else f)
        return 1
    print("FAILURES: 0")
    return 0


if __name__ == "__main__":
    import urllib.parse
    raise SystemExit(main(sys.argv[1], sys.argv[2], sys.argv[3]))
