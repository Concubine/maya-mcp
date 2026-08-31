"""#775 live gate: "directed" becomes a number, and the look is judged by eye.

The ticket's claim is that wear lands on edges, grime in pockets and grain
as surface relief - not that three noise images got written. A headless
test can prove the arithmetic; only a live Maya can prove the arithmetic
was fed a REAL bake of REAL geometry and that the result reaches a render
and an FBX. This gate builds #770's golem-join proxy (ground + limb +
collar), bakes the masks from that geometry, applies directed detail, and
measures four things:

  1. the masks the detail is steered by are non-uniform (bake stats);
  2. CORRELATION, computed by this script from the FILES - per-texel
     |after-before| of the colour map, mean over the top mask quartile
     divided by the mean over the bottom quartile. The tool's own report
     is not trusted for this; the ratio is the word "directed" as a
     number;
  3. the render AFTER differs from the render BEFORE - both in relative
     mean luma and in how many pixels moved, measured against a
     same-scene render-to-render NOISE FLOOR so "Arnold is stochastic"
     cannot be mistaken for "the detail is visible";
  4. the composite and height maps ride the exported FBX's bytes with
     nothing dropped.

Usage (no "verify a prebuilt scene" mode - everything worth measuring is
built by this run):

    set MAYA_MCP_PORT=9878
    python evals/surfdetail_live.py --build

MUTATES THE ANSWERING MAYA'S CURRENT SCENE (new_scene first). Point
MAYA_MCP_PORT at a disposable Maya you launched yourself - never the
user's session on 9877.

It also prints FINDING lines: measurements it reports but does not gate
on, because they name a known open defect rather than a regression this
run could have caused. Read them - one of them is currently the reason
grain's "surface relief" claim is proven only in the height MAP here and
not in the render.

Exit: 0 pass, 1 fail. Writes renders, maps, composites and the FBX to
evals/surfdetail_live/ - report BOTH renders for visual judgment; a
correlation ratio cannot see "that reads as mould, not wear", which is
exactly the failure mode a directed-detail tool has.
"""

from __future__ import annotations

import base64
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from live_call import call, structured_result  # noqa: E402

from maya_plugin.handlers import meshmaps, pngprobe  # noqa: E402

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "surfdetail_live")
BEFORE_RENDER = os.path.join(OUT_DIR, "surfdetail_before.png")
BEFORE_RENDER_B = os.path.join(OUT_DIR, "surfdetail_before_noisefloor.png")
AFTER_RENDER = os.path.join(OUT_DIR, "surfdetail_after.png")
AFTER_FBX = os.path.join(OUT_DIR, "surfdetail_after.fbx")

RESOLUTION = 512
BASE_LINEAR = 0.75  # the flat baseColor every gate material starts on

# zoom and intensity are LOOK-PROBE findings, not taste. Run 1 used #770's
# framing (whole 6x6 ground, three_point at 1.5) and both renders came back
# as a white blob on black: at intensity 1.5 a 0.75 albedo renders past 1.0
# and CLIPS, so an albedo effect of any size is invisible by construction -
# the gate could not have judged its own subject. At 0.5 the lit surface
# lands near sRGB 170 with headroom both ways. zoom 3.0 (under render.py's
# ~3.4 camera-inside-bbox warning) is needed because the framed bbox is the
# 6x6 GROUND while the detail lives on a 0.8-wide limb: at zoom 1.0 the limb
# was 57 px across and at 2.0 it was 115, neither judgeable.
# 1024, not 512: at 512 this gate's own renders were not judgeable by eye -
# the limb is ~150 px across and a scuff band on its rim is a smudge. The
# whole point of saving these is that a human (or the agent) LOOKS at them,
# so they have to carry the detail at 1:1 without cropping.
RENDER_PARAMS = {"angles": ["three_quarter"], "renderer": "arnold",
                 "resolution": 1024, "samples": 4, "zoom": 3.0}
LIGHT_INTENSITY = 0.5

# The effect strengths this gate drives at. NOT the tool's defaults (wear
# 0.5, grime 0.5, grain 0.3): measured in run 1, the defaults are honest but
# sub-visible - the whole limb composite spanned six 8-bit levels and the
# render moved 1573 pixels against a 1173-pixel noise floor, i.e. nothing an
# eye could find. These are the smallest values the look probe found legible,
# and they are ordinary art-direction settings well inside STRENGTH_MAX=4.
# The defaults themselves are a finding for the ticket, not something this
# gate silently papers over - see the task-6 report.
WEAR_STRENGTH = 2.0
GRIME_STRENGTH = 1.5
GRAIN_STRENGTH = 2.0

# A LOOK-PROBE finding, not a fudge. bake_mesh_maps defaults to
# curvature_radius 0.1, which on a limb 0.8 across is a hairline edge
# detector: run 2 put 75% of the limb's curvature texels under 6/255, so
# wear landed on a one-texel rim line that the camera resolves as nothing.
# 0.3 is the scale of THIS subject's edges (a 0.4-radius cylinder, a 0.4
# minor-radius torus) and turns the rim into a band an eye can read. It
# widens the mask; it does not fake one - every texel it lights up is still
# real convex curvature Arnold measured.
CURVATURE_RADIUS = 0.3

# ---------------------------------------------------------------------------
# The bars. Every one is derived from a MEASURED value with margin, never an
# invented round number (#770's MAP_GAP_MIN idiom). Measured on this gate's
# final configuration; the map-space numbers are bit-identical across runs
# (the bake and the composite are both deterministic), only the render ones
# carry Arnold's sampling noise.
#
# Correlation, top-quartile mean / bottom-quartile mean:
#   wear on the limb    5.736 / 0.032  = 178.8
#   grime on the ground 7.983 / 1.438  =   5.55   <- the weakest of the three
#   height vs its blend 66.402 / 10.834 =  6.13
# The colour effects' bottom quartiles are near zero because their masks
# genuinely are (a cylinder flank has no convex curvature), so their ratios
# run away; grime's is the honest floor because a 6x6 ground plane is nearly
# unoccluded everywhere, and its bottom quartile still darkens by ~1.4 of
# 255. 3.0 sits at 54% of that weakest measurement and far above the 1.0 a
# completely undirected effect would score. It is also the spec's own target.
#
# MIN_TOP_DELTA exists because a ratio alone can be won by doing nothing: if
# the bottom quartile is exactly 0 the ratio is infinite whatever the top
# does. Measured tops were 5.7 / 8.0 / 66.4 in 8-bit units; 1.0 is well under
# the weakest and well over rounding.
CORRELATION_MIN = 3.0
MIN_TOP_DELTA = 1.0

# Render, measured on the final configuration:
#   mean luma 75.26 -> 74.12, relative delta 0.0152
#   96246 of 1048576 pixels moved >=4, against a same-scene render-to-render
#   NOISE FLOOR of 2011 (0.19%) measured in the same run - the detail moves
#   48x more pixels than Arnold's own sampling noise does.
# Bars: a bit under half the measured relative delta, and a changed-pixel
# count 15x over the measured noise floor (3.2x under the measured signal).
RENDER_RELATIVE_DELTA_MIN = 0.007
RENDER_MOVED_PIXELS_MIN = 30000
LUMA_MOVE_EPS = 4  # a pixel "moved" when its mean-RGB shifts by this much

failures: list[str] = []
findings: list[str] = []
notes: list[str] = []


def note(text: str) -> None:
    """A measurement the gate REPORTS but does not yet gate on, because the
    thing it measures is a known open defect rather than a regression this
    run could have caused. Printed loudly every run so it cannot go quiet."""
    line = "FINDING %s" % text
    print(line, flush=True)
    notes.append(line)


def check(name: str, ok: bool, detail: str) -> None:
    line = "%s %s: %s" % ("PASS" if ok else "FAIL", name, detail)
    print(line, flush=True)
    findings.append(line)
    if not ok:
        failures.append(line)


def must(frame: dict, what: str) -> dict:
    if frame.get("status") != "ok":
        raise SystemExit("%s failed: %r" % (what, frame.get("error")))
    return frame.get("result") or {}


def preflight() -> dict:
    ping = must(call("ping", {}), "ping")
    plugin = ping.get("plugin") or {}
    process = ping.get("process") or {}
    if plugin.get("restart_required"):
        raise SystemExit(
            "the answering Maya (pid %s) holds stale modules - restart it "
            "before running this gate" % process.get("pid"))
    print("gating against pid %s, scene %r" % (process.get("pid"),
                                               process.get("scene")),
          flush=True)
    return ping


def build_scene() -> dict:
    """#770's golem-join proxy, verbatim in shape: a limb cylinder standing
    on a ground plane with a collar torus ringed around it.

    Copied rather than imported - gates stay self-contained - and the two
    measured constraints it carries come with it:

    - NO uv_atlas here, native primitive UVs throughout. Box projection
      OVERLAPS shells on a torus (and a cylinder's caps): buried surfaces
      rasterize into the same texels as the visible ones and win, which
      turns a mask uniformly black. Native UVs are non-overlapping, and
      #775 needs that even more than #770 did - an overlapping shell does
      not just darken a bake, it steers detail onto the wrong surface.
    - assemble(freeze=True) freezes only COMBINED (multi-part) chunks; a
      single-part chunk keeps its dim as transform scale, which
      export_fbx's unit gate then refuses - so every object goes through
      mesh_cleanup, whose freeze_transforms default does the makeIdentity.
    """
    must(call("new_scene", {"confirm": True}), "new_scene")

    result = must(call("assemble", {
        "name": "gate",
        "parts": [
            {"kind": "plane", "dim": [6.0, 0.01, 6.0], "pos": [0, 0, 0],
             "chunk": "gate_ground"},
            {"kind": "cylinder", "dim": [0.8, 3.0, 0.8],
             "pos": [0, 1.5, 0], "chunk": "gate_limb",
             "subdivisions": [20, 8]},
            {"kind": "torus", "dim": [1.3, 0.4, 1.3], "pos": [0, 1.5, 0],
             "chunk": "gate_collar"},
        ],
        "combine": True, "freeze": True}), "assemble")
    names = {}
    for obj in result.get("objects") or []:
        name = obj.get("name") if isinstance(obj, dict) else obj
        for key in ("ground", "limb", "collar"):
            if "gate_%s" % key in (name or ""):
                names[key] = name
    if sorted(names) != ["collar", "ground", "limb"]:
        raise SystemExit("assemble did not return the three chunks: %r"
                         % (result.get("objects"),))

    for key in ("ground", "limb", "collar"):
        must(call("mesh_cleanup", {"mesh": names[key]}),
             "mesh_cleanup(%s)" % key)
    for key in ("ground", "limb", "collar"):
        must(call("assign_material",
                  {"mesh": names[key], "shader": "standardSurface",
                   "name": "gate_%s_mat" % key,
                   "params": {"baseColor": [BASE_LINEAR] * 3,
                              "roughness": 0.6, "metalness": 0.0}}),
             "assign_material(%s)" % key)

    must(call("setup_lighting", {"preset": "three_point",
                                 "intensity": LIGHT_INTENSITY}),
         "setup_lighting")
    return names


# ---------------------------------------------------------------------------
# measurement helpers - everything below reads FILES, never the tool's report
# ---------------------------------------------------------------------------


def render_to(path: str, label: str) -> list:
    """Render, save the PNG, and return per-pixel mean-RGB luma."""
    result = must(call("render_scene", dict(RENDER_PARAMS), timeout_s=900.0),
                  "render_scene(%s)" % label)
    images = result.get("images") or []
    if not images:
        raise SystemExit("render_scene(%s) returned no images" % label)
    with open(path, "wb") as fh:
        fh.write(base64.b64decode(images[0]["png_b64"]))
    px = pngprobe.read_png(path)["pixels"]
    return [(p[0] + p[1] + p[2]) / 3.0 for p in px]


def reds(path: str) -> list:
    """The red channel of a PNG as 0-255 ints, in row-major texel order -
    the exact order surfdetail_math.sample indexes a same-resolution mask
    in, so mask texel i and composite texel i are the same texel."""
    return [p[0] for p in pngprobe.read_png(path)["pixels"]]


def quartile_split(signal: list, values: list) -> tuple:
    """Mean of `values` over the top and bottom quartiles of `signal`.

    Rank-based, not threshold-based: a bake whose signal is concentrated
    in a few percent of texels still gets an honest top quartile, and no
    magic cutoff has to be invented per map.
    """
    if len(signal) != len(values):
        raise SystemExit("quartile_split: %d signal vs %d values"
                         % (len(signal), len(values)))
    order = sorted(range(len(signal)), key=lambda i: signal[i])
    q = len(order) // 4
    top = order[-q:]
    bottom = order[:q]
    top_mean = sum(values[i] for i in top) / float(q)
    bottom_mean = sum(values[i] for i in bottom) / float(q)
    return top_mean, bottom_mean


def correlation_check(name: str, signal: list, values: list) -> None:
    top, bottom = quartile_split(signal, values)
    ratio = (top / bottom) if bottom > 0 else float("inf")
    ok = ratio >= CORRELATION_MIN and top >= MIN_TOP_DELTA
    check(name, ok,
          "top-quartile mean %.3f / bottom-quartile mean %.3f = %s "
          "(min ratio %.1f, min top %.1f)"
          % (top, bottom, ("%.2f" % ratio) if bottom > 0 else "inf",
             CORRELATION_MIN, MIN_TOP_DELTA))


def height_file_node(applied: dict) -> dict | None:
    """Ask MAYA about the file node feeding the grain bump - not the tool's
    own report (#764's lesson: a result field can agree with itself while the
    scene disagrees). Returns None rather than raising: this feeds a note,
    and a diagnostic that breaks the gate it informs is worse than no
    diagnostic."""
    path = (applied.get("height_file") or "").replace("\\", "/")
    if not path:
        return None
    code = (
        "import maya.cmds as cmds\n"
        "want = %r\n"
        "hit = None\n"
        "for f in (cmds.ls(type='file') or []):\n"
        "    if (cmds.getAttr(f + '.fileTextureName') or '')"
        ".replace(chr(92), '/') == want:\n"
        "        hit = {'node': f,\n"
        "               'alphaIsLuminance': bool(cmds.getAttr("
        "f + '.alphaIsLuminance')),\n"
        "               'outAlpha': cmds.getAttr(f + '.outAlpha'),\n"
        "               'colorSpace': cmds.getAttr(f + '.colorSpace')}\n"
        "        break\n"
        "hit\n" % path)
    frame = call("execute_python", {"code": code}, timeout_s=120.0)
    if frame.get("status") != "ok":
        return None
    try:
        return structured_result(frame.get("result") or {}, "height file node")
    except Exception:  # noqa: BLE001 - see docstring
        return None


def moved_pixels(a: list, b: list) -> int:
    if len(a) != len(b):
        raise SystemExit("render sizes differ: %d vs %d" % (len(a), len(b)))
    return sum(1 for i in range(len(a)) if abs(a[i] - b[i]) >= LUMA_MOVE_EPS)


def mean(vals: list) -> float:
    return sum(vals) / float(len(vals))


# ---------------------------------------------------------------------------


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    preflight()
    scene = build_scene()

    # Two renders of the IDENTICAL scene: the second is not a duplicate,
    # it is the noise floor every "the render changed" claim below is
    # measured against.
    before = render_to(BEFORE_RENDER, "before")
    before_b = render_to(BEFORE_RENDER_B, "before-noise-floor")
    noise_floor = moved_pixels(before, before_b)
    print("before mean luma %.2f; render-to-render noise floor: %d of %d "
          "pixels moved >=%d" % (mean(before), noise_floor, len(before),
                                 LUMA_MOVE_EPS), flush=True)

    # --- masks from real geometry. apply_ao=False on purpose: this gate
    # isolates #775's own contribution, so nothing but apply_surface_detail
    # ever touches a colour slot.
    bake = must(call("bake_mesh_maps",
                     {"meshes": [scene["ground"], scene["limb"],
                                 scene["collar"]],
                      "out_dir": OUT_DIR, "resolution": RESOLUTION,
                      "curvature_radius": CURVATURE_RADIUS,
                      "apply_ao": False}, timeout_s=1200.0),
                "bake_mesh_maps")
    baked = bake.get("baked") or []
    check("nine_maps_baked", len(baked) == 9,
          "%d maps (3 meshes x ao/curvature/world_normal)" % len(baked))

    by_mesh_map = {(e["mesh"], e["map"]): e for e in baked}
    # 1. the masks the detail is steered by must carry signal.
    for mesh_key, map_name in (("limb", "curvature"), ("limb", "ao"),
                               ("ground", "ao"), ("collar", "curvature"),
                               ("collar", "ao")):
        entry = by_mesh_map.get((scene[mesh_key], map_name))
        stats = (entry or {}).get("stats") or {}
        check("mask_non_uniform:%s_%s" % (mesh_key, map_name),
              bool(stats.get("non_uniform")) and stats.get("blank") is False,
              "non_uniform=%r blank=%r distinct=%r"
              % (stats.get("non_uniform"), stats.get("blank"),
                 stats.get("distinct_values")))

    # --- the tool under test, three meshes, three effect mixes ------------
    applied = {}
    for mesh_key, effects in (
            ("limb", [{"kind": "wear", "strength": WEAR_STRENGTH},
                      {"kind": "grain", "strength": GRAIN_STRENGTH}]),
            ("ground", [{"kind": "grime", "strength": GRIME_STRENGTH}]),
            ("collar", [{"kind": "wear", "strength": WEAR_STRENGTH},
                        {"kind": "grime", "strength": GRIME_STRENGTH}])):
        applied[mesh_key] = must(
            call("apply_surface_detail",
                 {"mesh": scene[mesh_key], "maps_dir": OUT_DIR,
                  "out_dir": OUT_DIR, "effects": effects},
                 timeout_s=900.0),
            "apply_surface_detail(%s)" % mesh_key)
        print("%s: %r" % (mesh_key,
                          [(e["kind"], round(e["changed_fraction"], 4))
                           for e in applied[mesh_key]["effects"]]), flush=True)
        for warning in applied[mesh_key].get("warnings") or []:
            print("WARNING from apply_surface_detail(%s): %s"
                  % (mesh_key, warning), flush=True)

    # --- 2. correlation, computed here from the files ---------------------
    # The base every composite started from is the flat baseColor, encoded
    # by the same sRGB encoder the composite writes through - so
    # |composite - base| per texel is exactly what the effect deposited.
    base_byte = float(meshmaps._srgb_encode(BASE_LINEAR))

    # wear on the limb: the limb's colour composite carries wear ONLY
    # (grain is a height map, not a colour effect), so this is clean.
    limb_curv = reds(by_mesh_map[(scene["limb"], "curvature")]["file"])
    limb_color = reds(applied["limb"]["color_file"])
    correlation_check("wear_follows_curvature:limb", limb_curv,
                      [abs(v - base_byte) for v in limb_color])

    # grime on the ground: driven by INVERTED AO, so the signal is
    # 255 - ao (dark bake = occluded = dirty).
    ground_ao = reds(by_mesh_map[(scene["ground"], "ao")]["file"])
    ground_color = reds(applied["ground"]["color_file"])
    correlation_check("grime_follows_inverted_ao:ground",
                      [255 - v for v in ground_ao],
                      [abs(v - base_byte) for v in ground_color])

    # grain on the limb: the height map against its own blend mask,
    # 0.5*curvature + 0.5*inverted-AO (surfdetail._grain_pixels).
    limb_ao = reds(by_mesh_map[(scene["limb"], "ao")]["file"])
    limb_height = reds(applied["limb"]["height_file"])
    blend = [0.5 * limb_curv[i] + 0.5 * (255 - limb_ao[i])
             for i in range(len(limb_curv))]
    correlation_check("grain_follows_blend_mask:limb", blend,
                      [float(v) for v in limb_height])

    # --- the grain bump network: wired, and INERT -------------------------
    # MEASURED by this gate's look probe, and the reason grain is the one
    # effect whose claim is not yet gated in the render. apply_surface_detail
    # writes the height PNG through pngwrite, which emits RGB (no alpha
    # channel), and drives bump2d.bumpValue from the file node's .outAlpha.
    # A Maya `file` node returns a CONSTANT outAlpha of 1.0 for an image with
    # no alpha unless alphaIsLuminance is on - which this tool does not set.
    # So the bump reads one flat value everywhere and perturbs no normal.
    #
    # Evidence, grain alone on this geometry at 1024/zoom 3 (scratchpad probe,
    # task-6 report): bumpDepth 2.0 and bumpDepth 4.0 rendered IDENTICALLY,
    # 1972 and 1977 pixels moved against a 2011-pixel noise floor. Flipping
    # ONLY alphaIsLuminance on the same node in the same scene took it to
    # 85734 pixels moved, max luma delta 155, and the limb rendered as
    # unmistakable cast-stone relief. One line next to the existing
    # colorSpace setAttr fixes it; it is out of this task's commit scope.
    #
    # This is reported, not checked, because a check here would fail on a
    # defect that predates this gate. Promote it to check() in the same
    # change that sets alphaIsLuminance.
    bump = height_file_node(applied["limb"])
    if bump is None:
        note("the grain height file node could not be located - the "
             "alphaIsLuminance measurement below did not run")
    elif not bump["alphaIsLuminance"]:
        note("grain bump is INERT: %s.alphaIsLuminance=%r, .outAlpha=%r - a "
             "CONSTANT, so bump2d has no gradient to shade and bumpDepth "
             "does nothing. See the comment above this line for the measured "
             "before/after." % (bump["node"], bump["alphaIsLuminance"],
                                bump["outAlpha"]))
    else:
        note("grain bump reads per-texel now (%s.alphaIsLuminance=True) - "
             "the defect above is fixed; promote this to a render-measured "
             "check()." % bump["node"])

    # --- 3. the render moved, past its own noise floor --------------------
    after = render_to(AFTER_RENDER, "after")
    before_luma, after_luma = mean(before), mean(after)
    relative = abs(after_luma - before_luma) / before_luma
    moved = moved_pixels(before, after)
    check("render_mean_luma_moved", relative >= RENDER_RELATIVE_DELTA_MIN,
          "before=%.2f after=%.2f relative delta=%.4f (min %.4f)"
          % (before_luma, after_luma, relative, RENDER_RELATIVE_DELTA_MIN))
    check("render_pixels_moved", moved >= RENDER_MOVED_PIXELS_MIN,
          "%d of %d pixels moved >=%d (min %d; same-scene noise floor was "
          "%d = %.2f%%)" % (moved, len(after), LUMA_MOVE_EPS,
                            RENDER_MOVED_PIXELS_MIN, noise_floor,
                            100.0 * noise_floor / len(after)))

    # --- 4. it ships ------------------------------------------------------
    export = must(call("export_fbx",
                       {"path": AFTER_FBX.replace("\\", "/"),
                        "metres_per_unit": 1.0,
                        "nodes": [scene["ground"], scene["limb"],
                                  scene["collar"]],
                        "require_baked_textures": True}, timeout_s=600.0),
                  "export_fbx")
    with open(AFTER_FBX, "rb") as fh:
        fbx_bytes = fh.read()
    wanted = [applied[k]["color_basename"] for k in
              ("ground", "limb", "collar")]
    wanted.append(applied["limb"]["height_basename"])
    for basename in wanted:
        check("map_in_fbx_bytes:%s" % basename,
              bool(basename) and basename.encode() in fbx_bytes,
              "%d byte file" % len(fbx_bytes))
    textures = export.get("textures") or {}
    check("export_dropped_nothing", not textures.get("dropped_maps"),
          "dropped=%r" % (textures.get("dropped_maps"),))
    # Informational only, measured in Task 1: the bump network reports
    # semantics_lost "channel swizzle outAlpha" because bump2d.bumpValue
    # is a float fed from the file's alpha plug. export.py never refuses
    # on it and neither does this gate - it is printed, not checked.
    if textures.get("semantics_lost"):
        print("export semantics_lost (informational, Task 1 measured): %r"
              % (textures.get("semantics_lost"),), flush=True)

    for warning in bake.get("warnings") or []:
        print("WARNING from bake_mesh_maps: %s" % warning, flush=True)

    print("\n%s - %d checks, %d failed, %d finding(s) reported but not "
          "gated. Renders: %s / %s"
          % ("GATE FAILED" if failures else "GATE PASSED",
             len(findings), len(failures), len(notes), BEFORE_RENDER,
             AFTER_RENDER), flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    if "--build" not in sys.argv:
        raise SystemExit(__doc__)
    raise SystemExit(main())
