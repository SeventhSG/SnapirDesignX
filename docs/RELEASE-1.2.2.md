# Snapir Design X 1.2.2

The survey is read flat by flat now, the rooms show the panorama that was shot
in them, and the layout gets out of the way of the dynamic island. The geometry
is untouched.

## Flats, then rooms

A 28-room job used to arrive as one 28-row table with a grey heading every few
rows. `Daire 51 - Salon` already carries its flat in its own name, so the
survey groups itself and nothing has to be typed:

```
  projects  ->  flats  ->  rooms in that flat  ->  workspace
```

**Flats.** One card per flat, with how many rooms it has and how many are
ready, built, or still waiting on an answer. The flat number is what an
operator hunts for at arm's length on site, so it is the largest text on the
screen and it carries the gold — the old heading was 11px grey uppercase, set
in the colour the interface uses for things it does not want you to read.

**Rooms.** One card per room, led by the panorama the survey camera shot in
that room. Then the room name, the status, the area, the ceiling height, and —
where a room still needs something — the one question it is waiting on, in
full, instead of a truncated table cell.

A survey whose rooms have no flat prefix skips the flats screen entirely and
goes straight to the room cards.

## The panoramas were already on disk

The camera writes `<room name>_Panorama/` beside each room CSV and Snapir had
never looked at it. It does now: the service lists what is in the folder and
streams a shot by index. It does not decode, resize, re-encode or write one —
there is no image library in the core and none is wanted. The survey folder
stays read-only, exactly as it was.

Cards load lazily and only for the flat that is open, so a phone never holds
more than a handful of 2 MB equirectangular JPEGs decoded at once rather than
all 28.

Both engines gained the same field and the same route, and were diffed against
each other room by room: identical panorama counts on all 28 rooms, and
byte-identical images out of both — including the Turkish-named rooms and
`Daire 55 - koridor`, which the camera capitalised differently from the total
station.

## Other rooms, without walking back

The inspector runs out of readings well before it runs out of column. The rest
of the flat lives in that space now: **Other rooms** opens the sibling rooms
with their status, and picking one goes straight there. Stacked under the
viewport on a phone it opens as a sheet instead of a popover, so it is never
clipped by the panel it came from.

## The dynamic island, the notch, the home indicator

On iPhone and iPad the page owns the whole window, under the island included —
that is deliberate, it is how the viewport gets the full screen. What was
missing is that nothing stepped back out of the way, so the title bar and its
buttons sat underneath the island and the export row sat under the home
indicator.

Two things were wrong and both are fixed:

- `index.html` did not carry `viewport-fit=cover`. Without it WKWebView reports
  every `env(safe-area-inset-*)` as zero, so even correct CSS would have had
  nothing to work with.
- No rule read the insets. All four are now read once into `--sa-t/r/b/l`, and
  every piece of chrome that touches an edge adds them: title bar, page
  padding, the viewport's own overlay, the edit rail, the sketch bar, the
  settings body, the inspector, the toast. Landscape is covered too, where the
  island moves to the leading edge and takes 59pt off the side.

**On Windows, Android and in a desktop browser all four insets are `0px`, so
the layout there is precisely what it was.**

Two smaller layout fixes fell out of checking it: the room grid was collapsing
to a single card per row on an iPad, wasting half the screen — it fits three
now — and the mobile breakpoints were overriding the title bar's padding, which
is what hid the top inset in the first place.

## Verified, and not

`tools/shoot_layouts.js` drives the built interface through the real navigation
at 412x915, 915x412, 800x1180 and 1440x900. It gained a `--insets` pass that
pins the safe-area variables to what an iPhone 15 Pro reports, because Chromium
reports zero no matter the viewport — without it, the one layout that cannot be
checked on this machine is the only one that ever goes wrong.

That is an emulation, not a device. The iOS workflow builds the app and shoots
an iPhone and an iPad simulator on every release; those screenshots are the
real proof, and they are attached to the run rather than to this note. There is
still no Android or iOS hardware here.

## Unchanged

The geometry. Same C++ core, same Open CASCADE 7.9.3, same numbers. Nothing in
this release touches parsing, plane fitting, solids or export, and the
Python-to-C++ comparison tools are unaffected.

Exports are still STEP and STL, and the Geomagic Design X escape hatch is still
exact wireframe as IGES or STEP curves plus points as ASC.

Both downloads are unsigned, so each will ask once before installing.
