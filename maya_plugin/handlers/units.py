"""The scene's linear unit, reported as a consequence rather than a label.

maya-mcp #634. Every geometry number crossing the tool boundary - bboxes,
translations, the #603 pivots - is quoted in an ambient the protocol never
named, and nothing on the surface set or reported it.

`linear_unit` alone would mislead. Under the #629 authoring convention the
scene sits in "cm" while the numbers MEAN metres, so a caller reading a bbox of
3.0 beside "cm" would conclude 3 cm. `export_metres_per_unit` carries what
actually matters: how many metres one scene unit becomes in an exported FBX.

Maya's internal linear unit is centimetres whatever `currentUnit` reports, and
the FBX exporter writes those internal numbers - so that figure IS the
centimetres-per-unit table below. **1.0 is the only value that produces a
metre-true delivery**, which makes it one number a caller can assert on instead
of a string they have to interpret. That is the move that closed #629 at the
artifact, applied to the live scene.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..dispatcher import HandlerError

# Maya's eight linear units, in centimetres. Doubles as metres-per-unit in the
# exported file, for the reason in the module docstring.
_CM_PER_UNIT = {
    "mm": 0.1,
    "cm": 1.0,
    "m": 100.0,
    "km": 100000.0,
    "in": 2.54,
    "ft": 30.48,
    "yd": 91.44,
    "mi": 160934.4,
}

# The convention every mesh deliverable out of this repo is authored under.
METRE_TRUE_UNIT = "cm"


def units_block(cmds) -> Dict[str, Any]:
    """The unit facts for the current scene. Queries only, never sets."""
    unit = cmds.currentUnit(query=True, linear=True)
    return {
        "linear_unit": unit,
        # None, not 1.0, for anything unrecognised: this is embedded in query
        # responses, so it must not take a whole call down - but a wrong guess
        # here would read as metre-true, which is the failure #634 exists for.
        "export_metres_per_unit": _CM_PER_UNIT.get(unit),
    }


def require_known_unit(unit: Optional[str]) -> None:
    """Raise unless `unit` is one Maya knows. None means leave it alone.

    Separate from set_linear_unit so a destructive caller can validate first:
    new_scene replaces the scene, and a bad param must not cost the user their
    work before anyone notices it was bad.
    """
    if unit is None or unit in _CM_PER_UNIT:
        return
    raise HandlerError(
        "unknown linear unit %r" % unit,
        hint="one of %s; %r is the convention every deliverable is "
        "authored under (1 unit = 1 m in the exported FBX)"
        % (", ".join(sorted(_CM_PER_UNIT)), METRE_TRUE_UNIT),
    )


def set_linear_unit(cmds, unit: Optional[str]) -> Dict[str, Any]:
    """Set the scene's linear unit and report the result. None leaves it alone."""
    require_known_unit(unit)
    if unit is None:
        return units_block(cmds)
    cmds.currentUnit(linear=unit)
    return units_block(cmds)
