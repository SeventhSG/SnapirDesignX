# Snapir Design X 1.3.9 — Snapshot

Everything the stair work added since 1.3.2 was tested against flights that
had been invented for the purpose. Against a real stairwell — Sofia, Villa
Tocheva — none of it fired. Three reasons, all now fixed.

## A tread is tagged as floor, because a tread is a floor

The detector only ever looked at shots the classifier could not place. Every
tread in the real survey is on the `Zemin` layer, which is correct — a tread
*is* a floor surface — so the whole flight arrived already claimed as outline
corners and was never offered to the stair detector at all.

A run of floor shots that climbs at a consistent riser is a staircase whatever
layer it was written on. The flights in that survey are now found: eleven steps
in the top-floor corridor, seventeen rising a full storey on the ground floor,
two more on the intermediate landing.

## A riser is not a skirting board

Two shots a centimetre apart in plan and sixteen centimetres apart in height —
that is a stair riser, and it is also exactly what a skirting pair looks like.
Skirting was being detected first, so every step of the corridor flight came
back as a board: nine of them, none real.

Stairs are claimed first now. The flight is recognised as a whole before
anything reads it two points at a time.

## The floor is where the floor shots are

Standing in a top-floor corridor, the lowest thing the instrument sees is the
landing a storey below. Taking the lowest reading as the floor dragged that
landing's corners into the ring and fitted the floor plane through two levels
at once.

The ring is built from the level most of the floor shots are on. And a corner
shot twice is one corner: where a flight arrives at a wall, the last tread and
the wall corner are the same place read a few millimetres apart, and the stub
between them doubled the ring back and read as a self-intersection.

## Checked

Both cores agree on the Sofia survey — 390 fields, zero mismatches — and on the
28-room reference job at 1725 fields, zero mismatches.

Three of the four Sofia rooms now build where one did before. The reference job
improved too, from three rooms with errors to two: `Daire 51 - Salon` was
failing on a corner shot twice and now closes cleanly at 23.03 m².

`Ara Kat` still does not produce a room, and should not. Once its two flights
are claimed, five floor shots remain, spread across three different levels — an
intermediate landing between flights, with no room outline in the survey to
build. The app says so rather than emitting a shape nobody measured.
