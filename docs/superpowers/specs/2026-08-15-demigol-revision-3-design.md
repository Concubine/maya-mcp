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

## 0. Confirmed with the Demigol side, 2026-08-15 — revision 3 is unblocked

Every point below was verified by them against their tree or the URP package source. This
section is authoritative over anything later in this document that contradicts it.

### 0.1 URP — author unchanged

The editor (6000.0.47f1) ships URP 17.0.4 embedded. `Universal Render Pipeline/Lit` declares
`_MetallicGlossMap` and reads **R = metallic, A = smoothness**, so the kit's packing is correct
as authored and the G duplicate is inert. **No art change for the pipeline swap.**

Two defects are theirs and are being fixed inside the conversion: `MaterialBaker` enables
Built-in's `_METALLICGLOSSMAP` keyword where URP's is `_METALLICSPECGLOSSMAP`, and
`MaterialBaker.cs:25` loads an existing `.mat` without ever reassigning its shader, so a re-bake
would silently keep `Standard`. They delete and re-bake.

**They are also switching to Linear colour space.** Our maps are unaffected — import settings
already have albedo sRGB-on with normal and mask sRGB-off, correct under both — but the look of
everything shifts. **Do not judge revision 3 against any screenshot taken before Linear lands.**
This bears on item 7 (palette) in particular: colour variety authored and judged in Maya is
valid, but its in-engine appearance will move.

### 0.2 `MAX_RUN` stays exactly as written — they repair their side

This is the significant one. Their sim does **not** consume authored boundaries; it partitions
the same grid independently at runtime in `SimWorld.cs:281` via `Cluster.SplitByMaterial`, under
`SimTuning.cs` budgets — frame `48 cells / span 6 / 4 storeys`, curtain `16 / 4 / 2`. So our
`MAX_RUN` partition and their cluster partition are two independent partitions of one grid.

- **Kit (one-cell): no conflict.** Every cluster is a whole number of cells, so any cluster is
  exactly coverable by whole kit pieces. `MAX_RUN glass = 1` costs them nothing.
- **Hero (multi-cell): a chunk can straddle a cluster boundary.** Our runs are ≤4 against their
  48/16, so a chunk will usually sit inside one cluster — but "usually" is not a guarantee when
  neither partition knows about the other.

They considered asking us to granulate to one cell and **rejected it**, on the grounds that it
would buy the guarantee by discarding what multi-cell chunks are *for*: `MAX_RUN steel = 4`
exists so the frame falls in large sections, and one-cell steel falls as confetti. The repair is
theirs — cluster over authored chunks as atomic units rather than over raw cells, which makes our
rule true by construction. Scoped to #612.

**Author revision 3 to the existing rule. Do not granulate, do not change `MAX_RUN`.**

### 0.3 The rest

- **`endcap` as a context, not a variant letter** — accepted outright. Chirality-by-hash stays
  ours; they consume what the naming says.
- **Gate-mass movement** — theirs, acknowledged.
- **Hero `material` block** — add it. Wiring is theirs under #612: `CatalogBaker.cs:108` reads
  `root.IsKit ? MaterialBaker.Bake(...) : null` and `ChunkCatalog.SharedMaterial` is documented
  kit-only, so a cross-delivery material reference is something their contract validator has
  never seen.
- **The revision-1 "12 triangles" correction** — accepted and propagating; their `CLAUDE.md` is
  being fixed.

### 0.4 Heads-up received: a ground context may be coming

Demigol #610 (destructible city floor, filed from this side) would make the ground a destructible
surface rather than one flat plane — which is the first thing that would want a **pavement/road
context** in the kit. **Do not author it now.** Recorded so a later contract adding a ground
context is not a surprise.

---

## 1. Why revision 3 exists, honestly

Two of #600's seven items are **unmet existing requirements**, not new taste. This matters
because it changes what revision 3 has to do to be the last one of its kind.

**Item 1 (no roofs) is entirely hero-side. The kit is not at fault.**

An earlier draft of this spec claimed the kit's six `roof` pieces were vertical facade pieces that
never presented a horizontal surface. That was wrong, and the arithmetic says so:
`slab(top=0.6)` spans `y` from −1.495 to 0.6, and the following
`box(0, 0.75, 0, FULL, 0.3, FULL)` lays a **full-cell deck plate from 0.6 to 0.9**. The `_b`
variants add a parapet box on the +Z edge and a cornice. These are real roofs.

The actual cause is that **the heroes never place anything on top of themselves.**
`evals/demigol_structures.py` computes `faces["ground"] = ch.y == 0` but has no top or roof
equivalent anywhere, and `clad()` only hangs perimeter cladding storey by storey. Nothing is ever
assigned to the upward surface of the topmost storey. All four buildings are therefore open
egg-crates, exactly as #600 describes.

Note also that the heroes do not consume kit pieces at all — they are separately generated and
merely share the atlas. So a kit fix could never have produced hero roofs.

**Item 2 (one silhouette family).** The structure contract already asks for *"parapets, a crown
that reads from across the district."* Revision 2 delivered four flat-topped rectangular prisms.

What both have in common is not the fault but the reason it shipped: revision 2's verification
tables check only **mechanical** properties — zero boundary edges, pivot at chunk centre, cells on
the lattice, triangles within budget, names parse and agree with measured position. Every one of
those is a property a wrong building satisfies just as easily as a right one. **No check in the
delivery could fail on "this building has no top" or "these four buildings are one shape."** A
roofless hero passes every single revision-2 check.

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

### 3.0 The division of labour: the hero frames the roof, the kit sheathes it

Directed by the user, 2026-08-15. **A roof is modelled the way a roof is actually built**, and the
two halves land on opposite sides of the delivery boundary:

| half | who builds it | roles | what it is | when destroyed |
|---|---|---|---|---|
| **roof structure** | **hero** (`demigol_structures.py`) | frame — `steel`, `concrete` | beams spanning the bay lines at the top storey, plus the deck substrate they carry | the roof **collapses** |
| **roof sheathing** | **kit** (`demigol_kit.py`) | cladding — `brick`, `infill`, `glass`, plus plant | the visible deck finish, the parapet upstand, rooftop clutter | it **peels off**, the building stands |

This is not a new concept — it is the existing frame/cladding split extended upward. The heroes
already build `steel` columns and `concrete` beams and hang cladding in the perimeter cells the
frame does not need; a roof is the same idea rotated into the horizontal.

Three things follow, and they resolve questions this spec previously left open:

1. **§4.4's deferred question is largely answered.** Roof and floor *structure* is structural and
   participates in the flood-fill. *Sheathing* is not. What remains to settle in sub-project 2 is
   only the narrower question of whether a floor's structure ties columns strongly enough to relax
   the stilt rules.
2. **The damage model falls out of it.** Strip the sheathing and the frame is exposed but standing;
   take the beams and the roof comes down. That is the distinction the user wants to feel.
3. **It sets the build order.** The kit sheathes what the hero frames, so the sheathing vocabulary
   must exist before the heroes can dress a roof — sub-project 1 still lands first.

### 3.1 The `roof` context keeps its pieces and gains the missing treatment

The contract names three roof treatments — *parapet / cap / plant*. Revision 2 delivered the
first two and **not the third**: `roof_a` variants are a flush deck (`cap`), `roof_b` variants add
a parapet and cornice, and nothing anywhere is `plant`.

So the kit's roof work in revision 3 is small and additive: **rooftop plant pieces** — vents, AC
blocks, a stair head. Existing roof pieces are unchanged and nothing is reclassified.

**`plant` is a gameplay piece, not set dressing.** The golem roof-slams, and a bare deck gives it
nothing to destroy on landing. Rooftop clutter is high feel-per-triangle: small, cheap, breaks
satisfyingly, and it makes a roof read as a place rather than a lid. Given the delivery goal is
judging how damage *feels*, this is the highest-value item in sub-project 1.

### 3.2 Open question — deck height against the collision surface

Flag to the Demigol dev agent rather than fix blind, because the answer depends on how collision
is generated and this side would be guessing.

A `roof_a` deck tops out at **`y = 0.9`**, while the cell's own top face is at **`y = 1.495`**.
Collision is generated from the grid, never from the art, so if an occupied roof cell yields a
full-cell collider the golem stands on an invisible ledge **0.6 m above the visible deck**.

Either the deck should rise to the cell top, or the collider for a roof cell should be shortened
to match the art. Both are one-line changes on their respective sides; picking the wrong one
silently is what makes it worth asking. **Do not change the kit for this until the dev agent
answers.**

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

### 4.3 Framing the roof, and floors as bay-sized plates

Per §3.0 the hero builds the roof **structure**, not its finish. Concretely, the topmost storey
gains what every other storey already has and one thing more:

- **roof beams** on the bay lines, in `concrete`, exactly as `frame()` already lays a beam grid at
  each storey — this is what ties the column tops
- **a deck substrate** carried by those beams, spanning the bays

The heroes therefore do not place kit pieces (they never have — they are separately generated and
merely share the atlas). They build the frame and the substrate; the kit's sheathing vocabulary
dresses the same surface through the shared material.

Floor plates and roof substrate are **multi-cell chunks, one per structural bay**, which the
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

**The deferred decision, now narrowed by §3.0.** Structure is structural and sheathing is not —
that much is settled, so a floor's *substrate* participates in the flood-fill and its finish does
not. What remains open to sub-project 2 is only the narrower question: **does a floor's structure
tie columns strongly enough to relax the stilt rules?** Today a column with no floor ties is a
stilt; once every storey carries real substrate spanning its bays, that definition may be doing
less work than it was. The answer must be made once, recorded in the manifest as a stated
property, and checked — sub-project 2 is not complete while it is still open.

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
| V1 | every building's topmost storey carries **roof structure** — beams on the bay lines and substrate spanning every bay | a building has no top; this is precisely the egg-crate revision 2 shipped, and it passed every mechanical check |
| V2 | every roof substrate chunk occupies **real lattice cells** | a deck exists as art over an empty cell, so collision is absent where the art says to stand and the golem falls through a visible floor |
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
