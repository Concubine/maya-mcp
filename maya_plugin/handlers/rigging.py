"""Skeletal rigging, phase 1 of #602: create_skeleton, bind_skin,
pose_skeleton, reset_pose.

Angles are degrees at the boundary (#636), positions are ordinary geometry
numbers (#629/#634), and every command reports what it MEASURED, not what it
was asked for: a bind reports the vertices no joint owns, a pose reports how
far the furthest vertex actually moved - from vertices, never bounding boxes
(#640). The shaping op that did nothing and said it succeeded is the worst
defect class this project knows (#636), and this module is built so that
failure is a number, not a feeling.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..dispatcher import HandlerError
from . import naming, rigmath, sculpt, sculpt_math, session, units


def _cmds():
    import maya.cmds as cmds  # noqa: PLC0415 - only importable inside Maya

    return cmds


def _short(name: str) -> str:
    return name.split("|")[-1]


def _long(cmds, node: str) -> str:
    return (cmds.ls(node, long=True) or [node])[0]


def create_skeleton(params: Dict[str, Any]) -> Dict[str, Any]:
    cmds = _cmds()
    resolved = rigmath.resolve_joints(params)
    session.auto_checkpoint("create_skeleton")

    warnings: List[str] = []
    long_names: Dict[str, str] = {}  # requested name -> created long name
    for joint in resolved:
        unique = naming.unique_name(cmds, joint["name"])
        if unique != joint["name"]:
            warnings.append(
                "%r already existed in the scene; created as %r"
                % (joint["name"], unique))
        if joint["parent"] is None:
            cmds.select(clear=True)
        else:
            cmds.select(long_names[joint["parent"]], replace=True)
        node = cmds.joint(name=unique, position=joint["position"])
        long_names[joint["name"]] = _long(cmds, node)

    root_long = long_names[resolved[0]["name"]]

    # Default orientation: aim the primary axis at the first child, Maya's own
    # convention; leaves are zeroed so nothing dangles a stray orient. The
    # explicit per-joint `orient` overrides afterwards. Whatever won is
    # REPORTED per joint, because orientation is where every rig surprise
    # lives.
    if cmds.listRelatives(root_long, children=True, type="joint"):
        cmds.joint(root_long, edit=True, orientJoint="xyz",
                   secondaryAxisOrient="yup", zeroScaleOrient=True,
                   children=True)
    for joint in resolved:
        node = long_names[joint["name"]]
        if not cmds.listRelatives(node, children=True, type="joint"):
            cmds.setAttr(node + ".jointOrient", 0.0, 0.0, 0.0)
        if joint["orient"] is not None:
            cmds.setAttr(node + ".jointOrient",
                         units.degrees_to_ui(cmds, joint["orient"][0]),
                         units.degrees_to_ui(cmds, joint["orient"][1]),
                         units.degrees_to_ui(cmds, joint["orient"][2]))

    joints_out = []
    for joint in resolved:
        node = long_names[joint["name"]]
        pos = cmds.xform(node, query=True, worldSpace=True, translation=True)
        raw = cmds.getAttr(node + ".jointOrient")[0]
        joints_out.append({
            "name": node,
            "position": [float(v) for v in pos],
            "parent": long_names[joint["parent"]] if joint["parent"] else None,
            "orient": [round(units.ui_to_degrees(cmds, v), 6) for v in raw],
        })
    return {"root": root_long, "joints": joints_out, "warnings": warnings}
