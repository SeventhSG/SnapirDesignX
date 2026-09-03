# Snapir Design X 1.3.1 — Snapshot

Three things the survey was already telling the app, and the app was throwing
away or getting wrong. None of them needed a new field on site; they were all
in the data already.

## A rectangle on a wall is not always a hole

A boiler is four corners on a wall. So is a socket panel, a wall lamp, and a
window. The classifier could only read them one way, so every бойлер and
щепсел ever surveyed as a rectangle was being cut clean through the wall of
the exported body, silently and without a single warning.

Rectangles now carry a kind — door, window, boiler, socket, lamp, panel, or
nothing at all — and only the first two are cut. The rest stand into the room
as solids: a boiler as an upright tank, the others as plates the size of the
rectangle they were shot as. Everything grows inward from the surveyed face,
the same rule the walls follow, so the measurement never moves.

The classifier still guesses a window, because from four corners on a wall
there is nothing better to go on. Click the rectangle and tell it what it
really is; the answer is remembered against the points it was built from, so
it survives every later rebuild.

Depth is the one thing the survey does not contain, so it comes from settings,
per kind.

## Skirting, shot as a pair, read as a corner

Pervaz gets shot twice at each corner: once on the wall above the board, once
at floor level on its outer face. The diagonal between them is the whole
measurement — the rise is the board's height, the plan offset is how far it
stands proud.

Both shots were landing in the outline. A four-corner room came out with
eight, a two-centimetre zigzag at every corner, a floor plane fitted through
two different heights, and an area out by more than a percent. It validated
cleanly, which is what made it dangerous.

The pair is recognised by its own geometry now and folded back into one
corner, with the board's height and depth kept. Nothing is moved: the
floor-level shot keeps the corner, because it is the one that measured the
floor.

## Stairs, shot either way

A flight is recognised whether it was traced one shot per nosing, or as the
zigzag where the treads meet the wall, corner by corner. The second is what
comes back when only the side wall of a stairwell is surveyed, and it used to
detect nothing at all. Which convention was used is read from the data, not
configured.

## Everything in the room now has a name

Under all three: a face in the body used to be identified by an OCCT ordinal,
which means something different after every rebuild. On the reference room,
removing a single wall leaves 74 of 123 face ids pointing at a different
element than before — so anything remembered against an id was quietly
remembered against the wrong thing.

Elements are named after the survey points they were built from —
`wall:P_003|P_004`, `opening:P_012|P_015` — and those names outlive a rebuild.
Click any face and the inspector says "Boiler" or "Wall 3 of 11" instead of
guessing from which way the face happens to point. On the reference room that
guess was wrong for 99 of 123 faces: a socket's underside was being reported
as floor.

Removed walls and rectangle kinds are keyed the same way. A key that no longer
resolves — its corner was dropped, the ring redrawn — is discarded rather than
applied to whatever now sits in that position.

## Drawing to where the survey stopped

Sketch lines can be dragged longer. The drag follows the line's own direction
and will not swing it: a wall's direction was measured, only how far it runs
is in question.

Where two lines cross is offered as a corner you can adopt, which is how a
survey that only covers one side of a stairwell gets closed — run both walls
out, take the crossing. Points made this way are marked as constructed, carry
how they were made, and are never mistaken for a shot.

## Fixed

- The Python reference could not load a `projects.json` the shipped app had
  written. `connections` is not a field it knows, and its store is built at
  import, so an unknown key took the whole implementation down. Either side
  now carries fields the other owns rather than rejecting or dropping them.
- A stair that failed to fuse was skipped in silence, reporting success for a
  body with geometry missing.
- `export-wall` resolved a picked face by projecting its centroid onto the
  ring, which answered "wall 4" for a stair riser or a door reveal and
  exported the wrong body. It also built a different body than `/export` did,
  ignoring removed walls.
- A detector could re-derive the very thing the operator had just corrected on
  the next rebuild. A point they have named is left alone now.
- `dump_parse.py` died on Windows before printing anything, because the
  instrument's own name does not fit cp1252 — so the two implementations could
  not be compared at all on the machine the port is developed on.

## Checked

The C++ core carries all of this, not just the Python reference, so it is in
the app rather than only in the tools.

`dump_parse` agrees between the two implementations on the reference room —
79 fields, zero mismatches — and on a fixture built to exercise the new code:
skirting pairs, a flight shot at the nosings, the same flight traced as a
zigzag, and a rectangle on a wall. 108 fields, zero mismatches. The parse dump
now spells out each flight and each skirting rather than counting them, since
two cores can tag the same points and still split them into different flights.

`Daire 53 - Salon` builds to 1 solid, 1 shell, 123 faces, 20.922131 m³ and
1220 triangles in both, unchanged from 1.3.0.
