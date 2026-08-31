# Desktop app

## Stack

| Layer | Choice | Why |
|---|---|---|
| Shell | Electron, packaged as a Windows `.exe` | Chromium ships inside the app, so the viewport renders identically on every machine in the team. That is the main defence against the flakiness we are trying to avoid. |
| UI | React + TypeScript | Types catch the class of bug that makes a tool feel unreliable. |
| Viewport | Three.js | Face picking by raycast, resolved back to real B-rep face ids. |
| Backend | Python, bundled as a sidecar | The kernel work stays where OCCT lives. Not a website, not a localhost tab: the frontend talks to a private local process the user never sees. |
| Kernel | OpenCASCADE via OCP | Analytic planes, exact booleans, STEP and STL out. |

It is a real desktop application. No browser, no URL, no server the user has to
start.

## Screen flow

Modelled on the Leica field platform, so it is familiar from site.

```
  splash
    v
  projects        open recent, or create a new project from a survey folder
    v
  flats           one card per flat in the survey, with its room roll-up
    v
  rooms           the rooms in that flat, each with the panorama shot in it
    v
  workspace       3D viewport, plan view, inspector
    v
  export          one body per room: STEP to work from, or STL to look at
```

### Splash
Logo, version, and what the backend is doing while it starts.

### Projects
Recent projects with room count, last opened, and how many rooms still need
review. Creating a project means pointing at a survey folder; the parser reads
every room CSV and the project is ready.

### Flats
`Daire 51 - Salon` carries its flat in its own name, so the survey groups
itself. One card per flat: how many rooms, and how many are ready, built or
still need an answer. The flat number is the thing an operator hunts for from
arm's length on site, so it is the largest text on the screen and it carries
the gold.

A survey whose rooms have no flat prefix skips this screen entirely.

### Rooms
One card per room, led by a panorama out of the room's own `_Panorama` folder
beside the CSV. Then area, ceiling height, and a status. Three states only.

| State | Meaning |
|---|---|
| Ready | Builds with no input. 21 of 28 in the reference job. |
| Needs you | One specific question, named. Outline order, or a missing ceiling height. |
| Built | Body written, with a timestamp. |

### Workspace
3D viewport as the main surface, plan view alongside it, inspector on the
right. Click a face to select it.

The inspector runs out of readings well before it runs out of column, and the
rest of the flat lives in that space: **Other rooms** opens the sibling rooms
with their status, so moving between rooms in a flat does not mean walking
back two screens. Stacked on a phone it opens as a sheet instead of a popover. Selection is a real B-rep face, so the
inspector can say `wall, 6.81 m2, vertical` and let you set a thickness for
that wall alone.

What the operator is ever asked to do:

- fix an outline where the survey order does not describe the ring
- supply a ceiling height where none was shot
- confirm, unmark or add an opening
- override thickness on a specific wall

Nothing else. Everything the data can prove, the app decides.

## Panoramas

The survey camera writes `<room name>_Panorama/` beside each room CSV. The
service lists what is there and streams a shot by index; it never decodes,
resizes or writes one. Cards load lazily and only for the flat that is open,
so a 28-room survey never has more than a handful of 2 MB equirectangular
JPEGs decoded at once.

Inside a room the panorama is a photograph you can stand in. The survey pins
where it was taken -- the instrument writes its own position into the CSV --
but nothing anywhere records which way it was facing, so the heading is
recovered from the picture, in the browser. 19 of the 34 shots in the reference
survey solve; the rest open as a plain 360 viewer that says it cannot be lined
up rather than being drawn wrong. See [PANORAMA.md](PANORAMA.md).

## Walking

Inside view is a walkthrough, not a fixed eye. It starts where the instrument
stood, since that is the one spot with a photograph to compare against. Drag to
look, `W A S D` to walk, tap the floor to go there, tap a station disc to
return to a setup. Movement is bounded by the surveyed ring, so a wall is a
wall.

## Phones and tablets

The page owns the whole window on all three shells, including under the
notch, so it is the page that has to clear the hardware. `index.html` carries
`viewport-fit=cover` -- without it WKWebView reports every
`env(safe-area-inset-*)` as zero -- and the four insets are read once into
`--sa-t/r/b/l`. Every piece of chrome that touches an edge adds them: the
title bar, the page padding, the viewport's own overlay, the edit rail, the
sketch bar, the inspector and the toast. On Windows, Android and in a desktop
browser all four are `0px`, so the layout there is exactly what it was.

`tools/shoot_layouts.js --insets` pins them to what an iPhone 15 Pro reports
and shoots the same screens, because Chromium reports zero no matter the
viewport and the one layout that cannot be checked here is the only one that
ever goes wrong.

## Settings

One thickness for the job, set per project. Per-wall overrides by clicking the
wall. Defaults live in `snapir/settings.py`.

## Packaging

Signed Windows installer, version in the title bar, settings per machine.
Built for the whole team, not just one workstation.

## Export formats

The format picker sits beside the Export button, and a STEP schema picker
appears next to it when STEP is chosen. Both remember the last choice, so the
decision is made once. The same picker is the one the Android and iOS apps
show: there is one React app behind all three shells.

| Format | Extension | Notes |
|---|---|---|
| STEP | `.step` | The body to work from. Schema AP203, AP214 or AP242; AP242 is the current one and what SolidWorks and Design X prefer. |
| STL | `.stl` | Binary, meshed at 0.1 mm. For viewing only - it is triangles, and nothing should be measured off it. |

Both are written in millimetres. `.sldprt` is not writable by anything outside
SolidWorks - see the README.

## Escape hatch

Every room has an **Export for Geomagic Design X** action: exact wireframe as
IGES or STEP curves, plus points as ASC. If Snapir ever gets something wrong,
nobody is stuck.
