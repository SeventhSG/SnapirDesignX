# Snapir Design X 1.3.0 — Snapshot

A project can now leave the machine it was surveyed on, and connecting two
rooms stopped being a guessing game played against a list of centimetres.

## A project is now a file

Every project used to live only in one install's own app data: the survey
folder, the operator's overrides, the doors linked between rooms - none of it
went anywhere. Export writes all of it into a single `.sdxp`, a project
zipped up whole, that opens on another install of Snapir - another machine,
another phone - with nothing else needed. Import unpacks it back into a real
project, survey files and all. Both live on the Projects screen and in each
project's own settings.

Built exports are deliberately left out. The kernel rebuilds a room from its
survey and overrides the same way on every install, so there is nothing to
carry that the receiving machine cannot make for itself.

## Connecting two rooms, by looking at them

The old way to link a door to the room beyond it was two dropdowns of
centimetre widths, and most doors in a flat are the same width. The doors
themselves now glow - click one, pick the room next to it, and its own doors
glow in turn. The room you picked appears where it actually sits, parked
clear of the room you are standing in until you choose its door, at which
point it snaps into the exact fit and waits for a confirm.

Getting the two rooms to actually face away from each other, rather than one
landing inside the other, turned out to need the alignment to be computed
from which way each room's interior really opens - not from an incidental
left-right ordering that depends on which way the survey happened to walk
each room's ring, and that a concave room could point the wrong way on
entirely.

## Building every room in a flat up front

"Load all", next to Connected doors, builds every room in the current flat
that has nothing left for the operator to decide, so walking through a
connected door does not sit on that room's first build.

## DXF stopped being one undifferentiated line soup

Every export used to cut a single horizontal section through the whole fused
room and write it as `LINE` entities on one layer. Opening it in AutoCAD gave
back a flat line drawing with no way to tell a wall from a fixture.

The DXF now carries the same room split into named layers: `FLOOR`, `CEILING`,
`WALL_1`, `WALL_2`, ..., and one `FIXTURE_<name>` per socket or pipe. Floor and
ceiling are their own footprint outline; every wall and fixture is cut at its
own mid-height, independently. `check_export` verifies each layer against a
fresh re-section of that element alone, not the file trusting itself.

## GLB: real solid bodies, not just a plan

DXF is still lines. If what you need is separate solid geometry - in SketchUp,
or anywhere else with no STEP or IGES importer - a plan was never going to be
enough, and DWG needs a paid Autodesk or ODA licence this project doesn't
have.

Binary glTF is the actual fix: Open CASCADE already writes it, and it carries
real triangulated solids with a proper node hierarchy, so floor, ceiling, each
wall, and each fixture come out as their own named body in one `.glb` file -
exactly the same split as DXF, but volumes instead of a line drawing.
`check_export` checks it the same way it checks the others: body count and
summed volume against those same elements, rebuilt independently and read
back through the same triangle-volume math STL already uses.

## The app checks for updates on its own

Every install used to sit at whatever version it was first put on until
someone ran the new setup by hand. On launch, the app now checks this
project's GitHub Releases in the background; if a newer build exists, it
downloads it and restarts into it on its own, silently. Nothing to click,
nothing that interrupts a session - closer to how a game client patches
itself than how most desktop tools update.

## Also in this release

- Pinch-to-zoom inside a room, which only ever answered to a mouse wheel and
  so never worked on a phone or tablet at all.
- A door's own click target is the glowing door itself now, in either camera
  mode, rather than the whole faded room beyond it standing in for it.
