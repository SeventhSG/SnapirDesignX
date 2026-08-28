# Snapir Design X

Turns Leica iCON room surveys into solid bodies. No mesh, no SketchUp, no STL.

Interior room volumes only. Wall thickness comes from app settings, not from
the survey.

---

## 1. Input format

Leica iCON trades export (iCS50 and compatible). Per room, the exporter writes
four files. **Only the plain `.csv` is used.**

| File | Use |
|---|---|
| `<Room>.csv` | **authoritative.** every measured point, with layer and Z |
| `<Room>_FUKOKU.csv` | field report, instrument metadata, partial connectivity |
| `<Room>_2D.dxf` | ignored |
| `<Room>_3D.dxf` | ignored |
| `<Room>_Panorama/*.jpg` | reference imagery, not geometry |

### Why the DXF is discarded

The DXF holds only the segments the operator happened to draw on site. In the
reference dataset, `Daire 53 - Koridor` has seven surveyed corners and three
drawn segments. The 2D variant additionally repeats the whole drawing across
three sheet frames (`Genel bakış`, `Projelendirilmemiş 3D`, `Yatay Düzlem 1`)
and flattens Z to zero. Anyone modelling from the DXF is rebuilding by hand
what the CSV already states exactly.

### CSV shape

```
Kimlik;X (cm);Y (cm);Z (cm);Katman
LEİCA_İCON_TOOL;166.86;-459.32;127.29
P_001;0.00;0.00;0.00;Zemin
```

Centimetres. One local origin per room, normally at `P_001`. Point names carry
the survey order, which is load-bearing: it defines the outline ring.

### Layers

| Layer | Meaning |
|---|---|
| `Zemin` | floor outline corner |
| `Kontak` | socket or switch |
| `Su tesisat` | plumbing |
| `Kontrol Noktaları` | ArUco reference target (`VTARGET_*`) |
| `Katman 0` / blank | untagged. classified geometrically |

---

## 2. Two field methods, one algorithm

The reference dataset contains both, sometimes in the same building.

**Walk the floor, then the ceiling.** All outline corners shot first at slab
level, then the same corners again at ceiling level. Outline usually tagged
`Zemin`.

**Corner verticals.** Each corner shot bottom and top as a pair before moving
on. Everything left on `Katman 0`.

Both reduce to the same operation:

1. Find the floor and ceiling **datum planes** by clustering Z into bands.
   The datum is not zero. One surveyor left the origin at instrument height,
   putting the entire floor at `Z = -126.66`.
2. Cluster the shots by **plan position**.
3. Read each cluster's vertical extent:
   - reaches floor **and** ceiling → room corner
   - sits on the floor only → outline corner
   - sits at the ceiling only → height reading
   - spans partially, stopping short of the ceiling → **door or window jamb**
   - anything else → unresolved, handed to the operator

Where the operator tagged `Zemin`, those tags win. Inference is the fallback,
never an override.

### Openings

Jambs pair up in survey order. Sill at or near the floor datum means a door,
otherwise a window. Verified against the reference data: doors come back as
`0.13 → 208`, windows as `14.82 → 244`.

---

## 3. Validation

Every room is checked before it can be built.

| Code | Severity | Meaning |
|---|---|---|
| `no-outline` | error | fewer than three floor points |
| `self-intersecting` | error | outline ring crosses itself |
| `tiny-area` | warning | encloses under 0.5 m² |
| `no-ceiling` | warning | no height shots, operator must supply one |
| `unclassified` | info | points left for the operator to assign |

Errors block the build. Warnings and notes do not.

### Current results on the reference dataset

28 rooms, 22 build without intervention. The six exceptions are real
ambiguities in the survey, not parser failures:

- four `Daire 51` rooms surveyed as corner verticals with no layer tags
- `Daire 52 - Oda`, `Daire 56 - Oda`: a section re-shot and appended after the
  ring was already closed, so survey order no longer describes the ring

Both categories are a few seconds of work in the plan view. Neither can be
resolved correctly without a human.

---

## 4. The body

Walls, floor and ceiling, extruded outward from the room. The cavity is empty.

**The surveyed surface is the inner face and is never moved.** Every offset
grows outward, so the measurement stays exactly where the instrument put it.

| Part | Source |
|---|---|
| inner ring | surveyed outline, untouched |
| outer ring | inner ring offset outward by wall thickness, mitred corners |
| floor plane | best-fit plane through the floor corners |
| ceiling plane | best-fit plane through the ceiling shots |
| slabs | floor and ceiling planes pushed out by their own thickness |

Rounded corner joins are rejected. A mitre keeps a corner a corner.

### Ceiling planes

Ceilings are fitted, not averaged. `Daire 53 - Salon` reads 269.77 to 273.99
across its corners; the fit returns a plane tilted 0.301 degrees with an RMS
residual of 0.21 cm. That is the building, kept exactly, and still a true
planar face for the kernel. A fit tilted more than three degrees means the
shots caught a beam or a bulkhead, so it is levelled and flagged instead.

### Openings

Cut through the wall, confirmed per room. Detection is automatic and the
operator can mark, unmark or add openings before the cut runs.

### Verification

Kernel volume is checked against the analytic prism volume on every build.
`Daire 53 - Salon`: analytic 22.632734 m3, kernel 22.632734 m3, zero
difference. Body reports one solid, one shell, fifty planar faces, and passes
`BRepCheck_Analyzer`.

## 5. Output

STEP AP214, millimetres, **one file per room**. B-rep throughout: planar faces
are planes, corners are exact intersections, and the body is watertight
because the kernel will not accept otherwise.

No mesh format is produced or passed through at any stage. The viewport
tessellates for pixels only; export always reads the B-rep.

### Escape hatch: export for Geomagic Design X

Any room can be sent to Design X instead, as exact wireframe rather than
points: outline ring, ceiling ring and opening rectangles as IGES or STEP
curves. Points are also offered as ASC for the cases where a cloud is wanted.
Nobody is ever trapped inside this app.

---

## 6. Module layout

```
snapir/
  model.py      Point, Jamb, Opening, Room, Project, Issue
  parser.py     Leica iCON CSV reader and classifier
  geometry.py   plane geometry, ring validation. no CAD kernel
  planes.py     least-squares plane fitting
  settings.py   job settings: thicknesses, tolerances, output
  solid.py      OCCT: loft, offset, cut openings, write STEP
  server.py     local API for the desktop frontend
tools/
  build.py      batch build a survey folder to STEP
  scan.py       batch report over a survey folder
```

`geometry.py` deliberately has no kernel dependency so ring logic stays
testable without OCCT installed.
