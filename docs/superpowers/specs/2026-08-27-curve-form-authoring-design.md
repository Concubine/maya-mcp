# Curve-driven form authoring — design (#768)

Date: 2026-08-27. Brainstormed with the user; all three open questions from the
ticket were decided explicitly. Investigation behind this design:
`docs/superpowers/plans/2026-08-26-modelling-vocabulary-gap.md` (committed
7e38357) — read it for the measurements; this document only records decisions.

## Problem, in one paragraph

The toolbox's entire geometry vocabulary starts from a primitive and pushes it
around; it cannot *describe a silhouette* and have Maya build a surface through
it. Curve-driven construction is the parametric half of modelling and the half
best suited to an author with no eyes: a curve is a short list of numbers,
which an LLM can write precisely and a gate can assert exactly.

## Decisions (each was an open question in the ticket)

1. **Constructors: the trio** — sweep, revolve, loft. All produce **poly**
   output; the NURBS-producing ones (`revolve`, `loft`) are tessellated via
   `nurbsToPoly` internally. `sweepMeshFromCurve` is poly-native.
2. **Curve specification: inline through-points.** Each kind takes plain
   number lists inline, in its natural frame, and curves INTERPOLATE the given
   points (edit points, not CVs) — the surface passes through what the caller
   wrote, so both the caller and the gate can reason from the same numbers.
   No persistent curve objects on the tool surface; construction curves are
   built, used, and deleted inside the call.
3. **Gate: station conformance + pipeline composition.** Numeric, in the
   `measure_clip` style — worst deviation of the produced mesh from the
   authored stations, as a fraction of form size, asserted within a stated
   tolerance and reported back. Plus manifold/budget checks and proof that the
   result composes with `boolean_op`, `uv_atlas`, and `bind_skin`.

Rejected during brainstorm: first-class curve objects (adds lifecycle and
calls, against the one-call-one-form grain shown by `assemble`); raw CVs +
degree (a control hull — the surface does not pass through the numbers, so a
blind author cannot predict the silhouette it wrote); structural-only and
rendered-silhouette gates (the first cannot tell flowing from mangled, the
second is pixels where this repo wants numbers).

## Tool surface

One new tool, **`maya_create_curve_form`**, following the `deform`/`sculpt_ops`
precedent of one tool per vocabulary family.

Common params:

| param | meaning |
|---|---|
| `kind` | `"sweep"` \| `"revolve"` \| `"loft"` — required |
| `name` | requested node name, claimed via the standard naming path |
| `resolution` | tessellation control, `{along, around}`, defaulted per kind; checked against the existing face budget before building |
| `cap_ends` | default `true`; closes open ends (sweep tube ends, loft first/last sections, partial revolves) |
| `translate` / `rotate` / `scale` | standard placement, as `create_primitive` takes them |

Per kind:

* **`sweep`** — `path`: list of ≥2 3D points the spine passes through.
  `width`: a single number (constant) or a ramp — list of `[t, width]` pairs
  with `t` ∈ [0,1] along the path; this taper ramp is what turns one path into
  horns, limbs, vines, straps. Optional `twist` ramp, same shape. Optional
  `profile_sides`: default circle; small ints give square straps / n-gon
  pipes. Implemented with `sweepMeshFromCurve`.
* **`revolve`** — `profile`: list of `[radius, height]` pairs in the
  half-plane (radius ≥ 0), revolved about Y by default (`axis` overridable),
  optional `degrees` < 360 for partial shells. Heads, vases, domes, tapering
  limbs. Implemented with `revolve` → `nurbsToPoly`.
* **`loft`** — `sections`: list of cross-section rings, each a closed ring of
  3D points, **same point count per ring** — that constraint keeps the
  section-to-section correspondence predictable for a blind author. Torso,
  tail, horn, hull. Implemented with `loft` → `nurbsToPoly`.

Top-level params validated with `dispatcher.require_known_keys` from day one
(#764's lesson), with synonym entries for the obvious traps (`points`→`path`,
`taper`→`width`, `curve`→`path`/`profile` per kind).

## Internals

New handler `maya_plugin/handlers/curveform.py` plus a pure-math module
`maya_plugin/handlers/curveform_math.py` (no Maya imports — the
`sculpt_math`/`arraymath` pattern): point-list and ramp validation, station
computation, expected-position math. The headless suite covers everything
except Maya's own surface construction.

Whole-call validation before any scene touch, `assemble`-style: a refused call
leaves nothing behind. Per-call pipeline:

1. validate everything (pure) →
2. build interpolating curve(s): `cmds.curve` with edit points, degree 3
   (degree 1 for 2-point paths) →
3. construct (`sweepMeshFromCurve` / `revolve` / `loft`) →
4. tessellate to poly where the result is NURBS →
5. cap ends →
6. delete history and construction curves (no orphan nodes) →
7. claim name, register with the ledger, run the standard meshcheck.

Limits, stated in error messages: max points per curve/ring, max sections,
face budget via the existing `check_face_budget`.

**Self-measurement in the result.** After the build, sample the mesh at each
authored station and report the worst deviation as a fraction of the form's
size — the `measure_clip` convention (thresholds are fractions, and are
reported back). Tessellation resolution is what controls this number, so a
caller can see when its resolution is too coarse for the curve it drew.

## Error handling

Every refusal names the param and carries a hint with a working example, house
style. Refused up front: duplicate consecutive points, negative radii in a
revolve profile, rings with mismatched point counts, ramps with `t` outside
[0,1] or unsorted, `kind` missing or unknown, both a constant and a ramp where
one is expected.

## Testing

* **Headless** (pytest): `curveform_math` in full — validation refusals,
  ramp parsing, station math; handler param validation via the dispatcher.
* **Live gate** (`evals/curve_form_live.py`, on the disposable agent Maya at
  9878 — never the user's 9877): author three canonical forms —
  a vase (revolve), a tapered horn (sweep with a width ramp), a torso (loft
  through 4 rings) — and assert: station conformance within the stated
  tolerance, closed manifold, quad-dominant, face budget respected. The
  tolerance VALUE is not guessed in this spec: it is chosen during
  implementation by measuring the three canonical forms at default resolution
  (the #773 method — pick the threshold that discriminates, then state it). Then the
  composition half: boolean the horn into a cube, uv_atlas the vase, bind_skin
  the torso to a 3-joint chain — all must keep working on curve-built meshes.
  One `render_sheet` at the end for eyes-on confirmation that the silhouettes
  flow.

## Out of scope (decided)

* `wire` / `softMod` curve deformers — rank #3 in the analysis; a follow-up
  ticket if wanted, not part of #768.
* `birail1`, `curveWarp`, `polyChamferVertex` — measured absent in this
  Maya 2027; do not plan around them.
* The subdivision-cage vocabulary — that is #769.
