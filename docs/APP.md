# Desktop app

## Stack

| Layer | Choice | Why |
|---|---|---|
| Shell | Electron, packaged as a Windows `.exe` | Chromium ships inside the app, so the viewport renders identically on every machine in the team. That is the main defence against the flakiness we are trying to avoid. |
| UI | React + TypeScript | Types catch the class of bug that makes a tool feel unreliable. |
| Viewport | Three.js | Face picking by raycast, resolved back to real B-rep face ids. |
| Backend | Python, bundled as a sidecar | The kernel work stays where OCCT lives. Not a website, not a localhost tab: the frontend talks to a private local process the user never sees. |
| Kernel | OpenCASCADE via OCP | Analytic planes, exact booleans, STEP. |

It is a real desktop application. No browser, no URL, no server the user has to
start.

## Screen flow

Modelled on the Leica field platform, so it is familiar from site.

```
  splash
    v
  projects        open recent, or create a new project from a survey folder
    v
  rooms           every room in the project, with its status
    v
  workspace       3D viewport, plan view, inspector
    v
  export          STEP per room
```

### Splash
Logo, version, and what the backend is doing while it starts.

### Projects
Recent projects with room count, last opened, and how many rooms still need
review. Creating a project means pointing at a survey folder; the parser reads
every room CSV and the project is ready.

### Rooms
One card per room: area, ceiling height, opening count, and a status. Three
states only.

| State | Meaning |
|---|---|
| Ready | Builds with no input. 21 of 28 in the reference job. |
| Needs you | One specific question, named. Outline order, or a missing ceiling height. |
| Built | STEP written, with a timestamp. |

### Workspace
3D viewport as the main surface, plan view alongside it, inspector on the
right. Click a face to select it. Selection is a real B-rep face, so the
inspector can say `wall, 6.81 m2, vertical` and let you set a thickness for
that wall alone.

What the operator is ever asked to do:

- fix an outline where the survey order does not describe the ring
- supply a ceiling height where none was shot
- confirm, unmark or add an opening
- override thickness on a specific wall

Nothing else. Everything the data can prove, the app decides.

## Settings

One thickness for the job, set per project. Per-wall overrides by clicking the
wall. Defaults live in `snapir/settings.py`.

## Packaging

Signed Windows installer, version in the title bar, settings per machine.
Built for the whole team, not just one workstation.

## Escape hatch

Every room has an **Export for Geomagic Design X** action: exact wireframe as
IGES or STEP curves, plus points as ASC. If Snapir ever gets something wrong,
nobody is stuck.
