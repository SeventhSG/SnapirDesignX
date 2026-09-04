# Snapir Design X 1.3.13 — Snapshot

Four things this time, all of them about the drawing rather than the body: what
leaves for Design X, what comes back from it, where a point is allowed to be,
and what a window in the corner of a room is.

## The dots now leave with the room

A shot in the middle of a rectangle is the one measurement the drawing cannot
show on its own — the four corners look identical whether the boiler is 8 cm
deep or 40. It was never written into the IGES or the STEP at all, so every
fitting arrived in Design X flat against its wall.

Each measured rectangle now goes out as a box: the far face where the shot put
it, joined back to the rectangle corner by corner. The shot itself goes as an
IGES point, and as a small cross so it survives STEP, whose writer drops a
loose vertex on the floor. Stairs go as the line the surveyor walked up;
skirting goes as the diagonal it was shot as. None of it was being handed over
before.

## And the room can come back

**From Design X** reads an edited sketch back into the room it came from. The
trick is names: a corner that lands on a surveyed shot keeps that shot's name,
so every decision already made about this room — a door relabelled a boiler, a
wall taken out, a role corrected — still finds the point it was made about.
Only what actually moved gets a new name, and those arrive as points waiting to
be told what they are rather than quietly joining the ring.

Importing again replaces the last import rather than piling on top of it, so
the same file twice leaves the room where once did, and **Drop the sketch**
goes back to the survey as shot. The CSV is never touched at any point.

## A point can be picked up

**Move**, under Layer, puts three axis handles on the selected point. Drag one
and the point goes along that axis and nowhere else. The panel says plainly
that it is not where the instrument put it, and **Put it back** returns it. The
shot as taken is still in the survey file the whole time.

## A window in the corner of a room

Two jambs on two different walls, with the pier between them glazed. The
classifier refused to pair those at all — a corner window was two loose jambs
and no opening — and where one did get through, from the surveyor's own drawn
lines, it was cut as a single box on the diagonal: a slice off the corner with
the pier still standing behind it.

Jambs now pair across one shared corner, and the cut follows the wall — jamb,
round the corner on the mitre, jamb — so both returns and the pier between them
come out together. Only where both jambs actually sit on their walls: further
off than the wall is thick and it is not a corner window, it is a shot the ring
never reached.

## Fixed

- The sign of a measured depth was decided by which way the outline happened to
  be wound and which jamb came first, in any room the surveyor did not draw
  lines for — because the ring had not been assembled yet when the depth was
  read. A boiler standing in the room could come back as a recess cut into the
  wall behind it.
- A doorway in `Daire 45 - Salon` was pairing a jamb at the corner with one
  nearly two metres away on the next wall, making a 192 cm hole where the
  building has an 86 cm door.

## Checked

Both cores agree across all four surveys: 248, 215, 395 and 409 fields, zero
mismatches. 84 tests, of which 80 run here — four need the private sample set.
`Ara Kat` still differs between the two cores, as it did before this release:
it is a landing with no outline of its own and builds as nine loose solids.
