# Snapir Design X 1.2.1

Three export formats instead of one, on all three shells. The geometry is
untouched.

## Export formats

STEP was the only way out. Now there are three, and a picker beside the Export
button to choose between them:

| Format | Extension | Opens in |
|---|---|---|
| STEP, schema AP203 / AP214 / AP242 | `.step` | SolidWorks, Geomagic Design X, Rhino, Revit, Inventor, Fusion, CATIA |
| IGES 5.3 solids | `.igs` | SolidWorks, Geomagic Design X, Rhino, older CAD |
| BREP | `.brep` | Open CASCADE tools, and Snapir itself |

The picker remembers what was chosen last, so the decision is made once. A
second picker appears next to it when the format is STEP, for the schema.

**AP242 is the reason to update.** It is the current STEP schema and the one
SolidWorks and Design X prefer; the files Snapir wrote until now were AP214.
The old default is unchanged, so anything already exported still matches.

Whole rooms and single walls both take the format. The Design X wireframe
export gains BREP alongside its IGES, STEP and ASC.

## Everything on offer is exact

Every format here is B-rep. Planes stay planes and the surveyed corner stays
where the instrument put it.

**No mesh format is offered, on purpose.** STL, OBJ, PLY and glTF all replace
that corner with a triangle and a tolerance, which is the one thing this tool
exists not to do.

That is a claim, so it is checked rather than repeated. `check_export` builds
every room in a survey, writes it in each format, reads it back through the
same kernel, and compares the face count and the volume against the body it
came from. Across the 28-room reference job:

```
all formats exact
```

STEP and BREP round-trip at zero volume drift. IGES loses about 1e-9 m3 to its
own ASCII precision — a thousandth of a cubic millimetre, and the reason it is
listed third.

IGES is written in BRep mode (5.3 MSBO) rather than the surface mode the
wireframe export uses, so a solid arrives as a solid instead of as a heap of
loose trimmed surfaces.

## About `.sldprt`

It cannot be written, by Snapir or by anything else outside SolidWorks. The
format is closed and undocumented. Parasolid `.x_t` and ACIS `.sat` are the
same, and additionally need a paid licence.

SolidWorks imports STEP and IGES natively, so AP242 is the route in. This is
written down in the README so it does not have to be worked out again.

## PC, Android and iOS

One change, three shells. The format picker is in the React app that Electron,
the Android `WebView` and the iOS `WKWebView` all load, and the writers are in
the C++ core all three compile. Neither mobile build file needed a line: both
already linked `TKDEIGES` and `TKBRep`.

No new Open CASCADE libraries, no OCCT rebuild, and no change to the size of
the installer or the APK.

The Android and iOS builds carry the identical core and the identical
interface, and remain unverified on hardware.

## Unchanged

The geometry. Same C++ core, same Open CASCADE 7.9.3, same numbers everywhere.
A room exported with no format chosen produces the byte-for-byte file 1.2.0
produced, so the Python-to-C++ comparison tools are unaffected.

Both downloads are unsigned, so each will ask once before installing.
