"""Pure rigging math and validation (#602 phase 1): no Maya, no scene.

The split follows arraymath/uvmath/sculpt_math: everything establishable
without Maya lives here so the headless suite carries it, and the handler
module is orchestration only.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..dispatcher import HandlerError

# A skeleton past this is a data error, not ambition: the humanoid the design
# plans for is ~20 joints, and a mocap-dense film rig is out of scope.
MAX_JOINTS = 256

# Below this a weight is float dust, not an influence: it neither holds a
# vertex nor shows up visually, and counting it would report a clean
# 4-influence bind as violating max_influences.
WEIGHT_TOL = 1e-4


def vec3(value, what: str, default=None) -> Optional[List[float]]:
    """Same contract as assemble._vec3; public because rigging validates maps."""
    if value is None:
        return default
    if (
        not isinstance(value, (list, tuple)) or len(value) != 3
        or not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                   for v in value)
    ):
        raise HandlerError(
            "%s must be a list of 3 numbers, got %r" % (what, value),
            hint="e.g. %s=[0, 1.5, 0]" % what,
        )
    return [float(v) for v in value]


def resolve_joints(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Resolve `joints` or the `chain` shorthand into ONE ordered list, or
    refuse the whole call. Parents come before children in the result.

    Whole-call validation is the assemble rule: a skeleton that dies halfway
    through creation is orphan cleanup nobody asked for.
    """
    joints = params.get("joints")
    chain = params.get("chain")
    if (joints is None) == (chain is None):
        raise HandlerError(
            "pass exactly one of 'joints' or 'chain'",
            hint="joints=[{name, position, parent?, orient?}] for an explicit "
                 "hierarchy; chain=[[x,y,z], ...] with chain_prefix for a "
                 "single parented run",
        )

    if chain is not None:
        prefix = params.get("chain_prefix", "joint")
        if not isinstance(prefix, str) or not prefix.strip():
            raise HandlerError("chain_prefix must be a non-empty string")
        prefix = prefix.strip()
        if not isinstance(chain, list) or len(chain) < 2:
            raise HandlerError(
                "chain must be a list of at least 2 positions",
                hint="one joint is not a chain - pass joints=[{...}] instead",
            )
        root_name = params.get("root_name")
        joints = []
        for index, pos in enumerate(chain):
            name = "%s_%02d" % (prefix, index + 1)
            if index == 0 and root_name is not None:
                name = str(root_name)
            joints.append({
                "name": name,
                "position": vec3(pos, "chain[%d]" % index),
                "parent": joints[index - 1]["name"] if index else None,
            })
    else:
        for shorthand_only in ("chain_prefix", "root_name"):
            if params.get(shorthand_only) is not None:
                raise HandlerError(
                    "%s only applies to the chain shorthand" % shorthand_only,
                    hint="the explicit joints form names every joint itself",
                )

    if not isinstance(joints, list) or not joints:
        raise HandlerError("joints must be a non-empty list")
    if len(joints) > MAX_JOINTS:
        raise HandlerError(
            "%d joints is over the %d-joint ceiling" % (len(joints), MAX_JOINTS),
            hint="split the creature, or question the source of the list",
        )

    resolved: List[Dict[str, Any]] = []
    by_name: Dict[str, Dict[str, Any]] = {}
    for index, joint in enumerate(joints):
        where = "joints[%d]" % index
        if not isinstance(joint, dict):
            raise HandlerError("%s must be an object, got %r" % (where, joint))
        unknown = set(joint) - {"name", "position", "parent", "orient"}
        if unknown:
            raise HandlerError(
                "%s has unknown keys: %s" % (where, ", ".join(sorted(unknown))),
                hint="valid: name, position, parent, orient",
            )
        name = joint.get("name")
        if not isinstance(name, str) or not name.strip():
            raise HandlerError("%s needs a non-empty 'name'" % where)
        name = name.strip()
        if name in by_name:
            raise HandlerError(
                "duplicate joint name %r" % name,
                hint="every joint needs its own name - it is the pose map's key",
            )
        parent = joint.get("parent")
        if parent is not None and (not isinstance(parent, str) or not parent.strip()):
            raise HandlerError("%s.parent must be a joint name or null" % where)
        entry = {
            "name": name,
            "position": vec3(joint.get("position"), where + ".position"),
            "parent": parent.strip() if isinstance(parent, str) else None,
            "orient": vec3(joint.get("orient"), where + ".orient"),
        }
        if entry["position"] is None:
            raise HandlerError("%s needs a 'position'" % where,
                               hint="world-space [x, y, z] in scene units")
        resolved.append(entry)
        by_name[name] = entry

    roots = [j for j in resolved if j["parent"] is None]
    for joint in resolved:
        if joint["parent"] is not None and joint["parent"] not in by_name:
            raise HandlerError(
                "joint %r names parent %r, which is not in this call"
                % (joint["name"], joint["parent"]),
                hint="parents must be joints of the same create_skeleton call",
            )
    if len(roots) != 1:
        raise HandlerError(
            "a skeleton has exactly one root; %d joints name no parent"
            % len(roots),
            hint="two roots are two skeletons - make two calls",
        )

    # Topological order by walking down from the root; anything unreached
    # hangs off a parent cycle.
    children: Dict[str, List[Dict[str, Any]]] = {}
    for joint in resolved:
        if joint["parent"] is not None:
            children.setdefault(joint["parent"], []).append(joint)
    order: List[Dict[str, Any]] = []
    frontier = [roots[0]]
    while frontier:
        joint = frontier.pop(0)
        order.append(joint)
        frontier.extend(children.get(joint["name"], []))
    if len(order) != len(resolved):
        stranded = sorted(set(by_name) - {j["name"] for j in order})
        raise HandlerError(
            "joints form a parent cycle: %s" % ", ".join(stranded[:6]),
            hint="every joint must chain up to the root",
        )
    return order


def weight_stats(influences: List[str], weights: List[float], num_verts: int,
                 max_influences: int) -> Dict[str, Any]:
    """Per-joint ownership from one flat vertex-major weight table.

    `weights[v * len(influences) + j]` is joint j's hold on vertex v - the
    layout MFnSkinCluster.getWeights returns. This is the whole of how an
    agent SEES a bind without a viewport: a joint owning zero vertices, or
    one joint owning everything, is a legible failure in these numbers.
    """
    ncols = len(influences)
    if num_verts * ncols != len(weights):
        raise ValueError(
            "weight table is %d entries, expected %d verts x %d influences"
            % (len(weights), num_verts, ncols))
    unweighted = 0
    exceeded = 0
    counts = [0] * ncols
    sums = [0.0] * ncols
    for v in range(num_verts):
        held = 0
        for j in range(ncols):
            w = weights[v * ncols + j]
            if w > WEIGHT_TOL:
                held += 1
                counts[j] += 1
                sums[j] += w
        if held == 0:
            unweighted += 1
        if held > max_influences:
            exceeded += 1
    return {
        "unweighted_vertices": unweighted,
        "max_influences_exceeded": exceeded,
        "per_joint": [
            {"joint": influences[j], "vertices": counts[j],
             "mean_weight": (sums[j] / counts[j]) if counts[j] else 0.0}
            for j in range(ncols)
        ],
    }


def displaced_count(before: List[float], after: List[float],
                    tol: float = 1e-5) -> int:
    """How many vertices moved more than `tol` between two flat xyz lists."""
    if len(before) != len(after) or len(before) % 3:
        raise ValueError(
            "position lists are %d and %d floats; expected equal xyz triples "
            "- a mismatch means the two captures are not the same mesh"
            % (len(before), len(after)))
    moved = 0
    for i in range(0, len(before), 3):
        dx = after[i] - before[i]
        dy = after[i + 1] - before[i + 1]
        dz = after[i + 2] - before[i + 2]
        if dx * dx + dy * dy + dz * dz > tol * tol:
            moved += 1
    return moved
