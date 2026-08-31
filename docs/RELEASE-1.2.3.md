# Snapir Design X 1.2.3

The panorama the survey camera shot in each room is now something you can stand
in, pointing the same way you are, and the inside view is a walkthrough rather
than a fixed eye. The geometry is untouched.

## Standing in the photograph

Inside a room, a strip of the panorama sits above the view, cropped to whatever
you are looking at. Click it and the photograph takes the viewport at the same
direction; click back and the model returns, still pointing the same way.

Placing a panorama in a room takes six numbers. The survey hands over five of
them for nothing, because the instrument writes its own position into the room
CSV: where it stood, how high — about 127 cm on every room in the reference
job — and level in both tilts.

The sixth, which way it was facing, is written down nowhere:

- the JPEG is bare JFIF, with no EXIF, no XMP and no GPano block
- the FUKOKU report carries the device, the serial, the firmware and the job
  date, and no orientation
- the export folder holds 56 CSVs and 56 DXFs and no sidecar of any kind

It cannot be assumed either, because the frame is not the instrument's. The
exporter rotates each room so the operator's first surveyed wall lands on the X
axis — in `Daire 53 - Salon`, `P_001 -> P_002` is exactly `0.0000°`, while the
same two corners measured at ceiling level read `-0.0262°`. The origin is an
arbitrary choice made per room, so the heading is a different unknown in each.

So it is recovered from the picture itself, in the browser, where Chromium
already is. The backend still streams the JPEG untouched and there is still no
image library on either side of it.

## What it is matching

Two independent things, scored together, because either one alone is not
enough:

**Corners.** A wall corner seen from the station is a vertical line, at a
column fixed by its azimuth. Door and window jambs count too, and are usually
the strongest verticals in a room.

**Rings.** Where the walls meet the floor and the ceiling is a long curve
running the whole way round the picture, and its shape is fixed by the room.
This is far more evidence than a handful of corners, and it is what separates
the true heading from a merely plausible one.

**19 of the 34 shots in the reference survey solve**, at confidences from 3.85
to 13.03. The rest are almost all bathrooms: tiled, small, and near enough
symmetric that no heading is better than another. Those open as a plain 360
viewer that says it cannot be lined up, rather than being drawn wrong. There is
no manual alignment step — the list of things an operator is asked to do is
short and is meant to stay that way.

## Walking

The inside view starts where the instrument stood, since that is the one spot
in the room with a photograph to compare against.

- **drag** to look
- **W A S D** to walk
- **tap the floor** to go there, which is how a phone gets around a room with
  no keyboard on it
- **tap a station disc** to return to a setup

Movement is bounded by the surveyed ring itself, so a wall is a wall. A blocked
move is retried one axis at a time, which turns walking into a wall into
sliding along it.

## Every setup, not just the last one

The parser was keeping one station per room. Rooms surveyed from several setups
have more — `Daire 51 - Salon` has four rows for three real positions, because
the instrument is written out again every time it is re-levelled without being
moved. All of them are kept now, merged within 5 cm, which makes stations match
panoramas exactly in 24 of the 28 rooms.

The other four disagree, because an operator can shoot two panoramas from one
setup or move without shooting at all. So panoramas are not paired with
stations by order: every combination is scored and the best wins, which costs
nothing once the picture has been read.

Python and C++ still agree exactly across the 28-room reference survey — 1670
fields, zero mismatches.

## Two things that were wrong

**The room name was unreadable in dark mode.** A room card is a button, and
nothing overrode the colour a browser gives one, so the name rendered black on
a `#1C1C1F` panel — a contrast ratio of 1.24:1. It is 14.77:1 now. The flat
cards had the same latent bug and only read correctly by accident.

**Ready and Needs you were whispering.** Built was a solid gold pill while the
other two were tinted text on a wash two percent off the panel behind it. All
three are solid now and read as one family at arm's length. The same green and
red carry through to the point colours in the 3D view and the plan view.

## Downloads

| | |
|---|---|
| `SnapirDesignX-1.2.3-setup.exe` | Windows installer |
| `SnapirDesignX-1.2.3.apk` | Android, arm64-v8a |
| `SnapirDesignX-1.2.3.ipa` | iOS, **unsigned** |

The iOS build is unsigned, as it has been since 1.2.0: there is no Apple
Developer account. Install it with Sideloadly or AltStore, which re-sign it
with your own Apple ID. On a free Apple ID that signature lasts seven days and
then wants redoing; a paid account makes it a year.
