# Snapir Design X 1.4.5 — Not every building is closed

Two rules, both of them things the survey was already saying and the builder
was not listening to.

## A wall needs a ceiling over it

A stairwell is open at the top. A landing has no ceiling of its own. The survey
says so by having nothing shot up there — and that is a measurement, not a gap.
Read as a gap, it put a wall and a slab across an opening the building has not
got, which is how `Ara Kat` came back as a sliver box 3.8 m tall enclosing
0.09 m².

A corner now counts as covered when something was shot at ceiling level within
120 cm of it in plan. An edge is a wall when at least one of its two ends is
covered — one end is enough, so a wall that runs up to an opening still gets
built and stops where the building does. Under three covered corners there is
no ceiling either, and the slab is not built.

The threshold is not a guess. Across five surveys and forty-five rooms, the
worst any real room manages is **105 cm**; the only corners that miss are the
ones over the stairwell, at **179 cm and beyond**. There is no third case in
the data, and the change touches no room but those two.

## A zigzag measured the wall, so a wall is what gets built

There are two ways to trace a flight, and they measure different things.

A nosing line runs along the middle of the treads: the flight was measured, so
the flight is built, as wide as the settings say, because its width is the one
thing the line cannot give.

A zigzag is the corner where each tread meets the wall — the tip goes against
the wall and you walk up. That line measured **the wall**. It now builds the
wall: the stepped profile, one wall thick. Ninety centimetres of flight hung on
it was a staircase nobody surveyed, half of it inside the masonry and half of
it in mid air. Every flight in `Sofia - Villa Tocheva` is a zigzag, and every
one of them sat like that.

## What that does to the stairwell

| room | before | after |
|---|---|---|
| `Ara Kat` | 6.023 m³ — a 0.09 m² box, 3.8 m tall | 2.860 m³ — the landing slab and the two flights' wall |
| `Giriş kat` | 20.144 m³ | 14.387 m³ — one side open, the flight a wall |
| `Son kat koridor` | 15.563 m³ | 13.784 m³ |

No other room in any of the five surveys changes by so much as a cubic
millimetre.

## Checked

Every room built before and after and diffed: three rooms changed, forty-two
did not. Parse parity across all five surveys, zero mismatches. 114 tests, of
which 110 run here.

`Ara Kat` still differs between the two cores, as it has since before this
release: its outline is a three-corner sliver the classifier should not have
made, and the two cores project a jamb onto different edges of it.
