# Panoramas

The survey camera writes `<room name>_Panorama/` beside each room CSV. Until
now Snapir only used the first shot, as a thumbnail on the room card. Inside
the room it is now a photograph you can stand in, pointing the same way you
are.

## What the survey gives us, and what it does not

An iCS50 panorama is a 4000x2000 JPEG: a full equirectangular sphere, exactly
2:1. Placing it in a room needs six numbers. The survey hands over five of
them for nothing:

| | Where it comes from |
|---|---|
| position | `LEİCA_İCON_TOOL` in the room CSV, to the centimetre |
| height | the same row: about 127 cm on all 28 rooms |
| roll, pitch | zero. the instrument is levelled |
| **heading** | **nowhere** |

The sixth is not written down anywhere. The JPEG is bare JFIF with no EXIF, no
XMP and no GPano block. The FUKOKU report carries the device, its serial, the
firmware and the job date, and no orientation. The export folder holds 56 CSVs
and 56 DXFs and no sidecar of any kind.

It cannot be assumed either, because the frame is not the instrument's. The
exporter rotates each room so the operator's first surveyed wall lands on the
X axis: in `Daire 53 - Salon`, `P_001 -> P_002` is exactly `0.0000°`, while the
same two corners measured at ceiling level read `-0.0262°`. The origin is an
arbitrary choice made per room, so the heading is a different unknown in every
one of them.

So it is recovered from the picture. `app/src/panorama.ts` does it, in the
browser: Chromium is already in all three shells, and the backend keeps
streaming the bytes untouched with no image library on either side.

## Recovering the heading

Everything in the room predicts where something should appear in the picture,
and every candidate heading shifts the whole prediction by the same amount. So
the search is a circular correlation over one scalar. Two independent kinds of
evidence are scored, standardised separately, and added:

**Corners.** A wall corner seen from the station is a vertical line, at a
column fixed by its azimuth. Door and window jambs count too, and are usually
the strongest verticals in a room. Each is weighted by the vertical angle it
subtends, so a corner two metres away outvotes the same corner across a salon.

**Rings.** Where the walls meet the floor and the ceiling is a long curve
running the whole way round the picture, and its shape is fixed by the room.
This is far more evidence than the corners give, and it is what separates the
true heading from a merely plausible one. An early version scored only the
corners and reported high confidence on all 34 shots while being wrong on
several of them.

Handedness is **not** searched. Azimuth runs the opposite way to the image, the
same way on all 34 panoramas, because it is a property of the camera and not of
any room. Searching it doubled the space and manufactured false peaks; fixing
it removed them. A camera that did it the other way would fail to solve any
room at all, which is the safe way to be wrong.

## Refusing

The confidence is the height of the peak over every rival heading, in standard
deviations, ignoring the peak's own shoulder. A room whose corners sit evenly
around the station scores the same at several headings, and there is no answer
in it to find.

Below `MIN_CONFIDENCE` the panorama still opens. It just opens as a plain 360
viewer that says it cannot be lined up, rather than being drawn wrong. There is
no manual alignment step, on purpose: the list of things an operator is asked
to do is short and is meant to stay that way.

On the 28-room reference survey, **19 of 34 shots solve**. The refusals are
almost all bathrooms -- tiled, small and near enough symmetric that no heading
is better than another. Confidence runs 3.85 to 13.03.

```
Daire 53 - Salon     13.03   solved  13.0°
Daire 55 - koridor   12.91   solved 185.6°
Daire 51 - Koridor   11.52   solved  69.3°
...
Daire 56 - Banyo      3.85   refused
```

The four highest were checked by projecting the floor and ceiling rings back
onto the photograph: both curves trace the real wall junctions, including door
thresholds and wall steps.

## Standing in the room

Inside view starts where the instrument stood, because that is the one spot in
the room with a photograph to compare against. From there:

- **drag** to look
- **W A S D** to walk
- **tap the floor** to walk there, which is how a phone gets around a room
  with no keyboard on it
- **tap a station disc** to return to a setup

Walking is bounded by the surveyed ring itself, so a wall is a wall. A blocked
move is retried one axis at a time, which turns walking into a wall into
sliding along it.

A strip of the panorama sits above the view, cropped to whatever the eye is
pointing at. Opening it swaps the body for the photograph, held at the exact
station position and height so the two agree. Closing it puts the model back,
still pointing the same way.

## Several setups in one room

A room can be surveyed from more than one setup, and the instrument is written
out again every time it is re-levelled without being moved. `Daire 51 - Salon`
has four station rows for three real positions. Distinct positions only are
kept, merged within 5 cm, which makes stations match panoramas exactly in 24 of
the 28 rooms.

The other four disagree because an operator can shoot two panoramas from one
setup, or move without shooting at all. So panoramas are not paired with
stations by order. Every combination is scored and the best one wins, which
costs nothing once the picture has been read and does not assume the operator
was tidy.
