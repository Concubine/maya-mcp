"""Live gate for maya-mcp #718 Task 10b: is the multi-take export gate
actually deterministic now, run after run, in one process?

Task 10 measured export.export_fbx()'s own byte gate (anim_violations)
refusing a genuinely correct two-clip export at RANDOM: 8 back-to-back
exports of one byte-identical scene, in one process, split 6 pass / 2 fail
(t718-10-report.md finding #3). The cause was a first-wins collapse of a
segmented plug's three duplicate AnimationCurveNode records (one per take,
see fbxbytes.py's FbxFacts docstring) keyed on an FBX-internal object UID
that is not stable run to run. Task 10b's fix (this branch) attributes
every curve record to the take that owns it structurally, through the
AnimationCurveNode -> AnimationLayer -> AnimationStack connection chain, so
anim_violations/anim_clip_facts can check each declared clip against only
its OWN take's records.

The determinism claim only means anything if it is actually run, not
reasoned about - a first-wins-on-an-unstable-UID bug is exactly the kind of
thing that "looks fixed" by inspection while still failing 1 run in 4. This
script is the re-runnable form of the probe whose output was previously
only quoted in .superpowers/sdd/t718-10b-report.md: it builds one two-clip
scene, calls the REAL export.export_fbx() (no bypass helper, the real
anim_violations gate) N times in a row in one process, and reports how many
of those N calls raised.

Run (mayapy, not a live Maya port - this needs maya.standalone, the same
way tests/test_handlers_mayapy.py does):

    E:\\Autodesk\\Maya2027\\bin\\mayapy.exe evals\\clip_export_determinism_live.py [N]

N defaults to 8, matching the exact repeat count Task 10's measurement
used (the count that exposed the 6/2 split). A higher N (the report also
ran 30) is a stronger proof of the same claim, at proportionally more
wall-clock cost - the loop body itself is cheap; the fbxmaya reload below
is what's expensive.

KNOWN PRE-EXISTING FRAGILITY, not a #718 defect: every include_animation
export forces fbxmaya's unloadPlugin/loadPlugin cycle (#695 - the bundled
FBX plugin caches the scene's frame rate at plugin LOAD time, so the
reload exists to make it re-read a possibly-changed fps before every
animated export). Repeating that reload cycle enough times in one mayapy
process has been measured (t718-10b-report.md) to eventually corrupt this
process's heap and crash INSIDE maya.standalone.uninitialize() at
teardown, AFTER every export in the loop has already succeeded and been
reported. That crash is a known fragility in the #695 reload workaround
under heavy repetition on this machine's mayapy/fbxmaya build - it is not
a symptom of the thing this script measures. Trust the per-run PASS/FAIL
lines and the SUMMARY line this script prints before exiting; a nonzero
process exit code or a traceback that appears only AFTER "SUMMARY" has
already printed a clean result is that known teardown fragility, not a
determinism failure of export_fbx's gate.

Exit: 0 if every run exported and passed the real gate, 1 if any run
raised, 2 if maya/mayapy is not importable.
"""

import sys

import os

try:
    import maya.standalone
except ImportError:
    print("mayapy / Maya's embedded Python is required - this cannot run "
          "against a live Maya port. See the module docstring for the "
          "mayapy invocation.")
    sys.exit(2)

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "clip_export_determinism_live")


def _two_clip_scene(cmds, prefix):
    """Same scene shape as tests/test_handlers_mayapy.py's
    TestMultiTakeExportInMaya._two_clip_scene: one rig, two 1s clips
    (idle keys the mid joint, walk keys the tip joint) on the shared
    self-contained timeline #718 established. Not imported from the test
    file on purpose - this script has to run standalone, without pytest,
    under a bare mayapy invocation.
    """
    from maya_plugin.handlers import clip, rigging

    base = cmds.ls(cmds.polyCube(name=prefix + "_base", height=2,
                                 subdivisionsHeight=4)[0], long=True)[0]
    skeleton = rigging.create_skeleton({"joints": [
        {"name": prefix + "_root", "position": [0.0, -1.0, 0.0]},
        {"name": prefix + "_mid", "position": [0.0, 0.0, 0.0],
         "parent": prefix + "_root"},
        {"name": prefix + "_tip", "position": [0.0, 1.0, 0.0],
         "parent": prefix + "_mid"}]})
    rigging.bind_skin({"mesh": base, "root": skeleton["root"]})
    clip.author_clip({
        "root": skeleton["root"], "name": "idle", "fps": 30,
        "keys": [
            {"time_s": 0.0, "rotations": {prefix + "_mid": [0, 0, 0]}},
            {"time_s": 0.5, "rotations": {prefix + "_mid": [0, 0, 30]}},
            {"time_s": 1.0, "rotations": {prefix + "_mid": [0, 0, 0]}}]})
    clip.author_clip({
        "root": skeleton["root"], "name": "walk", "fps": 30,
        "keys": [
            {"time_s": 0.0, "rotations": {prefix + "_tip": [0, 0, 0]}},
            {"time_s": 0.5, "rotations": {prefix + "_tip": [0, 0, 25]}},
            {"time_s": 1.0, "rotations": {prefix + "_tip": [0, 0, 0]}}]})
    return base, skeleton["root"]


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 8

    maya.standalone.initialize(name="python")
    import maya.cmds as cmds

    from maya_plugin.handlers import export

    os.makedirs(OUT_DIR, exist_ok=True)
    ok = 0
    fail = 0
    for i in range(n):
        cmds.file(new=True, force=True)
        base, root = _two_clip_scene(cmds, "pz")
        path = os.path.join(OUT_DIR, "run_%02d.fbx" % i).replace("\\", "/")
        try:
            result = export.export_fbx({
                "path": path, "metres_per_unit": 1.0,
                "nodes": [base, root], "include_animation": True})
            names = sorted(c["name"] for c in result["animation"]["clips"])
            print("RUN %d: OK, clips=%s" % (i, names))
            if names == ["idle", "walk"]:
                ok += 1
            else:
                print("RUN %d: WRONG CLIPS, treating as a failure" % i)
                fail += 1
        except Exception as exc:  # noqa: BLE001 - a gate refusal IS the result
            print("RUN %d: FAIL: %s" % (i, exc))
            fail += 1

    print("SUMMARY ok=%d fail=%d" % (ok, fail))
    sys.stdout.flush()
    exit_code = 0 if fail == 0 else 1

    # See the module docstring: a crash from here on is the known #695
    # reload-cycle teardown fragility, not a result of the loop above -
    # the SUMMARY line already printed is this script's real answer.
    try:
        maya.standalone.uninitialize()
    except Exception:
        pass
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
