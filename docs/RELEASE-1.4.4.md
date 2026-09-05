# Snapir Design X 1.4.4 — The merge is a room

Merging wrote a file. A file is not something you can work in, so the merged
whole now appears in the project as a room of its own, called **Merged**,
listed after the rooms it is made of.

It opens like any other room. The body is the whole survey in one frame — all
four floors of a stairwell, fused where the kernel will have it. The sketch is
every point and every line of every room it is made of, carried into that same
frame, each corner still carrying the name of the survey it came from and the
shot it was: `Kat 1/P_007`. Roles are kept as they were — each room was
classified on its own, correctly, and re-reading four floors as if they were
one would only undo that. It builds, it exports to STEP, GLB, STL and DXF, and
it goes to Design X, all through the paths every other room uses.

**It is derived, never stored.** Correct a wall in one of the rooms it is made
of, change that room's thickness, take a wall out, and the merged room has the
correction the next time you open it. Nothing has to be re-merged and there is
no second copy to keep in step.

What it does not have is a ring. A merged stairwell is not one outline and
never will be — it is four rooms that are now in one frame — so the outline
editor is not offered on it, and its body comes from the rooms it is made of
rather than from a ring drawn round the lot.

## Checked

Both cores return the same merged room for `Sofia - Villa Tocheva`: listed with
the other four, 245 points and 217 lines, opening, building to 5 solids and 492
faces at 43.547 m³, and exporting to both STEP and IGES. Thickening one source
room's walls moves the merged room to 52.376 m³ on both, without touching the
merge. 109 tests, of which 105 run here. Parse parity across all five surveys,
zero mismatches.
