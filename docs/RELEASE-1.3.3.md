# Snapir Design X 1.3.3 — Snapshot

## A thing on the wall is not a hole in it

1.3.2 could measure how far a boiler stuck out, and then punched a hole
straight through the wall behind it anyway. The rectangle was still being
guessed as a window, because that is all the four corners look like, and a
window is a hole.

The depth shot settles it. Nobody measures how far a doorway sticks out of a
wall, so a rectangle with a shot in the middle of it is a thing standing on
the wall — and the wall behind it stays whole. The box grows from the wall out
to exactly where that shot is and stops there.

Rectangles without a middle shot are unchanged: still guessed as a door or a
window, still yours to correct by clicking them.

## A room can have its own wall thickness

Where a wall runs like a pier or a narrow neck, one thickness for the whole
job is wrong for that room — the offset swallows the feature. Each room can
now carry its own thickness, set in the room panel, with one tap to hand it
back to the job default.

The override already survived export and `.sdxp`; what was missing was any way
to set it.

## An error says what went wrong

An unhandled failure in the geometry service reached the app as a bare
"internal server error" with the reason thrown away. On a tablet in a
stairwell that is the difference between a fixable problem and a dead end, so
the message now travels with it.

## Checked

Both cores agree across four rooms — skirting, both stair conventions, and
rectangles with their depth shots: 145 fields, zero mismatches. The box front
face lands on the dot to within a hundredth of a centimetre at 10, 35 and 60
cm, and the room's volume goes up when a fitting is added rather than down.
