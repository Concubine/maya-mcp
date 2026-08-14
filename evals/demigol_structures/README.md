# Demigol — four destructible hero buildings

Built to the **STRUCTURE MODEL CONTRACT**. The model *is* the building,
structurally as well as visually: nothing is generated underneath to hold the art
up, so the frame was designed first and the cladding hung on what was left.

Footprints match the four archetypes, so each is a **drop-in replacement** in the
generated district rather than something to place by hand.

| building | archetype | cells | size (m) | chunks | frame chunks | tris |
|---|---|---|---|---|---|---|
| `tower` | Tower | 13 × 13 × 14 | 39 × 42 × 39 | 772 | 492 | 9 264 |
| `block` | Block | 19 × 19 × 6 | 57 × 18 × 57 | 622 | 482 | 7 464 |
| `slab` | Slab | 10 × 19 × 8 | 30 × 24 × 57 | 504 | 304 | 6 048 |
| `stump` | Stump | 10 × 10 × 4 | 30 × 12 × 30 | 136 | 80 | 1 632 |

2 034 chunks, 24 408 triangles. 12 tris per chunk against a 200 budget.

## It stands — and that is checked, not claimed

**The one-action self-check is implemented in the generator.** Every
`brick`/`infill`/`glass` chunk is discarded and the remaining `steel`+`concrete`
is flood-filled from storey 0 through face-adjacency — the same question your
solver asks on load, asked here first. A build fails and produces **no FBX** if:

- any frame chunk is unreachable from the ground,
- any column fails to reach storey 0, or has a gap in it,
- any glass chunk is wider than 2 cells.

All four pass, with **zero stilt columns** (a column touching no concrete at its
own storey is reported by name).

### The structural model

- **Columns** — steel on every bay-line intersection, continuous from storey 0,
  merged into segments of up to 4 storeys so the frame falls as large bent
  sections rather than a shower of cubes.
- **Ties** — every storey carries a concrete beam grid on the bay lines. That is
  what joins the columns; it is not decoration.
- **Corner spandrels** — one cell beside each corner column is concrete rather
  than cladding. A corner's only two face-adjacent cells are both on the
  perimeter ring, so with cladding there it would touch nothing structural and be
  a stilt by your own definition.
- **Cladding** — hung only in perimeter cells the frame does not need. **No cell
  is ever claimed twice**, so the manifest is an unambiguous statement of what
  each cell is made of.
- **Glass** — emitted one cell at a time, so the 2-cell limit is unreachable
  rather than merely checked.

### Geometry check

Every chunk is also re-measured *in the scene* after building: closed (V−E+F = 2),
bounds on 3 m boundaries, pivot at chunk centre, scale `(1,1,1)`, name parses
**and agrees with measured position**. All four clean.

## One reading I had to choose — please confirm

**Vertical sense of the origin.** I placed the min-corner cell **centre** at local
`y = 0`, so the floor plane sits at `y = −1.5`. The other reading puts the floor
at `y = 0` and the origin 1.5 m above it. If that is what you meant, every
building needs a single **+1.5 m Y offset** — no regeneration.

## Known issue: coplanar faces will z-fight

Adjacent chunks share exact faces, because bounds must land on cell boundaries.
Contract point 4 encourages deep interpenetration as the escape, but that
conflicts with exact bounds. Cheapest fix is shrinking the **render** mesh a few
mm inside the lattice bounds. Worth deciding before more buildings are authored.

## The four, and how each fails

- **`tower`** — full frame, glazed bands every third storey, glazed crown, and an
  **open lobby**: ground-floor cladding omitted, columns present. Cut a column
  line and everything the frame carried above it drops.
- **`block`** — heavy brick perimeter, wide and squat, open colonnade at ground
  on all four sides. Lots of mass, short fall.
- **`slab`** — alternating glazed and infill storeys the full height, fully clad
  at ground. Long axis means it can shear rather than topple.
- **`stump`** — all brick with a glazed top band. Small enough (136 chunks) to be
  the cheap one to scatter.

## Deliberate character is available, and cheap

The generator refuses buildings that would collapse on load, but that is a floor,
not a straitjacket — and it is what makes deliberate weirdness *safe* to author.
A half-ruined tower with a missing column line, a slab with a collapsed corner, a
block already leaning: all are a few lines, and the solver will tell us
immediately whether the result still stands or needs declaring as
collapse-on-load by design. Say the word and it is quick.

## What is deliberately not here

- **No taper or curve.** A tapered chunk cannot have bounds on cell boundaries.
  Lattice conformance outranked ornament; character comes from massing, glazing
  pattern and open lobbies instead. If you want curves, the rule to relax is
  "bounds on cell boundaries".
- **No LOD**, per the contract.
- **No interiors** — no stairs, cores or partitions. The beam grid leaves the bays
  open, so there is room for them if the golem is ever meant to go inside.
