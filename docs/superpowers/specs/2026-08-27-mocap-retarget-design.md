# Mocap ingestion + HumanIK retargeting — design (#774)

Date: 2026-08-27. Brainstormed with the user; the source decision and both
design questions were made explicitly. Context: the ticket (#774) makes the
honest case — motion quality comes from the capture, not from authored
keyframes, and the toolbox's job is the mechanical, checkable part: get good
motion onto our rigs without breaking it. #773's `measure_clip` landed first
and is this ticket's acceptance instrument.

## Decisions (each made by the user)

1. **Source: the CMU Motion Capture Database + deterministic cleanup.** Open,
   no account, terms permit any use including commercial (no resale of the raw
   data). ML enhancement is explicitly deferred: open-weights motion models
   are research/NC-licensed down the chain (AMASS/SMPL; LaFAN1 is CC BY-NC),
   operate on SMPL bodies rather than skeletons, and generate rather than
   verify. If post-cleanup numbers still show defects that filtering and
   contact-locking cannot fix, a separate spike surveys the then-current
   landscape. LaFAN1 may serve privately as a quality benchmark during
   development only — never as a shipping source.
2. **Files are user-stocked, local.** Clips live in a local directory the
   user fills once (e.g. `mocap/`); the tool surface only ever reads local
   paths. No network access in the toolbox.
3. **Two tools: `retarget_clip` + `clean_clip`.** HIK characterization is
   created, used, and torn down INSIDE the retarget call — the baked
   keyframes are the artifact, no HIK state survives (the #768
   construction-curves discipline applied to rig state). Cleanup is a
   separate tool so authored (phase-6) clips benefit too.

Rejected: toolbox-side downloading (network failure class on the surface);
one mega-tool (cleanup unavailable to authored clips, bad attribution when a
number comes out wrong); an exposed characterize/retarget/bake pipeline
(persistent HIK state on the surface is the LLM-hostile part the ticket
warns about).

**Scope bound (technical fact, not a choice):** HumanIK is humanoid-only.
Targets are biped rigs from `create_skeleton`. Quadrupeds/non-humanoids are
out of scope — they would need a different mechanism entirely.

## Tool surface

### `maya_retarget_clip` — mocap file in, named clip out, nothing else left

| param | meaning |
|---|---|
| `file` | local `.bvh` or `.fbx` path (user-stocked). BVH is parsed internally — Maya has no native BVH import. |
| `root` | root joint of the target rig (a `create_skeleton` biped) |
| `clip` | name for the baked clip — it lands as a normal phase-6 clip: `preview_clip`, `measure_clip`, `delete_clip`, multi-take `export_fbx` (#718) all work unchanged |
| `start` / `end` | optional source frame-range trim |

fps is handled per the #695 lesson (fbxmaya caches export fps; the clip path
already carries that fix). Inside the call: parse/import source → build
source skeleton → HIK characterize both ends from fixed tables → retarget →
**bake to keyframes on the target** → delete the source skeleton and every
HIK node → measure. A failed call reaps everything it created.

**The result self-reports** `measure_clip`-style numbers for the baked clip
(slide, penetration, symmetry, worst frames) — every retarget measures
itself, `measure_clip` remains the independent instrument.

### `maya_clean_clip` — deterministic improvement on ANY clip

| param | meaning |
|---|---|
| `root` / `clip` | the rig and the existing clip (retargeted or authored) |
| `filter` | smoothing pass: on/off + cutoff/window params, defaulted |
| `lock_contacts` | contact runs detected via the #773 machinery; feet pinned during runs; blended at run edges |

Reports **before and after** numbers for every metric — the improvement is
the result payload, not a claim. A checkpoint is taken before modifying;
`undo` works.

Both tools: `require_known_keys` + synonym entries from day one (#764).

## Internals

- **Pure-Python BVH parser** in a new pure module (`mocapmath.py` pattern —
  no Maya imports): joint tree + channel rows → typed structure. Fully
  headless-testable against committed fixture bytes. The handler builds the
  source skeleton from parsed data with `cmds` directly — no external
  converter, no FBX round-trip for BVH.
- **Committed CMU fixtures**: one walk + one idle clip (small BVH files)
  live in the repo with attribution — permanent test inputs for the parser,
  the mayapy tests, and the live gate. CMU's terms permit this.
- **Two fixed characterization tables**, written once, probe-verified: our
  create_skeleton joint names (#668 conventions: auto-orient local X down
  the bone, SSC off per #703) → HIK slots; CMU BVH joint names → HIK slots.
  The map VALIDATES and names missing joints rather than guessing.
- **Probe-first HIK**: HumanIK's scripting surface is MEL-era and
  underdocumented. The plan's first task is a mayapy probe (the #768 method,
  which caught three would-be landmines there): characterize both ends,
  retarget one frame, measure, record the working invocations. If HIK
  cannot be driven scriptably, STOP and report — no silent alternative.
- **FBX sources** (the other accepted extension) import via Maya's native
  FBX path into an isolated namespace; the same characterization tables
  apply when the joint names match a known convention, and unknown skeletons
  are refused with the unmatched joints named.
- **Filter math is stdlib-pure** (no scipy): implemented in the pure module,
  applied to baked curves by the handler. Default cutoff/window values are
  not guessed in this spec: they are chosen during implementation by
  measuring the fixture clips (the same method as every threshold here).
- **Contact-locking** reuses `motionmath`'s contact-run detection; pinning
  via IK during runs, re-baked, blend windows at run edges.

## Error handling

Refusals with hints, house style: missing/unreadable file; unparseable BVH
(line/context named); target not a biped (the specific missing joints named);
clip-name collisions per `author_clip` conventions; degenerate ranges;
unknown filter params.

## Testing

- **Headless**: the BVH parser in full (fixture bytes, malformed refusals),
  filter math, characterization-map validation, wire-shape tests (the #768
  regression pattern: the server's exact request dict through the real
  validator).
- **mayapy**: build biped → retarget fixture walk → baked keys exist, no
  HIK/source nodes survive, self-reported numbers sane; clean_clip
  before/after on a deliberately dirtied clip.
- **Live gate** (`evals/retarget_live.py`, disposable 9878 Maya, never the
  user's 9877): thresholds on `measure_clip` numbers **chosen by
  measurement** (the #773/#768 method — measure first, pick the value that
  discriminates, state it). Two discrimination checks: (a) retargeting onto
  a deliberately re-proportioned rig must SHOW slide pre-clean; (b)
  `clean_clip` must measurably reduce it (before > after) — a cleanup no
  dirty clip can fail is not a gate. Composition: the retargeted clip goes
  through #718's multi-take FBX byte-gate unchanged; one `preview_clip`
  sheet for eyes.

## Out of scope (decided)

- Non-humanoid targets (HIK is humanoid-only).
- ML motion enhancement — deferred pending post-cleanup numbers; separate
  spike if warranted.
- Toolbox-side downloading of mocap data.
- The consumer side: Demigol still imports no animation; this ticket raises
  what the toolbox can produce.
