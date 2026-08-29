# Fixtures

## `survey/`

One room out of the PB Mustafa reference job: `Daire 53 - Salon`, the
known-good the C++ core has been checked against since the port.

```
1 solid · 1 shell · 123 faces · 20.922131 m3 · 1220 triangles
```

It is here so CI has something real to build. `tools/verify_ios_sim.py` stages
it into a booted simulator and asserts those numbers over the HTTP API; a room
whose volume moved is a failed build, not a warning.

**Redacted.** The instrument serial number in the `_FUKOKU.csv` is replaced
with `REDACTED`. The parser reads neither it nor the device model, and the
build was re-run afterwards to confirm the numbers are unchanged. What is left
is a room-local point cloud with its origin at 0,0,0 — no geo-reference, no
address.

Do not edit these files. Regenerating them from the survey folder means
redacting the serial again and re-checking the volume.
