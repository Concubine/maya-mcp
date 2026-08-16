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


def build_manifest(chunks):
    lo = [min(c["bbox_min_m"][i] for c in chunks.values()) for i in range(3)]
    hi = [max(c["bbox_max_m"][i] for c in chunks.values()) for i in range(3)]
    volume = sum(c["volume_m3"] for c in chunks.values())
    body = {k: v for k, v in chunks.items() if not k.startswith(TRACER)}

    out = []
    for name in sorted(chunks):
        c = chunks[name]
        out.append({
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
        "textures": "NOT embedded in the FBX (FBXExportEmbeddedTextures false). "
                    "The material names are carried so a consumer can bind its "
                    "own; the golem's maps live in the Maya scene beside this "
                    "file.",
        "poses": "NOT in this delivery. The handoff spec asks for 5 target "
                 "poses as per-chunk rotations; this file is the rest pose "
                 "only, and the poses are still to be authored.",
        "chunks_detail": out,
    }


def main():
    with open(CHUNKS) as fh:
        chunks = json.load(fh)
    manifest = build_manifest(chunks)

    violations = delivery_units.check_rig_delivery(
        FBX, delivery_units.GOLEM_HEIGHT_M, delivery_units.GOLEM_CEILING_M)
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
