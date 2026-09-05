# Snapir Design X 1.4.0

## The controls stopped landing on each other

Two bars were pinned to the bottom corners of the viewport — tools on the left,
actions on the right — with nothing stopping them meeting in the middle. As
they grew they did: at 1324 px the door group was sitting on top of **Back**.

They are one row now. The two groups share the width, push apart, and wrap onto
a second line rather than onto each other, at any window size. The ring
controls and the room-link bar joined the same column: both assumed the tool
bar was exactly one line high, which stopped being true the moment it wrapped.

## A project card holds its own folder name

A grid item will not shrink below its own min-content, and a folder path set
never to wrap has a min-content the width of the whole path. So the card grew
to fit `C:\Users\...\Sofia - Villa Tocheva` and sat on top of the card beside
it. The cards keep their track now and the path clips with an ellipsis, which
is what it was always dressed to do.

Both checked by rendering the built interface at 1324 × 860 — the window in the
report — as well as 1440, 1000, tablet and phone.

---

## What 1.4 is, since 1.3.12

**Openings.** A window that turns the corner of a room is cut all the way round
it, pier and all, whether it was shot as two jambs or as three with a mullion
on the corner. A doorway is cut from the floor plane and nowhere else: it was
leaving a threshold slab under the door where the jamb read high, and notching
the floor slab where it read low — fifty doorways across five surveys did the
second.

**Depth shots.** Both shots of a pair attach, not just the one nearest the
middle, so a boiler marked front and back is built between the two of them
instead of coming back as a plate with a void behind it. What keeps a stray out
is that the real ones are taken straight after the rectangle, and that nothing
hung on a wall is 131 cm deep.

**Design X.** The room goes out with everything it knows — measured depths as
boxes, stairs, skirting, every shot no curve carries, sockets as squares and
water pipes as real circles — and comes back again: an edited sketch imports
into the room it came from, keeping the surveyed name of every corner it lands
on, so decisions already made still apply. Out, back and drop sit in the room's
own panel.

**The sketch.** Points can be picked up and moved on three axis handles under
Layer, with the shot still in the survey file and one click to put it back. The
outline applies itself as you draw it instead of waiting for a button.

## Checked

Both cores agree across all five surveys: 248, 215, 395, 409 and 1725 fields,
zero mismatches on the parse, and every room body identical bar two
long-standing float differences and `Ara Kat`. 95 tests, of which 91 run here.
42 of 45 rooms build.
