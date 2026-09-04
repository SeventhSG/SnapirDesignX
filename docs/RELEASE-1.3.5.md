# Snapir Design X 1.3.5 — Snapshot

## A rectangle can be measured on both sides at once

Plenty of things on a wall are let into it and stand out of it at the same
time — a boiler in a niche, a panel sunk into a reveal. One shot in the middle
of the rectangle could only ever describe half of that, and 1.3.4 kept the
nearest one and discarded the rest.

Put a shot on each side and both are kept. The wall is hollowed back to the
one behind the face, and the body is built out to the one in front of it, on
the same rectangle. Either side on its own still works exactly as before, and
a rectangle with no shots at all still takes its depth from settings.

Where a side carries more than one shot, the furthest wins: a nearer one is
somewhere in the middle of the same object, not its face.

## Checked

Six rooms across both cores with zero mismatches — 226 parsed fields and 72
built ones — on a fixture carrying all three cases side by side: one rectangle
standing 38 cm out of the wall, one set 9 cm into it, and one measured at 26 cm
out and 11 cm in at once.

The two-sided rectangle builds as a single solid, carries more material than
the bare wall and less than the same box on an untouched one, and both depths
survive a rebuild.
