"""render_scene: pixels that do not need a viewport.

capture_viewport reads the VP2 viewport, which means it needs a mapped window -
an agent-launched Maya returns fully transparent playblasts - and that it
inherits VP2's approximations: transmission draws as plain transparency, so a
diamond and a plastic block look alike. cmds.render goes through the render
pipeline and needs neither. It renders headless, and under Arnold it refracts
for real (redmine #584).

The framing math is capture.py's, reused rather than restated. The one
difference is that capture lets viewFit refine its placement and viewFit needs a
panel, so here the camera's focal length is set to actually BE the field of view
the math assumes. Everything above the handler is pure and tested headless.
"""

from __future__ import annotations

import math
from typing import List, Optional, Sequence

from ..dispatcher import HandlerError
from . import capture

VALID_RENDERERS = ("arnold", "hw2")
RENDERER_TO_MAYA = {"arnold": "arnold", "hw2": "mayaHardware2"}
DEFAULT_RENDERER = "arnold"

# One angle by default, not capture's three: a rendered frame costs seconds.
# The 4-image ceiling is capture's, and holds for capture's reason - the token
# budget of the images coming back, not the time spent making them.
DEFAULT_ANGLES = ["three_quarter"]
DEFAULT_RESOLUTION = 512
MIN_RESOLUTION, MAX_RESOLUTION = 64, 2048
DEFAULT_SAMPLES, MIN_SAMPLES, MAX_SAMPLES = 3, 1, 8

# Maya's default camera vertical film aperture, in inches.
MAYA_VERTICAL_APERTURE_IN = 0.981


def focal_length_for_fov(
    fov_deg: float, aperture_inches: float = MAYA_VERTICAL_APERTURE_IN
) -> float:
    """Lens (mm) giving `fov_deg` vertical field of view on that film back."""
    half = math.radians(fov_deg) / 2.0
    return (aperture_inches * 25.4 / 2.0) / math.tan(half)


def resolve_angles(angles: Optional[Sequence[str]]) -> List[str]:
    if angles is None or angles == []:
        return list(DEFAULT_ANGLES)
    angles = list(angles)
    if len(angles) > capture.MAX_ANGLES_PER_CALL:
        raise HandlerError(
            "%d angles requested; the cap is %d images per call"
            % (len(angles), capture.MAX_ANGLES_PER_CALL),
            hint="split the render into multiple calls of up to 4 angles",
        )
    for angle in angles:
        if angle not in capture.VALID_ANGLES:
            raise HandlerError(
                "unknown angle %r" % angle,
                hint="valid angles: %s" % ", ".join(capture.VALID_ANGLES),
            )
    return angles


def resolve_renderer(renderer: Optional[str]) -> str:
    if renderer is None:
        return DEFAULT_RENDERER
    if renderer not in VALID_RENDERERS:
        raise HandlerError(
            "unknown renderer %r" % renderer,
            hint="valid renderers: %s ('arnold' refracts transmissive "
            "materials; 'hw2' is faster and does not)" % ", ".join(VALID_RENDERERS),
        )
    return renderer


def clamp_resolution(resolution: Optional[int]) -> int:
    if not isinstance(resolution, int) or isinstance(resolution, bool):
        return DEFAULT_RESOLUTION
    return max(MIN_RESOLUTION, min(MAX_RESOLUTION, resolution))


def resolve_samples(samples: Optional[int]) -> int:
    if samples is None:
        return DEFAULT_SAMPLES
    if (
        not isinstance(samples, int) or isinstance(samples, bool)
        or not (MIN_SAMPLES <= samples <= MAX_SAMPLES)
    ):
        raise HandlerError(
            "samples must be an integer %d..%d" % (MIN_SAMPLES, MAX_SAMPLES),
            hint="Arnold AA samples; 3 is a judgeable frame, 1 is noisy and "
            "fast. Ignored by the hw2 renderer.",
        )
    return samples


def frame_prefix(call_id: str, index: int, angle: str) -> str:
    """Image name for one frame.

    cmds.render writes into the project images dir and OVERWRITES a fixed path
    every call - both renders in the #584 probe landed on the same untitled.png.
    Every frame therefore gets its own prefix.
    """
    return "mayaMcpRender_%s_%d_%s" % (call_id, index, angle)
