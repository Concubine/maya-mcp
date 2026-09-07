# demigol_kit — TEST FIXTURE, not the asset

**The asset lives in `D:\devel\3d-assets\demigol\demigol_kit\`** (moved 2026-09-07, Redmine #870,
with its full revision-2 README, contact sheet, tiling proof and manifest). Edit it there.

What remains in this folder is the minimum the headless suite needs, pinned as regression input:

| File | Read by |
|---|---|
| `demigol_kit.fbx` | `tests/test_delivery_units.py:26` (five tests parse it without Maya) and `evals/fbx_probe_live.py:53` |
| `kit_albedo.png`, `kit_mask.png`, `kit_normal.png` | the FBX embeds them as same-folder relative names, and the four `demigol_structures` hero FBX embed them as `..\demigol_kit\*.png` |

`evals/fbx_probe_live.py:183` does `if not os.path.isfile(path): fail(...)` over its COMMITTED
list — it dies loudly on a missing artifact rather than skipping, so do not delete these.

Two warnings:

- **This is the SUPERSEDED revision 2.** The live kit is revision 4 in `D:\devel\maya-mcp-art`
  (branch `kit-revision-4`), and the Demigol game vendors its own copy under
  `D:/devel/Demigol/art/evals`. Do not treat this FBX as current art.
- **The generator will repopulate this folder.** `evals/demigol_kit.py` builds its OUT_DIR from
  `_HERE` and calls `os.makedirs(exist_ok=True)`; `evals/demigol_structures.py` additionally calls
  `kit.build_atlas_maps(KIT_DIR)`, which regenerates the three atlas PNGs from numpy. A generator
  run recreating files here has not undone the move — the asset home is still 3d-assets.

Do not add art to this folder.
