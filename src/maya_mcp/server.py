"""maya-mcp MCP server: tool schemas over the wire to the Maya plugin.

Every tool is a thin, validated wrapper around a plugin command. Perception
beats actuation: capture_viewport is THE critical tool; everything else exists
to give the LLM something worth looking at.

Run: `uv run maya-mcp` (stdio transport). Config via MAYA_MCP_* env vars.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Annotated, Dict, List, Literal, Optional, Union

from mcp.server import MCPServer
from mcp.server.mcpserver import Image
from mcp.types import ToolAnnotations
from pydantic import Field

# The plugin package ships in the same wheel (pyproject: hatch packages both),
# and logsetup is deliberately dependency-free so the deployed plugin copy -
# which cannot import maya_mcp - keeps working standalone. One implementation
# beats two copies of a rollover fix, one of which would rot.
from maya_plugin import logsetup

from . import images, refstore
from .connection import MayaConnection
from .schemas import (
    ArrayResult,
    AssembleResult,
    CombineResult,
    UvAtlasResult,
    BooleanResult,
    CameraResult,
    CheckpointResult,
    CleanupResult,
    DeformResult,
    DeleteResult,
    ExecuteResult,
    ExportFbxResult,
    LightingResult,
    MaterialResult,
    NameResult,
    NewSceneResult,
    ObjectInfoResult,
    OpenSceneResult,
    PbrResult,
    PoseSkeletonResult,
    ReferenceResult,
    RemeshResult,
    RenderedFrame,
    RenderResult,
    ResetNamespaceResult,
    ResetPoseResult,
    RestoreResult,
    SaveSceneResult,
    SceneGraphResult,
    SculptResult,
    CreateSkeletonResult,
    BindSkinResult,
    TextureRecipeResult,
    TransformResult,
    UndoResult,
    ViewportState,
)

log = logging.getLogger("maya_mcp.server")

Angle = Literal["front", "side", "back", "top", "three_quarter", "current"]
ShadingMode = Literal["smoothShaded", "flatShaded", "wireframe", "textured"]
Vec3 = Annotated[
    Optional[List[float]],
    Field(min_length=3, max_length=3, description="XYZ triple."),
]

# Transport grace on top of the per-command timeout the plugin enforces itself.
SCENE_TIMEOUT_S = 30.0
CAPTURE_TIMEOUT_S = 120.0
# A rendered frame is seconds, not milliseconds, and four of them at high
# sample counts is minutes - a capture-sized timeout would kill good renders.
# The default the render tools use when the caller says nothing.
RENDER_TIMEOUT_S = 600.0
# The ceiling, and the dispatcher's MAX_TIMEOUT_S exactly: asking for more is
# silently clamped there, so the two must move together. Both render tools take
# a timeout_s now - a 29-cell Arnold sheet exceeded the old 600 s ceiling, and
# the timeout error told the caller to pass a larger timeout_s that no schema
# offered and no ceiling would have honoured (#640).
MAX_RENDER_TIMEOUT_S = 1800.0
BOOL_TIMEOUT_S = 120.0
# A heavy scene takes tens of seconds to write, and the handler then re-reads
# and composes every vertex in the file before it answers.
EXPORT_TIMEOUT_S = 300.0


def _setup_logging() -> None:
    """One log file per process: `server-<pid>.log`.

    A server is spawned per MCP client, so two clients used to share one
    `server.log` and hit exactly the rollover deadlock #650 describes for the
    plugin. Same cause, same fix, same module.
    """
    logsetup.configure(logging.getLogger("maya_mcp"), "server")


# Image tools that can produce more than one frame per call name their files
# by label; the sheet tools produce one image and use `path` as given. Both go
# through _write_frames, so the reporting line is identical across all four.
def _resolve_path(path: Optional[str]) -> Optional[str]:
    """Validate an output path BEFORE Maya is asked to do anything.

    A rendered frame costs seconds; a contact sheet costs seconds times the
    kit. Discovering a typo'd path after the pixels exist would throw all of
    that away, so this runs first - the same discipline export_fbx states as
    "a bad call must cost nothing".
    """
    return images.resolve_output_path(path) if path is not None else None


def _write_frames(path: Optional[str], labels, pngs) -> Optional[str]:
    """Write full-resolution frames to an already-resolved path.

    Returns the line describing them, or None when no path was asked for. The
    bytes written are the ones the plugin produced, NOT the copy downscaled for
    the message: a deliverable that came back at 768px because that is what an
    LLM can read would be a strange thing to have asked Maya to render at 2048
    (#639).
    """
    if path is None:
        return None
    written = [
        images.write_png(out, png)
        for out, png in zip(images.label_paths(path, labels), pngs)
    ]
    return "wrote: " + json.dumps(written)


def create_server(conn: Optional[MayaConnection] = None) -> MCPServer:
    """Build the MCPServer; the connection is injectable for tests."""
    maya = conn if conn is not None else MayaConnection()
    # Per-server-process, not per-scene: references survive new_scene, never
    # dirty the user's file, and cannot be destroyed by a scene operation.
    # Scoped to this create_server() call (like `maya` above) so tests that
    # build multiple servers don't share loaded references.
    _references = refstore.ReferenceStore()
    mcp = MCPServer(
        "maya-mcp",
        instructions=(
            "Tools for modeling in a live Autodesk Maya session. Work iteratively: "
            "after each significant change, call maya_capture_viewport and correct "
            "what you see before adding detail. maya_execute_python runs arbitrary "
            "maya.cmds code with a persistent namespace; errors return complete "
            "tracebacks - read them, they are how you debug."
        ),
    )

    @mcp.tool(
        title="Execute Python in Maya",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=False
        ),
    )
    def maya_execute_python(
        code: Annotated[
            str,
            Field(description=(
                "Python source to execute inside Maya. `cmds` (maya.cmds), `mel`, "
                "and `pm` (pymel, if installed) are pre-imported. The namespace "
                "persists across calls. If the code ends in a bare expression its "
                "repr is returned as result_repr."
            )),
        ],
        timeout_s: Annotated[
            int, Field(ge=1, le=300, description="Seconds before the call times out.")
        ] = 30,
        risky: Annotated[
            bool,
            Field(description=(
                "Set true for operations that could damage the scene; an automatic "
                "checkpoint is saved first."
            )),
        ] = False,
    ) -> ExecuteResult:
        """Run arbitrary Python in the Maya session (persistent namespace).

        Returns stdout, stderr, result_repr, a complete verbatim traceback when
        the code raised (None otherwise), and the namespace keys.

        Output is capped - stdout/stderr at 8 KB, result_repr at 256 KB - and
        every cap reports itself: check result_truncated before parsing
        result_repr, because a truncated repr is not valid Python and will fail
        inside your parser rather than here. If a measurement is genuinely that
        large, have the code write it to a file and return the path.
        """
        return ExecuteResult.model_validate(
            maya.request(
                "execute_python",
                {"code": code, "timeout_s": timeout_s, "risky": risky},
                timeout_s=float(timeout_s),
            )
        )

    @mcp.tool(
        title="Get scene graph",
        annotations=ToolAnnotations(
            read_only_hint=True, destructive_hint=False, idempotent_hint=True
        ),
    )
    def maya_get_scene_graph(
        filter: Annotated[
            Optional[str],
            Field(description=(
                "Case-insensitive substring match on object name or type "
                '(e.g. "mesh", "light", "golem"). Omit for everything.'
            )),
        ] = None,
        max_objects: Annotated[
            int, Field(ge=1, le=500, description="Page size; paginate via cursor.")
        ] = 200,
        cursor: Annotated[
            Optional[str],
            Field(description="Opaque cursor from a previous call to fetch the next page."),
        ] = None,
    ) -> SceneGraphResult:
        """Compact outline of the scene: transforms/shapes with stats, never raw
        component data. Names are canonical long names (|group|node) — use them
        verbatim in follow-up calls."""
        return SceneGraphResult.model_validate(
            maya.request(
                "get_scene_graph",
                {"filter": filter, "max_objects": max_objects, "cursor": cursor},
                timeout_s=SCENE_TIMEOUT_S,
            )
        )

    @mcp.tool(
        title="Get object info",
        annotations=ToolAnnotations(
            read_only_hint=True, destructive_hint=False, idempotent_hint=True
        ),
    )
    def maya_get_object_info(
        name: Annotated[str, Field(min_length=1, description=(
            "Canonical long name, e.g. |golem|torso."
        ))],
        include: Annotated[
            List[Literal["transform", "mesh_stats", "uvs", "shading", "history"]],
            Field(description=(
                "Sections to return. uvs and history are summaries (counts and "
                "node types), never raw component data."
            )),
        ] = ["transform", "mesh_stats"],
    ) -> ObjectInfoResult:
        """Read one object's transform, mesh stats, UV sets, shading, or history.

        The shading section is how you verify a material actually landed."""
        return ObjectInfoResult.model_validate(
            maya.request(
                "get_object_info",
                {"name": name, "include": list(include)},
                timeout_s=SCENE_TIMEOUT_S,
            )
        )

    @mcp.tool(
        title="Capture viewport",
        annotations=ToolAnnotations(
            read_only_hint=True, destructive_hint=False, idempotent_hint=True
        ),
    )
    def maya_capture_viewport(
        angles: Annotated[
            List[Angle],
            Field(description=(
                "Up to 4 angles per call. 'current' uses the active camera "
                "unchanged; the rest frame the scene from canonical directions."
            )),
        ] = ["front", "side", "three_quarter"],
        shading: Annotated[
            Literal["smoothShaded", "flatShaded", "wireframe", "textured"],
            Field(description=(
                "Viewport shading mode for the capture. 'textured' reveals "
                "texture/bump networks; 'flatShaded' reveals facets and "
                "hard-surface reads (per-face normals, no interpolation); "
                "'smoothShaded' (the default) hides BOTH - a faceted gem or a "
                "bump map look identical to a plain shaded blob in it."
            )),
        ] = "smoothShaded",
        wireframe_overlay: Annotated[
            bool,
            Field(description="Overlay wireframe on shaded modes to judge topology."),
        ] = True,
        buffer: Annotated[
            Literal["beauty", "ssao"],
            Field(description=(
                "'ssao' enables viewport ambient occlusion - surfacing flaws hide "
                "in beauty renders and show in AO."
            )),
        ] = "beauty",
        lighting: Annotated[
            Literal["default", "scene", "flat"],
            Field(description=(
                "'scene' renders with the scene's own lights - required to judge "
                "a lit model; 'default' is Maya's headlight; 'flat' is unlit."
            )),
        ] = "default",
        shadows: Annotated[
            bool, Field(description="Viewport shadow casting; only meaningful with lighting='scene'.")
        ] = False,
        isolate: Annotated[
            Optional[List[str]],
            Field(description="Show only these objects (canonical long names)."),
        ] = None,
        target: Annotated[
            Optional[List[str]],
            Field(description=(
                "Frame ON these objects without hiding anything else — use this "
                "to close in on one part while its surroundings stay in shot. "
                "With neither target nor isolate the whole scene is framed, "
                "lights excluded."
            )),
        ] = None,
        frame_all: Annotated[
            bool, Field(description="Frame the subject before capturing.")
        ] = True,
        resolution: Annotated[
            int, Field(ge=64, le=2048, description="Capture resolution in pixels.")
        ] = 768,
        path: Annotated[
            Optional[str],
            Field(description=(
                "Absolute .png path to also WRITE the capture to, at full "
                "resolution. The parent directory must already exist. With "
                "several angles the angle name goes in before the extension: "
                "'D:/run/hero.png' writes hero_front.png, hero_side.png."
            )),
        ] = None,
    ) -> list:  # images + text; media results carry no structured-output schema
        """Capture the Maya viewport from one or more angles — your eyes.

        Returns one image per angle plus a text summary of camera positions,
        and writes the frames to disk when given a path.
        Captures are side-effect-free: all viewport state is restored."""
        if len(angles) > 4:
            raise ValueError("at most 4 angles per call; split larger captures")
        out_path = _resolve_path(path)
        result = maya.request(
            "capture_viewport",
            {
                "angles": list(angles),
                "shading": shading,
                "wireframe_overlay": wireframe_overlay,
                "buffer": buffer,
                "lighting": lighting,
                "shadows": shadows,
                "isolate": isolate,
                "target": target,
                "frame_all": frame_all,
                "resolution": resolution,
            },
            timeout_s=CAPTURE_TIMEOUT_S,
        )
        shots = result.get("images", [])
        content: List[Union[Image, str]] = []
        for shot in shots:
            png = images.decode_and_downscale(shot["png_b64"])
            content.append(Image(data=png, format="png"))
        content.append(
            "camera_positions: " + json.dumps(result.get("camera_positions", []))
        )
        wrote = _write_frames(
            out_path, [s["angle"] for s in shots],
            [base64.b64decode(s["png_b64"]) for s in shots],
        )
        if wrote:
            content.append(wrote)
        return content

    @mcp.tool(
        title="Capture turntable",
        annotations=ToolAnnotations(
            read_only_hint=True, destructive_hint=False, idempotent_hint=True
        ),
    )
    def maya_capture_turntable(
        target: Annotated[Optional[str], Field(description=(
            "Object to orbit and frame; omit to frame the whole scene."
        ))] = None,
        n_frames: Annotated[int, Field(ge=2, le=16, description=(
            "Views around the subject. Returns ONE contact sheet regardless."
        ))] = 8,
        resolution: Annotated[int, Field(ge=64, le=1024, description=(
            "Per-cell resolution, before the sheet is downscaled."
        ))] = 384,
        shading: Annotated[
            ShadingMode,
            Field(description=(
                "Viewport shading mode for every frame. 'textured' reveals "
                "texture/bump networks; 'flatShaded' reveals facets and "
                "hard-surface reads; 'smoothShaded' (the default) hides both."
            )),
        ] = "smoothShaded",
        lighting: Annotated[
            Literal["default", "scene", "flat"],
            Field(description="'scene' uses the scene's own lights."),
        ] = "default",
        path: Annotated[
            Optional[str],
            Field(description=(
                "Absolute .png path to also WRITE the contact sheet to, at full "
                "cell resolution. The parent directory must already exist."
            )),
        ] = None,
    ) -> list:
        """Orbit the subject and return a single contact-sheet image.

        Eight views for the token cost of one image - the final judgement pass."""
        out_path = _resolve_path(path)
        result = maya.request(
            "capture_turntable",
            {"target": target, "n_frames": n_frames,
             "resolution": resolution, "shading": shading, "lighting": lighting},
            timeout_s=CAPTURE_TIMEOUT_S,
        )
        cells = [
            images.decode_and_downscale(shot["png_b64"], max_px=resolution)
            for shot in result.get("images", [])
        ]
        sheet = images.contact_sheet(cells)
        content: List[Union[Image, str]] = [
            Image(data=images.decode_and_downscale(
                base64.b64encode(sheet).decode("ascii")), format="png"),
            "turntable: %d frames, azimuths %s" % (
                result.get("n_frames", 0),
                json.dumps([s["azimuth"] for s in result.get("images", [])]),
            ),
        ]
        wrote = _write_frames(out_path, ["sheet"], [sheet])
        if wrote:
            content.append(wrote)
        return content

    @mcp.tool(
        title="Render scene",
        annotations=ToolAnnotations(
            read_only_hint=True, destructive_hint=False, idempotent_hint=True
        ),
    )
    def maya_render_scene(
        angles: Annotated[Optional[List[Angle]], Field(max_length=4, description=(
            "Views to render. Defaults to one three_quarter frame - a rendered "
            "frame costs seconds, where a viewport capture costs milliseconds. "
            "'current' has no meaning without a viewport and renders as "
            "three_quarter."
        ))] = None,
        renderer: Annotated[
            Literal["arnold", "hw2"],
            Field(description=(
                "'arnold' (default) ray-traces: transmissive materials refract "
                "and tint, so gems, glass, ice and water are judgeable. 'hw2' "
                "is the fast rasteriser and draws transmission as plain "
                "transparency, exactly as the viewport does."
            )),
        ] = "arnold",
        resolution: Annotated[int, Field(ge=64, le=2048, description=(
            "Square frame size in pixels."
        ))] = 512,
        isolate: Annotated[Optional[List[str]], Field(description=(
            "VISIBILITY: render only these objects; everything else is hidden "
            "for the render and restored afterwards. Note that hiding the "
            "surroundings also removes what a transmissive material refracts - "
            "use `target` instead when you want a close-up that keeps the room."
        ))] = None,
        target: Annotated[Optional[List[str]], Field(description=(
            "FRAMING: point the camera at these objects while everything else "
            "stays visible. Independent of `isolate`; with neither, the whole "
            "scene is framed."
        ))] = None,
        zoom: Annotated[float, Field(ge=0.2, le=8.0, description=(
            "1.0 fits the framed objects; 2.0 is twice as close. Judging a "
            "material needs it large in frame - at 40 pixels a gem and paint "
            "look identical."
        ))] = 1.0,
        relight: Annotated[bool, Field(description=(
            "Swing maya_setup_lighting's own rig to follow the camera, so side "
            "and back angles are not rendered nearly black by a world-locked "
            "key light. Lights you authored yourself are never touched."
        ))] = True,
        samples: Annotated[int, Field(ge=1, le=8, description=(
            "Arnold AA samples. 3 is judgeable, 1 is fast and noisy. Ignored "
            "by hw2."
        ))] = 3,
        fallback_light: Annotated[bool, Field(description=(
            "Add a temporary key light when the scene has none, so an unlit "
            "scene does not come back as an indistinguishable black frame."
        ))] = True,
        path: Annotated[Optional[str], Field(description=(
            "Absolute .png path to also WRITE the frames to, at full render "
            "resolution. The parent directory must already exist. With several "
            "angles the angle name goes in before the extension: "
            "'D:/run/hero.png' writes hero_front.png, hero_side.png."
        ))] = None,
        timeout_s: Annotated[float, Field(ge=30.0, le=MAX_RENDER_TIMEOUT_S, description=(
            "Seconds to wait for ALL the angles. Four 2048px frames at 8 samples "
            "can exceed the 600 s default. A timeout does not stop the render - "
            "Maya finishes it and the session stays busy - so raising this costs "
            "nothing and a timeout costs you the frames."
        ))] = RENDER_TIMEOUT_S,
    ) -> list:
        """Render frames through the render pipeline instead of the viewport.

        Use this over maya_capture_viewport when the material's truth matters -
        transmission, refraction, real shadows - or when the viewport cannot
        render at all. Every frame reports its opaque pixel count, because a
        render of nothing is a valid image."""
        out_path = _resolve_path(path)
        result = maya.request(
            "render_scene",
            {"angles": angles, "renderer": renderer, "resolution": resolution,
             "isolate": isolate, "target": target, "zoom": zoom,
             "relight": relight, "samples": samples,
             "fallback_light": fallback_light},
            timeout_s=timeout_s,
        )
        content: List[Union[Image, str]] = []
        frames = []
        for shot in result.get("images", []):
            stats = images.pixel_stats(base64.b64decode(shot["png_b64"]))
            frames.append(
                RenderedFrame(
                    angle=shot["angle"],
                    opaque_px=stats["opaque_px"],
                    total_px=stats["total_px"],
                    distinct_colors=stats["distinct_colors"],
                    clipped_fraction=stats["clipped_fraction"],
                    mean_luma=stats["mean_luma"],
                )
            )
            content.append(
                Image(data=images.decode_and_downscale(shot["png_b64"]), format="png")
            )
        if frames and all(f.opaque_px == 0 for f in frames):
            # A render of nothing is a valid PNG and a success status; saying so
            # out loud is the whole reason the statistics are measured.
            raise ValueError(
                "every rendered frame came back blank (0 opaque pixels). The "
                "scene may be empty, unlit, or outside the camera - check "
                "maya_get_scene_graph and the light rig, and note that "
                "fallback_light only adds a key when the scene has NO light."
            )
        content.append(
            RenderResult(
                renderer=result.get("renderer", renderer),
                samples=result.get("samples", samples),
                fallback_light=bool(result.get("fallback_light", False)),
                frames=frames,
            ).model_dump_json()
        )
        content.append(
            "camera_positions: " + json.dumps(result.get("camera_positions", []))
        )
        wrote = _write_frames(
            out_path, [s["angle"] for s in result.get("images", [])],
            [base64.b64decode(s["png_b64"]) for s in result.get("images", [])],
        )
        if wrote:
            content.append(wrote)
        return content

    @mcp.tool(
        title="Render contact sheet",
        annotations=ToolAnnotations(
            read_only_hint=True, destructive_hint=False, idempotent_hint=True
        ),
    )
    def maya_render_sheet(
        subjects: Annotated[List[str], Field(min_length=1, max_length=48, description=(
            "One rendered cell per object, each isolated and framed on itself. "
            "For several ANGLES of one object use maya_render_scene."
        ))],
        angle: Annotated[Angle, Field(description=(
            "The single angle every cell is rendered from."
        ))] = "three_quarter",
        renderer: Annotated[
            Literal["arnold", "hw2"],
            Field(description=(
                "'hw2' is worth considering here: a sheet is N rendered frames, "
                "and unless the pieces are transmissive it shows the same thing "
                "far faster."
            )),
        ] = "arnold",
        resolution: Annotated[int, Field(ge=64, le=1024, description=(
            "Per-cell resolution, before the sheet is downscaled."
        ))] = 384,
        isolate: Annotated[bool, Field(description=(
            "Hide everything but each cell's own subject. True is the point of "
            "a sheet; pass false for transmissive pieces, which need the "
            "surroundings they refract."
        ))] = True,
        samples: Annotated[int, Field(ge=1, le=8, description=(
            "Arnold AA samples per cell. Cells are small - 1 or 2 is usually "
            "enough, and this multiplies by the number of subjects."
        ))] = 2,
        cols: Annotated[Optional[int], Field(ge=1, le=12, description=(
            "Grid columns; defaults to a roughly square layout."
        ))] = None,
        path: Annotated[Optional[str], Field(description=(
            "Absolute .png path to also WRITE the sheet to, at full cell "
            "resolution. The parent directory must already exist."
        ))] = None,
        timeout_s: Annotated[float, Field(ge=30.0, le=MAX_RENDER_TIMEOUT_S, description=(
            "Seconds to wait for the whole sheet. Every cell is a full render, "
            "so this is per-CALL, not per-cell: 29 Arnold cells can exceed the "
            "600 s default. Raise it rather than letting the call time out - the "
            "render keeps going in Maya either way and the session stays busy "
            "until it finishes, so a timeout costs you the images without saving "
            "any time."
        ))] = RENDER_TIMEOUT_S,
    ) -> list:
        """Render a whole kit as ONE contact-sheet image, in one call.

        A 41-piece kit sheet used to be 41 round-trips, each re-resolving the
        renderer, snapshotting and restoring the user's render globals, building
        a camera and re-hiding the scene. That is setup, not picture: here it
        happens once and the loop is just frames.

        Cells are row-major, top-left first, in the order given."""
        out_path = _resolve_path(path)
        result = maya.request(
            "render_sheet",
            {"subjects": subjects, "angle": angle, "renderer": renderer,
             "resolution": resolution, "isolate": isolate, "samples": samples},
            timeout_s=timeout_s,
        )
        shots = result.get("images", [])
        cells = [
            images.decode_and_downscale(shot["png_b64"], max_px=resolution)
            for shot in shots
        ]
        blank = [
            shot["label"] for shot, cell in zip(shots, cells)
            if images.pixel_stats(cell)["blank"]
        ]
        sheet = images.contact_sheet(cells, cols=cols)
        content: List[Union[Image, str]] = [
            Image(data=images.decode_and_downscale(
                base64.b64encode(sheet).decode("ascii")), format="png"),
            "cells (row-major): " + json.dumps([s["label"] for s in shots]),
            # A cell of nothing is a valid image. Naming the empty ones is the
            # difference between "that piece looks wrong" and "that piece did
            # not render".
            "blank cells: " + (json.dumps(blank) if blank else "none"),
        ]
        # A subject containing another is a decision this tool made about what
        # the cell shows; unstated, it reads as a broken render (#640).
        for warning in result.get("warnings", []):
            content.append("note: " + warning)
        wrote = _write_frames(out_path, ["sheet"], [sheet])
        if wrote:
            content.append(wrote)
        return content

    @mcp.tool(
        title="Load reference image",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, idempotent_hint=True
        ),
    )
    def maya_load_reference_image(
        source: Annotated[str, Field(min_length=1, description=(
            "Absolute path to an image file, or raw base64 image data."
        ))],
        ref_id: Annotated[str, Field(min_length=1, description=(
            "Short id you will pass to maya_compare_to_reference, e.g. 'hero_front'."
        ))],
    ) -> ReferenceResult:
        """Store a reference image in the server for later side-by-side comparison.

        Held in the MCP process, not the Maya scene - it survives new_scene and
        never dirties your file."""
        return ReferenceResult.model_validate(_references.put(ref_id, source))

    @mcp.tool(
        title="Compare to reference",
        annotations=ToolAnnotations(
            read_only_hint=True, destructive_hint=False, idempotent_hint=True
        ),
    )
    def maya_compare_to_reference(
        ref_id: Annotated[str, Field(min_length=1, description=(
            "Id from maya_load_reference_image."
        ))],
        angle: Annotated[
            Literal["front", "side", "back", "top", "three_quarter", "current"],
            Field(description="Viewport angle to capture for the right-hand panel."),
        ] = "three_quarter",
        resolution: Annotated[int, Field(ge=64, le=1024)] = 640,
        shading: Annotated[
            ShadingMode,
            Field(description="Viewport shading mode for the right-hand panel."),
        ] = "smoothShaded",
        lighting: Annotated[
            Literal["default", "scene", "flat"],
            Field(description="'scene' uses the scene's own lights."),
        ] = "default",
    ) -> list:
        """One side-by-side image: the reference on the left, your viewport on the right.

        Corrects toward a target instead of a vague ideal."""
        reference = _references.get(ref_id)
        result = maya.request(
            "capture_viewport",
            {"angles": [angle], "shading": shading,
             "wireframe_overlay": False, "buffer": "beauty", "isolate": None,
             "frame_all": True, "resolution": resolution,
             "lighting": lighting, "shadows": False},
            timeout_s=CAPTURE_TIMEOUT_S,
        )
        shots = result.get("images", [])
        if not shots:
            raise ValueError("capture returned no image to compare against")
        current = images.decode_and_downscale(shots[0]["png_b64"], max_px=resolution)
        reference = images.decode_and_downscale(
            base64.b64encode(reference).decode("ascii"), max_px=resolution
        )
        composite = images.decode_and_downscale(
            base64.b64encode(images.side_by_side(reference, current)).decode("ascii")
        )
        return [
            Image(data=composite, format="png"),
            "left: reference %r | right: viewport %s" % (ref_id, angle),
        ]

    SESSION_TIMEOUT_S = 60.0  # checkpoint saves of heavy scenes take a while

    @mcp.tool(
        title="Save checkpoint",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, idempotent_hint=False
        ),
    )
    def maya_checkpoint(
        label: Annotated[str, Field(min_length=1, max_length=60, description=(
            "Short label for the checkpoint, e.g. 'pre_rune'. Sanitized to "
            "[a-z0-9_-]; the returned checkpoint_id is NNN_label."
        ))],
    ) -> CheckpointResult:
        """Incremental scene save to <project>/checkpoints/. Keeps the newest
        20; older ones are pruned. Cheap insurance before experiments."""
        return CheckpointResult.model_validate(
            maya.request("checkpoint", {"label": label}, timeout_s=SESSION_TIMEOUT_S)
        )

    @mcp.tool(
        title="Restore checkpoint",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=False
        ),
    )
    def maya_restore_checkpoint(
        checkpoint_id: Annotated[str, Field(description=(
            "Id returned by maya_checkpoint (NNN_label). Ids are unique only "
            "within one directory, so prefer path= for an id issued before a "
            "new_scene/open_scene/restore."
        ))] = "",
        path: Annotated[str, Field(description=(
            "Absolute path to the checkpoint .ma, as returned alongside every "
            "checkpoint_id. Unambiguous - use it when the scene has changed since."
        ))] = "",
    ) -> RestoreResult:
        """Replace the current scene with a checkpoint, by id or by path. An
        auto-checkpoint of the current state is taken first (its own path comes
        back too). Discards the undo queue (file load)."""
        return RestoreResult.model_validate(
            maya.request(
                "restore_checkpoint",
                {"checkpoint_id": checkpoint_id, "path": path},
                timeout_s=SESSION_TIMEOUT_S,
            )
        )

    @mcp.tool(
        title="Undo",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=False
        ),
    )
    def maya_undo(
        steps: Annotated[int, Field(ge=1, le=50, description=(
            "How many tool calls to undo; each mutating call is one step."
        ))] = 1,
    ) -> UndoResult:
        """Undo the last N mutating tool calls. Undo is cheaper than re-modeling;
        returns how many steps actually landed (the queue may be shorter)."""
        return UndoResult.model_validate(
            maya.request("undo", {"steps": steps}, timeout_s=SESSION_TIMEOUT_S)
        )

    @mcp.tool(
        title="Redo",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=False
        ),
    )
    def maya_redo(
        steps: Annotated[int, Field(ge=1, le=50, description="Steps to redo.")] = 1,
    ) -> UndoResult:
        """Redo previously undone tool calls."""
        return UndoResult.model_validate(
            maya.request("redo", {"steps": steps}, timeout_s=SESSION_TIMEOUT_S)
        )

    @mcp.tool(
        title="New scene",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=False
        ),
    )
    def maya_new_scene(
        confirm: Annotated[bool, Field(description=(
            "Must be true; the current scene is discarded."
        ))] = False,
        linear_unit: Annotated[Optional[str], Field(description=(
            "Linear unit the new scene is SET to, after the replace. Default "
            "'cm' is the authoring convention for every deliverable out of this "
            "repo: the numbers you pass mean METRES, and the exporter writes "
            "them unchanged. 'm' instead makes the same numbers export 100x too "
            "large - the maya-mcp #629 defect, invisible to every in-Maya check. "
            "Pass null to inherit whatever the session already had, which is "
            "what this parameter exists to stop being the default."
        ))] = "cm",
    ) -> NewSceneResult:
        """Start an empty scene. REFUSES without confirm=true. Auto-checkpoints
        the discarded scene first (unlike undo, this survives a scene replace) -
        recover it via maya_restore_checkpoint(pre_checkpoint). Also STATES the
        scene's linear unit rather than inheriting it - see linear_unit."""
        return NewSceneResult.model_validate(
            maya.request(
                "new_scene", {"confirm": confirm, "linear_unit": linear_unit},
                timeout_s=SESSION_TIMEOUT_S,
            )
        )

    @mcp.tool(
        title="Open scene",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=False
        ),
    )
    def maya_open_scene(
        path: Annotated[str, Field(description="Absolute path to a .ma/.mb file.")],
        confirm: Annotated[bool, Field(description=(
            "Required (true) only when the current scene has unsaved changes."
        ))] = False,
    ) -> OpenSceneResult:
        """Open a scene file, replacing the current scene. Auto-checkpoints the
        discarded scene first (unlike undo, this survives a scene replace) -
        recover it via maya_restore_checkpoint(pre_checkpoint)."""
        return OpenSceneResult.model_validate(
            maya.request(
                "open_scene", {"path": path, "confirm": confirm}, timeout_s=SESSION_TIMEOUT_S
            )
        )

    @mcp.tool(
        title="Save scene",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, idempotent_hint=True
        ),
    )
    def maya_save_scene(
        path: Annotated[Optional[str], Field(description=(
            "Target path for save-as; omit to save in place (errors on an "
            "untitled scene)."
        ))] = None,
    ) -> SaveSceneResult:
        """Save the scene (.ma or .mb by extension)."""
        return SaveSceneResult.model_validate(
            maya.request("save_scene", {"path": path}, timeout_s=SESSION_TIMEOUT_S)
        )

    @mcp.tool(
        title="Export FBX",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, idempotent_hint=True
        ),
    )
    def maya_export_fbx(
        path: Annotated[str, Field(description=(
            "Absolute path ending in .fbx. The parent directory must exist."
        ))],
        metres_per_unit: Annotated[float, Field(description=(
            "What one scene unit means in metres. REQUIRED, and only 1.0 "
            "exports - there is no default because a guess here is what "
            "shipped three deliveries at 100x. Do NOT try to satisfy yourself "
            "in-scene first: the defect is written by the FBX exporter and is "
            "absent from the Maya scene, so every measurement you can take "
            "there reads correct while the file is wrong. If your scene is not "
            "metre-native, scale and freeze it first: the exporter cannot fix "
            "vertex magnitude, it can only add a compensating node scale, "
            "which this tool rejects."
        ))],
        nodes: Annotated[Optional[List[str]], Field(description=(
            "Objects to export; omit to export the whole scene."
        ))] = None,
        include_skins: Annotated[bool, Field(description=(
            "Export skinCluster deformers and the BindPose with the mesh. "
            "The gate then also verifies, from the bytes: skin records "
            "present, per-vertex weight sums ~1.0, BindPose present, and "
            "identity scale on every joint. For a selected export, list the "
            "skeleton root in nodes alongside the mesh."
        ))] = False,
    ) -> ExportFbxResult:
        """Export FBX and gate the result on the BYTES it just wrote.

        Writes to a temporary sibling and moves it into place only once it
        passes, so a refused export leaves nothing new behind and never
        destroys a file already at that path. It is refused if any node carries
        a non-identity scale or the unit declaration disagrees with the
        geometry - the two ways a wrong-sized asset renders correctly and ships
        anyway. Everything returned is read back out of the file, not queried
        from the scene."""
        return ExportFbxResult.model_validate(
            maya.request(
                "export_fbx",
                {"path": path, "metres_per_unit": metres_per_unit,
                 "nodes": nodes, "include_skins": include_skins},
                timeout_s=EXPORT_TIMEOUT_S,
            )
        )

    @mcp.tool(
        title="Reset Python namespace",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, idempotent_hint=True
        ),
    )
    def maya_reset_namespace() -> ResetNamespaceResult:
        """Clear the persistent maya_execute_python namespace."""
        return ResetNamespaceResult.model_validate(
            maya.request("reset_namespace", {}, timeout_s=SCENE_TIMEOUT_S)
        )

    @mcp.tool(
        title="Create primitive",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, idempotent_hint=False
        ),
    )
    def maya_create_primitive(
        kind: Annotated[
            Literal[
                "cube", "sphere", "cylinder", "plane", "torus", "cone",
                "octahedron", "icosahedron", "prism", "pyramid",
            ],
            Field(description=(
                "Primitive type. octahedron/icosahedron are platonic solids "
                "with a fixed face count (divisions has no effect); prism is "
                "a 3-sided, pyramid a 4-sided low-poly faceted form (divisions "
                "sets height subdivisions). Use these for cut-gem/crystalline "
                "forms - a bevelled cube is not the only faceted primitive. "
                "Every kind fills the same 1-unit box at scale 1, so switching "
                "kind never changes the size."
            )),
        ],
        name: Annotated[str, Field(min_length=1, description=(
            "Requested name; collisions get a deterministic _NNN suffix and the "
            "assigned canonical long name is returned."
        ))],
        translate: Vec3 = None,
        rotate: Vec3 = None,
        scale: Vec3 = None,
        divisions: Annotated[int, Field(ge=1, le=200, description=(
            "1 = Maya defaults; higher multiplies subdivision counts. This is a "
            "MULTIPLIER, and it costs very different amounts per kind: a cube "
            "spends it linearly per axis (6*d^2 faces) while a sphere or torus "
            "multiplies it by 20 on BOTH axes (400*d^2), so divisions=50 is a "
            "1M-face sphere but a 15k-face cube. Results are capped at 1,000,000 "
            "faces; over that the call is refused with the highest divisions that "
            "kind allows, rather than building a mesh that hangs Maya."
        ))] = 1,
    ) -> NameResult:
        """Create a polygon primitive at an optional transform (no construction
        history)."""
        return NameResult.model_validate(
            maya.request(
                "create_primitive",
                {"kind": kind, "name": name, "translate": translate,
                 "rotate": rotate, "scale": scale, "divisions": divisions},
                timeout_s=SCENE_TIMEOUT_S,
            )
        )

    @mcp.tool(
        title="Duplicate object",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, idempotent_hint=False
        ),
    )
    def maya_duplicate(
        name: Annotated[str, Field(min_length=1, description=(
            "Canonical long name of the object to duplicate."
        ))],
        new_name: Annotated[str, Field(min_length=1, description=(
            "Requested name for the copy; collisions get a deterministic _NNN "
            "suffix and the assigned canonical long name is returned."
        ))],
        translate: Vec3 = None,
        rotate: Vec3 = None,
        scale: Vec3 = None,
    ) -> NameResult:
        """Duplicate an object by name, optionally offsetting the copy
        (translate/rotate/scale are applied relative to the source)."""
        return NameResult.model_validate(
            maya.request(
                "duplicate",
                {"name": name, "new_name": new_name, "translate": translate,
                 "rotate": rotate, "scale": scale},
                timeout_s=SCENE_TIMEOUT_S,
            )
        )

    @mcp.tool(
        title="Array copies",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, idempotent_hint=False
        ),
    )
    def maya_array(
        name: Annotated[str, Field(description="Source object (canonical long name).")],
        mode: Annotated[
            Literal["mirror", "radial", "linear"],
            Field(description=(
                "'mirror' reflects one copy across a world plane - the way to build "
                "anything bilaterally symmetric once instead of twice. Requires the "
                "source to be a single polygon mesh (not a group, curve, or other "
                "assembly); mirror each chunk individually and group the results. "
                "'radial' rotates copies about an axis: gears, colonnades, spokes, "
                "petals. 'linear' runs copies along a vector: stairs, ribs, fence posts."
            )),
        ],
        count: Annotated[int, Field(ge=2, le=200, description=(
            "TOTAL elements in the finished array, INCLUDING the source - count=12 "
            "on a gear tooth gives a 12-tooth gear. Ignored by mirror, which "
            "always makes exactly one copy."
        ))] = 2,
        axis: Annotated[
            Optional[Literal["x", "y", "z"]],
            Field(description=(
                "radial: the axis copies rotate about, right-hand rule. Defaults to "
                "'y' (a ring lying flat in the XZ plane). mirror: the axis the "
                "reflection plane is perpendicular to. Defaults to 'x' (bilateral "
                "left/right symmetry)."
            )),
        ] = None,
        center: Annotated[Optional[List[float]], Field(description=(
            "radial only: world point the axis passes through. There is no radius "
            "parameter - the source's existing distance from this point IS the "
            "radius, so place one element where it belongs and ask for N of them."
        ))] = None,
        angle: Annotated[float, Field(ge=-360.0, le=360.0, description=(
            "radial only: total sweep in degrees. At 360 (the default) the step is "
            "angle/count, because the seam is where the source already sits. At any "
            "other value the step is angle/(count-1), so the first and last "
            "elements land on the arc's endpoints."
        ))] = 360.0,
        offset: Annotated[Optional[List[float]], Field(description=(
            "linear only, required: world displacement between consecutive copies."
        ))] = None,
        step_rotate: Annotated[Optional[List[float]], Field(description=(
            "linear only: degrees added per step, so a run can twist as it goes."
        ))] = None,
        step_scale: Annotated[Optional[List[float]], Field(description=(
            "linear only: per-step size multiplier, COMPOUNDING - 0.9 gives a "
            "geometric taper down the run. Must be positive."
        ))] = None,
        pivot: Annotated[Optional[List[float]], Field(description=(
            "mirror only: world point the reflection plane passes through. "
            "Defaults to the origin."
        ))] = None,
        name_prefix: Annotated[Optional[str], Field(description=(
            "Base name for the copies; defaults to the source's short name. "
            "radial and linear append _1.._N, since N copies need N names. "
            "mirror makes exactly ONE copy and takes this as its NAME verbatim - "
            "pass name_prefix='golem_R_arm' and that is what the copy is called, "
            "no suffix. Omit it and the mirror falls back to <source>_1."
        ))] = None,
        group_name: Annotated[Optional[str], Field(description=(
            "Parent the copies under a new group of this name. The source is "
            "never reparented."
        ))] = None,
    ) -> ArrayResult:
        """Copy an object into a mirror, a ring, or a run.

        The source never moves and is element 0 of the result. Copies are real
        duplicates, not instances, so each one takes its own booleans and
        materials. Mirror reports signed_volume: mirroring inverts face winding,
        and a mesh whose faces point inward renders black under Arnold - which
        looks exactly like a lighting bug and is not one."""
        return ArrayResult.model_validate(
            maya.request(
                "array",
                {"name": name, "mode": mode, "count": count, "axis": axis,
                 "center": center, "angle": angle, "offset": offset,
                 "step_rotate": step_rotate, "step_scale": step_scale,
                 "pivot": pivot, "name_prefix": name_prefix,
                 "group_name": group_name},
                timeout_s=BOOL_TIMEOUT_S,
            )
        )

    @mcp.tool(
        title="Transform objects",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, idempotent_hint=False
        ),
    )
    def maya_transform(
        names: Annotated[List[str], Field(min_length=1, description=(
            "Canonical long names of the objects to move."
        ))],
        translate: Vec3 = None,
        rotate: Vec3 = None,
        scale: Vec3 = None,
        relative: Annotated[bool, Field(description=(
            "True (default): offsets relative to current values. False: absolute "
            "world-space translate and rotate; object-space scale."
        ))] = True,
        pivot: Annotated[Vec3, Field(description=(
            "World-space point to place the object's pivot at. By itself, does "
            "NOT move the geometry - it moves what the geometry turns about. "
            "But it sets BOTH the rotate and the scale pivot (that is what "
            "`xform -piv` does), so a `scale` in the SAME call now scales about "
            "this point too and DOES move the geometry - differently than a "
            "`scale` would have before a pivot was placed here. Applied before "
            "translate/rotate/scale, so a relative rotate or scale in the same "
            "call acts about the new pivot."
        ))] = None,
    ) -> TransformResult:
        """Move/rotate/scale objects by name. Returns the resulting transforms —
        trust these over your own bookkeeping: the live user may also be moving
        things, and warnings will say so."""
        return TransformResult.model_validate(
            maya.request(
                "transform",
                {"names": names, "translate": translate, "rotate": rotate,
                 "scale": scale, "relative": relative, "pivot": pivot},
                timeout_s=SCENE_TIMEOUT_S,
            )
        )

    @mcp.tool(
        title="Group objects",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, idempotent_hint=False
        ),
    )
    def maya_group(
        names: Annotated[List[str], Field(min_length=1, description=(
            "Canonical long names of the objects to place under a new group "
            "transform."
        ))],
        group_name: Annotated[str, Field(min_length=1, description=(
            "Requested name for the new group; collisions get a deterministic "
            "_NNN suffix and the assigned canonical long name is returned."
        ))],
    ) -> NameResult:
        """Create a new group transform and parent the named objects under it."""
        return NameResult.model_validate(
            maya.request(
                "group",
                {"names": names, "group_name": group_name},
                timeout_s=SCENE_TIMEOUT_S,
            )
        )

    @mcp.tool(
        title="Parent object",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, idempotent_hint=False
        ),
    )
    def maya_parent(
        child: Annotated[str, Field(min_length=1, description=(
            "Canonical long name of the object to reparent."
        ))],
        parent: Annotated[str, Field(min_length=1, description=(
            "Canonical long name of the new parent transform."
        ))],
    ) -> NameResult:
        """Reparent one object under another. Returns the child's new canonical
        long name (its path changes when its parent changes)."""
        return NameResult.model_validate(
            maya.request(
                "parent",
                {"child": child, "parent": parent},
                timeout_s=SCENE_TIMEOUT_S,
            )
        )

    @mcp.tool(
        title="Rename object",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, idempotent_hint=False
        ),
    )
    def maya_rename(
        name: Annotated[str, Field(min_length=1, description=(
            "Canonical long name of the object to rename."
        ))],
        new_name: Annotated[str, Field(min_length=1, description=(
            "Requested new name; collisions get a deterministic _NNN suffix and "
            "the assigned canonical long name is returned."
        ))],
    ) -> NameResult:
        """Rename an object by name."""
        return NameResult.model_validate(
            maya.request(
                "rename",
                {"name": name, "new_name": new_name},
                timeout_s=SCENE_TIMEOUT_S,
            )
        )

    @mcp.tool(
        title="Delete objects",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=False
        ),
    )
    def maya_delete_objects(
        names: Annotated[List[str], Field(min_length=1, description=(
            "Canonical long names of the objects to delete. All-or-nothing: if "
            "any name is missing, nothing is deleted."
        ))],
    ) -> DeleteResult:
        """Delete objects by name. Fails clean (no partial deletion) if any
        name does not exist."""
        return DeleteResult.model_validate(
            maya.request(
                "delete_objects",
                {"names": names},
                timeout_s=SCENE_TIMEOUT_S,
            )
        )

    @mcp.tool(
        title="Boolean operation",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=False
        ),
    )
    def maya_boolean_op(
        a: Annotated[str, Field(description=(
            "First mesh. The result IS a rebuilt a: its material, pivot, parent "
            "and UV bounds are what the result inherits."
        ))],
        b: Annotated[str, Field(description=(
            "Second mesh; both inputs are consumed. Its UVs are folded into a's "
            "UV bounds, so the newly cut faces stay in a's atlas patch."
        ))],
        op: Annotated[Literal["union", "difference", "intersection"],
                      Field(description="difference = a minus b.")],
        new_name: Annotated[str, Field(min_length=1, description=(
            "Name for the result. This MAY be a's or b's own name - both are "
            "consumed by the boolean, so cutting a socket into X and having the "
            "result still be called X is expressible and is usually what you "
            "want. Only a name held by some OTHER object gets a _NNN suffix, and "
            "then it says so in warnings."
        ))],
    ) -> BooleanResult:
        """Boolean two meshes. Auto-checkpoints first; deletes construction
        history and collapses shading to one object-level material (per-face
        shading does not survive booleans). Carries a's pivot, a's parent and
        a's UV bounds onto the result, and reports all three - cut a socket into
        a rigged, parented, atlas-packed chunk and it stays rigged, parented and
        packed. Non-watertight results come back ok with a warning + cleanup
        hint."""
        return BooleanResult.model_validate(
            maya.request(
                "boolean_op", {"a": a, "b": b, "op": op, "new_name": new_name},
                timeout_s=BOOL_TIMEOUT_S,
            )
        )

    @mcp.tool(
        title="Combine meshes into one object",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=False
        ),
    )
    def maya_combine(
        names: Annotated[List[str], Field(min_length=2, description=(
            "Two or more meshes to merge. All are consumed."
        ))],
        name: Annotated[Optional[str], Field(description=(
            "Name for the merged object; defaults to <first input>_combined."
        ))] = None,
        pivot: Annotated[Literal["center", "origin", "keep"], Field(description=(
            "Where the result's pivot lands. 'center' (default) is the bounding "
            "box centre - what a chunk of debris rotates about. 'origin' is the "
            "world origin, which is what a kit piece authored around 0,0,0 wants."
        ))] = "center",
        freeze: Annotated[bool, Field(description=(
            "Freeze transforms on the result, leaving scale (1,1,1)."
        ))] = True,
    ) -> CombineResult:
        """Merge meshes into ONE object while keeping each as its own shell.

        This is not a boolean union. Nothing is welded, no intersections are
        recomputed, and coincident faces are left alone - the inputs simply
        stop being separate objects. That is what you want for a part built
        out of primitives, and it is far cheaper than union on the same
        geometry.

        Reports the measured shell count: it should equal the number of
        inputs, and a lower number means inputs were already fused. Combining
        meshes with different shaders collapses them to one object-level
        material and warns, because per-face shading on united meshes is the
        state that makes later per-face work silently no-op."""
        return CombineResult.model_validate(
            maya.request(
                "combine",
                {"names": names, "name": name, "pivot": pivot, "freeze": freeze},
                timeout_s=BOOL_TIMEOUT_S,
            )
        )

    @mcp.tool(
        title="Assemble parts into objects",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=False
        ),
    )
    def maya_assemble(
        name: Annotated[str, Field(min_length=1, description=(
            "Name of the assembled object, and the prefix for its parts. Parts "
            "that set their own 'chunk' are named after that instead."
        ))],
        parts: Annotated[List[dict], Field(min_length=1, description=(
            "One entry per primitive:\n"
            "  dim     [w, h, d] in scene units - REQUIRED. Every kind is built "
            "to fill a 1-unit box, so dim is literally the size.\n"
            "  pos     [x, y, z] centre, default origin\n"
            "  kind    cube (default), sphere, cylinder, plane, torus, cone, "
            "octahedron, icosahedron, prism, pyramid\n"
            "  rotate  [x, y, z] degrees\n"
            "  patch   atlas patch index, or [col, row]\n"
            "  taper   a MULTIPLIER on the far end (0.6 = 60% as wide at the "
            "top), or the full flare params. Baked - no deformer survives.\n"
            "  chunk   which object this part belongs to. Parts sharing a chunk "
            "are united into one object named after it.\n"
            "  divisions, name  as in maya_create_primitive"
        ))],
        atlas: Annotated[Optional[dict], Field(description=(
            "UV packing applied to each part before merging: {cols, rows, "
            "margin, world_scale, project, normalize}. world_scale is the metres "
            "one patch represents, which is what makes texel density equal "
            "across parts of different sizes. Pass null to leave UVs untouched."
        ))] = None,
        combine: Annotated[bool, Field(description=(
            "Unite each chunk's parts into one object. False leaves every part "
            "as its own object."
        ))] = True,
        pivot: Annotated[Literal["center", "origin", "keep"], Field(description=(
            "Pivot for each combined object, as in maya_combine."
        ))] = "center",
        pivots: Annotated[Optional[Dict[str, Vec3]], Field(description=(
            "Chunk name -> world-space pivot. What an omitted chunk keeps "
            "depends on its shape: a MULTI-part chunk still gets the global "
            "`pivot` mode (it always goes through combine.unite, which always "
            "places one); a SINGLE-part chunk gets NO pivot treatment at all - "
            "`combine` never runs for it, so Maya's own default pivot stands. "
            "For an articulated figure this is the rig: each chunk pivots at "
            "its own joint, which `center` never gets right."
        ))] = None,
        freeze: Annotated[bool, Field(description=(
            "Freeze transforms on each combined object."
        ))] = True,
    ) -> AssembleResult:
        """Build many primitives, pack their UVs, and merge them - in ONE call.

        This is the build loop a kit or a building generator actually runs:
        primitive -> taper -> place -> atlas patch -> unite. Doing it a tool call
        at a time costs thousands of round-trips, and doing it inside
        maya_execute_python means nothing about the build is measured.

        The parts list is FLAT and each part names its chunk, because that is
        what a generator emits: 2,000 chunks of four boxes is 8,000 rows.

        The whole call is validated before anything is built - a run that died
        halfway would leave thousands of orphans - and it takes ONE checkpoint,
        not one per object. Reports per-object tris/verts/faces/shells plus how
        many parts ended up with UVs outside their patch."""
        return AssembleResult.model_validate(
            maya.request(
                "assemble",
                {"name": name, "parts": parts, "atlas": atlas,
                 "combine": combine, "pivot": pivot, "pivots": pivots,
                 "freeze": freeze},
                timeout_s=RENDER_TIMEOUT_S,
            )
        )

    @mcp.tool(
        title="Pack UVs into an atlas patch",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, idempotent_hint=True
        ),
    )
    def maya_uv_atlas(
        names: Annotated[List[str], Field(min_length=1, description=(
            "Meshes to pack. All of them land in the SAME patch, so pass the "
            "group of parts that share one material region."
        ))],
        # Typed as a real union, not `object`: `object` constrains nothing, so a
        # client sending "0" got the STRING through untouched and the handler
        # rejected the very form its own error message named (#640).
        patch: Annotated[Union[int, List[int]], Field(description=(
            "Which patch to write to: an integer index, or [col, row]. Index 0 "
            "is the TOP-LEFT patch and counts along the row first - the way the "
            "atlas image reads in a viewer."
        ))] = 0,
        cols: Annotated[int, Field(ge=1, le=64, description="Atlas columns.")] = 4,
        rows: Annotated[int, Field(ge=1, le=64, description="Atlas rows.")] = 4,
        margin: Annotated[float, Field(ge=0.0, lt=0.5, description=(
            "Inset as a FRACTION of the patch, keeping UVs off the patch edge "
            "so bilinear filtering cannot drag in the neighbouring patch's "
            "pixels. Default 0.02. Use 0.0 only when the patch has no neighbours."
        ))] = 0.02,
        project: Annotated[Literal["box", "planar", "keep"], Field(description=(
            "'box' (default) re-projects with automatic projection, which suits "
            "primitives and hard-surface parts. 'planar' projects down -z. "
            "'keep' preserves an existing layout and only moves it into the patch."
        ))] = "box",
        normalize: Annotated[bool, Field(description=(
            "Normalise UVs to 0..1 collectively before fitting. Leave this on: "
            "Maya's primitives do not share a UV convention, so without it each "
            "primitive kind lands in the patch at a different scale. Ignored "
            "when world_scale is given."
        ))] = True,
        world_scale: Annotated[Optional[float], Field(gt=0.0, description=(
            "Metres of real geometry that map across one patch. Setting it "
            "switches from 'make this object fill the patch' to a FIXED TEXEL "
            "DENSITY: a 3 m slab and a 0.5 m band then carry the same pixels "
            "per metre. Without it, a small piece is magnified to patch size "
            "and its material reads several times oversize - which is what "
            "makes a wall look like a model of a wall. Pixels per metre is "
            "(atlas_px / cols) / world_scale."
        ))] = None,
    ) -> UvAtlasResult:
        """Pack meshes' UVs into one patch of a shared texture atlas.

        The reason to do this is downstream, not in Maya: engines batch
        instanced geometry BY MATERIAL, so geometry drawn tens of thousands of
        times can afford exactly one material. An atlas is how pieces still
        look different from each other under that constraint.

        Returns the MEASURED UV bounding box per mesh and an all_inside flag -
        not a claim that the command ran. If all_inside is false the piece will
        sample a neighbouring patch and read as the wrong material."""
        return UvAtlasResult.model_validate(
            maya.request(
                "uv_atlas",
                {"names": names, "patch": patch, "cols": cols, "rows": rows,
                 "margin": margin, "project": project, "normalize": normalize,
                 "world_scale": world_scale},
                timeout_s=BOOL_TIMEOUT_S,
            )
        )

    @mcp.tool(
        title="Etch text into a face",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=False
        ),
    )
    def maya_etch_text(
        mesh: Annotated[str, Field(description="Target mesh (canonical long name).")],
        text: Annotated[str, Field(min_length=1, max_length=32, description=(
            "Characters to carve; Unicode ok (Hebrew renders in correct RTL "
            "visual order)."
        ))],
        face: Annotated[int, Field(ge=0, description=(
            "Face id to carve into; the glyph is oriented to this face's actual "
            "normal (works on smoothed/bowed faces)."
        ))],
        width: Annotated[float, Field(gt=0, description="Carve width, scene units.")] = 0.6,
        depth: Annotated[float, Field(gt=0, description="Recess depth, scene units.")] = 0.1,
        font: Annotated[str, Field(description="Font for the Type node.")] = "Arial",
        mirror: Annotated[bool, Field(description=(
            "Mirror the glyph horizontally (e.g. the golem's inverted-mirrored aleph)."
        ))] = False,
        rotate_deg: Annotated[float, Field(description=(
            "Extra in-plane rotation in degrees (180 = inverted)."
        ))] = 0.0,
        new_name: Annotated[Optional[str], Field(description=(
            "Name for the carved result; defaults to <mesh>_etched. May be "
            "`mesh`'s own name - the boolean consumes it - so etching a plate and "
            "keeping its name is expressible."
        ))] = None,
    ) -> BooleanResult:
        """Carve text into a mesh face in ONE call: glyph -> sized -> oriented
        to the face's normal frame -> depth-forced -> boolean difference ->
        cleanup. Auto-checkpoints first; leaves zero Type/history nodes behind."""
        return BooleanResult.model_validate(
            maya.request(
                "etch_text",
                {"mesh": mesh, "text": text, "face": face, "width": width,
                 "depth": depth, "font": font, "mirror": mirror,
                 "rotate_deg": rotate_deg, "new_name": new_name},
                timeout_s=BOOL_TIMEOUT_S,
            )
        )

    @mcp.tool(
        title="Sculpt operations",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=False
        ),
    )
    def maya_sculpt_ops(
        mesh: Annotated[str, Field(description="Target mesh (canonical long name).")],
        ops: Annotated[List[dict], Field(min_length=1, max_length=20, description=(
            'Applied in order; aborts on first failure reporting what landed. '
            'Tagged by "op": '
            'soft_move {center:[x,y,z]|vertex_id, radius, falloff:"smooth"|"linear", delta:[x,y,z]} '
            '— THE organic tool, weighted vertex offsets; '
            'inflate_region {center, radius, amount} — push along normals; '
            'displace_noise {amp:0.05, freq:2.6, octaves:2, soften_angle:55?} '
            '— value-noise rock-surface breakup, kills the untouched-primitive look; '
            'smooth {divisions:1..3}; '
            'extrude_faces {faces:"f[120:135]", distance, keep_together:true}; '
            'bevel_edges {edges:"e[3:7]", width, segments:1..10}; '
            'crease_edges {edges, amount:0..10} — stone-plate joints; '
            'bridge {edges_a, edges_b}. '
            'soft_move/inflate_region/displace_noise are fast vertex ops that write '
            'via the Maya API and bypass the undo queue entirely — maya_undo will NOT '
            'revert them. If any of the three appear in this list, the call '
            'auto-checkpoints before applying anything; pass the returned '
            'checkpoint_id to maya_restore_checkpoint to revert. The other five '
            'ops (smooth, extrude_faces, bevel_edges, '
            'crease_edges, bridge) are cmds-based and undo normally.'
        ))],
    ) -> SculptResult:
        """Apply sculpt ops in order to one mesh. cmds-based ops (smooth,
        extrude_faces, bevel_edges, crease_edges, bridge) undo normally via
        maya_undo(1). soft_move, inflate_region, and displace_noise write
        vertices via the Maya API and bypass the undo queue - when any of
        those three are requested, the call auto-checkpoints first, and
        restoring the returned checkpoint_id via maya_restore_checkpoint
        (not maya_undo) is how you revert this call. On partial failure,
        applied ops stay and the response says which recovery path applies."""
        return SculptResult.model_validate(
            maya.request(
                "sculpt_ops", {"mesh": mesh, "ops": ops}, timeout_s=BOOL_TIMEOUT_S
            )
        )

    @mcp.tool(
        title="Deform mesh",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=False
        ),
    )
    def maya_deform(
        mesh: Annotated[str, Field(description="Target mesh (canonical long name).")],
        deformer: Annotated[
            Literal["bend", "flare", "lattice", "sculpt", "sine", "squash", "twist", "wave"],
            Field(description="Nonlinear/lattice deformer type to apply."),
        ],
        params: Annotated[
            Optional[dict],
            Field(description=(
                "Deformer parameters, whitelisted per type. ANGLES ARE IN "
                "DEGREES: bend: curvature - the bend angle, so 0.35 is a third "
                "of a degree and does nothing; a visible hunch is 20-60. "
                "squash: factor. twist: startAngle/endAngle. flare: curve, "
                "startFlareX/Z, endFlareX/Z - THE taper, for a limb thick at "
                "one end and thin at the other. sine: amplitude, wavelength, "
                "offset, dropoff - linear ripple. wave: amplitude, wavelength, "
                "offset, dropoff, minRadius, maxRadius - concentric radial "
                "ripple; note wave is bounded radially and takes NO lowBound/"
                "highBound. sculpt: maxDisplacement/dropoffDistance. lattice: "
                "divisions:[x,y,z]. bend/squash/twist/flare/sine also take "
                "lowBound/highBound. Every type also accepts translate/rotate, "
                "applied to the deformer handle. Unknown keys are rejected with "
                "that type's whitelist in the error hint."
            )),
        ] = None,
        delete_history_after: Annotated[
            bool,
            Field(description=(
                "Bake the deformation into the mesh and delete the deformer "
                "(construction history) instead of returning it live for further "
                "tweaking."
            )),
        ] = False,
    ) -> DeformResult:
        """Apply a nonlinear or lattice deformer to a mesh by name. Returns the
        deformer node names so maya_execute_python can tweak their attributes
        further; delete_history_after=true bakes the shape and consumes the
        deformer instead. max_displacement reports how far the furthest vertex
        actually moved - check it, do not assume the shape changed."""
        return DeformResult.model_validate(
            maya.request(
                "deform",
                {"mesh": mesh, "deformer": deformer, "params": params,
                 "delete_history_after": delete_history_after},
                timeout_s=BOOL_TIMEOUT_S,
            )
        )

    @mcp.tool(
        title="Remesh / retopologize",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=False
        ),
    )
    def maya_remesh_retopo(
        mesh: Annotated[str, Field(description="Target mesh (canonical long name).")],
        target_polycount: Annotated[
            int,
            Field(ge=100, le=200000, description="Target face count to retopologize toward."),
        ],
        keep_original: Annotated[
            bool,
            Field(description=(
                "Keep a hidden <name>_orig backup of the source mesh before "
                "remeshing."
            )),
        ] = True,
    ) -> RemeshResult:
        """Retopologize a mesh toward target_polycount. Auto-checkpoints first.
        Tries polyRetopo, then polyRemesh, then polyReduce, in that order, as
        compatibility fallbacks across Maya versions — the response's method
        field says which one actually ran, and a fallback adds a warning
        naming what was unavailable.

        polyRetopo produces uniform quads and smooths the surface - the wrong
        tool for crystalline/faceted forms, which it will round off."""
        return RemeshResult.model_validate(
            maya.request(
                "remesh_retopo",
                {"mesh": mesh, "target_polycount": target_polycount,
                 "keep_original": keep_original},
                timeout_s=BOOL_TIMEOUT_S,
            )
        )

    @mcp.tool(
        title="Clean up mesh",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, idempotent_hint=False
        ),
    )
    def maya_mesh_cleanup(
        mesh: Annotated[str, Field(description="Target mesh (canonical long name).")],
        merge_verts_threshold: Annotated[
            float, Field(gt=0, le=1.0, description="Merge distance for polyMergeVertex.")
        ] = 0.001,
        delete_history: Annotated[
            bool, Field(description="Delete construction history after cleanup.")
        ] = True,
        freeze_transforms: Annotated[
            bool, Field(description="Freeze translate/rotate/scale to identity.")
        ] = True,
        conform_normals: Annotated[
            bool, Field(description="Conform face normal winding (polyNormal).")
        ] = True,
    ) -> CleanupResult:
        """Merge near-duplicate vertices, then (in order) conform normals,
        freeze transforms, and delete construction history. Returns mesh
        stats from before and after so you can confirm the cleanup did
        something."""
        return CleanupResult.model_validate(
            maya.request(
                "mesh_cleanup",
                {"mesh": mesh, "merge_verts_threshold": merge_verts_threshold,
                 "delete_history": delete_history, "freeze_transforms": freeze_transforms,
                 "conform_normals": conform_normals},
                timeout_s=BOOL_TIMEOUT_S,
            )
        )

    @mcp.tool(
        title="Configure viewport",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, idempotent_hint=True
        ),
    )
    def maya_set_viewport(
        show_grid: Annotated[Optional[bool], Field(description="Grid visibility.")] = None,
        show_light_icons: Annotated[Optional[bool], Field(description=(
            "Light icons render into playblasts - keep off while capturing art."
        ))] = None,
        show_camera_icons: Annotated[Optional[bool], Field(description="Camera icons.")] = None,
        show_locators: Annotated[Optional[bool], Field(description="Locator display.")] = None,
        show_manipulators: Annotated[Optional[bool], Field(description="Manipulator display.")] = None,
        show_texture_placements: Annotated[Optional[bool], Field(description=(
            "place3dTexture widgets - they render into captures too."
        ))] = None,
        wireframe_on_shaded: Annotated[Optional[bool], Field(description="Wire overlay.")] = None,
        display_lights: Annotated[
            Optional[Literal["default", "all", "active", "flat", "none"]],
            Field(description="Which lights illuminate the viewport."),
        ] = None,
    ) -> ViewportState:
        """Persistently configure the working viewport (unlike captures, which
        restore themselves). Only the params you pass change; the FULL resulting
        state always comes back - call with no params to just read it."""
        return ViewportState.model_validate(
            maya.request(
                "set_viewport",
                {"show_grid": show_grid, "show_light_icons": show_light_icons,
                 "show_camera_icons": show_camera_icons,
                 "show_locators": show_locators,
                 "show_manipulators": show_manipulators,
                 "show_texture_placements": show_texture_placements,
                 "wireframe_on_shaded": wireframe_on_shaded,
                 "display_lights": display_lights},
                timeout_s=SCENE_TIMEOUT_S,
            )
        )

    @mcp.tool(
        title="Set camera",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, idempotent_hint=True
        ),
    )
    def maya_set_camera(
        camera: Annotated[str, Field(description=(
            "Camera name; created if missing. Use a dedicated named camera "
            "instead of trusting whatever the panel last looked through."
        ))] = "mcpCam",
        position: Annotated[Optional[List[float]], Field(
            min_length=3, max_length=3, description="World-space position.",
        )] = None,
        look_at: Annotated[Optional[List[float]], Field(
            min_length=3, max_length=3, description="World-space aim point.",
        )] = None,
        focal_length: Annotated[Optional[float], Field(gt=0, description="mm.")] = None,
        set_active: Annotated[bool, Field(description=(
            "Make the viewport look through this camera (what capture 'current' uses)."
        ))] = True,
    ) -> CameraResult:
        """Create/position a named camera and (by default) make it the active
        viewport camera, so capture_viewport 'current' is deterministic."""
        return CameraResult.model_validate(
            maya.request(
                "set_camera",
                {"camera": camera, "position": position, "look_at": look_at,
                 "focal_length": focal_length, "set_active": set_active},
                timeout_s=SCENE_TIMEOUT_S,
            )
        )

    @mcp.tool(
        title="Setup lighting",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=False
        ),
    )
    def maya_setup_lighting(
        preset: Annotated[
            Literal["three_point", "single_sun", "hdri", "environment"],
            Field(description=(
                "'three_point' and 'single_sun' are directional rigs - right for "
                "reading form and silhouette.\n"
                "'environment' is an Arnold sky dome with a horizon, needing no "
                "file. REQUIRED for anything metallic: a full metal has no "
                "diffuse response, so in a directional rig it has nothing to "
                "reflect and renders BLACK at every intensity.\n"
                "'hdri' is the same dome driven by your own .hdr/.exr."
            )),
        ],
        intensity: Annotated[float, Field(gt=0, le=20, description=(
            "Rig intensity, in fully-lit surfaces. 1.0 means a surface facing "
            "the key reads its OWN albedo - a light grey wall renders light "
            "grey. 0.5 is visibly dim, 2.0 deliberately hot. The key/fill/rim "
            "ratio is fixed; this scales the whole rig."
        ))] = 1.0,
        hdri_path: Annotated[Optional[str], Field(description=(
            "Absolute path to an .hdr/.exr. Required for preset='hdri' - no HDRI "
            "is bundled. Use preset='environment' for a dome without a file."
        ))] = None,
        replace_existing: Annotated[bool, Field(description=(
            "Delete existing lights first. Auto-checkpoints before doing so. "
            "Only light transforms are removed; other nodes are never touched."
        ))] = True,
    ) -> LightingResult:
        """Build a lighting rig so the model can actually be judged.

        Pair with maya_capture_viewport(lighting='scene') to see it - or, for a
        dome, with maya_render_scene: image-based lighting is a render feature,
        and the viewport will not show it.

        The dome presets need Arnold. Without it they fall back to a directional
        light and SAY SO in warnings, because that fallback cannot show a metal
        correctly and a silent substitution would look like a material bug."""
        return LightingResult.model_validate(
            maya.request(
                "setup_lighting",
                {"preset": preset, "intensity": intensity,
                 "hdri_path": hdri_path, "replace_existing": replace_existing},
                timeout_s=SCENE_TIMEOUT_S,
            )
        )

    @mcp.tool(
        title="Assign material",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, idempotent_hint=False
        ),
    )
    def maya_assign_material(
        mesh: Annotated[str, Field(min_length=1, description="Canonical long name.")],
        shader: Annotated[
            Literal["standardSurface", "lambert", "blinn"],
            Field(description="Shader type to create."),
        ] = "standardSurface",
        params: Annotated[dict, Field(description=(
            "Whitelisted per shader. standardSurface: baseColor, roughness, "
            "metalness, emission, emissionColor, specular, transmission "
            "(0..1), transmissionColor, transmissionDepth (0..100), ior "
            "(1.0..3.0 - water 1.33, glass 1.5, diamond 2.42), coat, "
            "coatRoughness. lambert: color, transparency, incandescence. blinn "
            "adds eccentricity, specularColor. Colours are [r, g, b] in 0..1. "
            "Unknown keys are rejected with that shader's whitelist in the hint."
            "\n\nGEM/GLASS WARNING: transmissionColor is an ABSORPTION tint, "
            "not a paint colour - light that gets through is multiplied by it. "
            "Saturating it (e.g. [0.75, 0.04, 0.09] for a ruby) absorbs almost "
            "everything and renders a dark solid indistinguishable from opaque "
            "paint. Use a PALE tint with transmission 1.0, and set "
            "transmissionDepth to roughly the object's own size to control the "
            "colour physically. A cut gem also wants coat 1.0 with a low "
            "coatRoughness for its polish."
        ))] = {},
        name: Annotated[Optional[str], Field(description=(
            "Material name; defaults to <mesh>_mat. Collisions get a _NNN suffix."
        ))] = None,
    ) -> MaterialResult:
        """Assign one material to a whole mesh (object-level shading only).

        If name matches an existing shader of the SAME shader type, that
        shader is reused (params are applied to it) instead of minting a new
        one - the way to share one material across many meshes without
        leaking a shader node per call. A name that exists as a different
        node type, or a shader of a different type, is a clear error.

        Multi-material looks come from splitting geometry into separate meshes -
        per-face assignment is unreliable on boolean output."""
        return MaterialResult.model_validate(
            maya.request(
                "assign_material",
                {"mesh": mesh, "shader": shader, "params": params, "name": name},
                timeout_s=SCENE_TIMEOUT_S,
            )
        )

    @mcp.tool(
        title="Assign PBR material",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, idempotent_hint=False
        ),
    )
    def maya_assign_pbr(
        mesh: Annotated[Union[str, List[str]], Field(description=(
            "One canonical long name, or a list of them. A list shares ONE "
            "material across every mesh - which is the point when they all read "
            "from a common atlas."
        ))],
        maps: Annotated[dict, Field(description=(
            "Slot -> image. A bare string is the path; an object takes "
            "{path, channel, invert, raw, mip_filter}.\n"
            "Slots: color, emission_color (colour, whole image), metalness, "
            "roughness (scalar, one channel), normal (tangent-space normal map "
            "via bump2d).\n"
            "channel (r/g/b/a, scalar slots only, default r) is how a packed "
            "mask drives several slots from ONE image - two slots naming the "
            "same file share a single file node.\n"
            "invert inserts a reverse node: that is how a SMOOTHNESS map "
            "becomes roughness.\n"
            "raw defaults to true for metalness/roughness/normal, false for "
            "colour - normal and mask maps are data, not colour, and an sRGB "
            "curve on them bends the normals and shifts every roughness value.\n"
            "mip_filter defaults true; pass false for an ATLAS, where mip blur "
            "bleeds neighbouring patches across every seam.\n"
            'e.g. {"color": "D:/kit_albedo.png", "normal": "D:/kit_nrm.png", '
            '"metalness": {"path": "D:/kit_mask.png", "channel": "r"}, '
            '"roughness": {"path": "D:/kit_mask.png", "channel": "g", '
            '"invert": true}}'
        ))],
        params: Annotated[dict, Field(description=(
            "Constant standardSurface values for anything NOT driven by a map "
            "(base, specular, ior, coat...). Same whitelist as "
            "maya_assign_material. Naming a param that a map also drives is an "
            "error, not a silent override."
        ))] = {},
        name: Annotated[Optional[str], Field(description=(
            "Material name; an existing standardSurface of this name is REUSED, "
            "which is how a whole kit ends up on one shader."
        ))] = None,
    ) -> PbrResult:
        """Wire a full multi-map standardSurface in one call.

        Builds file nodes + place2dTexture + reverse (for inverted scalars) +
        bump2d, then assigns the material to every mesh given. Texture paths are
        resolved on the machine running MAYA, and a missing file is refused
        rather than rendered flat - Maya reports nothing for a missing map, the
        material simply looks wrong.

        Use maya_assign_material instead when there are no textures at all."""
        return PbrResult.model_validate(
            maya.request(
                "assign_pbr",
                {"mesh": mesh, "maps": maps, "params": params, "name": name},
                timeout_s=SCENE_TIMEOUT_S,
            )
        )

    @mcp.tool(
        title="Apply texture recipe",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, idempotent_hint=False
        ),
    )
    def maya_apply_texture_recipe(
        mesh: Annotated[str, Field(min_length=1, description="Canonical long name.")],
        recipe: Annotated[
            Literal["noise_bump", "ramp_gradient", "layered_mask", "file_texture"],
            Field(description=(
                "noise_bump - surface grain via bump; ramp_gradient - gradient "
                "into colour; layered_mask - masked blend; file_texture - an "
                "image file. Requires a material on the mesh first."
            )),
        ],
        params: Annotated[dict, Field(description=(
            "noise_bump: scale, depth. file_texture: file_path (required). "
            "Others take no params yet."
        ))] = {},
        slot: Annotated[
            Optional[Literal["color", "roughness", "normal"]],
            Field(description=(
                "Override the recipe's default slot. Mapped to the real attribute "
                "per shader type; a slot the shader lacks is an error, not a no-op."
            )),
        ] = None,
    ) -> TextureRecipeResult:
        """Build a named texture network and wire it into the mesh's shader.

        Capture with shading="textured" to see the result - smoothShaded
        (the default capture mode) hides texture networks exactly as it
        hides facets, and you will conclude the recipe did nothing."""
        return TextureRecipeResult.model_validate(
            maya.request(
                "apply_texture_recipe",
                {"mesh": mesh, "recipe": recipe, "params": params, "slot": slot},
                timeout_s=SCENE_TIMEOUT_S,
            )
        )

    @mcp.tool(
        title="Create joint skeleton",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=False
        ),
    )
    def maya_create_skeleton(
        joints: Annotated[Optional[List[dict]], Field(description=(
            "Explicit form: one entry per joint - {name, position: [x,y,z] "
            "scene units, parent?: joint name from this same call, orient?: "
            "[x,y,z] DEGREES}. Any order; duplicate names, unknown parents "
            "and cycles refuse the whole call before any joint exists. "
            "Exactly one joint names no parent - a skeleton has one root."
        ))] = None,
        chain: Annotated[Optional[List[List[float]]], Field(description=(
            "Shorthand for one parented run: world positions, at least 2. "
            "Each joint parents to the previous; names are "
            "<chain_prefix>_01, _02, ... Pass either chain or joints, never "
            "both."
        ))] = None,
        chain_prefix: Annotated[str, Field(description=(
            "Name prefix for the chain shorthand."
        ))] = "joint",
        root_name: Annotated[Optional[str], Field(description=(
            "Renames the chain's first joint (the root)."
        ))] = None,
    ) -> CreateSkeletonResult:
        """Build a validated joint hierarchy in one call.

        Joint orientation defaults to Maya's own convention - X aims at the
        first child, leaves zeroed - and whatever orientation actually landed
        is reported per joint in degrees, because orientation is where every
        rig surprise lives. Returns canonical long names; use them as the
        keys of maya_pose_skeleton's rotations map."""
        params = {"joints": joints, "chain": chain}
        if chain is not None:
            params["chain_prefix"] = chain_prefix
            params["root_name"] = root_name
        return CreateSkeletonResult.model_validate(
            maya.request("create_skeleton", params, timeout_s=SCENE_TIMEOUT_S)
        )

    @mcp.tool(
        title="Bind mesh to skeleton",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=False
        ),
    )
    def maya_bind_skin(
        mesh: Annotated[str, Field(description="Mesh to bind (long name).")],
        root: Annotated[str, Field(description=(
            "Skeleton root joint from maya_create_skeleton. The whole "
            "hierarchy under it becomes influences."
        ))],
        max_influences: Annotated[int, Field(ge=1, le=8, description=(
            "Joints allowed per vertex. 4 is the game-engine convention."
        ))] = 4,
        method: Annotated[
            Literal["closestDistance", "heatMap", "geodesicVoxel"],
            Field(description=(
                "Initial weighting. closestDistance is robust everywhere; "
                "heatMap follows the surface (fails on non-manifold meshes); "
                "geodesicVoxel handles overlapping shells."
            )),
        ] = "closestDistance",
    ) -> BindSkinResult:
        """Bind a mesh to a skeleton and MEASURE the result.

        unweighted_vertices must be 0 for a deliverable bind - a vertex no
        joint owns stays behind when the creature moves, and nothing looks
        wrong at bind time. per_joint says which joints own which share of
        the mesh, which is how to see a bind without a viewport. Re-binding
        an already-bound mesh is refused (stacked skinClusters make weights
        unexplainable) - unbind first, or restore the pre-bind checkpoint."""
        return BindSkinResult.model_validate(
            maya.request(
                "bind_skin",
                {"mesh": mesh, "root": root, "max_influences": max_influences,
                 "method": method},
                timeout_s=BOOL_TIMEOUT_S,
            )
        )

    @mcp.tool(
        title="Pose skeleton",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=True
        ),
    )
    def maya_pose_skeleton(
        root: Annotated[str, Field(description="Skeleton root joint.")],
        rotations: Annotated[dict, Field(description=(
            "Map of joint name to [rx, ry, rz] local euler DEGREES - absolute "
            "values, not deltas, so re-applying a pose is idempotent. This "
            "map IS the pose currency: phase-3 IK bakes into it and a "
            "phase-6 clip keys it."
        ))],
    ) -> PoseSkeletonResult:
        """Apply per-joint local rotations and MEASURE what moved.

        Reports every joint's achieved world position and the bound mesh's
        max vertex displacement (vertices, never bounding boxes). A pose
        whose displacement is near zero against the mesh's size warns
        loudly - rotations that land on joints owning no vertices look
        exactly like success otherwise."""
        return PoseSkeletonResult.model_validate(
            maya.request(
                "pose_skeleton",
                {"root": root, "rotations": rotations, "space": "local"},
                timeout_s=BOOL_TIMEOUT_S,
            )
        )

    @mcp.tool(
        title="Reset to bind pose",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=True
        ),
    )
    def maya_reset_pose(
        root: Annotated[str, Field(description="Skeleton root joint.")],
    ) -> ResetPoseResult:
        """Return a skeleton to its bind pose.

        Every measurement and every export must happen from a KNOWN pose;
        'whatever the last test left behind' is not a bind pose. Unbound
        skeletons have no bind pose - rotations are zeroed (the
        create_skeleton rest pose) and a warning says so."""
        return ResetPoseResult.model_validate(
            maya.request("reset_pose", {"root": root}, timeout_s=BOOL_TIMEOUT_S)
        )

    return mcp


def main() -> None:
    _setup_logging()
    log.info("starting maya-mcp server (stdio)")
    create_server().run("stdio")


if __name__ == "__main__":
    main()
