# Snapir Design X 1.3.10 — Snapshot

Four real jobs now open and build: Villa Tocheva, Bojidar, Serkan Bey and
Plovdiv. Before this, Villa Tocheva built one room out of four.

## Skirting was never looked for on most rooms

The board is traced as two runs — the outer line down where the real floor is,
then the same way back along the top of it. That was understood. What was not:
skirting detection only ever ran on rooms whose ring came from the layer tags
or from shot order. On a room with drawn lines beside it — which is most of
them — it was skipped entirely, so the upper run stayed tagged as floor and no
board was ever reported.

`Daire 45 - Oda` now returns all six of its skirtings, 6.4 cm tall and 2.2 cm
proud, with the ring still on the outer line where it belongs.

## A descending flight built itself upside down

Every step box was stacked upward from the room's floor. Seen from the top of a
staircase the flight descends, so each step sits below that floor, and the box
was built inverted. Fusing those into the shell destroyed it: a 10.6 m²
corridor came back as **0.15 m³ across three loose solids**. A step's mass now
runs from its own tread down to whatever the flight rests on. That corridor is
15.5 m³.

## The floor was the landing a storey below

The datum was the lowest reading in the file. Stand in a top-floor corridor and
that is the landing one floor down — 160 cm too low. Every door in the room was
measured against a sill test at that depth and came back a window, then was cut
floor to ceiling. The room's floor is the level its own floor shots sit on,
worked out once the flights have been claimed.

## Fixed

- `dump_solid`, `compare_dumps`, `compare_servers`, `scan` and `build` all died
  on Windows before printing anything, on any room name carrying a Turkish
  letter. `dump_parse` was fixed in 1.3.9; the rest were not.

## Checked

Both cores agree on all four jobs plus the reference: 394, 408, 214 and 1725
fields, zero mismatches each. The 28-room reference job went from 24 rooms
building to 25, and its three remaining failures are the ones its own README
documents.
