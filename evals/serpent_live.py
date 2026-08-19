"""Phase-1 gate for #602: the serpent. A 12-joint chain through one mesh -
the purest deformation test, one variable, fails legibly (a rigid-chunk
serpent reads as a bike chain).

Measured checks (this script) + judged renders (written for pixel judgment):

    1  build serpent mesh + 12-joint chain + bind      unweighted == 0,
                                                       every joint owns verts
    2  bend 90 degrees distributed along the chain     tip travels the arc the
                                                       chain geometry implies
                                                       (FK computed here),
                                                       max_displacement in a
                                                       window around it
    3  tearing detector                                posed mesh stays ONE
                                                       shell; no edge longer
                                                       than 1.5x bind length
    4  renders (front/side, posed)                     JUDGED - not scripted
    5  reset_pose                                      mesh back to bind
    6  export include_skins                            skin block green; byte
                                                       re-read agrees; baseline
                                                       recorded for consumer

DESTRUCTIVE: calls new_scene. Port 9878, the agent-launched Maya, per the
two-Maya policy - never point this at the user's 9877.

Run:  uv run python evals/serpent_live.py
Exit: 0 pass, 1 fail, 2 no connection.
Artifacts: evals/serpent_live/{serpent_posed_front,serpent_posed_side}.png,
           serpent.fbx, baseline.json
"""

from __future__ import annotations

import base64
import json
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

from live_call import call, structured_result  # noqa: E402
from maya_plugin.handlers import fbxbytes  # noqa: E402 - pure stdlib reader
from maya_plugin.handlers.export import WEIGHT_SUM_TOL  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9878"))
OUT_DIR = os.path.join(_HERE, "serpent_live")

MESH = "serpent"
LENGTH = 3.6           # metres, standing on y = 0
GIRTH = 0.3
JOINT_COUNT = 12
SEG = LENGTH / (JOINT_COUNT - 1)       # 11 segments between 12 joints
BEND_TOTAL = 90.0                      # degrees, distributed over the chain
BEND_STEP = BEND_TOTAL / (JOINT_COUNT - 1)
CHAIN_PREFIX = "serp"

# The brief specified divisions=8. `divisions` is a MULTIPLIER whose meaning
# differs per axis for a cylinder: subdivisionsAxis = 20 x divisions but
# subdivisionsHeight = divisions (modeling.build_unit_primitive). At 8 the tube
# therefore gets 160 sides around and only 8 rows ALONG its length - fewer rows
# than the 12 joints driving them, which is not a judgeable deformation test:
# each row would swing 11.25 degrees from the last and the silhouette would
# read as faceted whatever the rig did. The mayapy suite's own 12-joint case
# (test_a_max_influences_bind_survives_the_exporters_weight_pruning) uses 24
# length sections for exactly this chain; DIVISIONS here is the create_primitive
# equivalent, at the cost of an absurdly dense circumference the coupling
# forces on us.
DIVISIONS = 16

TIP_TOL_FRAC = 0.02            # the arc window from the brief
DISP_WINDOW = (0.9, 1.3)       # max_displacement / |tip_bind - tip_posed|
EDGE_STRETCH_MAX = 1.5         # a longer edge than this is a tear
RESET_TOL = 1e-3

CHECKS = []


def check(label, passed, detail=""):
    CHECKS.append((bool(passed), label))
    print("%s %s%s" % ("PASS" if passed else "FAIL", label,
                       ("  [%s]" % detail) if detail else ""))
    return bool(passed)


def send(command, params, timeout_s=300.0):
    """The raw response frame - a refusal is a measurement here, not an error."""
    try:
        return call(command, params, timeout_s=timeout_s, port=PORT)
    except (ConnectionRefusedError, OSError) as exc:
        print("could not reach a Maya plugin on %s: %s" % (PORT, exc))
        sys.exit(2)


def ok(command, params, timeout_s=300.0):
    response = send(command, params, timeout_s)
    if response.get("status") != "ok":
        print("FAIL: %s: %s" % (command, json.dumps(response.get("error"))[:600]))
        sys.exit(1)
    return response.get("result") or {}


def py(code, what, timeout_s=300.0):
    return structured_result(ok("execute_python", {"code": code}, timeout_s), what)


def out(name):
    return os.path.join(OUT_DIR, name)


# World points come from cmds.xform (sculpt.vertex_positions' proven pattern)
# rather than MFnMesh.getPoints: MSpace constants are ints and a positional
# space argument can silently select an index overload, which returns a
# wrong-but-plausible vector. Only the edge CONNECTIVITY needs the API, and
# vertexId() takes no space at all.
PROBE = """
import maya.cmds as cmds
import maya.api.OpenMaya as om

_mesh = %(mesh)r
_shape = cmds.listRelatives(_mesh, shapes=True, fullPath=True)[0]
_flat = cmds.xform(_mesh + '.vtx[*]', query=True, worldSpace=True,
                   translation=True)
_sel = om.MSelectionList()
_sel.add(_shape)
_it = om.MItMeshEdge(_sel.getDagPath(0))
_max_edge = 0.0
_edges = 0
while not _it.isDone():
    _a = _it.vertexId(0) * 3
    _b = _it.vertexId(1) * 3
    _dx = _flat[_a] - _flat[_b]
    _dy = _flat[_a + 1] - _flat[_b + 1]
    _dz = _flat[_a + 2] - _flat[_b + 2]
    _d = (_dx * _dx + _dy * _dy + _dz * _dz) ** 0.5
    if _d > _max_edge:
        _max_edge = _d
    _edges += 1
    _it.next()
_tip = cmds.xform(%(tip)r, query=True, worldSpace=True, translation=True)
{'shells': cmds.polyEvaluate(_mesh, shell=True),
 'vertices': len(_flat) // 3,
 'edges': _edges,
 'max_edge': round(_max_edge, 9),
 'tip_joint': [round(float(_v), 9) for _v in _tip]}
"""


def probe(mesh, tip_joint, what):
    return py(PROBE % {"mesh": mesh, "tip": tip_joint}, what)


def expected_tip():
    """Where forward kinematics puts the tip of the bent chain. Pure math.

    Segment s (joint s -> joint s+1) carries the accumulated rotation of every
    joint at or above it in the chain, and the ROOT is not rotated - so segment
    s is turned by s * BEND_STEP, s = 0..10, and the last segment sits at
    10 * (90/11) = 81.8 degrees rather than 90. That is what an 11-segment
    chain with 11 equal increments geometrically IS; asking for the tip at 90
    would be asking the eval to disagree with the rig it is measuring.

    Direction: create_skeleton's default orient (xyz/yup) aims local X along a
    +Y chain, leaving local Z on world Z, so a positive local-Z rotation takes
    +Y toward -X (Rz(t) . (0,1,0) = (-sin t, cos t, 0)). Measured that way in
    task 6 too; the achieved position is printed either way.
    """
    x = y = 0.0
    for s in range(JOINT_COUNT - 1):
        theta = math.radians(BEND_STEP * s)
        x -= SEG * math.sin(theta)
        y += SEG * math.cos(theta)
    return [x, y, 0.0]


def distance(a, b):
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def render_posed():
    """Front and side of the posed serpent, written for JUDGMENT.

    Arnold if this Maya has it, hw2 otherwise: the judgment here is silhouette
    continuity, which either renderer shows.
    """
    params = {"angles": ["front", "side"], "target": [MESH],
              "resolution": 640, "samples": 3, "renderer": "arnold"}
    response = send("render_scene", params, timeout_s=900.0)
    if response.get("status") != "ok":
        print("arnold render failed (%s); falling back to hw2"
              % json.dumps(response.get("error"))[:200])
        params["renderer"] = "hw2"
        response = send("render_scene", params, timeout_s=900.0)
    if response.get("status") != "ok":
        check("the posed serpent renders", False,
              json.dumps(response.get("error"))[:200])
        return []
    result = response["result"]
    written = []
    for image in result["images"]:
        path = out("serpent_posed_%s.png" % image["angle"])
        with open(path, "wb") as fh:
            fh.write(base64.b64decode(image["png_b64"]))
        written.append(path)
    check("the posed serpent renders", len(written) == 2,
          "renderer=%s, %d image(s)" % (result.get("renderer"), len(written)))
    return written


def main():
    if PORT == 9877:
        print("refusing to run on 9877: this eval discards the open scene "
              "(two-Maya policy). Launch a disposable Maya on 9878.")
        return 2

    os.makedirs(OUT_DIR, exist_ok=True)
    identity = py("import os\n{'pid': os.getpid()}", "identity")
    print("Maya on %d: pid %s, writing to %s\n" % (PORT, identity["pid"], OUT_DIR))

    # ---- 1. build, bind
    ok("new_scene", {"confirm": True})
    mesh = ok("create_primitive", {
        "kind": "cylinder", "name": MESH, "divisions": DIVISIONS,
        "scale": [GIRTH, LENGTH, GIRTH], "translate": [0, LENGTH / 2.0, 0],
    })["name"]
    # create_primitive leaves the SCALE on the node (it builds a unit box and
    # scales it), and export_fbx refuses any scale that reaches a vertex
    # (#629). Freeze it into the vertices before binding - after a bind the
    # transform is no longer freely freezable. Translation is left alone: it
    # does not multiply a vertex, and the gate does not care about it.
    frozen = py("import maya.cmds as cmds\n"
                "cmds.makeIdentity(%r, apply=True, translate=False, "
                "rotate=True, scale=True, normal=0, preserveNormals=True)\n"
                "[round(v, 9) for v in cmds.getAttr(%r + '.scale')[0]]"
                % (mesh, mesh), "freeze the primitive's scale")
    check("the serpent carries no node scale before binding",
          frozen == [1.0, 1.0, 1.0], "scale=%s" % (frozen,))

    skeleton = ok("create_skeleton", {
        "chain": [[0, LENGTH * i / (JOINT_COUNT - 1), 0]
                  for i in range(JOINT_COUNT)],
        "chain_prefix": CHAIN_PREFIX,
    })
    joints = [j["name"] for j in skeleton["joints"]]
    tip_joint = joints[-1]
    check("the chain built %d joints along the serpent" % JOINT_COUNT,
          len(joints) == JOINT_COUNT
          and abs(skeleton["joints"][-1]["position"][1] - LENGTH) < 1e-6,
          "root=%s tip=%s at y=%.4f"
          % (skeleton["root"], tip_joint,
             skeleton["joints"][-1]["position"][1]))

    bind = ok("bind_skin", {"mesh": mesh, "root": skeleton["root"]})
    check("the bind leaves NO vertex unowned",
          bind["unweighted_vertices"] == 0,
          "unweighted=%d of %s verts, warnings=%s"
          % (bind["unweighted_vertices"],
             sum(p["vertices"] for p in bind["per_joint"]) or "?",
             bind["warnings"]))
    empty = [p["joint"].split("|")[-1] for p in bind["per_joint"]
             if p["vertices"] == 0]
    check("every joint owns vertices", not empty,
          "influences=%d, empty=%s" % (len(bind["influences"]), empty))
    check("all %d joints are influences" % JOINT_COUNT,
          len(bind["influences"]) == JOINT_COUNT,
          "influences=%d" % len(bind["influences"]))

    at_bind = probe(mesh, tip_joint, "probe the bind pose")
    print("  bind: %s" % json.dumps(at_bind))
    check("the bind mesh is ONE shell", at_bind["shells"] == 1,
          "shells=%d, %d verts, %d edges"
          % (at_bind["shells"], at_bind["vertices"], at_bind["edges"]))

    # ---- 2. the bend
    rotations = {joints[i]: [0.0, 0.0, BEND_STEP] for i in range(1, JOINT_COUNT)}
    pose = ok("pose_skeleton", {"root": skeleton["root"], "rotations": rotations})
    check("the pose applied every non-root joint",
          pose["applied"] == JOINT_COUNT - 1 and not pose["warnings"],
          "applied=%d warnings=%s" % (pose["applied"], pose["warnings"]))

    want = expected_tip()
    got = pose["joints"][-1]["world_position"]
    tip_error = distance(want, got)
    tolerance = TIP_TOL_FRAC * math.sqrt(want[0] ** 2 + want[1] ** 2)
    check("the tip travelled the arc the chain implies",
          tip_error <= tolerance,
          "expected [%.5f, %.5f, %.5f], achieved [%.5f, %.5f, %.5f], "
          "error %.6f, tolerance %.6f"
          % (want[0], want[1], want[2], got[0], got[1], got[2],
             tip_error, tolerance))

    tip_travel = distance([0.0, LENGTH, 0.0], got)
    lo, hi = DISP_WINDOW[0] * tip_travel, DISP_WINDOW[1] * tip_travel
    check("the MESH moved with the chain, not more and not less",
          lo <= pose["max_displacement"] <= hi,
          "max_displacement=%.5f, window [%.5f, %.5f] around a tip travel of "
          "%.5f, displaced_vertices=%d"
          % (pose["max_displacement"], lo, hi, tip_travel,
             pose["displaced_vertices"]))

    # ---- 3. tearing
    posed = probe(mesh, tip_joint, "probe the posed mesh")
    print("  posed: %s" % json.dumps(posed))
    check("the posed mesh is still ONE shell", posed["shells"] == 1,
          "shells=%d" % posed["shells"])
    stretch = posed["max_edge"] / at_bind["max_edge"] if at_bind["max_edge"] else 0
    check("no edge stretched past %.1fx its bind length" % EDGE_STRETCH_MAX,
          stretch <= EDGE_STRETCH_MAX,
          "max edge %.6f posed vs %.6f at bind (%.3fx)"
          % (posed["max_edge"], at_bind["max_edge"], stretch))
    check("the posed vertex and edge counts are unchanged",
          posed["vertices"] == at_bind["vertices"]
          and posed["edges"] == at_bind["edges"],
          "%d verts / %d edges" % (posed["vertices"], posed["edges"]))

    # ---- 4. the renders, for judgment
    ok("setup_lighting", {"preset": "three_point"})
    written = render_posed()
    print("\n" + "=" * 72)
    print("JUDGE: the posed serpent must read as ONE CONTINUOUS CURVED BODY.")
    print("Faceted rigid segments, pinches or tears at the joints are a FAIL")
    print("even with every number above green.")
    for path in written:
        print("  " + path)
    print("=" * 72 + "\n")

    # ---- 5. reset
    reset = ok("reset_pose", {"root": skeleton["root"]})
    check("reset_pose undid what the pose did",
          abs(reset["max_displacement"] - pose["max_displacement"])
          <= 0.1 * pose["max_displacement"],
          "reset %.5f vs pose %.5f, warnings=%s"
          % (reset["max_displacement"], pose["max_displacement"],
             reset["warnings"]))
    back = probe(mesh, tip_joint, "probe the reset mesh")
    check("the tip joint is back at the bind pose",
          distance(back["tip_joint"], [0.0, LENGTH, 0.0]) < RESET_TOL,
          "tip_joint=%s" % (back["tip_joint"],))
    check("and the mesh itself returned to its bind shape",
          abs(back["max_edge"] - at_bind["max_edge"]) < 1e-6,
          "max_edge %.9f vs %.9f at bind"
          % (back["max_edge"], at_bind["max_edge"]))

    # ---- 6. the skinned export, gated in the bytes
    fbx = out("serpent.fbx")
    if os.path.exists(fbx):
        os.unlink(fbx)
    response = send("export_fbx", {"path": fbx.replace("\\", "/"),
                                   "metres_per_unit": 1.0,
                                   "include_skins": True}, timeout_s=600.0)
    exported = check("the skinned scene exports",
                     response.get("status") == "ok",
                     json.dumps(response.get("error"))[:300])
    result = response.get("result") or {}
    baseline = None
    if exported:
        skin = result["skin"]
        print("  skin: %s" % json.dumps(skin))
        check("the file holds exactly one skin deformer",
              skin["deformers"] == 1, "deformers=%d" % skin["deformers"])
        check("with one cluster per joint",
              skin["clusters"] == JOINT_COUNT, "clusters=%d" % skin["clusters"])
        check("and a bind pose", skin["bind_pose_present"] is True)
        check("no vertex is unowned in the FILE",
              skin["unweighted_file_vertices"] == 0,
              "unweighted_file_vertices=%d" % skin["unweighted_file_vertices"])
        # NOT the brief's 1e-3: Maya's exporter drops every weight below 1e-3
        # and does not renormalise, so a correct bind legitimately lands up to
        # ~7e-3 short of 1.0. Measured in tasks 8+9; export.WEIGHT_SUM_TOL is
        # the same constant the tool gates on, imported rather than restated.
        check("the file's weight sums are normalised within the exporter's "
              "own pruning", skin["max_weight_sum_error"] is not None
              and skin["max_weight_sum_error"] < WEIGHT_SUM_TOL,
              "max_weight_sum_error=%r, tolerance %g"
              % (skin["max_weight_sum_error"], WEIGHT_SUM_TOL))

        # The byte re-read: the tool measured the file it wrote, and this
        # measures the same file INDEPENDENTLY, from a reader that never saw Maya.
        # It proves fbxbytes works standalone on the shipped artifact and the
        # numbers survived TCP/JSON transport. It does not catch exporter defects.
        facts = fbxbytes.read_fbx(fbx)
        limbs = [n for n in facts.nodes if n.kind == "LimbNode"]
        check("the bytes carry %d LimbNode joints" % JOINT_COUNT,
              len(limbs) == JOINT_COUNT,
              "LimbNodes=%d of %d Models" % (len(limbs), len(facts.nodes)))
        reread = fbxbytes.skin_facts(facts)
        check("an independent read of the bytes agrees with the tool",
              reread == skin,
              "reread=%s" % json.dumps(reread))
        check("the file declares metres",
              facts.unit_scale_factor == fbxbytes.DECLARES_METRES,
              "UnitScaleFactor=%r" % facts.unit_scale_factor)

        # The consumer's import ticket needs to know what is IN the file, not
        # just that the skin is green: this is a whole-scene export of a lit
        # working scene, so the three-point rig is in there too (16 Models =
        # 12 LimbNode + the serpent + 3 lights). That is what an artist's scene
        # actually exports, and the importer has to cope with it.
        baseline = {
            "fbx": "serpent.fbx",
            "bytes": result["bytes"],
            "node_count": result["node_count"],
            "mesh_count": result["mesh_count"],
            "joint_models": len(limbs),
            "skin": skin,
            "world_bounds_min": result["world_bounds_min"],
            "world_bounds_max": result["world_bounds_max"],
            "bend_test": {
                "rotations_deg": {k.split("|")[-1]: v
                                  for k, v in rotations.items()},
                "expected_tip": want,
                "achieved_tip": got,
            },
        }
        with open(out("baseline.json"), "w") as fh:
            json.dump(baseline, fh, indent=2, sort_keys=True)
        print("  baseline: %s" % out("baseline.json"))

    failed = [label for passed, label in CHECKS if not passed]
    print("\n%d/%d passed" % (len(CHECKS) - len(failed), len(CHECKS)))
    for label in failed:
        print("  FAILED: %s" % label)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
