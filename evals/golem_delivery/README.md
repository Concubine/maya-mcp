# Golem — one articulated 4 m colossus

**33 nodes (29 chunks + 4 tracer emitters), 14,130 triangles, 4.02173 m tall,
metre-native with identity scales.** Built through the MCP tools for maya-mcp
#601; packaged under #641 against the handoff design in
`docs/superpowers/specs/2026-08-15-golem-motion-handoff-design.md`.

| file | what |
|---|---|
| `golem.fbx` | the delivery. One tree rooted at `golem_C_pelvis`, translate+rotate only |
| `manifest.json` | per-chunk pivot, collider box, volume, mass share, centre of mass, tri count, material |
| `golem_metre.mb` | the Maya scene the FBX was written from, after the bake |
| `chunks.json` | the raw measurements taken out of that scene; the manifest is derived from it |
| `hero_*.png` | Arnold renders (front / side / three-quarter) |

Rebuild the manifest and re-run the gate:

```bash
python evals/golem_delivery_package.py
```

## The scale decision

The handoff spec pinned two things that could not both hold as built: **1 u =
0.8 m with a 4.0 m rest height**, and **metre-native, transforms frozen**. The
golem was modelled at **5.027162 units**, which is 4.02 m under the first rule
and 5.03 m under the second.

Settled by the user this session: **bake the 0.8 into the vertices.** The
delivered file is metre-native — 1 unit is 1 metre, every node scale is
identity — and it stands **4.02173 m**, which is the pinned rest height. Nothing
carries a conversion factor, so there is nowhere for a unit error to hide.

The bake was not a freeze. `makeIdentity` on this tree would have wrecked it,
and the reason is recorded in `evals/maya_export.py`: freezing scale on a group
bakes each child's world position into its vertices. Instead every node's world
translation was scaled by 0.8, every pivot with it, scales set to identity, and
each mesh's vertices recomputed from its **new** world matrix — which also
absorbs the shear that 21 non-uniformly scaled parents used to impose on their
rotated children. Measured afterwards, in Maya: every world vertex within
**1.2e-7** of 0.8x its old position, every pivot within **8.9e-16**, and the
height ratio 0.800000001.

## The gate

The units claim is asserted **against the bytes**, never against the scene.
`delivery_units.check_rig_delivery` opens the .fbx with no Maya in the loop,
composes the parent chain, and requires the height to measure 4.02173 m, one
root, zero non-identity node scales, and a header declaring metres. It runs in
`evals/golem_delivery_package.py`, which refuses to write a manifest for a file
that fails, and again in `tests/test_delivery_units.py` on every test run.

The demigol gate could not be reused as-is. It reads per-vertex magnitude
against a ceiling, and **a rig defeats that**: every chunk here is under a metre
whatever the unit, so a centimetre golem would pass it. The height only exists
once the tree is composed, so the reader learned to compose one.

It earned its keep immediately: Maya wrote `UnitScaleFactor 1.0` — centimetres —
into a file whose vertices are metres. Same self-contradiction as #629, caught
on the artifact and corrected there (`fbx_probe.set_unit_scale_factor`).

## The rig

One tree, root `golem_C_pelvis`, six deep at the deepest. **Every pivot is its
chunk's proximal joint centre in world space**, which differs on purpose from
the demigol kit and hero rule (min-corner cell centre at y = 0) — a reader must
not have to infer that.

Poses are **not** in this delivery. The spec asks for five target poses as
per-chunk rotations; this is the rest pose only.

Mass ships as **volume and share**, not kilograms: total 5.2657 m³, and each
chunk's `mass_fraction` of it. The engine's mass unit is abstract (a 3 m steel
cell = 4.0), so a share is the part that survives their rescale.

## Three measurements worth arguing with

- **Arm reach is 2.5528 m**, shoulder pivot to furthest fist vertex. The spec's
  own arithmetic predicted 2.56 and the geometry agrees, so its flag stands:
  `GrabReach = 4` is ~1.4 m past the arm and needs a lunge or a step.
- **The joins fail under SSAO.** Gasket collars show almost no contact
  darkening; they read as balls threaded on a limb. A model note, not a tool
  note, and unchanged by this package.
- **The body seam glow is invisible** at its measured emission (0.013–0.315)
  against a lit body. Left at the measured values rather than quietly dialled
  up. The visor tracer, which is the light that reads, is four emitters parented
  under `golem_C_brow` — detach the brow and the light goes with it.

## Known limits

- **Textures are not embedded.** The FBX carries material names only; the maps
  live in the Maya scene beside it.
- The renders were made **before** the bake. The bake is a uniform 0.8 world
  scale, verified to 1.2e-7, so they are the same image of the same shape at a
  different number of metres — but they are not fresh frames of the delivered
  file.
- There is **no MCP tool that exports anything** (maya-mcp #642). This package
  cost an `execute_python` escape to write, as every delivery before it has.
