# Snapir Design X 1.3.2 — Snapshot

## The depth of a wall fitting is measured now, not assumed

1.3.1 could tell a boiler from a window, but only because the operator said
so, and how far the thing stuck out of the wall came from a number in
settings. That number was the same for every boiler in every flat, which is
another way of saying it was made up.

Shoot the rectangle, then put one point in the middle of it. The distance from
that shot to the wall is the depth, and the fitting is built to it. Where
there is no middle shot the settings' depth is still used, so nothing that
worked before stops working.

This is the same rule the rest of the app follows: what the instrument
measured wins, and the app only fills in what the survey does not contain.
The middle shot also stops being an unresolved point the operator has to look
at — it is now part of the rectangle it sits in.

## Checked

Both cores agree on a fixture carrying two rectangles with their middle shots,
alongside the skirting and stair fixtures from 1.3.1: 145 fields, zero
mismatches, the depth reading 42.0 cm on each side. The parse dump now carries
each rectangle's depth, so a divergence here cannot pass unnoticed.

Windows, Android and iOS all carry it.
