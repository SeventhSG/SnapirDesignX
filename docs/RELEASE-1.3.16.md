# Snapir Design X 1.3.16 — Snapshot

## A doorway starts at the floor

1.3.15 stopped a doorway leaving a slab of wall standing under it. It did not
stop the other half of the same mistake: where the jamb was shot a centimetre
*below* the floor datum, the cut went down into the slab and left a trench
across the threshold. **Fifty doorways in five surveys** did that, up to 4 cm
deep.

The bottom of a doorway is not a measurement at all. The surveyor shoots the
jamb where the frame is, and that reading lands a centimetre or two either side
of the floor plane depending on where the tip went. So a door is cut from the
floor plane, full stop — never above it, never below it. The slab underneath
runs unbroken, which is what a doorway does.

A window keeps the sill it was shot with. That one really is measured.

## Every loose shot goes to Design X

The handover carried the curves and the depth shots. It did not carry the
points that are on no curve at all — a socket, a control point, a corner the
surveyor took and never joined to anything, a reading the classifier could not
place. Those are exactly the ones that still need a decision, and they were the
ones being left behind.

Anything no polyline already passes through now goes over as a point, with a
small cross through it so it survives STEP too. Nothing is sent twice: a corner
the outline already draws is left to the outline.

## Design X, on the room it belongs to

Send out, bring back, and drop, as three actions in the room's own panel on the
right, with what they do written next to them. They were only in the bar along
the bottom before. The bottom bar still has them.

## Checked

Both cores agree across all five surveys: 248, 215, 395, 409 and 1725 fields,
zero mismatches on the parse, every room body identical bar the two
long-standing float differences and `Ara Kat`. 93 tests, of which 89 run here.
42 of 45 rooms build.
