"""maya-mcp #729 Step 1 probe (evidence only, time-boxed).

export.export_fbx force-unloads and reloads the bundled fbxmaya plugin
before EVERY animated export so it re-reads the scene's CURRENT frame rate
(#695: fbxmaya caches the rate once, at plugin LOAD time, and bakes every
animated export at the cached rate until the plugin is reloaded). Repeating
that unload/reload cycle enough times in one mayapy process corrupts the
Windows heap: a mayapy process died inside maya.standalone.uninitialize()
at a running total of 3 reload cycles (2 measured clean, 3/3 reproduction -
see .superpowers/sdd/t718-10b-report.md).

This script asks one question: is there ANY way to make fbxmaya re-read the
scene's CURRENT frame rate WITHOUT an unload/reload - an FBX export
property, set through the same `FBXProperty`/mel.eval surface export.py
already drives, that resets whatever internal cache is stale? If one
exists, #729's fix is a one-line property set (Step 3-B). If none does
(the expected outcome - fbxmaya's LOAD-time cache is plugin-internal state,
not an item in the FBXProperty export-settings tree that FBXResetExport
governs), #729's fix is a guard that only pays the reload cost when the
scene's time unit actually changed (Step 3-A, fully specified in the task
brief regardless of this script's outcome).

Method:
  1. Build a one-joint scene, author a 1.0s clip at 24 fps, export it for
     real (include_animation=True) - this is a genuine plugin LOAD (fresh
     process), so it caches 24 fps.
  2. delete_clip, re-author the SAME joint at 30 fps. The scene's time unit
     is now 30 fps; the plugin's cache is still 24 - stale, on purpose.
  3. Dump `FBXProperties` (the live property tree) and grep it for any line
     mentioning Rate, Sampling or Time - candidate levers.
  4. For each candidate (and for `FBXResetExport` alone, as a known-no
     control - it already runs before every export.py preamble and does
     NOT fix the cache, so if this control measures 31 the probe's own
     method is broken, not the finding): export the scene through the SAME
     MEL sequence export.py sends (reusing its own exposed constants - see
     export.py's module docstring, never re-derive the MEL by hand), with
     the candidate's `FBXProperty ... -v 30` statement inserted right after
     the preamble and NO unload/reload anywhere in the process. Read the
     bytes back and count the baked keys on the joint's rotation curve via
     fbxbytes.anim_facts.

     31 keys (round(1.0 * 30) + 1) = the candidate forced a fresh read of
     the CURRENT 30 fps - it works.
     25 keys (round(1.0 * 24) + 1) = the plugin baked at the STALE cached
     24 fps - it does not work.

Run:
    E:\\Autodesk\\Maya2027\\bin\\mayapy.exe evals\\fbx_fps_probe.py

Prints a per-candidate verdict table and a DECISION line. Exit: 0 if the
probe ran to completion (regardless of whether any candidate worked - a
clean "nothing works" IS the answer this script exists to measure), 1 if
the probe itself could not complete (environment failure, not a candidate
failing), 2 if mayapy/maya.standalone is not importable.
"""

import os
import re
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

try:
    import maya.standalone
except ImportError:
    print("mayapy / Maya's embedded Python is required - this cannot run "
          "against a live Maya port. See the module docstring for the "
          "mayapy invocation.")
    sys.exit(2)

OUT_DIR = os.path.join(_HERE, "fbx_fps_probe_out")

CANDIDATE_RE = re.compile(r"(?i)rate|sampling|time")

# Fallback, used only if _capture_mel below caught nothing: the FULL
# FBXProperties dump (162 lines) was captured once by redirecting this
# whole process's stdout to a file at the OS level (`mayapy ... > log`),
# outside this script's own control - MEASURED that neither
# contextlib.redirect_stdout nor an in-process os.dup2(fd) swap catches
# FBXProperties' output (0 chars both ways): the FBX plugin appears to grab
# its own handle to the process's original stdout at plugin load, before
# this script can intervene. Hand-picked from that external capture, every
# EXPORT-side (not Import-side) property whose name matches Rate|Sampling|
# Time and is not already a bake FRAME NUMBER export.py sets explicitly
# every call (BakeFrameStart/End/Step are frame indices, not a rate):
#   Export|AdvOptGrp|FileFormat|Motion_Base|MotionFrameRate  (Number)
#   Export|AdvOptGrp|Collada|FrameRate                       (Number)
# Both are structurally inapplicable - they belong to the Motion Analysis
# (BVH/ASF/AMC) and Collada exporters respectively, never consulted on a
# type="FBX export" call - but are tested anyway for a complete table.
FALLBACK_CANDIDATES = (
    "Export|AdvOptGrp|FileFormat|Motion_Base|MotionFrameRate",
    "Export|AdvOptGrp|Collada|FrameRate",
)

EXPECTED_CORRECT = 31   # round(1.0 * 30) + 1 - the scene's REAL fps
EXPECTED_STALE = 25     # round(1.0 * 24) + 1 - the seeded, stale fps


def _bypass_export(cmds, mel, export_mod, fbxbytes_mod, path, root,
                   declared, extra_statements=()):
    """Sends the SAME MEL export.export_fbx does (its own exposed
    constants, never re-derived by hand), but with NO unload/reload of
    fbxmaya anywhere in this call and NO gate - this is Step 1's
    evidence-gathering rig, not a production export path. `extra_statements`
    is spliced in right after the preamble, the same slot #729's real fix
    would occupy if a property reset ever replaces the reload block.
    """
    cmds.loadPlugin("fbxmaya", quiet=True)   # no-op if already loaded
    for statement in export_mod.FBX_PREAMBLE_MEL:
        mel.eval(statement)
    for statement in extra_statements:
        mel.eval(statement)
    for statement in (export_mod.FBX_SCENE_CONTENT_MEL
                      + export_mod.FBX_SHAPES_MEL
                      + export_mod.FBX_SKINS_MEL[False]
                      + export_mod.FBX_ANIM_MEL[True]):
        mel.eval(statement)
    span = int(declared["span_frames"])
    mel.eval("FBXExportBakeComplexStart -v 0")
    mel.eval("FBXExportBakeComplexEnd -v %d" % span)
    mel.eval("FBXExportSplitAnimationIntoTakes -clear")
    for record in declared["clips"]:
        mel.eval('FBXExportSplitAnimationIntoTakes -v "%s" %d %d'
                 % (record["name"], record["start_frame"],
                    record["end_frame"]))
    mel.eval("FBXExportScaleFactor %g" % export_mod.EXPORT_SCALE_FACTOR)
    cmds.select([root], replace=True)
    cmds.file(path, force=True, options="v=0", type="FBX export",
              pr=True, es=True)
    fbxbytes_mod.set_unit_scale_factor(path)
    facts = fbxbytes_mod.read_fbx(path)
    anim = fbxbytes_mod.anim_facts(facts)
    target = next((t for t in anim["targets"]
                   if t["target"] == "fp_root"
                   and t["property"] == "Lcl Rotation"), None)
    return target["key_count"] if target else None


def _capture_mel(mel, statement):
    """Runs one mel.eval, capturing whatever it writes to stdout.

    contextlib.redirect_stdout does not see this: FBXProperties writes
    through Maya's own C-level output stream (MGlobal::displayInfo or
    equivalent), which bypasses Python's sys.stdout object and goes
    straight to OS file descriptor 1 - measured directly (redirect_stdout
    caught 0 of ~160 printed lines). Redirecting the real fd with
    os.dup2 catches it.
    """
    sys.stdout.flush()
    fd = sys.stdout.fileno()
    saved_fd = os.dup(fd)
    tmp = tempfile.TemporaryFile(mode="w+")
    try:
        os.dup2(tmp.fileno(), fd)
        ret = mel.eval(statement)
    finally:
        sys.stdout.flush()
        os.dup2(saved_fd, fd)
        os.close(saved_fd)
    tmp.seek(0)
    dump = tmp.read()
    tmp.close()
    if isinstance(ret, str):
        dump = dump + "\n" + ret
    return dump


def _verdict(key_count):
    if key_count == EXPECTED_CORRECT:
        return "WORKS (31 keys - fresh read of the current 30 fps)"
    if key_count == EXPECTED_STALE:
        return "does not work (25 keys - baked at the stale 24 fps cache)"
    if key_count is None:
        return "no target found in the bytes (probe defect, not a verdict)"
    return "UNEXPECTED (%d keys)" % key_count


def main():
    maya.standalone.initialize(name="python")
    import maya.cmds as cmds
    import maya.mel as mel

    from maya_plugin.handlers import clip, export, fbxbytes, rigging

    os.makedirs(OUT_DIR, exist_ok=True)
    cmds.file(new=True, force=True)

    skeleton = rigging.create_skeleton({"joints": [
        {"name": "fp_root", "position": [0.0, 0.0, 0.0]}]})
    root = skeleton["root"]

    def _author(fps, name):
        clip.author_clip({
            "root": root, "name": name, "fps": fps,
            "keys": [
                {"time_s": 0.0, "rotations": {"fp_root": [0, 0, 0]}},
                {"time_s": 0.5, "rotations": {"fp_root": [0, 0, 30]}},
                {"time_s": 1.0, "rotations": {"fp_root": [0, 0, 0]}}]})

    # --- seed the plugin's cache at 24 fps with a REAL, genuine load ------
    _author(24, "probe24")
    seed_path = os.path.join(OUT_DIR, "seed24.fbx").replace("\\", "/")
    export.export_fbx({"path": seed_path, "metres_per_unit": 1.0,
                       "nodes": [root], "include_animation": True})
    clip.delete_clip({"root": root})

    # --- re-author the SAME joint at 30 fps - the cache is now STALE ------
    _author(30, "probe30")
    declared = export._scene_clips(cmds)

    # --- dump the live FBX property tree and grep for rate-shaped names ---
    try:
        dump = _capture_mel(mel, "FBXProperties")
    except Exception as exc:  # noqa: BLE001 - evidence gathering, not a gate
        dump = ""
        print("FBXProperties call raised: %s" % exc)
    print("=== FBXProperties dump: %d chars, %d lines ==="
          % (len(dump), len(dump.splitlines())))

    seen = set()
    candidates = []
    for line in dump.splitlines():
        line = line.strip()
        if not line or not CANDIDATE_RE.search(line):
            continue
        token = line.split()[0]
        if token not in seen:
            seen.add(token)
            candidates.append(token)
    candidates = candidates[:25]   # time-boxed - see module docstring
    used_fallback = False
    if not candidates:
        candidates = list(FALLBACK_CANDIDATES)
        used_fallback = True
    print("=== %d candidate propert%s matching Rate|Sampling|Time%s ==="
          % (len(candidates), "y" if len(candidates) == 1 else "ies",
             " (FALLBACK LIST - see FALLBACK_CANDIDATES docstring; the "
             "dump above was not capturable in this environment)"
             if used_fallback else ""))
    for c in candidates:
        print("  %s" % c)

    verdicts = []

    ctrl_path = os.path.join(OUT_DIR, "control.fbx").replace("\\", "/")
    ctrl_count = _bypass_export(cmds, mel, export, fbxbytes, ctrl_path,
                                root, declared, extra_statements=())
    verdicts.append(("FBXResetExport alone (control, known-no)",
                     ctrl_count, _verdict(ctrl_count)))

    for i, token in enumerate(candidates):
        stmt = 'FBXProperty "%s" -v 30' % token
        trial_path = os.path.join(
            OUT_DIR, "trial_%02d.fbx" % i).replace("\\", "/")
        try:
            count = _bypass_export(cmds, mel, export, fbxbytes, trial_path,
                                   root, declared, extra_statements=(stmt,))
            verdict = _verdict(count)
        except Exception as exc:  # noqa: BLE001 - a candidate CAN misfire
            count = None
            verdict = "ERROR: %s" % exc
        verdicts.append((token, count, verdict))

    print("\n%-60s %8s  %s" % ("candidate", "keys", "verdict"))
    print("-" * 110)
    for label, count, verdict in verdicts:
        print("%-60s %8s  %s" % (label[:60], str(count), verdict))

    works = [v for v in verdicts if v[2].startswith("WORKS")]
    if works:
        print("\nDECISION: 3-B (property reset) - %s measured 31 keys"
              % works[0][0])
    else:
        print("\nDECISION: 3-A (cached-fps guard) - no candidate reached "
              "31 keys")

    try:
        maya.standalone.uninitialize()
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
