# Snapir Design X 1.2.1

A second way out, and the STEP schema picker that should have been there all
along. The geometry is untouched.

## Export formats

STEP was the only way a body could leave. Now there are two, chosen from a
picker beside the Export button:

| Format | Extension | What it is for |
|---|---|---|
| **STEP**, schema AP203 / AP214 / AP242 | `.step` | The body to work from. Exact B-rep. Opens in SolidWorks, Geomagic Design X, Rhino, Revit, Inventor, Fusion, CATIA. |
| **STL**, binary | `.stl` | Looking at the room in something that will not open a STEP file. |

The picker remembers what was chosen last, so the decision is made once. Whole
rooms and single walls both take a format.

**AP242 is the other reason to update.** It is the current STEP schema and the
one SolidWorks and Design X prefer; every file Snapir wrote until now was
AP214, and the schema could not be changed from the app at all.

More exactly than that: the schema was never really being set. Open CASCADE
takes it by the name of its own enum, and quietly falls back to the default
when handed anything else — so the literal `"AP214"` in the settings had been
doing nothing since the first release. It happened to land on the same schema,
so nothing looked wrong. It is now set by value, and AP203 and AP242 actually
apply.

## What each format costs, measured

`check_export` builds every room, writes it in both formats and reads it back
through the same kernel. The two are not held to the same standard, because
they are not for the same thing. Across the 28-room reference job:

```
STEP exact everywhere, worst STL error 0.000013%
```

STEP returns with the same face count and zero volume drift. Any drift there
would be a bug.

The STL is meshed at 0.1 mm. Because these rooms are almost entirely flat, the
triangles land nearly on the real surfaces — the worst room is out by about one
part in eight million by volume. That is far better than an STL usually is, and
it is still triangles: open it, turn it around, do not measure from it.

## About `.sldprt`

It cannot be written, by Snapir or by anything else outside SolidWorks. The
format is closed and undocumented. Parasolid `.x_t` and ACIS `.sat` are the
same, and additionally need a paid licence.

SolidWorks imports STEP natively, so AP242 is the route in. This is written
down in the README so it does not have to be worked out again.

## PC, Android and iOS

One change, three shells. The picker is in the React app that Electron, the
Android `WebView` and the iOS `WKWebView` all load, and the writer is in the
C++ core all three compile. Each build gained one Open CASCADE toolkit,
`TKDESTL`, and nothing else.

The Android and iOS builds carry the identical core and the identical
interface, and remain unverified on hardware.

## Unchanged

The geometry. Same C++ core, same Open CASCADE 7.9.3, same numbers everywhere.
A room exported with no format chosen produces the byte-for-byte file 1.2.0
produced, so the Python-to-C++ comparison tools are unaffected.

The Geomagic Design X escape hatch is also as it was: exact wireframe as IGES
or STEP curves, plus points as ASC.

Both downloads are unsigned, so each will ask once before installing.
