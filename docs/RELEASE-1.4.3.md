# Snapir Design X 1.4.3 — A quarter turn, by hand

Two matches fix a room's heading. When those two corners are close together,
they fix it out of a couple of centimetres of difference between two readings —
and when one of them is matched to the wrong corner, they fix it out of nothing
at all. Either way the room lands attached in the right place and facing the
wrong way, and no amount of solving will say so: by its own measure the answer
it gave is the best one there is.

So the room list has **↺** and **↻** on every room. A quarter turn each way, up
to a full turn and back to none, with the angle shown next to the arrows once
it is on.

It turns **about the match**, which is the one place that must not move: the
room swings round the corners it was pinned by, so the pinning stays exactly as
good as it was — the RMS does not change — and only the heading is different.
And a room placed *through* a turned room follows it, so fixing one floor of a
stairwell carries the floors matched to it rather than tearing them off.

The turns are stored with the matches, and like the matches they are the
operator's: nothing derives them, nothing overwrites them, and **Clear all**
drops them along with everything else.

## Checked

Both cores return byte-identical answers through a full cycle of turns on
`Sofia - Villa Tocheva` — 90°, 180°, 270°, and back to none, landing on exactly
the placement it started from, with the residual unchanged at every step and
`Ara Kat`, which is placed through `Kat 1`, following each turn. 107 tests, of
which 103 run here. Parse parity across all five surveys, zero mismatches.
