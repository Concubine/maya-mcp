"""#669 live gate: a limb can resolve its LENGTH without buying a circumference.

The defect, measured in Maya 2027 (evals/divisions_probe_669.py): the
`divisions` multiplier spends itself at a fixed per-kind ratio, and on a
cylinder or cone that ratio is 20 AROUND for every 1 ALONG. A long thin limb -
serpent, arm, femur - needs rows along its length and almost nothing around it,
so the only way to get them was to pay 26x the faces for a circumference no
shape needed. The serpent gate paid a 160-side tube for 16 length rows and
said so in a comment.

The fix adds `subdivisions`: literal counts, one per axis of the kind in hand.
This gate proves the thing that actually matters - that the cheap mesh DEFORMS
as well as the expensive one - rather than only that the numbers came back
right, which the mayapy suite already checks.

The measurement: build the same limb twice, once each way, bend both by the
same 90 degrees, and compare the ANGULAR STEP between consecutive rows of the
deformed silhouette. Both carry 16 rows, so both should turn about 5.6 degrees
per row; if the cheap one is coarser along its length then `subdivisions` did
not buy what it claimed. Faces are counted alongside, and that is where the
two differ.

Rows are identified by their Y BEFORE the bend and tracked by vertex index
after it, so the clustering never depends on Maya's vertex ordering.

Usage:

    set MAYA_MCP_PORT=9877
    set MAYA_MCP_EXPECT_PID=<the pid you launched>
    python evals/divisions_live.py

MUTATES THE ANSWERING MAYA'S CURRENT SCENE (new_scene, then several limbs).
MAYA_MCP_EXPECT_PID is REQUIRED, not optional: this discards the open scene, so
it refuses to guess which Maya is disposable. A port is not an identity (#648).

Exit: 0 pass, 1 fail. Writes a viewport capture of both limbs to
evals/divisions_live/ - look at it: the two silhouettes should be
indistinguishable.
"""

from __future__ import annotations

import base64
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from live_call import call, structured_result  # noqa: E402
from maya_plugin.handlers import modeling, pngprobe  # noqa: E402

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "divisions_live")
ROWS = 16                  # length rows both limbs carry
AROUND = 12                # a circumference a limb actually needs
BEND_DEG = 90.0
LIMB_SCALE = [0.15, 2.0, 0.15]
# 16 rows the old way is 5122 faces; the same 16 rows with a 12-sided tube is
# 194. Anything under 20x and the fixture stopped reproducing the complaint.
MIN_SAVING = 20.0
# Two meshes with the same row count must turn by the same amount per row. The
# window is generous because the deformer resamples on a different vertex set,
# not because the claim is soft - the measured pair sits far inside it.
STEP_TOL_DEG = 0.5
# The band claim 6's picture has to land in: dark enough to prove the frame is
# not empty, bright enough to prove it is not a white-out. Two limbs on an
# empty background is a mostly-dark frame, so the floor is what does the work.
DARK_LUMA = 3.0
BRIGHT_LUMA = 250.0

failures: list = []


def mean_luma(path: str) -> float:
    pixels = pngprobe.read_png(path)["pixels"]
    if not pixels:
        return 0.0
    return sum(sum(p[:3]) / 3.0 for p in pixels) / len(pixels)


def fail(message: str) -> None:
    failures.append(message)
    print("FAIL: " + message)


def preflight() -> dict:
    if not (os.environ.get("MAYA_MCP_EXPECT_PID") or "").strip():
        raise SystemExit(
            "MAYA_MCP_EXPECT_PID is not set. This gate discards the answering "
            "Maya's scene, so it will not guess which one is disposable - "
            "launch one yourself and name its pid (#648).")
    frame = call("ping", {})
    if frame.get("status") != "ok":
        raise SystemExit("ping failed: %r" % (frame.get("error"),))
    ping = frame.get("result") or {}
    if not ping:
        raise SystemExit("no Maya answered - start one, or check "
                         "MAYA_MCP_PORT. Do NOT fall back to batchmode.")
    if (ping.get("plugin") or {}).get("restart_required"):
        raise SystemExit(
            "the answering Maya (pid %s) holds stale modules - restart it "
            "before running this gate"
            % (ping.get("process") or {}).get("pid"))
    return ping


def ok(command: str, params: dict, timeout_s: float = 120.0) -> dict:
    frame = call(command, params, timeout_s=timeout_s)
    if frame.get("status") != "ok":
        raise SystemExit("%s failed: %r" % (command, frame.get("error")))
    return frame.get("result") or {}


def refused(command: str, params: dict) -> str:
    """Send a call that MUST be refused; return the error text."""
    frame = call(command, params, timeout_s=60.0)
    if frame.get("status") == "ok":
        fail("%s(%r) was accepted - it must be refused" % (command, params))
        return ""
    error = frame.get("error") or {}
    return "%s %s" % (error.get("message", ""), error.get("hint", ""))


def python(code: str, what: str, timeout_s: float = 120.0):
    result = ok("execute_python", {"code": code, "timeout_s": timeout_s},
                timeout_s=timeout_s + 30)
    return structured_result(result, what)


def row_clusters(mesh: str) -> str:
    """Code fragment: rows keyed by the vertex Y before anything deformed it."""
    return (
        "import maya.cmds as cmds, math\n"
        "def rows_of(mesh):\n"
        "    n = cmds.polyEvaluate(mesh, vertex=True)\n"
        "    pts = cmds.xform(mesh + '.vtx[0:%d]' % (n - 1), q=True, ws=True,\n"
        "                     t=True)\n"
        "    return [pts[i:i + 3] for i in range(0, len(pts), 3)]\n"
    )


def build(name: str, params: dict) -> dict:
    """Create one limb, bend it, and report rows / faces / angular steps."""
    result = ok("create_primitive", dict(params, kind="cylinder", name=name,
                                         scale=LIMB_SCALE))
    mesh = result["name"]
    measured = python(
        row_clusters(mesh) +
        "pts = rows_of(%r)\n"
        "keys = [round(p[1], 5) for p in pts]\n"
        "{'faces': cmds.polyEvaluate(%r, face=True),\n"
        " 'verts': len(pts),\n"
        " 'rows': sorted(set(keys)),\n"
        " 'keys': keys}\n" % (mesh, mesh),
        "%s rest rows" % name)
    ok("deform", {"mesh": mesh, "deformer": "bend",
                  "params": {"curvature": BEND_DEG}})
    steps = python(
        row_clusters(mesh) +
        "import math\n"
        "pts = rows_of(%r)\n"
        "keys = %r\n"
        "rows = %r\n"
        "cents = []\n"
        "for key in rows:\n"
        "    members = [p for p, k in zip(pts, keys) if k == key]\n"
        "    cents.append([sum(c) / len(members) for c in zip(*members)])\n"
        "segs = []\n"
        "for a, b in zip(cents, cents[1:]):\n"
        "    v = [b[i] - a[i] for i in range(3)]\n"
        "    segs.append(v)\n"
        "angles = []\n"
        "for u, v in zip(segs, segs[1:]):\n"
        "    du = math.sqrt(sum(c * c for c in u))\n"
        "    dv = math.sqrt(sum(c * c for c in v))\n"
        "    if du == 0 or dv == 0:\n"
        "        continue\n"
        "    dot = sum(a * b for a, b in zip(u, v)) / (du * dv)\n"
        "    angles.append(math.degrees(math.acos(max(-1.0, min(1.0, dot)))))\n"
        "{'max_step': max(angles), 'total_turn': sum(angles),\n"
        " 'steps': len(angles)}\n"
        % (mesh, measured["keys"], measured["rows"]),
        "%s bent rows" % name)
    return {
        "mesh": mesh, "declared": result.get("subdivisions"),
        "reported_faces": result.get("faces"), "faces": measured["faces"],
        "rows": len(measured["rows"]), **steps,
    }


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    ping = preflight()
    print("answering Maya: pid %s" % (ping.get("process") or {}).get("pid"))
    ok("new_scene", {"confirm": True})

    print("claim 1: the same 16 rows, bought both ways")
    free = build("limb_free", {"subdivisions": [AROUND, ROWS]})
    coupled = build("limb_coupled", {"divisions": ROWS})
    for label, got in (("free", free), ("coupled", coupled)):
        print("  %-8s %-12s %6d faces (reported %s), %d rows, "
              "max step %.2f deg, total turn %.1f deg"
              % (label, got["declared"], got["faces"], got["reported_faces"],
                 got["rows"], got["max_step"], got["total_turn"]))
        if got["reported_faces"] != got["faces"]:
            fail("%s: the tool reported %s faces and the mesh has %d"
                 % (label, got["reported_faces"], got["faces"]))
        if got["rows"] != ROWS + 1:
            fail("%s: %d rows of vertices, expected %d (%d subdivisions along "
                 "a cylinder means %d rings)"
                 % (label, got["rows"], ROWS + 1, ROWS, ROWS + 1))

    print("claim 2: the cheap limb deforms as well as the expensive one")
    gap = abs(free["max_step"] - coupled["max_step"])
    print("  max step %.3f vs %.3f deg (gap %.3f), total turn %.2f vs %.2f"
          % (free["max_step"], coupled["max_step"], gap,
             free["total_turn"], coupled["total_turn"]))
    if gap > STEP_TOL_DEG:
        fail("the two limbs bend differently: %.3f vs %.3f degrees per row. "
             "Same row count must mean the same silhouette resolution, or "
             "`subdivisions` did not buy the length it claimed."
             % (free["max_step"], coupled["max_step"]))

    print("claim 3: and it costs a fraction of the faces")
    saving = float(coupled["faces"]) / float(free["faces"])
    print("  %d faces against %d - %.1fx" % (free["faces"], coupled["faces"],
                                             saving))
    if saving < MIN_SAVING:
        fail("only %.1fx cheaper (%d vs %d faces) - the fixture no longer "
             "reproduces the coupling this ticket is about"
             % (saving, free["faces"], coupled["faces"]))

    print("claim 4: what Maya would swallow, the tool refuses")
    text = refused("create_primitive", {
        "kind": "cylinder", "name": "too_few", "subdivisions": [2, ROWS]})
    if "around" not in text:
        fail("a 2-sided tube was not refused by name: %r" % text)
    else:
        print("  below the minimum: %s" % text.split(".")[0])
    text = refused("create_primitive", {
        "kind": "cylinder", "name": "both", "divisions": 4,
        "subdivisions": [AROUND, ROWS]})
    if "not both" not in text:
        fail("passing both currencies was not refused: %r" % text)
    else:
        print("  both currencies: refused")
    text = refused("create_primitive", {
        "kind": "octahedron", "name": "platonic", "subdivisions": [4, 4]})
    if "no subdivision axes" not in text:
        fail("subdivisions on a platonic solid was not refused: %r" % text)
    else:
        print("  platonic solid: refused")

    print("claim 5: the projection the face budget spends is still exact")
    kinds = list(modeling.PRIMITIVE_KINDS)
    measured = python(
        "import maya.cmds as cmds\n"
        "from maya_plugin.handlers import modeling\n"
        "out = []\n"
        "for kind in %r:\n"
        "    for d in (1, 2, 5):\n"
        "        cmds.file(new=True, force=True)\n"
        "        n = modeling.build_unit_primitive(cmds, kind, 'p', d)\n"
        "        out.append((kind, d, cmds.polyEvaluate(n, face=True)))\n"
        "out\n" % (kinds,), "face projection sweep")
    wrong = [(k, d, f) for k, d, f in measured
             if modeling.projected_faces(k, d) != f]
    if wrong:
        for kind, d, faces in wrong:
            fail("projected_faces(%s, %d) says %d, Maya built %d"
                 % (kind, d, modeling.projected_faces(kind, d), faces))
    else:
        print("  %d kind/divisions pairs, all exact" % len(measured))

    print("claim 6: a picture of both, side by side")
    ok("new_scene", {"confirm": True})
    ok("create_primitive", {"kind": "cylinder", "name": "shot_free",
                            "subdivisions": [AROUND, ROWS],
                            "scale": LIMB_SCALE, "translate": [-0.5, 0, 0]})
    ok("create_primitive", {"kind": "cylinder", "name": "shot_coupled",
                            "divisions": ROWS, "scale": LIMB_SCALE,
                            "translate": [0.5, 0, 0]})
    for mesh in ("|shot_free", "|shot_coupled"):
        # Bake the deformer away for the picture. A live bend handle is a big
        # NURBS-ish curve in the viewport, and framing includes it: the first
        # version of this shot came back as two blue arcs and no geometry at
        # all, which is the same blank-capture trap as #618's framing.
        ok("deform", {"mesh": mesh, "deformer": "bend",
                      "params": {"curvature": BEND_DEG},
                      "delete_history_after": True})
    # render_scene, NOT capture_viewport: on this machine an agent-launched
    # Maya's viewport capture comes back as an empty framebuffer (mean luma
    # 6.6, no geometry at any angle, foregrounded or not) and reports nothing
    # wrong - the first version of this gate PASSED while handing over a blank
    # white square. Filed separately; an offline render does not depend on a
    # window being drawn, which is why #670's gate uses one too.
    shot = ok("render_scene", {"angles": ["front"], "renderer": "arnold",
                               "resolution": 512, "samples": 2},
              timeout_s=600.0)
    image = (shot.get("images") or [None])[0]
    if not image:
        fail("render_scene returned no image")
    else:
        path = os.path.join(OUT_DIR, "divisions_side_by_side.png")
        with open(path, "wb") as fh:
            fh.write(base64.b64decode(image["png_b64"]))
        lit = mean_luma(path)
        print("  wrote %s (mean luma %.1f)" % (path, lit))
        # A gate that says "now look at this" and hands over an empty frame
        # proves nothing. The band is wide on purpose: the claim is that
        # something was drawn, not that it was drawn prettily.
        if not (DARK_LUMA < lit < BRIGHT_LUMA):
            fail("the picture is blank (mean luma %.1f, band %.0f-%.0f): "
                 "nothing was rendered, so there is nothing to judge"
                 % (lit, DARK_LUMA, BRIGHT_LUMA))

    print()
    if failures:
        print("GATE FAILED (%d)" % len(failures))
        return 1
    print("GATE PASSED - now LOOK at %s: the left limb (12 around) and the "
          "right (320 around) should read the same, and only one of them cost "
          "5122 faces." % OUT_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
