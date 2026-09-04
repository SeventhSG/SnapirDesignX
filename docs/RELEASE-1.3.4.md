# Snapir Design X 1.3.4 — Snapshot

## The middle shot can go into the wall as well as out of it

1.3.3 took the distance from the middle shot to the wall and threw away which
side of the wall it was on. Every rectangle with a depth shot became a thing
standing in the room, whether or not that is what was measured.

The depth is signed now. A shot standing into the room is a thing mounted on
the wall and material is added out to it. A shot behind the wall face is a
recess, and the wall is hollowed back to exactly that depth — and no further,
which is what separates a recess from a doorway.

Which side counts as "into the room" is worked out per wall from the room's
own outline, so it does not depend on which way the ring happened to be wound.

## Fixed

- A rectangle's depth was found only while its middle shot was still
  unclassified. The operator's first correction re-ran the classifier, the
  shot was no longer unclassified, the depth was lost, and the object turned
  straight back into a hole in the wall.
- `point_in_polygon` existed twice, once privately inside the solid builder.
  Both the builder and the classifier need to know which side of a wall the
  room is on, so there is one of it now.

## Checked

Five rooms, both cores, zero mismatches across 182 parsed fields and 60 built
ones — including a fixture carrying one rectangle standing 42 cm out of a wall
and another set 9 cm back into it, which read identically on each side.

A recess removes less material than a hole through the same rectangle and more
than none, the room stays a single solid, and a deeper shot takes more wall
away.
