# NOTES — lizard build

## What I built

A single rigged, textured lizard, **399.6 mm** nose to tail tip (the scene is metre-native:
1 Maya unit = 1 m, verified through the FBX export gate).

| | |
|---|---|
| Meshes | 6 — `lizard_body`, `lizard_jaw`, `lizard_frill_L/R`, `lizard_eyes`, `lizard_mouth` |
| Triangles | 45,024 total (body 34,304) |
| Skeleton | 34 joints — root at the hips, 4 limb chains, 6-joint tail, jaw, 2 frill joints |
| Skinning | 6 skinClusters, max 4 influences/vertex, 0 unweighted vertices |
| UVs | shared 2×2 atlas — patch 0 body+jaw, 1 frills, 2 eyes, 3 mouth; all inside their patch |
| Materials | 5 standardSurface, plus a procedural `noise_bump` grain on the body |
| Articulation | jaw opens 34°, frill folds/flares ±72°, spine and tail bend, feet plantable by IK |

Deliverables in this folder:

- `lizard.ma` — the scene, saved in bind pose
- `turntable.png` — 8-azimuth contact sheet
- `hero.png` — Arnold, 1400², 6 AA samples, three-point + sky dome, ground contact shadow
- `lizard.fbx` — 2.09 MB, FBX 7700, skins and bind pose included, 0 unweighted vertices
- `pose_idle.png`, `pose_threat.png` — the two required poses

### Time

About **80 minutes** of build (12:47 → 14:06), across two sessions — the first ended on a dead
MCP bridge, the second did the work. That excludes environment setup, which was already done.

---

## What fought me

**Joint orientation — the expensive one.** `maya_create_skeleton` orients bones
**X-down-the-bone**. I assumed Y. So `jaw: [34, 0, 0]` — which reads like "open the jaw 34°" — is
a pure *twist* about the bone's own axis and moves nothing. It reports `applied: 1` and a
plausible displacement (the jaw *mesh* rotates in place), so it looks like it worked. I rendered
a whole threat display with a shut mouth before I sampled `jaw_end`'s world position across six
candidate rotations and found that **local Z** is the hinge. Nothing in the tool descriptions
states the convention; the only reliable way to find it is to rotate a joint and measure where
its child lands.

**Non-identity transform scale hiding in a bound mesh.** `lizard_mouth` still carried
`scale = (0.021, 0.009, 0.036)` from the primitive that made it — never frozen, and invisible in
every measurement I had taken, because bounding boxes are reported in world space. Two attempts to
reshape it with `cmds.scale(..., r=True)` *multiplied* that scale and threw the mesh 13 mm out of
position while I tried to work out why a factor of 0.5 was making something bigger. Fixed by
freezing first, then remapping vertices onto an explicitly measured target box. It would also have
**refused the FBX export** — the exporter gates on non-identity scale — so it had to be found.

**Unbinding does not restore the bind pose.** I unbound `lizard_body` while the threat pose was
applied and the mesh froze *in that pose* — a permanently curled tail, baked into the asset. It
was only caught because a downstream shell filter dropped 35 shells instead of the expected 34
(the curled tail tip had crossed the threshold). `maya_reset_pose` **before** unbinding is
mandatory, and nothing warns you.

**The frill took four designs.** A full flat disc read as a CD. A fan of rounded petals read as a
daisy. A fan of flat-capped rib cylinders read as a cog wheel. What finally worked is a solid
half-disc membrane, boolean-cut at the midline, with four ellipsoid ribs laid on the surface —
membrane first, ribs after.

**Limb joints were squares.** Flagged by the client, correctly. The limbs were flat-capped
`cylinder` primitives butted end to end — a hard faceted step at every bend — and the palm was
literally a `cube`. Rebuilt with spheres at shoulder/elbow/wrist/hip/knee/ankle and an ellipsoid
palm pad. That cost a full rebuild of everything downstream: split, merge, UV, material, bind,
weights, poses, renders.

**The muzzle was three stacked blobs.** From the top it read as a caterpillar, not a snout. Fixed
by extracting the 7 head shells, boolean-unioning them into one watertight surface (verified: 0
border edges, 0 non-manifold), `polyRetopo`-ing to 2,964 tris, then relaxing the snout vertices
with `polyAverageVertex`.

**Bind method matters.** `geodesicVoxel` produced garbage — only leaf joints owned vertices, and
25 of 34 joints owned nothing at all. `closestDistance` gave a sane distribution immediately.

**Frill and jaw joints owned body vertices**, so flaring the frill dragged the skull with it. I had
to zero those four influences on the body's skinCluster and re-verify. Body displacement is now
exactly **0** when the jaw opens.

**The mouth interior escaped the mouth.** Weighted as one blob on the jaw hinge, it swung out past
the lips and rendered as a berry stuck to the face. Fixed by weighting it as a *gradient by height*
— roof to `head`, floor to `jaw` — so it opens as a wedge, plus shrinking it and killing its
specular highlight.

---

## What I wanted and could not get

**A camera angle of my own choosing.** `maya_set_camera` exists, but `maya_render_scene`'s `angles`
is a closed enum of five canonical directions, and `angles: ["current"]` **ignores the active
camera** and silently falls back to `three_quarter`. Every render here is from one of five fixed
directions. I wanted a low, near-ground hero shot looking slightly up at the flared frill;
`three_quarter` looks *down* at 28°, which is the least flattering choice for a threat display.
The hero is the best of five options, not the shot I wanted.

**A tighter turntable.** `maya_capture_turntable` has no zoom. Orbit distance is fixed to fit the
subject at its widest azimuth, so a long thin animal is well framed at 90°/270° and small with big
margins at 0°/180°. The sheet is legible but loose.

**Toe tips under 400 faces.** `divisions` floors at 1, and a `divisions: 1` sphere is 400 faces.
Twenty toe-tip spheres would have been 16k triangles of nothing. I redesigned the toes as single
*tapered ellipsoids* — rounded at both ends, one primitive per toe instead of two. Better result
and half the cost, but forced by the floor rather than chosen.

**Painted texture maps.** The namespace offers procedural recipes (`noise_bump`, `ramp_gradient`,
`layered_mask`, `file_texture`) but no way to author an image. So the skin is one flat albedo plus
a procedural bump — no dorsal banding, no countershading, no scale detail beyond the grain. This
is the single biggest gap between what is here and "portfolio quality".

**A single watertight body.** The body is 79 intersecting shells united into one object, not one
continuous skin. It renders, skins and exports correctly, but it is not what you would ship.

**No unbind tool, and no way to drop a single influence.** `maya_bind_skin`'s own error tells you
to "unbind first" and nothing in the namespace unbinds. Both operations went through
`maya_execute_python` (`skinCluster -e -unbind`, `skinPercent -transformValue 0`).

---

## Surprises — tools that did something other than their description implied

**`maya_mesh_cleanup` created 82 non-manifold edges where there were 0.** Its vertex merge is
unconditional, and it welded the exactly-coincident butt-jointed caps of my tail segments into a
non-manifold mess. A cleanup tool made the mesh dirtier. Undone with `maya_undo(1)`; I froze
transforms with `makeIdentity` + `polyNormal` + delete-history instead and never used it again.

**`maya_capture_viewport(shading="textured")` renders nearly unlit.** The description says textured
"reveals texture/bump networks" and that `smoothShaded` hides them, so it reads as the mode to
judge a finished model in. In practice it came back so dark the model was barely visible — at both
`lighting="scene"` and `lighting="default"` — while plain `smoothShaded` was correctly lit. The
turntable here is `smoothShaded` for that reason.

**`maya_render_scene`'s `isolate` controls visibility but not framing.** Isolating the lizard still
framed the whole scene and the subject came back as 0.95% of the pixels. `target` is what frames.
They are independent, and you usually need both.

**`maya_array` mirror bakes the source's rotation into the copy's vertices** rather than carrying a
mirrored transform. The two frill lobes therefore need *different* rotation values on their joints
to stay symmetric, which reads as a rigging bug until you know why.

**`maya_boolean_op` returned `tris: 0`** — consuming the entire input — when `a` was a 5-shell
self-intersecting combined mesh, and reported success. Booleaning single closed shells pairwise
works reliably; feeding it a combined multi-shell object does not.

**`maya_assemble`: single-part chunks are named after the *part*, not the chunk**, and are not run
through combine at all — which also means the `pivots` map silently does nothing for them.

**`maya_combine(pivot="keep")` returned the world origin** rather than either input's pivot.

**`maya_create_skeleton` with a forced `orient: [0,0,0]` moved `jaw_end` off the position I asked
for.** Forcing the orient and specifying the position are not independent.

**Redmine `create_issue` silently ignored `status_id`** — it needed a follow-up `update_issue`.

Not the MCP's fault, but worth recording: **`polyInfo` has no boundary-edge flag.** `-be` is
invalid; counting border edges needs `polySelectConstraint(mode=3, type=0x8000, where=1)`.

---

## Honest assessment

What I would defend: the silhouette reads as a lizard from all eight turntable azimuths, which is
the failure mode the brief called out. The rig is measurably clean — 0 unweighted vertices, weight
sums within 2.2e-16, and the body provably does not move when the jaw opens or the frill flares.
The limb articulation is real now. The threat display works: the frill genuinely flares, the jaw
genuinely opens, and the feet stay planted through IK.

What I would not: **45k triangles is roughly 4× what this asset should cost.** The joint spheres
and toe ellipsoids are 400 faces each because that is the floor, and nothing was retopologised
except the head. A production pass would remesh the body to 8–12k. The skin is a single flat colour
with a procedural bump and no painted maps. The folded frill still reads as two orange fins at the
neck rather than lying flush against it. The mouth is a dark lozenge, not a modelled cavity — no
teeth, no tongue. And the hero render is from a camera angle I did not choose.

---

# ADDENDUM — taking it into Unity

Done after the fact, testing the FBX in Unity 6000.0.47f1 (URP). This section exists because
the test found a real defect in what I had already delivered.

## The delivered FBX was broken, and the export gate passed it

Imported into Unity, every joint below `root` arrived with **localScale = 100**, compounding down
the chain to 100^7 — bones landed at 1e10 world units and the skinned mesh exploded to 1e14 across.

Cause: the Maya scene's `linearUnit` is **cm**, the FBX declares metres, and all 34 joints had
Maya's default **`segmentScaleCompensate = True`** with 33 `inverseScale` connections. The exporter
writes a compensating scale of 100 on each joint and expects the consumer to cancel it via segment
scale compensate. Maya does. **Unity does not.** So it multiplies instead.

Fix: disconnect `inverseScale`, set `segmentScaleCompensate = 0` on all 34 joints, re-export.
The mesh did not move — bbox drift was **0.000e+00** — confirming it was purely an export artifact.
After the fix the baked world size in Unity is **(0.1756, 0.0884, 0.3996)**, matching Maya to four
decimals, with `min.y = 0.0000` so the feet sit exactly on the floor.

**This is the surprise worth flagging.** `maya_export_fbx`'s description says it is "refused if any
node carries a non-identity scale", and that everything it reports is "read back out of the file,
not queried from the scene". It passed this file — twice, before and after the fix, with byte-identical
verdicts apart from size. Whatever it checks, it is not the joint scales the engine actually sees.
The gate's whole promise is catching wrong-sized assets that "render correctly and ship anyway", and
this is exactly that defect, shipped anyway. A joint-scale check belongs in that gate.

## Other Unity-side findings

**`import_model_file` scale-normalizes by default.** It set `globalScale = 2.502349` and
`useFileScale = false` — precisely 1/0.3996 — resizing my 40 cm lizard to exactly 1 Unity unit.
`target_size` is documented as the scale-normalize control, so omitting it reads like "don't
normalize"; it actually means "normalize to 1". Correct import needs `globalScale = 1`,
`useFileScale = true`.

**`animation_type: "generic"` does not produce an Avatar.** It sets `animationType = Generic` but
leaves `avatarSetup = NoAvatar`, so the model imports with a rig and no Avatar — and a Generic
Animator with no Avatar drives nothing. Silent: no error, no warning, just a creature that will not
move. Needs `avatarSetup = CreateFromThisModel`.

**`maya_export_fbx` does export animation, undocumented.** It has no animation parameter and never
mentions animation in its output. After keyframing 17 joints in Maya (408 keys) the file grew 70 KB
and Unity found `Take 001`, 5.83 s @ 24 fps, 110 curves. Useful, but you would not know from the
tool that it was an option.

## Why the animation was authored in Maya, not Unity

I first tried building the clip in Unity directly, and could not reproduce the frill flare: no
single-axis rotation of `frill_L` matched Maya's flared bounds, in either composition order
(`rest * euler` or `euler * rest`), swept at 4-degree steps over all three axes. Best error 0.011
against a 0.048 target.

Rather than keep guessing at the handedness conversion, I keyed the animation in Maya — where I had
already measured every axis — and let the FBX carry it. That sidestepped the conversion entirely.

One correction to my own reasoning: I initially read a bbox mismatch at frame 48 as a broken clip.
It was not. I was comparing Maya with **only** `frill_L` rotated against Unity at a frame where the
whole spine and neck are also reared — different poses, so different bounds. The screenshot settled
it in one look, where three rounds of numeric comparison had only misled me. Capture the image.

## Result

`ThreatDisplay`, 140 frames @ 24 fps, looping: idle → rear up, frill flare, jaw open → hold with a
counter-swung tail → settle. Verified live in Play mode with the bones moving off their rest
positions, materials rebuilt in URP (Maya's shaders do not cross the FBX boundary), and captured at
both ends of the loop.

The lizard moves.
