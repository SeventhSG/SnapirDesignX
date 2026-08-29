# Snapir Design X 1.1.1

Fixes from the first run of the Android app on a real phone.

## The interface now fits the screen it is on

The layout was drawn for a desktop window and shipped to a phone unchanged,
which is exactly how it looked. It now adapts, without changing a single
colour, weight or rule of the design:

- **Phone, portrait.** The viewport takes the top of the screen and the
  inspector sits under it, each scrolling on its own. Before, a fixed 292 px
  inspector on a 412 px screen left a strip of viewport too narrow to read a
  room in.
- **Phone, landscape.** Back to side by side, because stacking a 412 px-tall
  screen would leave nothing to look at.
- **Tablet.** Same stacking, with the readings held to a column so a label and
  its number stay a pair instead of drifting to opposite edges.
- **Titlebar.** The name, the project and the room stay on one line; the room
  name shortens rather than pushing the title onto a third row.
- **Viewport controls.** The tools sat in one corner and the actions in the
  other, and they overlapped once there was not room for both. They are now a
  column that wraps, so nothing can land on top of anything else. This was
  keyed to the space available rather than to a device class, which is why it
  also fixes a phone held sideways at 915 px.
- **Room table.** Openings and corners drop first, then ceiling height, so the
  columns that decide what to open are never cut off.
- **Settings.** The section list moves above its own body instead of taking a
  fifth of a phone screen.
- **Touch.** Every control is sized for a thumb wherever the pointer is coarse,
  which covers a tablet and a touchscreen laptop as well as a phone.

Checked by rendering the built interface against the real backend at
412x915, 915x412, 800x1180 and 1440x900. The desktop layout is unchanged.

## Rotation

The app forced itself to follow the sensor, so it flipped at about fifteen
degrees of tilt and ignored the system rotation lock entirely. It now follows
the same rule every other app does: rotate when you have rotation unlocked,
stay put when you have not.

## Folder picking

Choosing a survey folder now opens the system Files app. The picker hands back
a `content://` reference and the geometry core opens files with the standard
library, so the choice is mapped back to a real path; anything that does not
map falls back to the previous in-app browser rather than failing.

## Outline editing

**Wipe outline** clears the ring so it can be picked from scratch, next to the
existing **Reset to survey**, which puts the surveyed one back. Sketch mode
also gets a taller viewport on a small screen, where the outline bar was taking
a third of the drawing area.

## Unchanged

The geometry. Same C++ core, same Open CASCADE 7.9.3, same numbers on both
platforms: `Daire 51 - Ebeveyn odası` still builds to 1 solid, 71 faces,
16.384 m³ on the phone and on the desktop.

Both downloads are unsigned, so each will ask once before installing.
