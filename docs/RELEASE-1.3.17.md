# Snapir Design X 1.3.17 — Snapshot

## A socket looks like a socket in Design X

A socket and a water pipe both arrive from the instrument as a single reading,
and as a single reading they both left as the same dot. That tells you where a
service is and nothing whatever about what it is — which is the one thing the
drawing was there to say.

They now go over as what they are, seated on the wall face the way the body
seats them:

- **Kontak** — a square the size of a faceplate, `socket_width` by
  `socket_height` from the job settings, lying in the wall plane at the shot's
  own height.
- **Su tesisat** — a true circular arc of `pipe_diameter`, not a polygon
  pretending to be one, so Design X gives back a diameter you can dimension
  off.

A service with a shape of its own no longer gets a cross through it as well:
two marks on one reading is one more than the drawing needs. Its exact point
is still written, so nothing loses precision.

None of this touches the body. It is how the room is drawn on the way out, and
only on the way out.

## Checked

Both cores write the same file, entity for entity: `Daire 56 - Salon` goes out
as 5 circular arcs, 183 lines, 48 points and 26 composite curves from either
one. Parse parity across all five surveys: 248, 215, 395, 409 and 1725 fields,
zero mismatches. 95 tests, of which 91 run here.
