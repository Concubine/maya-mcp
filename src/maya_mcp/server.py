"""maya-mcp MCP server: tool schemas over the wire to the Maya plugin.

Every tool is a thin, validated wrapper around a plugin command. Perception
beats actuation: capture_viewport is THE critical tool; everything else exists
to give the LLM something worth looking at.

Run: `uv run maya-mcp` (stdio transport). Config via MAYA_MCP_* env vars.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
from typing import Annotated, List, Literal, Optional, Union

from mcp.server import MCPServer
from mcp.server.mcpserver import Image
from mcp.types import ToolAnnotations
from pydantic import Field

from . import images
from .connection import MayaConnection
from .schemas import (
    CheckpointResult,
    ExecuteResult,
    NewSceneResult,
    OpenSceneResult,
    ResetNamespaceResult,
    RestoreResult,
    SaveSceneResult,
    SceneGraphResult,
    UndoResult,
)

log = logging.getLogger("maya_mcp.server")

Angle = Literal["front", "side", "back", "top", "three_quarter", "current"]

# Transport grace on top of the per-command timeout the plugin enforces itself.
SCENE_TIMEOUT_S = 30.0
CAPTURE_TIMEOUT_S = 120.0


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
        """Start an empty scene. REFUSES without confirm=true."""
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
        """Open a scene file, replacing the current scene."""
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

    return mcp


def main() -> None:
    _setup_logging()
    log.info("starting maya-mcp server (stdio)")
    create_server().run("stdio")


if __name__ == "__main__":
    main()
