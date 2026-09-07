# structures — TEST FIXTURE, not the asset

**The asset lives in `D:\devel\3d-assets\structures\`** (moved 2026-09-07, Redmine #870, with the
four Maya scenes, the four renders and the manifest). Edit it there.

What remains here is the minimum the headless suite needs, pinned as regression input:

| File | Read by |
|---|---|
| `clock_tower.fbx` | `tests/test_fbxbytes.py:157`, the #645 regression — asserts the height Maya measures, 37.10 |
| `clock_tower.fbx`, `gate.fbx`, `rotunda.fbx`, `water_tower.fbx` | `evals/fbx_probe_live.py:48-51` COMMITTED list |

`evals/fbx_probe_live.py:183` hard-fails on a missing committed artifact instead of skipping, so
do not delete these.

Notes:

- This is the **older centimetre-convention run** (2026-08-14). Its manifest records
  "maya default (cm); 1 unit = 1 metre if imported at 100x" — which is exactly what makes it a
  stable regression fixture. Do not "fix" the units.
- `evals/structures/rotunda.fbx` is a real gated asset and is **a different thing** from the
  `evals/rotunda/` folder, which is twelve iteration renders from a design probe (#587).
- The six Maya auto-checkpoints that used to sit in `checkpoints/` were removed with the move and
  are now git-ignored; `evals/structures.py` rebuilds this folder from `_HERE` if re-run.

Do not add art to this folder.
