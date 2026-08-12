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
from .schemas import ExecuteResult, SceneGraphResult

log = logging.getLogger("maya_mcp.server")

Angle = Literal["front", "side", "back", "top", "three_quarter", "current"]

# Transport grace on top of the per-command timeout the plugin enforces itself.
SCENE_TIMEOUT_S = 30.0
CAPTURE_TIMEOUT_S = 120.0


def _setup_logging() -> None:
    log_dir = os.path.join(os.path.expanduser("~"), ".maya-mcp", "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            os.path.join(log_dir, "server.log"), maxBytes=2_000_000, backupCount=3
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        root = logging.getLogger("maya_mcp")
        root.addHandler(handler)
        root.setLevel(os.environ.get("MAYA_MCP_LOG_LEVEL", "INFO").upper())
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
        annotations=ToolAnnotations(read_only_hint=False, destructive_hint=True),
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
        annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True),
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
        annotations=ToolAnnotations(read_only_hint=True),
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

    return mcp


def main() -> None:
    _setup_logging()
    log.info("starting maya-mcp server (stdio)")
    create_server().run("stdio")


if __name__ == "__main__":
    main()
