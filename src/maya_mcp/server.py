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
import logging.handlers
import os
from typing import Annotated, List, Literal, Optional, Union

from mcp.server import MCPServer
from mcp.server.mcpserver import Image
from mcp.types import ToolAnnotations
from pydantic import Field

from . import images, refstore
from .connection import MayaConnection
from .schemas import (
    BooleanResult,
    CameraResult,
    CheckpointResult,
    CleanupResult,
    DeformResult,
    DeleteResult,
    ExecuteResult,
    LightingResult,
    MaterialResult,
    NameResult,
    NewSceneResult,
    ObjectInfoResult,
    OpenSceneResult,
    ReferenceResult,
    RemeshResult,
    ResetNamespaceResult,
    RestoreResult,
    SaveSceneResult,
    SceneGraphResult,
    SculptResult,
    TransformResult,
    UndoResult,
    ViewportState,
)

log = logging.getLogger("maya_mcp.server")

Angle = Literal["front", "side", "back", "top", "three_quarter", "current"]
Vec3 = Annotated[
    Optional[List[float]],
    Field(min_length=3, max_length=3, description="XYZ triple."),
]

# Transport grace on top of the per-command timeout the plugin enforces itself.
SCENE_TIMEOUT_S = 30.0
CAPTURE_TIMEOUT_S = 120.0
BOOL_TIMEOUT_S = 120.0


def _setup_logging() -> None:
    root = logging.getLogger("maya_mcp")
    # Unknown MAYA_MCP_LOG_LEVEL values fall back to INFO; a typo'd env var
    # must never prevent the server from starting.
    name = os.environ.get("MAYA_MCP_LOG_LEVEL", "INFO").strip().upper()
    level = getattr(logging, name, None)
    root.setLevel(level if isinstance(level, int) else logging.INFO)
    if any(isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers):
        return
    log_dir = os.path.join(os.path.expanduser("~"), ".maya-mcp", "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            os.path.join(log_dir, "server.log"), maxBytes=2_000_000, backupCount=3
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        root.addHandler(handler)
    except OSError:
        pass


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
        the code raised (None otherwise), and the namespace keys. stdout is
        capped at 8 KB with an explicit truncation notice.
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
            Field(description="Viewport shading mode for the capture."),
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
        frame_all: Annotated[
            bool, Field(description="Frame the subject before capturing.")
        ] = True,
        resolution: Annotated[
            int, Field(ge=64, le=2048, description="Capture resolution in pixels.")
        ] = 768,
    ) -> list:  # images + text; media results carry no structured-output schema
        """Capture the Maya viewport from one or more angles — your eyes.

        Returns one image per angle plus a text summary of camera positions.
        Captures are side-effect-free: all viewport state is restored."""
        if len(angles) > 4:
            raise ValueError("at most 4 angles per call; split larger captures")
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
                "frame_all": frame_all,
                "resolution": resolution,
            },
            timeout_s=CAPTURE_TIMEOUT_S,
        )
        content: List[Union[Image, str]] = []
        for shot in result.get("images", []):
            png = images.decode_and_downscale(shot["png_b64"])
            content.append(Image(data=png, format="png"))
        content.append(
            "camera_positions: " + json.dumps(result.get("camera_positions", []))
        )
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
        lighting: Annotated[
            Literal["default", "scene", "flat"],
            Field(description="'scene' uses the scene's own lights."),
        ] = "default",
    ) -> list:
        """Orbit the subject and return a single contact-sheet image.

        Eight views for the token cost of one image - the final judgement pass."""
        result = maya.request(
            "capture_turntable",
            {"target": target, "n_frames": n_frames,
             "resolution": resolution, "lighting": lighting},
            timeout_s=CAPTURE_TIMEOUT_S,
        )
        cells = [
            images.decode_and_downscale(shot["png_b64"], max_px=resolution)
            for shot in result.get("images", [])
        ]
        sheet = images.contact_sheet(cells)
        return [
            Image(data=images.decode_and_downscale(
                base64.b64encode(sheet).decode("ascii")), format="png"),
            "turntable: %d frames, azimuths %s" % (
                result.get("n_frames", 0),
                json.dumps([s["azimuth"] for s in result.get("images", [])]),
            ),
        ]

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
            {"angles": [angle], "shading": "smoothShaded",
             "wireframe_overlay": False, "buffer": "beauty", "isolate": None,
             "frame_all": True, "resolution": resolution,
             "lighting": lighting, "shadows": False},
            timeout_s=CAPTURE_TIMEOUT_S,
        )
        shots = result.get("images", [])
        if not shots:
            raise ValueError("capture returned no image to compare against")
        current = images.decode_and_downscale(shots[0]["png_b64"], max_px=resolution)
        composite = images.side_by_side(reference, current)
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
            "Id returned by maya_checkpoint (NNN_label)."
        ))],
    ) -> RestoreResult:
        """Replace the current scene with a checkpoint. An auto-checkpoint of
        the current state is taken first. Discards the undo queue (file load)."""
        return RestoreResult.model_validate(
            maya.request(
                "restore_checkpoint", {"checkpoint_id": checkpoint_id},
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
    ) -> NewSceneResult:
        """Start an empty scene. REFUSES without confirm=true. Auto-checkpoints
        the discarded scene first (unlike undo, this survives a scene replace) -
        recover it via maya_restore_checkpoint(pre_checkpoint)."""
        return NewSceneResult.model_validate(
            maya.request("new_scene", {"confirm": confirm}, timeout_s=SESSION_TIMEOUT_S)
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
            Literal["cube", "sphere", "cylinder", "plane", "torus", "cone"],
            Field(description="Primitive type."),
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
    ) -> TransformResult:
        """Move/rotate/scale objects by name. Returns the resulting transforms —
        trust these over your own bookkeeping: the live user may also be moving
        things, and warnings will say so."""
        return TransformResult.model_validate(
            maya.request(
                "transform",
                {"names": names, "translate": translate, "rotate": rotate,
                 "scale": scale, "relative": relative},
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
        a: Annotated[str, Field(description="First mesh (kept material wins).")],
        b: Annotated[str, Field(description="Second mesh; both inputs are consumed.")],
        op: Annotated[Literal["union", "difference", "intersection"],
                      Field(description="difference = a minus b.")],
        new_name: Annotated[str, Field(min_length=1, description="Name for the result.")],
    ) -> BooleanResult:
        """Boolean two meshes. Auto-checkpoints first; deletes construction
        history and collapses shading to one object-level material (per-face
        shading does not survive booleans). Non-watertight results come back
        ok with a warning + cleanup hint."""
        return BooleanResult.model_validate(
            maya.request(
                "boolean_op", {"a": a, "b": b, "op": op, "new_name": new_name},
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
            "Name for the carved result; defaults to <mesh>_etched."
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
            Literal["bend", "lattice", "squash", "twist", "sculpt"],
            Field(description="Nonlinear/lattice deformer type to apply."),
        ],
        params: Annotated[
            Optional[dict],
            Field(description=(
                "Deformer parameters, whitelisted per type: bend takes curvature; "
                "squash takes factor; twist takes startAngle/endAngle; sculpt takes "
                "maxDisplacement/dropoffDistance; all four also take lowBound/"
                "highBound; lattice takes divisions:[x,y,z]. Every type also accepts "
                "translate/rotate, applied to the deformer handle. Unknown keys are "
                "rejected with that type's whitelist in the error hint."
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
        deformer instead."""
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
        naming what was unavailable."""
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
            Literal["three_point", "single_sun", "hdri"],
            Field(description="Light rig to build."),
        ],
        intensity: Annotated[float, Field(gt=0, le=20, description=(
            "Overall rig intensity; 1.0 is neutral."
        ))] = 1.0,
        hdri_path: Annotated[Optional[str], Field(description=(
            "Absolute path to an .hdr/.exr. Required for preset='hdri' - no HDRI "
            "is bundled."
        ))] = None,
        replace_existing: Annotated[bool, Field(description=(
            "Delete existing lights first. Auto-checkpoints before doing so. "
            "Only light transforms are removed; other nodes are never touched."
        ))] = True,
    ) -> LightingResult:
        """Build a lighting rig so the model can actually be judged.

        Pair with maya_capture_viewport(lighting='scene') to see it."""
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
            "metalness, emission, emissionColor, specular. lambert: color, "
            "transparency, incandescence. blinn adds eccentricity, "
            "specularColor. Colours are [r, g, b] in 0..1. Unknown keys are "
            "rejected with that shader's whitelist in the hint."
        ))] = {},
        name: Annotated[Optional[str], Field(description=(
            "Material name; defaults to <mesh>_mat. Collisions get a _NNN suffix."
        ))] = None,
    ) -> MaterialResult:
        """Assign one material to a whole mesh (object-level shading only).

        Multi-material looks come from splitting geometry into separate meshes -
        per-face assignment is unreliable on boolean output."""
        return MaterialResult.model_validate(
            maya.request(
                "assign_material",
                {"mesh": mesh, "shader": shader, "params": params, "name": name},
                timeout_s=SCENE_TIMEOUT_S,
            )
        )

    return mcp


def main() -> None:
    _setup_logging()
    log.info("starting maya-mcp server (stdio)")
    create_server().run("stdio")


if __name__ == "__main__":
    main()
