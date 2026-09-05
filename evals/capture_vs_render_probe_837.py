"""Throwaway probe for redmine #837: do capture_viewport and render_scene
encode the same lit surface differently, and which transform does each use?

The kethran run saw a 0.028-albedo material near-black in the viewport and
pale mid-grey in Arnold, and needed ~2x different rig intensity per path.
render_scene (#615) encodes with "Un-tone-mapped (sRGB)"; capture_viewport is
a plain offscreen playblast that takes whatever the panel and the
colour-management prefs apply. Hypothesis: the playblast goes through the
scene's VIEW transform (ACES 1.0 SDR-video by default in 2027), which is
tone-mapped and pushes darks darker.

Measured, nothing asserted. Every variant is recorded on its own, so one
that raises does not lose the others:

  Q1  colorManagementPrefs as this Maya has them
  Q2  the calibration plane (linear 0.5, lit N.L = 1 by a light at pi) through
      render_scene and through capture_viewport lighting=scene - the modal lit
      value of each. Un-tone-mapped sRGB says 187/188.
  Q3  the same with albedo 0.028 (the run's "claw"). sRGB says ~47.
  Q4  the capture again with the VIEW transform set to Un-tone-mapped (sRGB)
  Q5  the capture again with the OUTPUT transform enabled and set to it,
      outputUseViewTransform off (the flags render.py uses), view untouched
  Q6  lighting=default for reference
  Q7  what capture_viewport's result says about colour, if anything

Run:  MAYA_MCP_PORT=9879 MAYA_MCP_EXPECT_PID=<pid> .venv/Scripts/python.exe evals/capture_vs_render_probe_837.py

MUTATES THE ANSWERING MAYA'S SCENE (new_scene first). Refuses 9877.
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
import textwrap
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, _HERE)

from live_call import call, structured_result  # noqa: E402

PORT = int(os.environ.get("MAYA_MCP_PORT", "9879"))
if PORT == 9877:
    raise SystemExit("refusing 9877 - that is the user's Maya")
OUT = os.path.join(_HERE, "capture_vs_render_probe_837")
os.makedirs(OUT, exist_ok=True)
FINDINGS: dict = {"port": PORT}
UNTONED = "Un-tone-mapped (sRGB)"


def save() -> None:
    with open(os.path.join(OUT, "findings.json"), "w", encoding="utf-8") as fh:
        json.dump(FINDINGS, fh, indent=1, default=str)


def show(label: str, value) -> None:
    FINDINGS[label] = value
    save()
    print("\n--- %s ---" % label, flush=True)
    print(json.dumps(value, indent=1, sort_keys=True, default=str), flush=True)


def frame_of(command: str, params: dict, timeout_s: float = 300.0) -> dict:
    return call(command, params, timeout_s=timeout_s, port=PORT)


def ok(command: str, params: dict, timeout_s: float = 300.0) -> dict:
    frame = frame_of(command, params, timeout_s)
    if frame.get("status") != "ok":
        raise RuntimeError("%s failed: %s"
                           % (command, json.dumps(frame.get("error"), indent=1)))
    return frame.get("result") or {}


def py(code: str, timeout_s: float = 120.0):
    body = textwrap.dedent(code).strip() + "\nr"
    res = ok("execute_python", {"code": body}, timeout_s=timeout_s)
    if res.get("traceback"):
        raise RuntimeError("execute_python raised:\n" + res["traceback"])
    return structured_result(res, "r")


def attempt(label: str, fn):
    """Record the value or the failure, never stop the run."""
    try:
        value = fn()
    except BaseException as exc:  # noqa: BLE001 - a probe records, it does not die
        value = {"error": "%s: %s" % (type(exc).__name__, str(exc)[:600]),
                 "trace": traceback.format_exc()[-800:]}
    show(label, value)
    return value


def lit_value(png_bytes: bytes) -> dict:
    """Modal lit colour (RGB) - the plane does not fill the frame."""
    from PIL import Image

    image = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    colors = image.getcolors(maxcolors=image.width * image.height) or []
    lit = sorted((c for c in colors if sum(c[1]) > 12), reverse=True)
    return {"modal_rgb": list(lit[0][1]) if lit else None,
            "modal_count": lit[0][0] if lit else 0,
            "size": [image.width, image.height]}


def first_png(result: dict) -> bytes:
    for key in ("images", "frames", "captures", "shots"):
        items = result.get(key)
        if isinstance(items, list) and items:
            item = items[0]
            for pkey in ("png_b64", "image_b64", "b64"):
                if item.get(pkey):
                    return base64.b64decode(item[pkey])
    raise RuntimeError("no image in result keys %s" % sorted(result))


def save_png(name: str, data: bytes) -> str:
    path = os.path.join(OUT, name + ".png")
    with open(path, "wb") as fh:
        fh.write(data)
    return path


# ---------------------------------------------------------------- Q1: prefs

ok("new_scene", {"confirm": True})

attempt("Q1_prefs", lambda: py("""
    import maya.cmds as cmds
    r = {}
    for flag in ("cmEnabled", "viewTransformName", "viewName", "displayName",
                 "renderingSpaceName", "outputTransformEnabled",
                 "outputTransformName", "outputUseViewTransform",
                 "viewTransformNames", "configFilePath", "ocioRulesEnabled"):
        try:
            r[flag] = cmds.colorManagementPrefs(query=True, **{flag: True})
        except Exception as exc:
            r[flag] = "ERR %s" % (str(exc).strip()[:80],)
    r["maya_version"] = cmds.about(version=True)
    # the modelPanel's own colour-management state, if it has one
    try:
        panels = cmds.getPanel(type="modelPanel") or []
        r["panels"] = {p: {"cmEnabled": cmds.modelEditor(p, query=True, cmEnabled=True)}
                       for p in panels}
    except Exception as exc:
        r["panels"] = "ERR %s" % (str(exc).strip()[:80],)
    r
"""))

# ---------------------------------------------------------------- the plane

py("""
    import maya.cmds as cmds, math
    probe = cmds.directionalLight(name="calibLight", intensity=math.pi)
    cmds.xform(cmds.listRelatives(probe, parent=True, fullPath=True)[0],
               rotation=(-90, 0, 0), worldSpace=True)
    plane = cmds.polyPlane(name="calibPlane", width=20, height=20, sx=1, sy=1)[0]
    cmds.xform(plane, translation=(120, 20, 0), worldSpace=True)
    mat = cmds.shadingNode("standardSurface", asShader=True, name="calibMat")
    cmds.setAttr(mat + ".baseColor", 0.5, 0.5, 0.5, type="double3")
    cmds.setAttr(mat + ".base", 1.0)
    cmds.setAttr(mat + ".specular", 0.0)
    sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name=mat + "SG")
    cmds.connectAttr(mat + ".outColor", sg + ".surfaceShader", force=True)
    cmds.sets(plane, edit=True, forceElement=sg)
    r = {"plane": plane}
""")


def set_albedo(value: float) -> None:
    py("""
        import maya.cmds as cmds
        cmds.setAttr("calibMat.baseColor", %r, %r, %r, type="double3")
        r = cmds.getAttr("calibMat.baseColor")
    """ % (value, value, value))


def render() -> dict:
    result = ok("render_scene", {"isolate": ["calibPlane"], "angles": ["top"],
                                 "relight": False, "fallback_light": False,
                                 "resolution": 256, "samples": 3}, 600)
    out = lit_value(first_png(result))
    out["warnings"] = result.get("warnings")
    return out


def capture(lighting: str, tag: str) -> dict:
    result = ok("capture_viewport", {"isolate": ["calibPlane"], "angles": ["top"],
                                     "lighting": lighting, "resolution": 256}, 300)
    png = first_png(result)
    out = lit_value(png)
    out["png"] = save_png(tag, png)
    out["warnings"] = result.get("warnings")
    out["result_keys"] = sorted(result)
    return out


def with_view_transform(name: str, fn):
    before = py("""
        import maya.cmds as cmds
        r = cmds.colorManagementPrefs(query=True, viewTransformName=True)
    """)
    try:
        applied = py("""
            import maya.cmds as cmds
            cmds.colorManagementPrefs(edit=True, viewTransformName=%r)
            r = cmds.colorManagementPrefs(query=True, viewTransformName=True)
        """ % name)
        out = fn()
        out["applied_view"] = applied
        return out
    finally:
        py("""
            import maya.cmds as cmds
            cmds.colorManagementPrefs(edit=True, viewTransformName=%r)
            r = 1
        """ % before)


def with_output_transform(name: str, fn):
    saved = py("""
        import maya.cmds as cmds
        r = {"enabled": cmds.colorManagementPrefs(query=True, outputTransformEnabled=True),
             "name": cmds.colorManagementPrefs(query=True, outputTransformName=True),
             "use_view": cmds.colorManagementPrefs(query=True, outputUseViewTransform=True)}
    """)
    try:
        applied = py("""
            import maya.cmds as cmds
            cmds.colorManagementPrefs(edit=True, outputUseViewTransform=False)
            cmds.colorManagementPrefs(edit=True, outputTransformName=%r)
            cmds.colorManagementPrefs(edit=True, outputTransformEnabled=True)
            r = {"enabled": cmds.colorManagementPrefs(query=True, outputTransformEnabled=True),
                 "name": cmds.colorManagementPrefs(query=True, outputTransformName=True),
                 "use_view": cmds.colorManagementPrefs(query=True, outputUseViewTransform=True)}
        """ % name)
        out = fn()
        out["applied_output"] = applied
        return out
    finally:
        py("""
            import maya.cmds as cmds
            cmds.colorManagementPrefs(edit=True, outputTransformEnabled=%r)
            cmds.colorManagementPrefs(edit=True, outputTransformName=%r)
            cmds.colorManagementPrefs(edit=True, outputUseViewTransform=%r)
            r = 1
        """ % (bool(saved["enabled"]), saved["name"], bool(saved["use_view"])))


def srgb(v: float) -> int:
    return round(255 * (1.055 * v ** (1 / 2.4) - 0.055) if v > 0.0031308
                 else 255 * 12.92 * v)


for albedo in (0.5, 0.028):
    set_albedo(albedo)
    tag = "albedo_%s" % str(albedo).replace(".", "p")
    show(tag + "_expected", {"albedo": albedo, "srgb_expected": srgb(albedo)})
    attempt(tag + "_render_scene", render)
    attempt(tag + "_capture_scene", lambda: capture("scene", tag + "_capture_scene"))
    attempt(tag + "_capture_default", lambda: capture("default", tag + "_capture_default"))
    attempt(tag + "_capture_scene_view_untoned", lambda: with_view_transform(
        UNTONED, lambda: capture("scene", tag + "_capture_view_untoned")))
    attempt(tag + "_capture_scene_output_untoned", lambda: with_output_transform(
        UNTONED, lambda: capture("scene", tag + "_capture_output_untoned")))
    attempt(tag + "_capture_scene_view_raw", lambda: with_view_transform(
        "Raw (sRGB)", lambda: capture("scene", tag + "_capture_view_raw")))

ok("new_scene", {"confirm": True})
print("\nfindings ->", os.path.join(OUT, "findings.json"), flush=True)
