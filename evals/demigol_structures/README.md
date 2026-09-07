# demigol_structures — TEST FIXTURE, not the asset

**The asset lives in `D:\devel\3d-assets\demigol\demigol_structures\`** (moved 2026-09-07,
Redmine #870, with its full revision-3 README, the four beauty renders and the per-chunk
manifest). Edit it there.

What remains here is the minimum the headless suite needs, pinned as regression input:

| File | Read by |
|---|---|
| `tower.fbx`, `block.fbx`, `slab.fbx`, `stump.fbx` | `tests/test_delivery_units.py:27-29` parametrises over all four heroes (`test_every_delivery_declares_metres`, `test_hero_is_metre_true`) |
| `tower.fbx` | also gated by `evals/fbx_probe_live.py:54` |

`evals/fbx_probe_live.py:183` hard-fails on a missing committed artifact instead of skipping, so
do not delete these.

**The sibling constraint applies here too.** Each hero FBX embeds `..\demigol_kit\kit_albedo.png`
(plus `kit_mask`, `kit_normal`) and its manifest declares `material.shared_with: "demigol_kit"`.
That is why `evals/demigol_kit/` keeps its three atlas PNGs, and why the asset copies in 3d-assets
sit side by side under a shared `demigol/` parent. Never move one without the other.

`evals/demigol_structures.py` rebuilds this folder from `_HERE` and regenerates the kit atlas maps
on the way; a generator run recreating files here has not undone the move.

Do not add art to this folder.
