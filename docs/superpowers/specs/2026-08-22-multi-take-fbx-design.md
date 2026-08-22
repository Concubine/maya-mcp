# Multiple named takes in one FBX (design)

Ticket: #718. Parent spec: `2026-08-20-rigging-p6-clips-design.md` — this doc
**supersedes that spec's decision 1** ("one clip at a time"), agreed with the
user 2026-08-22. Everything else phase 6 settled stands: the currency is the
phase-1 pose map keyed over time, the engine owns feel, there is no persistent
solver state and no Trax/Time Editor clip library.

Measured origin (#713 v3 golem run, `out_v3/NOTES.md` Wall 1): an animated
asset had to ship one FBX PER take (`golem.fbx` + `golem_idle.fbx` +
`golem_visor_scan.fbx`), the `.ma` could not hold both takes at once, and the
key data had to ride in a `golem_takes.json` sidecar to stay reconstructable.

## Decisions settled with the user

1. **One rig, N clips.** A single skeleton carries as many named clips as the
   asset needs, and all of them export as takes into one file. Two SKELETONS
   carrying clips still refuses — a take is a frame range over the whole file,
   so a multi-rig file needs its own timeline policy. That refusal's message
   changes from a flat "one file is one take" to one that says multi-CLIP is
   supported and multi-RIG is not.
2. **Sequential ranges on one timeline** (approach A of three). Clips coexist
   as curves laid end to end, each owning a frame range. Rejected: Trax/Time
   Editor clip containers (stateful, poor blind-driving fit — the capability
   roadmap parks it at Tier 1), and store-keys-replay-at-export (leaves the
   `.ma` unable to hold all clips, which is half the reported pain, and makes
   export a large scene mutator).
3. **Auto-append layout.** `author_clip` places a new clip after the last one
   and REPORTS the range it took. The caller never computes frames. No
   explicit `start_frame` parameter — it would hand the caller collision
   avoidance, and an overlap silently corrupts two takes.
4. **Re-authoring a name replaces it AT THE TAIL.** The old range's keys are
   removed and the new version is appended after the current last clip. No
   other clip's MOTION ever changes, so re-authoring cannot disturb a take
   already judged. (The one thing authoring may add to another clip is a
   rest-value pin on a channel that clip never declared — see the
   self-contained rule; that preserves its motion, it does not alter it.) Take ORDER in the file changes; each take is still independently
   named, which is all a consumer reads.
5. **`delete_clip` takes an optional `name`.** With a name: that clip only.
   Without: every clip, plus the bind-pose restore that exists today (the
   current single-clip behaviour, unchanged for existing callers). Gaps left
   behind are not re-packed — takes are explicit ranges, so a gap costs
   nothing and re-packing would move keys the caller did not touch.
6. **One fps per rig.** A second clip at a different fps refuses, naming the
   fps already in use. Not a compromise: a take IS a frame range, so one file
   cannot carry two frame rates.
7. **Takes are self-contained** (see the rule below) — the correctness
   decision this whole design turns on.
8. **The consumer gate is a real Unity re-import**, measured, the #703 proof
   shape — not the byte gate alone.

## The self-contained takes rule

All clips on a rig share the SAME curves: one `rotateX` curve per joint,
spanning every range. So a joint keyed in `idle` but never mentioned in `walk`
would, throughout `walk`'s frames, hold whatever value `idle`'s last key left
on it — a curve holds its final value after its last key. Take `walk` would
ship contaminated by `idle`, and nothing in the bytes would look wrong.

**Rule:** at its own first and last frame, every clip keys EVERY channel that
any clip on that rig touches. Channels the clip does not mention are keyed at
their rest value (the bind pose for rotations, 0.0 for weight channels, the
bind position for root translation).

Consequences, all of them deliberate:

* **A clip that introduces a NEW channel back-fills rest keys at every
  existing clip's boundary frames.** Contamination runs BACKWARDS too: a curve
  holds its first key's value backwards in time, so the moment `walk` creates
  an arm curve at frame 62, `idle`'s frames 0-60 inherit `walk`'s opening arm
  pose — a clip already authored, previewed and judged silently changes. The
  back-fill pins that channel at rest across every earlier range, which
  RESTORES what each earlier clip measured when it was authored rather than
  altering it. It is the one case where authoring touches another clip's
  curves, and it can only ever add rest-value keys on channels that clip never
  declared. `author_clip` reports it: the names back-filled and the channels
  added. The live gate measures each earlier clip's displacement before and
  after, and requires them equal.
* The one-frame gap between clips is where the interpolation between two
  clips lives. No take's range includes it.
* A clip's declared `joints` / `weight_channels` metadata stays what the
  CALLER keyed, not the padded set — the metadata describes design intent,
  and the gate uses it to assert that a take moves only what it declared.

## Metadata

`mcp_clip` on the root becomes a JSON LIST of clip records, in timeline order:

```json
[{"name": "idle", "fps": 30, "start_frame": 0, "end_frame": 60,
  "duration_s": 2.0, "loop": true, "interpolation": "smooth",
  "joints": ["chest", "spine_01"], "weight_channels": ["blink"],
  "root_position_used": false}, ...]
```

`clip_meta` reads BOTH shapes: a bare object (every scene authored before this
change) is read as a one-element list whose record gains
`start_frame: 0, end_frame: round(duration_s * fps)`. Nothing migrates on
disk; the next `author_clip` or `delete_clip` writes the list form. A value
that fails to parse is still reported as name-only rather than crashing a
guard, as today.

## Tool surface

### `author_clip(root, name, fps=30, keys=[...], interpolation, loop, timeout_s)`

Unchanged parameters — the layout is derived, not passed. New behaviour:

* Appends after the last clip's `end_frame` + 1 (the gap frame). The first
  clip on a rig starts at frame 0.
* A name that already exists: its keys are cut from its old range, the record
  is dropped, and the clip is re-appended at the tail. The warning names the
  measured range it vacated and the range it now occupies.
* Refuses a second fps, naming the existing one and the clips using it.
* Pads every clip's boundary frames per the self-contained rule above, and
  back-fills rest keys at every EXISTING clip's boundaries for any channel
  this clip introduces. Reported, never silent.
* Sets the playback range to the FULL span (0 .. last `end_frame`), so opening
  the `.ma` and scrubbing shows every clip.
* Returns today's fields plus `start_frame`, `end_frame`, and `clips` — the
  ordered names now on the rig. `replaced` keeps its meaning.
* Warns when ANOTHER skeleton in the scene already carries a clip, because
  `export_fbx` will refuse that scene. #718's design note asks for exactly
  this: the ceiling should be discovered at authoring time, not at write time.

### `delete_clip(root, name=None)`

* With `name`: cuts that clip's keys from its range, drops its record, leaves
  every other clip untouched, and reports the measured `deleted_curves` (curve
  nodes left empty are deleted) and the displacement of the return.
* Without: today's behaviour — all curves deleted, weight channels zeroed,
  bind pose restored, `mcp_clip` removed.
* Refuses a name no clip carries, listing the names present.

### `preview_clip(root, name, ...)`

Renders the NAMED clip's frame range. The "must be the live clip" refusal is
replaced by "no clip named X on this rig (has: ...)". Frame selection,
`every_nth`, the 16-cell cap, the held camera and `zoom` are unchanged; the
frames it reports are absolute timeline frames, and the `time_s` it reports is
relative to the clip's own start, so a preview reads the same whether the clip
is first or fourth.

### `export_fbx(..., include_animation=True)`

* Bakes across the whole span: `FBXExportBakeComplexStart 0`,
  `...End <last end_frame>`.
* One `FBXExportSplitAnimationIntoTakes -v "<name>" <start> <end>` per clip,
  after a single `-clear`.
* `animation` in the result grows a per-clip list: name, frame range, duration
  and the curve count measured back from the bytes.
* The multi-RIG refusal stays, with the corrected message.

## Byte gate (`fbxbytes` / `export.anim_violations`)

Per declared clip, from the bytes alone:

* a take of that name exists (by-name lookup — Maya's own `Take 001` is still
  present and still tolerated, the phase-6 measured truth)
* its local start/stop ticks match the declared frame range, converted through
  the KTIME constant pinned in phase 6
* the take carries rotation curves for every joint the clip declared, root
  translation curves when `root_position_used`, and DeformPercent curves for
  every declared weight channel
* takes do not overlap, and their names are unique

A take present in the file but not declared is NOT a violation (the rule
`shape_violations` already applies to undeclared blendShape channels).

## Live Maya gate (`evals/multi_take_live.py`)

Three clips on ONE rig, deliberately keying DIFFERENT channel sets so the
self-contained rule is what's under test:

1. each clip's reported range is contiguous-with-a-gap and non-overlapping
2. re-authoring the middle clip moves it to the tail and leaves the other two
   clips' keys byte-identical (measured, not asserted by construction)
3. **contamination check, both directions**: at frames inside clip B's range,
   every joint B did not declare sits at rest (forwards); and clip A's
   measured per-frame displacement is IDENTICAL before and after clip C
   introduces a channel A never used (backwards). A failure here is the exact
   defect the rule exists to prevent, and the backwards half is the one that
   is easy to ship broken.
4. `delete_clip` with a name removes one clip and leaves the others measurable
5. the export carries three takes with the right spans, and previews of each
   clip render its own motion (judged, not just counted)

## Unity gate (`evals/multi_take_unity.py`)

The #703 proof shape, in a scratch project, via the unityMCP tools:

* import the multi-take FBX with `importAnimation` ON (Demigol forces it OFF,
  which is why this cannot run in Demigol's project)
* measure that N clips arrive, named as declared
* measure each clip's length against the Maya duration to 3 decimals
* measure that a joint not keyed in a clip does not move within that clip —
  the contamination check again, this time on the consumer's side

If the Unity editor is not open, the gate reports that and stops. It never
falls back to a CLI batchmode run without the user's say-so.

## Out of scope

* **Multi-RIG files** — two skeletons in one FBX. Needs a shared-timeline
  policy of its own; the refusal stays and now explains itself.
* **Re-packing** the timeline after a delete, and **explicit start frames**.
* **Transitions/blending between clips** — phase 6 settled that the engine
  owns blending; the gap frame is a separator, not a transition.
* **A clip library that survives across scenes**, and `#714` (procedural
  texture maps dropped at export), which is its own round.
