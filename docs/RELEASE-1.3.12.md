# Snapir Design X 1.3.12 — Snapshot

Every room of every job on this machine builds: seventeen rooms across four
surveys, through the shipped service, each one a single valid body except the
stairwell rooms whose flights lie beyond their own walls.

## A room with a niche narrower than its own walls

`Daire 56 - Salon` refused to build with *"wall offset split the outline;
thickness is too large"* while the reference implementation built it fine. The
room has an alcove 37 cm wide, and the walls are 20 cm. Offsetting outward,
the alcove's two sides each move 20 cm toward the other and cross, so the
mitred ring folds back on itself.

That fold is not an error. It is the alcove filling with wall, which is what
the building does. The C++ core kept the fold and gave up; the Python one used
a proper buffer, which dissolves it. The fold is now dissolved on both sides,
by cutting the ring at the crossing — 12 corners become 10, and the two agree
on 27.88 m² to the centimetre.

## A doorway read as a solid object

A shot two metres up, at the very top of a doorway, was claimed as that
doorway's depth measurement. The door became an "object" 84 cm wide, 200 cm
tall and **131 cm deep**, standing in the middle of the corridor.

The convention is a point *in the middle* of the rectangle, and that was never
checked — only that the shot fell somewhere inside its span. It now has to be
within the middle half in both directions. The stray shot was 95% of the way
to the top; the two genuine ones in that room, at 16% and 37% off centre, are
untouched and still measure 11.5 cm and 3.5 cm.

## Fixed

- The command-line tools crash outright on any survey folder whose name is not
  pure ASCII — `Dışa aktarımlar`, `çay`, `özel` all abort with a stack fault.
  Windows hands `argv` in the ANSI codepage, the path fails to resolve, and the
  throw is never caught. The service takes its paths as UTF-8 over HTTP and is
  unaffected, which is why projects open at all.

## Checked

Both cores agree across all five jobs: 248, 215, 394, 408 and 1725 fields,
zero mismatches. 66 tests.
