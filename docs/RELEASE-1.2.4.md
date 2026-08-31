# Snapir Design X 1.2.4

Three fixes to what 1.2.3 shipped. No geometry changes.

## The panorama asks instead of announcing

1.2.3 put a strip of the photograph over the view the moment you stepped
inside, and a room whose heading could not be recovered sat there permanently
saying so. That is a warning about something nobody had asked for yet.

There is a **Panorama** button in the toolbar now, next to Inside, and it only
appears once you are inside a room that has a shot. Nothing covers the view
until you press it.

A shot whose heading could not be recovered carries that on the button itself,
in red. Open it and the reason appears once, for five seconds, and then gets
out of the way and leaves a plain 360 view. The walking hint is hidden while
the photograph is up, because you are held at the station there and cannot
walk anyway.

## The station disc was buried in the floor

The disc marking where the instrument stood only showed through **See
through**, which made it look like a bug in the transparency rather than what
it was: it was underground.

`floorY` was the underside of the body, and the floor slab hangs below the
surveyed floor by its own thickness, so the disc was inside the concrete and
only the depth test made it look otherwise. It stands on the surveyed floor
datum now and is visible in the normal view.

The same datum sets eye height, so standing inside a room was also lower than
1.6 m by the thickness of the slab. That is right now too.
