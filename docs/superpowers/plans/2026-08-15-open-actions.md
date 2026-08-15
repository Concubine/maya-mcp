# Open actions — 2026-08-15

Two live workstreams, both owned by **maya-mcp**. Written to survive a context
clear. Ranked; the top two are the ones that block other work.

Sources: Demigol's review of hero/kit revision 3 (accepted, merged `f3512e5`),
and `2026-08-15-golem-motion-handoff-design.md` (confirmed against the engine).

---

## 1. The unit-scale defect — CLOSED, and two things below it were wrong

> **Corrected 2026-08-15, after the fix landed (maya-mcp #629, merged `3243362`).**
> Two claims in this section were disproven by measurement. Both are struck
> below, in place, rather than deleted — the wrong diagnosis is the useful part.
>
> **(a) The prescribed fix would not have worked.** "Item 3 is the point.
> Without it this ships green again" named an *in-Maya* assertion. Measured: a
> probe cube reads 3.0 m at scale `[1,1,1]` with transforms frozen and exports
> as `300.0`. **The defect is written by the FBX exporter and is absent from the
> Maya scene**, so `scale == (1,1,1)` — which already existed — passed green on
> all three broken ships, and would have been the fourth. The real fix was to
> author metre-native, patch the unit declaration on the artifact, and gate the
> **FBX bytes** in pure stdlib (`evals/delivery_units.py`, `evals/fbx_probe.py`,
> no Maya in the loop).
>
> **(b) The precedent cited below is not evidence.** The golem blockout's
> metre-true claim rests on an in-Maya bbox query — exactly the measurement class
> (a) just disproved. The blockout was built through MCP tool calls, which never
> touch `currentUnit`; that scene is gone; it was never exported; there is no
> golem `.fbx` anywhere in the repo. Whether it was 4 m or 400 cm is **not
> recoverable**. Do not cite it. Tracked as maya-mcp #634, which generalises the
> underlying gap: nothing on the tool surface sets or reports the scene's linear
> unit, so every number crossing the MCP boundary is quoted in an ambient nobody
> named.

### As originally written — superseded, kept for the record

Revision 3 is a good delivery: 2,025 hero chunks / 2,025 distinct meshes / 0
nulls, kit at 41 pieces with one shading group and a 4096 atlas, generator
self-checks green, and the revision-2 ceilings genuinely taken (triangles
24,408 → 264,000, outset used on 1,879 of 2,025 chunks up to 0.47 m of the 0.5 m
allowance).

**One real defect, and it is the previous one wearing a new hat.** The delivery
still measures **0.0100×** in Unity:

- both baked catalogs carry `UnitScale: 0.01`
- Demigol's importer logs five warnings that the bare Mesh assets are not metre-true
- FBX headers read `UnitScaleFactor = 100.0` against `OriginalUnitScaleFactor = 1.0`
- the manifest states `units: "metres, Y-up, 1 unit = 1 m, cell = 3 m"`

**The file declares metres and delivers centimetres.** maya-mcp #600 asked for
metre-authored geometry with **frozen transforms**; the export unit was changed
and the transforms were not. Unity expresses the difference as transform scale,
and no importer setting fixes it — adjudicated during #596 with all four
combinations measured.

This matters more than a scale factor: a manifest asserting something measurably
false is the failure class Demigol #606 exists for.

**Do:**

1. **Reopen maya-mcp #600 in Redmine.** It is marked Resolved and is not — this
   is the third ship of the same defect (#596, #600, revision 3). Not done yet;
   left for a session that can confirm with the user first.
2. Freeze transforms at source so the **vertices** are metre-true.
3. Add to the generator's `geometry_self_check`, as fatal:
   - `scale == (1, 1, 1)` on every exported node
   - a **known-size chunk measures its declared size in metres**

Item 3 is the point. Without it this ships green again.

**Precedent that it works:** — ***STRUCK, see (b) above. Not evidence.*** — the golem blockout was rebuilt metre-native on
2026-08-15 and measured live — total **4.000 m**, pelvis bottom **1.600 m**,
group scale **[1,1,1]**, transforms frozen. It imports at 1.0 with no yaw fix
and no `UnitScale` factor. That is the standard; make it the rule for every mesh
deliverable out of this repo.

## 2. #603 — per-object pivot placement — DONE, gated live 2026-08-15

> **Corrected 2026-08-15.** This section is stale: the feature shipped in
> `4b7fbfc → 69ed649 → 478052b → 3b7f2ce` on `main`. `transform` takes a
> world-space `pivot` vec3 applied before translate/rotate/scale; `assemble`
> takes a `pivots` map of chunk name → vec3. The deployed plugin under
> `Documents/maya/scripts/maya_plugin` matches the repo source file-for-file.
>
> `evals/assemble_pivots_live.py` was run against Maya on 9877 and answers the
> question the unit tests could not — **a mode-only chunk's pivot survives
> `combine.unite`'s internal freeze**:
>
> | chunk | case | reported | measured |
> |---|---|---|---|
> | A | multi-part, explicit `pivots` entry | `[0.0, 9.0, 0.0]` | `[0.0, 9.0, 0.0]` |
> | B | multi-part, omitted → global mode `center` | `[5.0, 0.5, 0.0]` | `[5.0, 0.5, 0.0]` |
> | C | single-part, omitted → no treatment | `null` | `[10.0, 0.0, 0.0]` |
>
> C is the contract from the other side: `null` means no pivot treatment ran and
> Maya's default pivot stands, which is why an articulated figure must supply
> `pivots` explicitly. **The golem is no longer blocked on this.**

### As originally written — superseded, kept for the record

No tool path exists. `transform` has no pivot parameter; `assemble`/`combine`
take one global mode for the whole call; `array`'s pivot is only the mirror plane.

Confirmed twice by measurement: `assemble` returns `pivot: null` for all 29 golem
chunks, because **single-part chunks never go through `combine` and keep Maya's
default pivot**. That is the specific case that has to change.

Until it lands, nothing in the motion handoff is expressible — poses are
rotations about joint pivots, and with the pivot at the centroid every rotation
also translates the chunk and the limb comes apart.

Needs an implementation plan before any code.

## 3. Manifest fields that disagree with the artifact

Same class as the unit-scale claim — the manifest asserting what the artifact
contradicts.

- **Stale triangle count.** The deviations block says "45–54 triangles per chunk
  against the 200 allowed". Measured is **135.6 per chunk / 63.6 per cell**.
  Stale from revision 2; the manifest is understating its own improvement.
- **`endcap` coverage.** Now a distinct context with 4 pieces, which resolves the
  corner-chirality gap. **Confirm coverage is complete** — a wall that simply
  ends, in *both* handednesses — rather than partial. Demigol's consumer selects
  on context and can never choose chirality by hash, so a missing handedness is
  unrecoverable downstream.

## 4. Contract amendments — write the couplings down

- **Texel density is 113.8 px/m, not a shortfall.** The derivation is accepted:
  box auto-projection spans 2.858 face-widths, so a patch covers ~9 m, and ~170
  px/m would need a 6144 atlas. **Demigol amends the contract number.**
- **Brick calibration depends on mipmaps being off.** 6 courses/m with the mortar
  bed at 3.03 px is calibrated against Demigol's import path *disabling mipmaps*.
  **Write that dependency into the contract doc in BOTH repos.** If anyone
  re-enables mipmaps during the URP conversion or a texture-memory pass, brick
  silently mis-calibrates — and the fix lives here, not there.
- Corner spandrels and budget-used-not-exhausted: accepted, no action, recorded
  so they are not re-litigated.

## 5. Revision 4 lever — silhouette

Our own deviation note names it: no curves, every hero chunk axis-aligned boxes;
tapers are available and used on the kit but not the heroes. The bounds rule that
forbade it is gone, so this is now a budget choice — and we are at **32% of the
triangle budget**.

Silhouette reads first and from furthest away. That is where the next visible
jump lives.

Note the tension with the existing rev-3 finding that triangles were held at 35%
of cap deliberately, because past that per-face relief aliases instead of reading.
That argument constrains *surface relief*, not *silhouette*. Curves and tapers
spend triangles on the outline, which is the read that survives distance. The two
are compatible; state it explicitly when revision 4 is specced.

## 6. Golem — carried, not blocked by us

Design confirmed by the developer agent. Awaiting nothing from them except two
answers that do not block modelling:

- `GrabReach = 4` m against an actual **2.56 m** arm (3.2u × 0.8 m/u).
  `PunchReach` 3.5 m is fine with a forward lean. Recommended: accept that grab
  includes a lunge.
- Contact-pair cost of 29 chunks brawling inside live rubble — engine-side
  measurement. **Do not merge chunks for performance**; merging changes the
  breakage story, and the breakage story is the game.

Everything else is settled: 5 poses (`rest`, `crouch`, `extend`, `air`,
`absorb`), 1u = 0.8 m, +Z forward, swing/twist cones, primitive colliders with
the sculpt's COM, breakage ordering ours and magnitude theirs, and the brow plate
as the emet→met kill condition that also kills all seam emission.
