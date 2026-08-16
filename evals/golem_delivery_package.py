"""Compose the golem delivery manifest, and refuse to write one the FBX fails.

Unlike the demigol generators this does not build anything: the golem was built
through the MCP tools by hand (maya-mcp #601), so the measurements come from
`chunks.json`, which was written out of the live scene after the metre bake.
Everything derived - fractions, totals, extents - is computed here rather than
typed, so the manifest cannot drift from the numbers it was made from.

The gate at the end is the point. It reads the delivered .fbx BYTES with no
Maya in the loop, because the unit defect of maya-mcp #629 is written by the
exporter and is absent from the scene.
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import delivery_units          # noqa: E402
import fbx_probe               # noqa: E402

OUT_DIR = os.path.join(_HERE, "golem_delivery")
FBX = os.path.join(OUT_DIR, "golem.fbx")
CHUNKS = os.path.join(OUT_DIR, "chunks.json")
POSES = os.path.join(OUT_DIR, "poses.json")
MANIFEST = os.path.join(OUT_DIR, "manifest.json")

ROOT = "golem_C_pelvis"
# The tracer bars are geometry, not destruction chunks: they are the emitters of
# the visor scan and they hang off the brow, which is what makes "detach the
# brow and the light dies" a physical fact rather than a scripted rule.
TRACER = "golem_C_tracer_"

# Modelled height x the pinned metres-per-unit. Both halves are stated because
# the discrepancy between them is what this delivery had to settle: the motion
# handoff spec pinned 1u = 0.8 m and a 4.0 m rest height, and the built golem
# measured 5.027162 units, which is 4.02 m under that convention and 5.03 m
# under the metre-native one the same spec also asks for.
MODELLED_UNITS = 5.027162
METRES_PER_UNIT = 0.8


# Break ordering is the design statement Maya can defend; the engine owns the
# magnitude. Straight from the handoff spec's table, except `shoulder`, which
# the spec does not list - it is the pauldron the whole arm hangs from, so it
# is priced with the upper arm and flagged as an addition.
BREAK = [
    ("_gasket", 0.25, "first to go - daylight between chunks is the earliest "
                      "'it's coming apart' read, at almost no mass cost"),
    ("_brow", 0.5, "the kill condition: the brow carries the four tracer "
                   "emitters, so losing it puts the visor light out"),
    ("_fist", 0.6, "extremity, distal, high leverage"),
    ("_foot", 0.6, "extremity, distal, high leverage"),
    ("_forearm", 1.0, "the reference"),
    ("_shin", 1.0, "the reference"),
    ("_upperarm", 1.8, "losing a whole limb should cost real effort"),
    ("_thigh", 1.8, "losing a whole limb should cost real effort"),
    ("_shoulder", 1.8, "NOT in the spec's table - the pauldron the arm hangs "
                       "from, priced with the upper arm"),
    ("_head", 4.0, "extreme only"),
]
UNBREAKABLE = ("_pelvis", "_belly", "_chest_girdle")

# Every hinge in this rig turns about LOCAL X - measured, not assumed: each
# joint's local X maps to world X in the rest pose. Ranges are the arc the five
# poses actually use, widened to a defensible limit, in absolute local degrees.
JOINT = [
    ("_pelvis",  (0, 0),      "root - the controller moves this; it has no "
                              "parent joint to limit"),
    ("_thigh",   (-70, 10),   "hip"),
    ("_shin",    (0, 110),    "knee - 0 IS straight, so no-hyperextension is "
                              "the range's own edge rather than a special case"),
    ("_foot",    (-50, 10),   "ankle"),
    ("_upperarm", (-120, 100), "shoulder - ASYMMETRIC and wide: crouch parks "
                               "the arm at +95 and extend throws it to -115, a "
                               "210 degree swing. Per the spec this is the "
                               "named joint that earns a ConfigurableJoint"),
    ("_forearm", (-100, 0),   "elbow - flexes one way only"),
    ("_fist",    (-30, 30),   "wrist"),
    ("_head",    (-25, 25),   "neck"),
    ("_brow",    (-8, 8),     "brow plate, near-rigid on the skull"),
    ("_belly",   (-30, 15),   "waist"),
    ("_chest_girdle", (-30, 15), "chest"),
    ("_gasket",  (-10, 10),   "a collar, not a joint - it rides the proximal "
                              "member and lags it"),
    ("_tracer_", (0, 0),      "rigid to the brow"),
]


def _lookup(table, name, default=None):
    for key, *rest in table:
        if key in name:
            return rest
    return default


def build_manifest(chunks, poses):
    lo = [min(c["bbox_min_m"][i] for c in chunks.values()) for i in range(3)]
    hi = [max(c["bbox_max_m"][i] for c in chunks.values()) for i in range(3)]
    volume = sum(c["volume_m3"] for c in chunks.values())
    body = {k: v for k, v in chunks.items() if not k.startswith(TRACER)}

    out = []
    for name in sorted(chunks):
        c = chunks[name]
        mult, why = _lookup(BREAK, name, [None, None])
        rng, joint_note = _lookup(JOINT, name, [(0, 0), "unclassified"])
        breakable = not any(k in name for k in UNBREAKABLE) and mult is not None
        out.append({
            "joint": {
                "hinge_axis_local": [1, 0, 0],
                "hinge_range_deg": list(rng),
                "rest_deg": poses["rest"]["rotations_deg"][name],
                "twist": "locked near zero",
                "note": joint_note,
            },
            "breakable": breakable,
            "break_impulse_mult": mult if breakable else None,
            "break_note": (why if breakable else
                           "the core is the body - losing it is not a damage "
                           "state" if any(k in name for k in UNBREAKABLE) else
                           "detaches with golem_C_brow, never on its own"),
            "name": name,
            "parent": c["parent"],
            # The rig. Proximal joint centre, world space, in the rest pose -
            # NOT the min-corner cell centre the demigol kit and heroes use.
            "pivot_m": c["pivot_world_m"],
            "bbox_min_m": c["bbox_min_m"],
            "bbox_max_m": c["bbox_max_m"],
            "collider": c["collider"],
            "volume_m3": c["volume_m3"],
            # Mass is authored as volume x one density constant, so what a
            # consumer needs from Maya is the SHARE. Multiply by whatever
            # GolemMass is on their side and the distribution is right at any
            # scale, which is what the handoff spec asked for.
            "mass_fraction": round(c["volume_m3"] / volume, 6),
            "centre_of_mass_m": c["centre_of_mass_m"],
            "tris": c["tris"],
            "verts": c["verts"],
            "materials": c["materials"],
            "role": "tracer_emitter" if name.startswith(TRACER) else "chunk",
        })

    return {
        "contract": "GOLEM MODEL CONTRACT",
        "scope": "one articulated golem, rigged by parent hierarchy; not a "
                 "parts library and not an animated asset",
        "units": "metres, Y-up, 1 unit = 1 m. Modelled at %g units and baked "
                 "x%g into the vertices, so the delivered file is metre-native "
                 "with identity scales rather than carrying the conversion on a "
                 "node." % (MODELLED_UNITS, METRES_PER_UNIT),
        "units_gate": (
            "MEASURED AND GATED, not aspirational, and asserted against the "
            "exported FBX BYTES rather than the Maya scene: the unit defect "
            "this guards is written by the exporter and is absent from the "
            "scene, so every in-scene check passed green while three earlier "
            "deliveries shipped at 100x (maya-mcp #596, #600, #629). "
            "`delivery_units.check_rig_delivery` reads this .fbx with no Maya "
            "in the loop, composes the parent chain, and requires: the "
            "delivered HEIGHT to measure %.5f m, exactly one root, ZERO "
            "non-identity node scales, and a header that declares metres. "
            "`evals/golem_delivery_package.py` runs it and refuses to write "
            "this manifest if it fails; `tests/test_delivery_units.py` runs it "
            "again on every test run, against the committed file. A rig needed "
            "the height check because the demigol test - per-vertex magnitude "
            "against a ceiling - cannot see this defect at all: every chunk "
            "here is under a metre whatever the unit."
            % delivery_units.GOLEM_HEIGHT_M),
        "orientation": "+Z forward, Y-up. Measured, not assumed: the brow's "
                       "mean vertex sits at z +0.585 against the head's +0.239.",
        "origin": "world origin between the feet, floor at y = 0 (lowest vertex "
                  "-0.0067 m). The root chunk's own pivot is the hip, not the "
                  "origin.",
        "height_m": round(hi[1] - lo[1], 5),
        "width_m": round(hi[0] - lo[0], 5),
        "depth_m": round(hi[2] - lo[2], 5),
        "rig": {
            "root": ROOT,
            "nodes": len(chunks),
            "chunks": len(body),
            "tracer_emitters": len(chunks) - len(body),
            "pivot_convention": "each chunk's pivot is its PROXIMAL joint "
                                "centre, in world space, in the rest pose - "
                                "differs deliberately from the demigol kit and "
                                "hero rule (min-corner cell centre at y = 0)",
            "transforms": "translate + rotate only; every scale is identity and "
                          "every shear is zero, baked into the vertices",
        },
        "reach_m": {
            "shoulder_pivot_to_furthest_fist_vertex": 2.5528,
            "note": "the motion spec's GrabReach of 4 m is ~1.4 m past this. "
                    "Its own arithmetic (3.2u x 0.8) predicted 2.56 and the "
                    "delivered geometry measures 2.5528, so the flag stands: "
                    "grab needs a lunge or a step.",
        },
        "mass_model": {
            "total_volume_m3": round(volume, 6),
            "rule": "mass = volume x one density constant, uncompensated for "
                    "scale. The engine's mass unit is abstract (a 3 m steel "
                    "cell = 4.0), so what ships is the volume and the share.",
        },
        "destruction_unit": "a CHUNK is the unit of destruction - detach it at "
                            "its own pivot, never subdivide it. The four "
                            "tracer emitters are not chunks: they hang off "
                            "golem_C_brow, so detaching the brow takes the "
                            "visor light with it.",
        "materials": sorted({m for c in chunks.values() for m in c["materials"]}),
        "textures": {
            "embedded": False,
            "maps": ["evals/demigol_kit/kit_albedo.png",
                     "evals/demigol_kit/kit_mask.png",
                     "evals/demigol_kit/kit_normal.png"],
            "note": "All ten materials sample the SHARED DEMIGOL KIT ATLAS, "
                    "measured off the file nodes - not a golem-specific map "
                    "set. A consumer that already has the buildings already has "
                    "these three maps, and the FBX carries the UVs into them. "
                    "The ten names differ only in emission: one base material "
                    "plus five seam-glow variants and four tracer emitters.",
        },
        "poses": {
            "file": "poses.json",
            "form": "per-chunk ABSOLUTE local euler XYZ in degrees - set them, "
                    "do not add them. `rest` is exactly what the FBX nodes "
                    "already carry, so importing and doing nothing is `rest`.",
            "list": {k: {"trigger": v["trigger"],
                         "bbox_height_m": v["bbox_height_m"],
                         "crown_height_m": v["crown_height_m"],
                         "pelvis_height_m": v["pelvis_height_m"]}
                     for k, v in poses.items()},
            "gate": "delivery_units.check_poses re-composes every pose from the "
                    "FBX BYTES and requires it to reach the height it declares, "
                    "so the two files cannot drift apart.",
            "rotation_only": "no pose touches a translate - asserted in Maya "
                             "across all 33 chunks and all five poses.",
            "gaskets": "the ten collars keep their rest rotation in every pose. "
                       "They are the momentum-reading device: hung off the limb "
                       "they collar, they should settle AFTER it stops, which is "
                       "simulation rather than pose data.",
            "damage": "still gets no pose, deliberately - impulse at the contact "
                      "chunk plus joint limits and mass distribution.",
        },
        "emission_rule": "brow detached -> all golem emission to zero. The four "
                         "tracer emitters are parented to golem_C_brow, so the "
                         "visor light physically leaves with it; the body seam "
                         "glow has to be killed by that one engine-side rule.",
        "chunks_detail": out,
    }


def main():
    with open(CHUNKS) as fh:
        chunks = json.load(fh)
    with open(POSES) as fh:
        poses = json.load(fh)
    manifest = build_manifest(chunks, poses)

    violations = delivery_units.check_rig_delivery(
        FBX, delivery_units.GOLEM_HEIGHT_M, delivery_units.GOLEM_CEILING_M)
    violations += delivery_units.check_poses(FBX, poses)
    if violations:
        print("DELIVERY IS NOT METRE-TRUE - refusing to write a manifest for it:")
        for v in violations:
            print("   ", v)
        return 1

    with open(MANIFEST, "w") as fh:
        json.dump(manifest, fh, indent=1)
    facts = fbx_probe.read_fbx(FBX)
    lo, hi = fbx_probe.world_vertex_bounds(facts)
    print("%s: %d nodes, %.5f m tall, declared %g, gate clean"
          % (os.path.basename(FBX), len(facts.nodes), hi[1] - lo[1],
             facts.unit_scale_factor))
    return 0


if __name__ == "__main__":
    sys.exit(main())
