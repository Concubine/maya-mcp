# Transition prompt — next maya-mcp session

Paste the block below as the opening message of the next session.

---

Working dir must be `D:\devel\maya-mcp` (starting from `D:\devel\Demigol\maya-mcp`
loads the wrong project memory).

## What just landed

maya-mcp **#629** — the hero/kit unit defect — is fixed and merged to `main` as
`3243362`. Full suite green. The ticket sits at **Feedback**, not Resolved, on
purpose: it is closed by one measurement from the Demigol side, not by us.

The short version, because it overturns advice that is still written down in
places: **the defect was written by the FBX exporter and was absent from the
Maya scene.** A probe cube reads 3.0 m at scale [1,1,1] with transforms frozen
and exports as 300.0. So every in-Maya gate — including the `scale == (1,1,1)`
check that already existed — passed green on all three broken ships. The fix was
to author metre-native, patch the unit declaration on the artifact, and gate the
**FBX bytes** in pure stdlib so it runs in the normal pytest suite forever.

Full detail is in the `maya-mcp-metre-true-means-frozen` memory and in
`docs/superpowers/plans/2026-08-15-delivery-unit-truth.md`.

## Ranked, what is actually open

**1. #603 — per-object pivot placement. BLOCKING THE GOLEM.**
Untouched. No tool path exists: `transform` has no pivot parameter,
`assemble`/`combine` take one global mode per call, `array`'s pivot is only the
mirror plane. Confirmed twice by measurement — `assemble` returns `pivot: null`
for all 29 golem chunks, because **single-part chunks never go through `combine`
and keep Maya's default pivot**. That is the specific case to change. Nothing in
the golem motion handoff is expressible until it lands, because poses are
rotations about joint pivots. **Write an implementation plan before any code.**

**2. Two corrections owed to documents that now contain falsehoods.**

- `docs/superpowers/plans/2026-08-15-open-actions.md` section 1 still prescribes
  the in-Maya `geometry_self_check` assertion as "the point — without it this
  ships green again". Measured false; that assertion would have been the fourth
  green ship. The file is untracked and was left alone deliberately — ask before
  editing it.
- The **golem blockout's metre-true claim is unverified at artifact level**. Both
  that doc and #629 cite it as the working precedent, but it rests on an in-Maya
  measurement of exactly the blind kind, and there is no golem `.fbx` in the repo
  to check. Either export `|golemFeel|` through `evals/maya_export.py` and
  measure it with `evals/delivery_units.py`, or stop citing it. This matters for
  #601: a 100× error in the golem surfaces as physics that cannot be tuned.

**3. Awaiting Demigol, not us.** #629 closes when they report
`sharedMesh.bounds` ≈ 3.065 for a tower chunk, `lossyScale` 1.0, and
`ChunkCatalog.UnitScale` 1.0. They need no code change — `CatalogBaker.UnitScaleOf`
measures it — beyond unpinning `MeasuredUnitScale = 0.01f`. They should also
re-run the kit render-substitution spike and delete its `localScale 0.01` plus
the 300-unit compensating `BoxCollider`; that compensation is what rendered
detached debris 1 cm across against a 3 m collider.
A handoff prompt for them was written this session — ask if it still needs sending.

**4. Lower.** From the open-actions doc, still valid: the stale triangle count in
the hero manifest `deviations` block (says 45–54/chunk, measured 125–136),
`endcap` chirality coverage, writing the brick-pitch/mipmaps-off coupling into
both repos' contract docs, and the revision-4 silhouette lever (curves/tapers at
32% of triangle budget).

## Environment notes that cost time this session

- **The deployed plugin is what Maya loads** — `C:\Users\plotk\Documents\maya\scripts\maya_plugin\`,
  not the repo. A repo-only edit to a handler is silently ignored. Copy the file
  across before trusting any live result.
- **The generators talk to `MAYA_MCP_PORT`, default 9878**, which was refusing
  connections; port **9877** is the instance the MCP tools reach. Everything this
  session ran with `MAYA_MCP_PORT=9877`.
- The generators call `new_scene` per building, so running them wipes the live
  scene. The user has confirmed they are the only one using Maya and that
  closing/reopening instances is fine.
- Run tests with `.venv\Scripts\python.exe -m pytest`; system Python fails on an
  unrelated `mcp` import.

## How the user likes to work

Short, precise replies. Measured numbers over assurances. Flag it plainly when a
prior claim turns out wrong rather than quietly moving on.
