# Snapir Design X 1.4.1 — Sketch merger

## Putting a survey into one frame

Every room is measured from wherever the instrument happened to stand, so a
survey is not one drawing: it is a dozen drawings each in its own coordinate
system, and nothing in the file says how they sit relative to each other. A
stairwell shot floor by floor is where that hurts most — the flights are the
same staircase, and until the floors are in one frame there is no staircase,
only four unrelated boxes.

**Merge sketches**, next to Project settings on the rooms screen, is where they
go into one.

Every room of the survey is drawn in a single plan, each in its own colour. The
room you have made the frame sits where it was surveyed; rooms already matched
sit where they were solved to; rooms nobody has matched are parked in a column
to the right, out of the way but still clickable. Click a corner in one room,
then the same corner in another, and that is a match. Click a **line** in each
instead and both its ends are matched at once — which end answers to which is
worked out rather than asked for, from the placement if there is one and from
the direction of the two runs if there is not.

Nothing is guessed:

- **One match shifts a room. Two fix it.** A single point says where a room is,
  not which way round it is, so the room keeps its own heading until there is a
  second match. Two solve the rotation and the shift together.
- **A third does not overrule the first two, it averages with them** — least
  squares — and the room list carries the RMS in centimetres so a match that
  does not fit says so. Villa Tocheva's reused target names come out at 24 cm,
  which is the app telling you they are not the same markers.
- **A room reaches the frame through another room.** Nobody can see the top of
  a stairwell and the bottom at once, so a room matched only to a room matched
  only to the frame still lands, and the list says which room it came through.
- **Only the matches are stored.** The placements are solved from them on every
  read, so a match deleted never leaves a stale transform behind it.

**Export merged** writes every placed room into one STEP in one frame, fused
into a single body where the kernel will have it — a stairwell's flights share
their walls, so one body is what the building is — and side by side in one file
where it will not, saying which happened.

## Checked

The four floors of `Sofia - Villa Tocheva` merge and export as one fused body.
Both cores return byte-identical answers for the same seven matches, including
which end of a line answers to which. Parse parity across all five surveys:
248, 215, 395, 409 and 1725 fields, zero mismatches. 104 tests, of which 100
run here. The screen itself was driven in a browser rather than assumed: open
the merger, click two corners in one room and the same two in another, and read
back what moved.
