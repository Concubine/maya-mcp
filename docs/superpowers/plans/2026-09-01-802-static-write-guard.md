# #802 Static-Write Guard — Plan and Record

**Goal:** No command writes a plug a user has locked, constrained, keyed or wired without asking first. Eight defects #799 pinned as `xfail(strict=True)` flip to passing; `pose_ik` (unpinned, same defect) is fixed with them.

**Spec:** Redmine #802 (http://localhost:3000/issues/802) — the ticket body, corrected by the live probe below.

**Outcome:** DONE 2026-09-01. Suite 2600 → **2674 / 0 failed / 11 xfail** (19 − 8). Live gate `evals/static_write_guard_live.py` **30/30** on Maya 2027 (pid 47860, port 9878, working-tree code verified by phase 0).

## The probe came first, and it refuted the ticket

Per the ticket's own instruction and #796's lesson, `evals/static_write_probe_802.py` and `evals/static_write_probe_802b.py` ran before any design. Two rounds, 14 wirings, every write recorded. The findings the fix is built on (full text in `_802b.py`'s docstring):

1. **Maya does NOT refuse a constraint-driven or keyed static write.** `setAttr(joint.rotate, 77, 77, 77)` on an orientConstraint-driven joint returns cleanly, reads back 77, and reverts to the constraint's value at the next evaluation (O4/O5/O6). Same for a keyed plug across a frame change (K3/K4/K5) and for `xform` on a parentConstrained camera (R3/R4/R5). The write is **futile, not refused** — worse than the ticket said, because the handler reports success.
2. **`cmds.xform` never raises.** It writes the children it can and silently skips the rest (L2/L3, L8/L9, P8/P9, X5/X6). `cmds.move` and `cmds.hide` likewise (L4/L5, W2/W3). So `transform`, `set_camera` and `_hide_non_targets` were silent *partial* writers, and no `except` could catch what does not raise.
3. **A LOCK, a plain `connectAttr` or an expression makes `setAttr` raise** — "A child attribute of 'x.translate' is locked or connected" on a compound (A04, L6, P6, X3). This is the only half of the ticket's mechanism that was true.
4. **Compound and child queries do not see each other.** `getAttr(".rotate", lock=True)` is False while rotateX is locked (A01); `listConnections` on a compound is None while every child is constraint-fed (B01, C01).
5. `getAttr(plug, settable=True)` predicted setAttr's outcome 14/14 but answers True for `worldMatrix[0]` and raises on a missing plug — a refusal predicate, not a writability one.
6. `cmds.xform` has **no `edit` flag** — found by the live gate the moment a bare `except` was removed (see below).

**Consequence:** the guard had to be a pre-check. The ticket's "catch the RuntimeError and convert it" would have caught nothing in the common case.

## Architecture

- **`maya_plugin/handlers/plugwrite.py`** (new) — one guard. `family(plug)` = the plug, its children (if a compound), its parent (if a child), never siblings (A05). `blocker()` asks `getAttr(lock=True)` then `clip.driven_weight_source` (the package's ONE classifier, imported lazily — clip imports render, render imports plugwrite). `blockers()` reports every obstacle, not the first (delete_objects' idiom). `refuse()`/`guard()` raise a `HandlerError` naming command, plug, obstacle, kind-specific fix and a caller-supplied consequence; `describe()` is the warning sentence for passes that must not refuse. `transform_plugs()` expands `pivots` to both pivots.
- **Callers:** `rigging.pose_skeleton` (the joints it will write), `reset_pose` (the whole hierarchy — the honest approximation of the dagPose branch's write set), `pose_ik` (chain `.rotate` + `.preferredAngle`), `viewport.set_camera` (translate/rotate/focalLength together, before the first lands — the half-move fix), `modeling.transform` (every plug of every name before the loop — all-or-nothing), `render._orient_rig` / `_hide_non_targets` (warn and name; `_restore_rig` skips a light it never moved), `correctives._joint_rotation_writable` (now delegates — one classifier).
- **Fakes:** `tests/test_viewport.py`, `test_render.py`, `test_modeling.py` gained `getAttr(lock=)`, `listConnections()`, `locked_plugs`; `driven_plugs` values became SOURCE PLUGS with declared node types; a fed source node exists by definition. Each carries new `TestTheFakeRefusesWhatMayaRefuses` cases pinning A01 and B01/B02. `tests/test_plugwrite.py` (38 tests) covers the guard directly.

## Found by the live gate, not the suite

`render._orient_rig` called `cmds.xform(transform, edit=True, rotateAxis=(0, 0, 0))` inside its own `except Exception: pass`. **`cmds.xform` has no `edit` flag** — that line raised `TypeError: Invalid flag 'edit'` on every render since it was written, and the swallow ate it. Confirmed against Maya 2027 on its own (`xform(loc, rotateAxis=...)` succeeds; `edit=True` raises). The render fake had accepted `edit=True`, which is how it stayed green. **Deleted rather than repaired:** making a write work for the first time is a behaviour change no measurement backs, and `_restore_rig` never restored rotateAxis. The fake now raises on `edit=`.

## Tasks (all done)

- [x] Live probe, two rounds, findings posted to the ticket before design.
- [x] `plugwrite.py` + `tests/test_plugwrite.py`.
- [x] Wire rigging ×3, viewport, modeling, render ×2, correctives.
- [x] Harden three fakes; update ~14 fixtures to source plugs + types.
- [x] Unpin the 8 xfails; rewrite reason prose that asserted the raise-based mechanism as fact.
- [x] pose_ik tests (constrained, locked, driven preferredAngle) + an over-refusal control (a constrained joint OUTSIDE the write set does not refuse).
- [x] Live gate `evals/static_write_guard_live.py`, each refusal paired with its negative control; 24/24.
- [x] `docs/protocol.md` Rules bullet.
- [x] Adversarial review: 5 angles → 54 findings → per-finding refutation → 22 confirmed. Fixed: `pose_ik` guarded `preferredAngle` on every chain joint where the solve seeds it only on `chain[1:-1]` and only when straight+pole (over-refusal on every bent limb); `reset_pose` guarded `.rotate` for a setAttr its bound-rig branch never makes and missed the translate `dagPose -restore` does write (now asks the bind pose first and guards rotate+translate on that branch, scale deliberately excluded — riggers lock it routinely and the restore leaves it); `relit_lights` still counted lights DISCOVERED (now counts swung; the gate's 4a' discriminates); `_orient_rig`'s warning named `render_scene` to `render_sheet`/`preview_clip` callers ("the relight pass" now); `_hide_non_targets` warnings repeated once per sheet cell (deduped); `blocker()` stopped at the first obstacle in a family (reports all); the "clip" hint sent a keyed CAMERA to `delete_clip`, a skeleton-only tool (hint now depends on whether the owner is a joint); the modeling fake refused `rotatePivot` only where `xform -pivots` writes both. Coverage added for: guard-before-checkpoint ordering ×3, `_restore_rig`'s skip, the hint dedupe's suppressing branch, scalePivot, bound-rig reset. Gate checks 4b/4d relabelled as damage assertions (they pass both ways); 1h–1k added for the bound rig; 2d' for the hint.
- [x] Deploy, user's 9877 ping-verified.

## Left open / noted

- `reset_pose` guards the hierarchy's `.rotate`; its dagPose branch restores whatever that node covers. Same policy `guard_static_pose` already applies (any curve in the hierarchy refuses), so consistent, but a constrained leaf (an eye aim) makes `reset_pose` unusable on that rig — as it already did for a keyed one.
- Pre-existing, out of scope, filed in the ticket: `_rig_lights` reads a WORLD yaw (`xform -q -ws -ro`) that `_orient_rig`/`_restore_rig` write into the LOCAL `.rotateY` — identical only while rig lights sit at world level, which `setup_lighting` guarantees today.
- The fakes still refuse a constraint-driven setAttr where Maya takes and discards it. Documented as the stricter of the two; every handler test asserts the guard ran BEFORE the write, so the divergence cannot hide a handler that writes-and-gets-overridden.
- Fake vocabulary is still inconsistent across files (`driven_plugs` vs `connected_plugs`, `node_type` vs `node_types`). Not #802's to fix.
