# Golem motion handoff — what Maya ships so the game can feel good

Decided 2026-08-15 with the user. Extends `2026-08-15-golem-articulated-design.md`
(#601). **Confirmed against the engine 2026-08-15** by the developer agent;
every open question below is now answered except breakage, which this revision
answers back.

The goal that drove this: the golem must **jump, land and take damage** feeling
natural but with a *wow* — momentum visibly translating through the body. This
document decides only what **Maya** owes the developer agent. Maya never
simulates and never judges feel.

## The finding that forced this

**A passive ragdoll cannot jump.** #601's 29 rigid bodies are right for damage
and for going down, but jumping and landing are *actuated* — a passive body has
nothing driving it. Physics-only reads as a thrown sack; animation-only destroys
the momentum translation that is the entire point. Decision: **hybrid** —
authored intent, physics reaction.

**Where the boundary sits, confirmed.** Sharper than active ragdoll: the golem's
root is a **kinematic `CharacterController` capsule** with hand-rolled velocity
and self-applied gravity, and that capsule stays the authority for where the
golem is — 22 PlayMode gates, the momentum ramp and the charge-jump curve all
ride on it. The articulated body is a **pose-driven visual and damage layer on
top**. Root motion kinematic, limbs pose-driven, physics for reaction.

There is no animation system in the project at all — no `Animator`, no clips,
`importAnimation = false` — and no `CharacterJoint`/`ConfigurableJoint` yet. So
poses-vs-clips, called "the consequential one", is settled: **poses**.

## Scale — the number that was never pinned

**1u = 0.8 m. Rest height 4.0 m, extended 4.64 m.**

Reasoning is from the sim, not taste: the world's atom is a 3 m cell = one
storey, and the golem must read as bigger than one storey (4 m ≈ 1.3). The grab
system already implies it — `HandoffClearance` 2.3 m is derived from holding a
full 3 m cell clear of the body, and under ~3.5 m the golem is hugging a building
rather than hefting a block.

The graybox capsule is currently 2.4 m and has never been scaled to the design;
growing it touches step height, camera framing and clearance math, all engine-side.

**Gravity is not absolute here**, which retires the worry behind the question:
the golem uses `GolemTuning.Gravity = 32` m/s² (~3.3 g) and never reads
`Physics.gravity`; debris runs ~2 g. Scale-dependent feel is a dial they turn
deliberately, because heavy things falling at 1 g look floaty. **Author masses as
measured volume × one density constant and do not compensate for scale.**

Their mass unit is abstract, not kg — anchored on a 3 m steel cell = 4.0, with
`GolemMass = 40` ≈ ten steel cells. Maya ships real volumes plus the density
constant; they rescale.

### Flagged: the reach numbers don't fit 4.0 m

`PunchReach = 3.5` and `GrabReach = 4` were described as "arm's length on a 4 m
creature". Against #601's own proportions they aren't. Arm total is
1.2 + 1.35 + 0.65 = **3.2u**, which at 0.8 m/u is **2.56 m** — not 4 m.

- `PunchReach` 3.5 m is reachable *with a lean*: shoulder at 3.2 m, pitching
  forward ~30° carries it ~0.8 m, giving ~3.36 m from the body axis. Fine.
- `GrabReach` 4 m is roughly **0.6 m optimistic** — it needs a lunge or a step,
  not just an arm.

Not a blocker and not a reason to overrule 4.0 m. Three ways out, theirs to pick:
accept that grab includes a lunge; raise the golem to ~6.25 m so 3.2u really is
4 m (but that's over two storeys, losing the 1.3-storey read they wanted); or
lengthen the arms past #601's silverback proportion. **Recommend: accept the
lunge.** This is exactly the class of error that only surfaces once scale is
pinned, which is why it was worth pinning.

## Orientation and units

- **+Z forward, Y-up, left-handed.** The blockout currently faces **+X**;
  rotating at source (Y = −90°) beats every consumer applying a yaw fix.
- **Metres native, transforms frozen.** Both previous deliveries were
  centimetre-authored, which Unity expresses as transform scale rather than baked
  vertices — 0.01 on the file root for heroes, on each leaf for the kit. No
  importer setting fixes it; all four combinations were measured. A metre-native
  golem is a one-constant change on their side and no wart. This is maya-mcp #600
  and it has now bitten twice.
- **State the pivot convention in the manifest.** Proximal joint centre is right,
  but the kit/hero rule is min-corner cell centre at y = 0, so a reader must not
  have to infer that the golem differs.

## The handoff contract

| | what |
|---|---|
| Geometry | 29 watertight chunks, metres, frozen, +Z forward |
| Rig | parent hierarchy + pivot per chunk at its **proximal joint centre** |
| Manifest | per-chunk mass, **sculpt** centre of mass, collider primitive(s), joint limits, breakage |
| Poses | **5** target poses as per-chunk rotations |

## The rig

Pelvis is root; hierarchy per #601. Gaskets parent to the **proximal** member of
their joint, so an elbow collar rides the upper arm and *lags* the forearm.

Pivot at the proximal joint centre is what makes a pose expressible: with the
pivot right a pose is a rotation; with it at the centroid every rotation also
translates the chunk and the limb comes apart. `center` is wrong for all 22
non-core chunks.

**#603 is the only hard blocker.** Measured on the blockout: `assemble` returns
`pivot: null` for all 29 single-part chunks.

## The poses — five

Authored as per-chunk rotations about the joint pivots. Not timed clips.

| pose | driven by | what it is |
|---|---|---|
| `rest` | idle | the modelled crouch, 4.0 m |
| `crouch` | `ChargeFraction` 0→1 over the 1.1 s wind-up | wind-up. Knees deeper, pelvis lower, torso pitched forward, arms trailing |
| `extend` | release | full push-off — the only pose reaching **4.64 m** |
| `air` | airborne | **added on engine advice.** `JumpMax = 58` with apex ~52 m means multiple seconds of flight; holding `extend` through that reads dead |
| `absorb` | `OnLanded(speed)`, depth scaled by impact speed | landing. Deepest knee flex, arms swung forward and down, feet planted |

All five map onto controller state that is already public and already tested.

**Damage still gets no pose.** Impulse at the contact chunk plus the joint limits
and mass distribution. A canned hit-react would flatten the variety that makes
damage read as real.

### The 4.64 m reveal

#601 gives the golem 0.8u of height it never shows standing still. Spend it on
`extend` and nowhere else, so the jump reveals something the player has never
seen. Free, already in the design, and the strongest wow lever available.

### The gaskets are the momentum-reading device

Ten collars, low mass, hung off the limb they collar, settling *after* that limb
has stopped. Ten of them still ticking a beat after the golem plants is the most
legible "that has weight" cue in the creature, and costs only correct parenting.

## Joint limits — swing/twist cones

Unity `CharacterJoint`. Per joint: `axis` and `swingAxis` as unit vectors in
chunk-local space, `swing1Limit`/`swing2Limit` (symmetric, degrees),
`lowTwistLimit`/`highTwistLimit` (asymmetric, degrees).

The knee falls straight out: axis along the hinge, `swing2Limit = 0`,
`swing1Limit` covering the flex arc, twist locked near zero, and the arc placed
so **neutral sits at the extreme**. No-hyperextension is then a consequence of the
asymmetric range rather than a special case.

Do not author per-axis min/max across all 29 to cover one joint. If a specific
joint genuinely needs asymmetric swing, name it and it gets a
`ConfigurableJoint`; cones are the cheaper solver and the common shape.

## Colliders — primitives, and they stay primitives

There is not one `MeshCollider` in the project; that is a deliberate position.
**The collider does not have to match the sculpt**, and there is precedent: the
building kit generates collision from the 3 m grid and lets render geometry
oversail its cell by up to 0.5 m, with 1,879 of 2,025 hero chunks declaring an
outset.

So: sculpt freely, and declare a primitive per chunk in the manifest — `box`
(half-extents + local offset + rotation), `sphere`, or `capsule`. A chunk that
cannot be one primitive declares **two or three**, not a convex hull. Compound
primitives beat a convex mesh, and Unity's convex `MeshCollider` caps at 255
triangles and cooks a hull that won't match the sculpt anyway.

**Ship the sculpt's centre of mass, not the primitive's.** They set
`Rigidbody.centerOfMass` explicitly, so a crude box with an honest COM behaves
correctly — which is exactly why COM is its own manifest field.

## Body budget — 29 stands, never merge

Measured: the debris system runs a 360-body ceiling with 141–325 peaks during a
whole-building cascade, worst frame 9.4–16.1 ms, 0 over-budget frames in ~2.3 M.
City scale idle worst frame 3.21 ms. 29 bodies is noise, and **there is only ever
one golem** — the asymmetric hunt is one golem vs N hunters, and hunters are men.

The cost that could bite is **contact pairs**, not bodies: 29 chunks brawling
inside a live rubble pile is a different profile from 29 in free air. Engine-side
to measure; the fix is a collision layer. **Do not merge chunks for performance —
merging changes the breakage story, and the breakage story is the game.**

## Breakage — answering the question they asked back

Yes, chunks detach. #601 already requires every chunk to be watertight
specifically so it can rip off, and the seam glow sits at chunk joins so
detachment reads for free.

**Split of authority: Maya ships the *ordering*, the engine picks the
*magnitude*.** Authoring 28 absolute impulses blind would be inventing numbers
with no way to check them; ordering is a design statement the modeller can
actually defend. So each joint carries `breakable` and a
`breakImpulseMult` — a multiplier on one engine-side constant, leaving them a
single dial.

| joint group | mult | why |
|---|---|---|
| gaskets (10) | **0.25** | first to go. Losing a collar exposes daylight between chunks — the cheapest, earliest "it's coming apart" read, at almost no mass cost |
| brow plate | **0.5** | see below |
| fist, foot | 0.6 | extremities, distal, high leverage |
| forearm, shin | 1.0 | the reference |
| upper arm, thigh | 1.8 | losing a whole limb should cost real effort |
| head | 4.0 | extreme only |
| pelvis, belly, chest girdle | **non-breakable** | the core is the body; losing it is not a damage state |

### The brow plate is the kill condition

The rune is an **aleph on the brow plate**. In the folklore the golem is animated
by *emet* (אמת, truth) and killed by striking the aleph to leave *met* (מת,
death). So detaching the brow plate **is** the canonical death, and the design
already put the rune there without anyone noticing that it hands us a weak point
for free.

Recommendation: brow plate breakable at 0.5, but placed high and forward so it is
hard to reach — a skill target, not an accident. And because #601 bakes seam
emission **per chunk from its rest distance to the rune**, losing the brow plate
should **kill every seam glow on the body**. The golem goes dark and drops. That
is the damage beat the whole material story has been paying for.

Flagged for the engine: this needs one rule — "brow plate detached → all golem
emission to zero" — and it is worth more than any hit-react animation.

## Verification

Per the live gate: measured numbers from a live Maya, not headless green.

| check | how |
|---|---|
| every pivot at its joint centre | query each chunk's pivot against the joint coordinate; 29/29 or fail |
| a pose is rotation-only | apply `extend`, assert no chunk's pivot translated |
| `rest` is 4.0 m, `extend` is 4.64 m | measure bbox height in each pose |
| metre-native | assert bbox height ≈ 4.0 with transforms frozen, scale 1.0 |
| faces +Z | assert the brow plate's centroid is at +Z of the skull's |
| mass ordering | fist > forearm, thigh > shin, from measured volumes |
| knee cannot hyperextend | limit data present, `swing2Limit == 0`, neutral at the arc extreme |
| every chunk has a collider primitive | 29/29 declared, none falling back to a hull |

## Tool gaps

1. **#603 per-object pivots — blocker.** Everything is downstream of it.
2. **#602 physics metadata — now required.** Mass, sculpt COM, collider
   primitives, swing/twist limits, breakable + `breakImpulseMult`.
3. **Pose export.** Rotations are authorable today; there is no path to get a
   named pose out.
4. **#600 metre-native + frozen transforms.** Has now bitten twice.
5. **No animation surface needed.** Confirmed — the project has none and wants
   none.

## Still open

- `GrabReach` 4 m vs a 2.56 m arm (above). Engine's call.
- Contact-pair cost of 29 chunks inside a live rubble pile. Engine-side measurement.
