# #812 — apply_texture_recipe re-applied on a slot strands its previous network

Redmine #812. The one item #804 left open: `orphans.py` gave assign_pbr,
setup_lighting and bake_textures a capture-then-sweep for the network a call
replaces, and `apply_texture_recipe` never got it. The probe
(`evals/recipe_orphans_probe.py`, findings in `evals/recipe_orphans_probe_812/`)
was written BEFORE any design, per the house rule.

## What the probe measured (Maya 2027, agent session on 9878, repo cwd)

**1. Every recipe twice on one slot.** The old node stays in the scene, wired
only to `defaultTextureList1` (ramp, noise, layeredTexture) or
`defaultRenderUtilityList1` (bump2d), and the new one is minted `mcpTex_ramp_001`
/ `mcpTex_noise_001` + `mcpTex_bump_001` / `mcpTex_layered_001` + `mcpTex_mask_001`.
`materialInfo1` moves with the connection: the displaced node loses it, so
`real_outputs` sees nothing real on the old node without a special case.

**2. A recipe over a slot assign_pbr mapped.** `clay_color_tex` AND
`clay_color_p2d` both strand — the p2d still feeds the file, the file feeds
only `defaultTextureList1`. Two hops up, the same walk pbr already does.

**3. The other direction.** assign_pbr over a recipe slot already sweeps the
ramp (`replaced: ["mcpTex_ramp"]`) — #804's SWEEPABLE_TYPES has noise / ramp /
layeredTexture. The fix is one-directional.

**4. A shared old ramp.** Hand-wired into a second shader (`other.color`), its
outputs after the re-apply are `[defaultTextureList1, other]` — a real output,
so the survivor rule applies unchanged.

**5. file_texture.** The recipe makes NO place2dTexture — one file node only,
`mcpTex_file`. Nothing to add for it.

**6. A scalar slot.** ramp on roughness twice: same strand, `outColorR` feeds
the scalar.

## What shipped

`handlers/texture_recipes.py`: `_node()` mints every recipe node under its
base name and records the claim; `apply_texture_recipe` captures
`orphans.upstream_network(shader.attr)` before the builder, sweeps it after
(excluding `created`), reports `replaced`, adds `survivor_warnings`, and
renames the new nodes back to the base names the swept ones held. The failure
sweep still deletes only `created`, so a failed recipe leaves the previous
network exactly as it was (gate phase 8 measured it live by refusing bump2d
creation mid-builder).

`tests/test_texture_recipes.py`: the fake's `listConnections` now honours the
direction flags (it answered SOURCES whatever was asked, so `real_outputs` read a
bump2d's noise as a consumer and the sweep could not be modelled), and gained
`rename` on the pbr fake's suffix-on-collision model. Eight tests in
`TestReApplyingARecipeSweepsWhatItReplaces`.

`src/maya_mcp/schemas.py`: `TextureRecipeResult.replaced`. `docs/protocol.md`:
the row and a sentence in the #804 paragraph.

## Gate

`evals/recipe_orphans_live.py` — **20 / 20** on 9878 pid 42332 (repo cwd, phase
0 asserts the working tree is what answered). Log in `evals/recipe_orphans_live/`.

## Suite

See the ticket's closing note for the junit numbers.
