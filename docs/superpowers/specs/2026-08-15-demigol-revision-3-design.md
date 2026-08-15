# Demigol — revision 3 design: kit and heroes

**Status:** design, approved in conversation 2026-08-15. Source of requirements: Redmine
[#600](http://localhost:3000/issues/600). Parent art tickets: Demigol #594 (hero buildings +
kit), #596 (import pipeline).

**Deliverable goal, stated by the user:** hand revision 3 to the Demigol dev agent so it can
regenerate the map, and judge two things — how the buildings *look*, and how damage *feels*.
That second one is a design constraint, not a nicety, and it decides at least one structural
choice below.

Contracts being revised (they live in the Demigol repo, not here):

- `D:\devel\Demigol\docs\superpowers\specs\2026-08-15-kit-of-parts-contract.md`
- `D:\devel\Demigol\docs\superpowers\specs\2026-08-14-structure-model-contract.md`

Generators being revised (here):

- `evals/demigol_kit.py` — 1,144 lines, produces `evals/demigol_kit/`
- `evals/demigol_structures.py` — 838 lines, produces `evals/demigol_structures/`

---

## 1. Why revision 3 exists, honestly

Two of #600's seven items are **unmet existing requirements**, not new taste. This matters
because it changes what revision 3 has to do to be the last one of its kind.

**Item 1 (no roofs).** The kit contract already defines the `roof` context as *"top face
exposed — parapet / cap / plant."* Revision 2 built all six `roof` pieces as **vertical facade
pieces with a cornice on top** — `kit_concrete_roof_a/b`, `kit_brick_roof_a/b`,
`kit_infill_roof_a`, `kit_glass_roof_a`. Not one presents a horizontal surface. The context was
reported as covered while nothing in it satisfied the definition.

**Item 2 (one silhouette family).** The structure contract already asks for *"parapets, a crown
that reads from across the district."* Revision 2 delivered four flat-topped rectangular prisms.

The cause is the same in both cases: revision 2's verification tables check only **mechanical**
properties — zero boundary edges, pivot at chunk centre, cells on the lattice, triangles within
budget, names parse and agree with measured position. Every one of those is a property a wrong
building satisfies just as easily as a right one. **No check in the delivery could fail on "this
roof is not a roof" or "these four buildings are one shape."**

So revision 3 adds intent checks alongside the art. Without them, revision 4 can re-report a
covered context that is not covered, and the loop does not converge.

**What revision 3 cannot prevent.** Item 3 — brick reading as corduroy — only became visible
once something was rendered at a real, stated texel density. That class of finding requires a
revision to exist before it can be seen. Revision 3 shrinks revision 4 to *only* that kind of
discovery; it does not eliminate it. This is the honest floor.

---

## 2. Settled decisions

### 2.1 Item 3 — coarsen the brick, do not re-plumb the atlas

Brick is authored at a **deliberately coarsened course pitch** (13 courses/m → ~6), mip filtering
stays off, and the atlas keeps its `margin: 0.03`.

The alternative — "solve the patch-margin problem so mips can be on" — is recorded here as a
known option **not taken**, with its reasoning, so it is not rediscovered from scratch later:

A patch atlas and mipmapping are structurally incompatible. The margin protects *bilinear*
filtering only. By mip level 5 a 1024 px patch is 32 px and the 3% margin is 1 px; beyond that
patches bleed into each other regardless of margin. The real fix is to stop using a patch atlas —
16 patches become a 16-slice `Texture2DArray`, slice index carried per-vertex so it remains one
material and one draw call. Mips then work correctly, the margin becomes unnecessary (regaining
~6% texel density), and brick could stay physically correct at 13 courses/m.

It is not taken because it requires a shader and importer change on the Demigol side, and no
render has yet demonstrated that coarsened brick is insufficient. Revisit only if revision 3's
renders still alias at city distance.

### 2.2 Scope and decomposition

Kit and heroes are **one contract**, delivered as **three sub-projects** in dependency order.
Sub-project 1 must land first because the heroes place its pieces.

### 2.3 Tool gaps

Gaps in the 40-tool MCP surface found while building revision 3 are collected and filed as a
**separate Redmine ticket**, not folded in here. #600 was explicitly filed as asset contract
changes, not tool work, and the two have different review audiences.

---

## 3. Sub-project 1 — kit revision 3

Self-contained in `evals/demigol_kit.py`. No dependency on the heroes.

### 3.1 The `roof` context gains what it always meant

A `roof` cell is one whose **top face is exposed**. Its top face *is* the roof surface, so a
`roof` piece must present a horizontal deck plate at the cell top (`y = +1.5`), plus exactly one
of three treatments:

| treatment | what | where it is used |
|---|---|---|
| `parapet` | a wall rising above the deck into the 0.5 m outset allowance | perimeter roof cells |
| `cap` | flush deck, no upstand | setback shoulders, where another mass rises behind |
| `plant` | deck plus mechanical clutter — vents, AC blocks, a stair head | interior roof cells |

The outset allowance is what a parapet spends. This is the allowance being used for its original
purpose rather than only for cornices.

**`plant` is a gameplay piece, not set dressing.** The golem roof-slams, and a bare deck gives it
nothing to destroy on landing. Rooftop clutter is high feel-per-triangle: small, cheap, breaks
satisfyingly, and it makes a roof read as a place rather than a lid.

**The revision-2 cornice pieces are not deleted.** They are reclassified as top-storey `facade`,
which is what they actually are. Deleting them would throw away good work; leaving them labelled
`roof` is what caused the problem.

### 3.2 Deck pieces must be collidable

Collision is generated from the grid and never from the art. So a roof deck reads as a walkable
surface **only if its cells are genuinely occupied cells in the lattice** — a deck modelled as
ornament oversailing an empty cell would be visually right and physically absent, and the golem
would fall through it. This is a hard requirement, checked in §6.

### 3.3 Brick pitch and palette

Brick coarsened per §2.1. Palette family 2 is spent on **colour variety** rather than decay, per
item 7 — the four heroes currently share one blue-glass/grey/rust identity. The revision-2 README
states the generator is parameterised by patch table and box list, so this is a table edit; that
claim is tested by doing it.

---

## 4. Sub-project 2 — hero structure revision 3

The large one. `evals/demigol_structures.py`.

### 4.1 The blocker: `Building` assumes one footprint

`Building.__init__(label, nx, nz, storeys)` computes `self.bx, self.bz = bay_lines(nx),
bay_lines(nz)` **once**, and `frame()` reuses those same bay lines for every storey. A varying
footprint is therefore not expressible. This is the one genuinely new cost in revision 3 and the
reason it is more expensive than revision 2 was.

**Setbacks must step by whole bays (3 cells).** An upper mass's columns must land on lower
columns, or the frame has floating columns — which either fails the load-path flood-fill or,
worse, passes it while being structurally nonsense. Whole-bay stepping guarantees the upper bay
lines are a subset of the lower ones.

**Naming.** Names encode `<role>_x##_y##_z##` from the **building's** min corner, not the
storey's. A setback storey's cells keep building-global indices, so a setback does not renumber
anything below it.

### 4.2 Four archetypes, four silhouettes

| | revision 2 | revision 3 |
|---|---|---|
| `tower` | 13×13×14 → 39.9 × 42.0 × 39.9 m, a cube | taller, setbacks at two heights, crowned plant room |
| `block` | 19×19×6 prism | courtyard void punched through — distinct from above, and it earns interior facades |
| `slab` | 10×19×8, effectively a fat box (30.9 × 24 × 57.9) | genuinely thin, stepped top |
| `stump` | 10×10×4 prism | squat ruin, partially collapsed top storey |

The tower's height comes from **more storeys**, not only from setting back — 13 cells wide is
39.9 m, so at 14 storeys it is a cube no matter what happens at the top.

The `block` courtyard is the highest-value single change for the map: it is the only one that
produces a silhouette which differs *from above*, which now matters because revision 3 has roofs
and the golem plays on them.

### 4.3 Floors and roofs as bay-sized plates — a damage-feel decision

Floor plates and roof decks are **multi-cell chunks, one per structural bay**, which the
generator already supports (*"Multi-cell chunks are named for their min-corner cell"*).

Not per-cell, for two reasons:

1. **Feel.** A floor that comes down in a handful of slabs reads as a floor collapsing. The same
   floor as 169 individual tiles reads as confetti. The user's stated goal is judging how damage
   feels, so this is the governing reason.
2. **Cost.** Per-cell plates take the tower from 772 chunks to roughly 3,100.

### 4.4 The ripple, stated up front

Revision 2's whole ornament system keys off **face exposure**, computed by probing each chunk's
neighbours in the occupied-cell set. Adding floors and roofs changes which faces are exposed for
essentially every chunk in every building. Revision 3 is therefore **not additive** — the entire
delivery re-derives and must be re-validated, not just extended.

**One decision is deliberately deferred to sub-project 2, and must not survive it:** whether a
floor plate counts as structural for the load-path flood-fill. If it does, floors tie columns and
the stilt rules relax; if it does not, floors are cladding that happens to be horizontal. Both are
defensible and the answer depends on how the plates actually behave once built. The choice must be
made once, recorded in the manifest as a stated property, and checked — sub-project 2 is not
complete while it is still open.

**One input to that decision, recorded now.** The user's longer-term intent is a **destructible
city floor**, with buildings sitting on top of it. That is a Demigol concern and not part of any
Maya delivery — heroes describe themselves from their own origin (min-corner cell centre at local
`y = 0`, floor plane at `y = −1.5`) and say nothing about ground.

But it invalidates an assumption the hero contract currently bakes in: the load-path check
**flood-fills the frame from storey 0**, which treats ground as an immovable anchor and makes
"reaches storey 0" the definition of supported. If the floor beneath a building can be destroyed,
that definition no longer holds, and Demigol's `SupportSolver` needs another anchor.

This argues *for* floor plates being structural — a building with internal load paths survives
losing part of its base, where one relying solely on ground contact does not. Not decisive on its
own, but it should be weighed when §4.4 is settled, and flagged to the Demigol side as a contract
assumption with a known expiry.

---

## 5. Sub-project 3 — hero finish

Small, rides after sub-project 2.

### 5.1 Item 4 — declare `outset_m` per chunk, as an ARRAY

The heroes use up to 0.47 m of outset and declare none; the kit declares all nine of its. 2,034
warnings become silence.

**Schema constraint:** the importer's `DeliveryManifest` is a `[Serializable]` DTO parsed with
plain `JsonUtility` and **no Newtonsoft dependency**. `JsonUtility` cannot deserialize
dictionaries. So per-chunk outset must be a **field on each entry of the existing chunk array**,
never a name-keyed map. (The kit manifest's `patches` object is exactly such a map — it survives
only because unknown/unparseable fields are ignored and `MaterialBaker` does not need it. Do not
copy that shape into anything the importer must read.)

### 5.2 Item 5 — the hero manifest names the atlas it shares

The heroes' README says they sample the kit atlas; the hero manifest has no `material` block at
all, so an importer cannot wire it without hardcoding cross-delivery knowledge.

**This is not a manifest-only fix.** The import pipeline's catalog documents `material` as
*"shared Material asset (kit deliveries; null for hero)"*, and `MaterialBaker` is marked **"Kit
deliveries only."** So the hero manifest gains a block naming the kit delivery and its maps, *and*
the Demigol side must honour a hero delivery that references another delivery's material. Flag
this to the dev agent explicitly — it is the one item in revision 3 that cannot be completed
entirely from the art side.

### 5.3 Item 6 — spend the triangle budget

45–54 of 200 is 25%. Revision 3 targets **~100–140 of 200** on heroes.

**Curves are permitted for heroes.** Per #600's own note: the tool spec's Tier-3 deferral of
curve construction cited both blast radius and triangle budget; the budget argument does not hold
for heroes sitting on 4× headroom. The blast-radius argument survives on its own (a curve is a new
object type across `get_scene_graph`, `get_object_info`, the ledger and mesh cleanup), so the
deferral stands — but **do not re-quote the budget argument for heroes.**

The kit keeps its 120-cap and its no-curves deviation. That argument is still true there.

---

## 6. Verification — the intent checks

These are the additions that make revision 3 different in kind. Each must be **executed by the
generator and fail the build**, in the same manner as revision 2's existing load-path check
("a build that fails exits non-zero and produces no FBX").

| # | check | fails when |
|---|---|---|
| V1 | every `roof` piece presents a horizontal surface at the cell top | a `roof` piece has no upward-facing geometry at `y = +1.5` — the exact defect revision 2 shipped |
| V2 | every roof deck cell is an **occupied lattice cell** | a deck exists as art over an empty cell, so the golem falls through a visible floor |
| V3 | each building shows **≥2 distinct occupied-cell footprints** across its storeys | a building is a flat-topped prism — no setback, no crown |
| V4 | for every pair of the four buildings, the normalised extent ratio `(w : d : h)` differs by **>20% on at least one axis** | four archetypes collapse to one silhouette family |
| V5 | every occupied cell with **no occupied cell directly above it** is a `roof` cell | the egg-crate condition, stated positively — this is the check that would have failed revision 2 |
| V6 | every chunk declares `outset_m`, and declared ≥ measured | item 4's 2,034 warnings |
| V7 | setback bay lines are a **subset** of the storey below | floating columns — the structural trap in §4.1 |

Revision 2's existing mechanical checks all stay. They were never wrong, only insufficient.

---

## 7. Handoff to the Demigol dev agent

The delivery must be regenerable and importable without conversation. `DeliverySync.Import
(sourceDir, name)` reads the delivery folder directly from `D:\devel\maya-mcp\evals\...`, and is
invocable both as a menu item and via `-executeMethod` in batchmode.

Revision 3 hands over:

1. Both delivery folders, regenerated — FBX, atlas maps, manifests, contact sheets, tiling proof.
2. Both READMEs, rewritten, with the verification table showing **measured** results as revision 2
   did — executed, not asserted.
3. Both contracts amended to revision 3 in the Demigol repo.
4. **An explicit note on §5.2**, the one item needing a Demigol-side change.
5. The tool-gap ticket number, if any gaps were found (§2.3).

---

## 8. Sizing

From git timestamps on the revision-2 wave (no Redmine time entries were ever logged):

| | built | elapsed |
|---|---|---|
| kit rev 1 → rev 2 | 00:40 → 01:25 | 45 min |
| heroes rev 1 → rev 2 | 23:54 → 01:39 | ~1h45 |

Revision 3 estimate: **~4–6 h wall clock across 2–3 sessions** — kit ~1 h, hero structure 2–3 h,
hero finish ~45 min, contracts and READMEs ~45 min. Token cost is dominated by live-Maya
iteration with render inspection rather than code volume; roughly 150–300k per sub-project.

Treat the hours as grounded and the tokens as an estimate. Build sub-project 1 first and check
the estimate against it before committing to sub-project 2.

---

## 9. Risks

1. **The ripple in §4.4 is the schedule risk.** If re-deriving face exposure destabilises the
   revision-2 ornament work, sub-project 2 overruns. Mitigation: land sub-project 1 first, so the
   kit is stable while the heroes churn.
2. **Neither generator has unit tests.** Nothing in `tests/` references `demigol_kit.py` or
   `demigol_structures.py`; all verification is in-scene against live Maya, so there is no fast
   feedback loop. The V1–V7 checks partly close this, but they are build-time, not test-time.
3. **§5.2 depends on another repo.** It cannot be finished from the art side alone, so it must be
   communicated rather than silently left incomplete.
4. **`JsonUtility` schema limits are easy to violate.** Any new manifest structure must be objects
   and numeric arrays only. A name-keyed map will parse as nothing and fail silently at import.
