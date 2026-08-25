"""Pure rigging math and validation (#602 phase 1): no Maya, no scene.

The split follows arraymath/uvmath/sculpt_math: everything establishable
without Maya lives here so the headless suite carries it, and the handler
module is orchestration only.
"""

from __future__ import annotations

import math
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


def normalize_row(row: List[float]) -> List[float]:
    """One vertex's weights scaled to sum 1. An all-zero row has nothing to
    scale and stays zero - the caller counts it as unweighted, not an error."""
    total = sum(row)
    if total <= 0.0:
        return list(row)
    return [w / total for w in row]


def prune_row(row: List[float], max_influences: int) -> List[float]:
    """Keep the max_influences largest weights, zero the rest, renormalize.
    Smoothing bleeds weight onto every neighbouring influence; without this
    every smooth pass would grow influence counts past what bind_skin promised
    the exporter."""
    keep = set(sorted(range(len(row)), key=lambda j: row[j], reverse=True)
               [:max_influences])
    return normalize_row([row[j] if j in keep else 0.0
                          for j in range(len(row))])


def changed_rows(before: List[float], after: List[float], ncols: int,
                 tol: float = WEIGHT_TOL) -> int:
    """How many vertices' weight rows actually differ - the measured 'what did
    this op do' number every weight mutator reports."""
    if len(before) != len(after) or (ncols and len(before) % ncols):
        raise ValueError(
            "weight tables are %d and %d entries - not the same table"
            % (len(before), len(after)))
    changed = 0
    for v in range(0, len(before), ncols):
        if any(abs(after[v + j] - before[v + j]) > tol for j in range(ncols)):
            changed += 1
    return changed


def weight_report_stats(influences: List[str], weights: List[float],
                        num_verts: int, max_influences: int,
                        sample: int = 8) -> Dict[str, Any]:
    """weight_stats plus what an agent needs to ACT on a bad bind: which
    vertices offend (sample ids for set_region_weights targeting), how far
    sums drift, and the influence-count histogram that makes 'one joint owns
    everything' and 'weights smeared across eight joints' both legible."""
    out = weight_stats(influences, weights, num_verts, max_influences)
    ncols = len(influences)
    unweighted_sample: List[int] = []
    exceeded_sample: List[int] = []
    histogram: Dict[int, int] = {}
    max_err = 0.0
    for v in range(num_verts):
        held = 0
        total = 0.0
        for j in range(ncols):
            w = weights[v * ncols + j]
            total += w
            if w > WEIGHT_TOL:
                held += 1
        histogram[held] = histogram.get(held, 0) + 1
        if held == 0:
            if len(unweighted_sample) < sample:
                unweighted_sample.append(v)
        else:
            max_err = max(max_err, abs(total - 1.0))
        if held > max_influences and len(exceeded_sample) < sample:
            exceeded_sample.append(v)
    out["unweighted_sample"] = unweighted_sample
    out["exceeded_sample"] = exceeded_sample
    out["max_weight_sum_error"] = max_err
    out["histogram"] = [{"influences": k, "vertices": histogram[k]}
                        for k in sorted(histogram)]
    return out


def _cell(x: float, y: float, z: float, size: float):
    return (int(math.floor(x / size)), int(math.floor(y / size)),
            int(math.floor(z / size)))


def _nearest_within(positions: List[float], candidates_by_cell, target,
                    tolerance: float):
    """Index of the position nearest `target` within `tolerance`, else None.
    Grid-hash lookup: O(27) cells, not O(n) - the humanoid has ~15k verts."""
    base = _cell(target[0], target[1], target[2], tolerance)
    best, best_d2 = None, tolerance * tolerance
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                for i in candidates_by_cell.get(
                        (base[0] + dx, base[1] + dy, base[2] + dz), ()):
                    px, py, pz = positions[3 * i:3 * i + 3]
                    d2 = ((px - target[0]) ** 2 + (py - target[1]) ** 2
                          + (pz - target[2]) ** 2)
                    if d2 <= best_d2:
                        best, best_d2 = i, d2
    return best


def mirror_pairs(positions: List[float], axis_index: int, tolerance: float,
                 source_positive: bool = True):
    """(source, destination) vertex pairs across the mirror plane, by
    reflected position. On-plane vertices are neither; a source vertex whose
    reflection lands on no vertex is unpaired - an asymmetric mesh, reported
    not guessed."""
    n = len(positions) // 3
    by_cell: Dict[Any, List[int]] = {}
    for i in range(n):
        by_cell.setdefault(
            _cell(positions[3 * i], positions[3 * i + 1],
                  positions[3 * i + 2], tolerance), []).append(i)
    pairs, on_plane, unpaired = [], [], []
    for i in range(n):
        c = positions[3 * i + axis_index]
        if abs(c) <= tolerance:
            on_plane.append(i)
            continue
        if (c > 0) != source_positive:
            continue
        target = list(positions[3 * i:3 * i + 3])
        target[axis_index] = -target[axis_index]
        partner = _nearest_within(positions, by_cell, target, tolerance)
        if partner is None:
            unpaired.append(i)
        else:
            pairs.append((i, partner))
    return pairs, on_plane, unpaired


def mirror_influence_map(influence_positions: List[List[float]],
                         axis_index: int, tolerance: float):
    """Column j of the source side writes column mapping[j] on the mirrored
    side: the influence nearest j's reflected position. On-plane influences
    (spine, head) map to themselves; an off-plane influence with no partner
    maps to itself AND is returned in unmatched - the handler refuses on it,
    because copying left-arm weights onto left-arm joints for right-side
    vertices is exactly the silent wrong answer this surface never gives."""
    flat: List[float] = []
    for p in influence_positions:
        flat.extend(p)
    n = len(influence_positions)
    by_cell: Dict[Any, List[int]] = {}
    for i in range(n):
        by_cell.setdefault(
            _cell(flat[3 * i], flat[3 * i + 1], flat[3 * i + 2], tolerance),
            []).append(i)
    mapping, unmatched = [], []
    for i in range(n):
        c = flat[3 * i + axis_index]
        if abs(c) <= tolerance:
            mapping.append(i)
            continue
        target = list(flat[3 * i:3 * i + 3])
        target[axis_index] = -target[axis_index]
        partner = _nearest_within(flat, by_cell, target, tolerance)
        if partner is None or partner == i:
            mapping.append(i)
            unmatched.append(i)
        else:
            mapping.append(partner)
    return mapping, unmatched


def mirror_weight_table(weights: List[float], ncols: int, pairs,
                        mapping: List[int]) -> List[float]:
    """Write each source row onto its partner through the influence map.
    A mirrored row is a permutation of a normalized row, so normalization
    survives by construction."""
    out = list(weights)
    for src, dst in pairs:
        for j in range(ncols):
            out[dst * ncols + mapping[j]] = weights[src * ncols + j]
    return out


# Half own, half neighbourhood: strong enough that 2-3 passes visibly soften
# a stair-step, weak enough that a pass cannot invert local ownership.
SMOOTH_ALPHA = 0.5
MAX_SMOOTH_ITERATIONS = 50


def smooth_weight_table(weights: List[float], ncols: int,
                        adjacency: List[List[int]], iterations: int,
                        max_influences: int, rows=None,
                        alpha: float = SMOOTH_ALPHA) -> List[float]:
    """Laplacian smoothing over the mesh graph, the fix for stair-stepped
    falloff at hips and shoulders. Every smoothed row is pruned back to
    max_influences and renormalized - smoothing bleeds weight onto every
    neighbouring influence, and unchecked that breaks the bind's promise to
    the exporter."""
    num = len(weights) // ncols
    targets = list(range(num)) if rows is None else sorted(rows)
    current = list(weights)
    for _ in range(iterations):
        nxt = list(current)
        for v in targets:
            neighbours = adjacency[v]
            if not neighbours:
                continue
            row = []
            for j in range(ncols):
                # Jacobi on purpose: read in-progress results (Gauss-Seidel) would
                # make smoothing depend on vertex order and break L/R symmetry after
                # a mirror operation.
                mean = (sum(current[n * ncols + j] for n in neighbours)
                        / len(neighbours))
                row.append((1.0 - alpha) * current[v * ncols + j]
                           + alpha * mean)
            nxt[v * ncols:(v + 1) * ncols] = prune_row(row, max_influences)
        current = nxt
    return current


def radius_factors(positions: List[float], center: List[float],
                   radius: float, falloff: str) -> Dict[int, float]:
    """Vertex -> blend factor for a spherical region. Factors are (0, 1]:
    a zero factor is not-in-the-region, never a stored no-op."""
    out: Dict[int, float] = {}
    for v in range(len(positions) // 3):
        dx = positions[3 * v] - center[0]
        dy = positions[3 * v + 1] - center[1]
        dz = positions[3 * v + 2] - center[2]
        d = math.sqrt(dx * dx + dy * dy + dz * dz)
        if d > radius:
            continue
        factor = 1.0 if falloff == "none" else 1.0 - d / radius
        if factor > 0.0:
            out[v] = factor
    return out


def apply_region_weights(weights: List[float], ncols: int, joint_col: int,
                         factors: Dict[int, float], weight: float):
    """Blend one joint toward `weight` on the factored vertices; the other
    influences share what remains in their existing proportions. A vertex the
    joint solely owns cannot shed weight it has nobody to give to - it stays
    fully owned and is counted, because a silent 0.6 that reads back 1.0 is
    the lying-success defect class (#636)."""
    out = list(weights)
    sole_owner = 0
    for v, factor in factors.items():
        base = v * ncols
        old_j = weights[base + joint_col]
        new_j = old_j + (weight - old_j) * factor
        others = sum(weights[base + j] for j in range(ncols)
                     if j != joint_col)
        if others > 0.0:
            scale = (1.0 - new_j) / others
            for j in range(ncols):
                out[base + j] = new_j if j == joint_col \
                    else weights[base + j] * scale
        else:
            if new_j < 1.0 and old_j > 0.0:
                sole_owner += 1
            out[base + joint_col] = 1.0 if (old_j > 0.0 or new_j > 0.0) \
                else 0.0
    return out, sole_owner


# --- phase 3 (#671): IK chain geometry --------------------------------------


def _sub(a, b):
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0]]


def dist(a: List[float], b: List[float]) -> float:
    return math.sqrt(_dot(_sub(a, b), _sub(a, b)))


def chain_reach(positions: List[List[float]]) -> float:
    """Sum of bone lengths - the furthest the chain can straighten."""
    return sum(dist(positions[i], positions[i + 1])
               for i in range(len(positions) - 1))


def _perp_offsets(positions):
    """(interior point, its perpendicular offset from the start-end line)."""
    axis = _sub(positions[-1], positions[0])
    length = math.sqrt(_dot(axis, axis))
    out = []
    for mid in positions[1:-1]:
        offset = _sub(mid, positions[0])
        if length < 1e-12:
            out.append((mid, offset))
            continue
        along = _dot(offset, axis) / (length * length)
        out.append((mid, _sub(offset, [v * along for v in axis])))
    return out


def chain_deviation(positions: List[List[float]]) -> float:
    """How far the most-bent interior joint sits off the start-end line.
    Below ~1% of reach the RP solver sees a straight chain and cannot fold
    it on its own - the pre-bend exists for exactly that case."""
    if len(positions) < 3:
        return 0.0
    return max((math.sqrt(_dot(p, p)) for _, p in _perp_offsets(positions)),
               default=0.0)


def default_pole(positions, collinear_ratio: float) -> Optional[List[float]]:
    """A pole that PRESERVES the chain's own bend plane - the least
    surprising default: an already-bent knee keeps facing the way it faces.
    None when the chain is too straight to have a plane of its own."""
    if len(positions) < 3:
        return None
    reach = chain_reach(positions)
    best_mid, best_perp, best_norm = None, None, 0.0
    for mid, perp in _perp_offsets(positions):
        norm = math.sqrt(_dot(perp, perp))
        if norm > best_norm:
            best_mid, best_perp, best_norm = mid, perp, norm
    if best_mid is None or best_norm < collinear_ratio * max(reach, 1e-12):
        return None
    return [best_mid[k] + best_perp[k] / best_norm * reach for k in range(3)]


def plane_normal(start, target, pole) -> Optional[List[float]]:
    """Unit normal of the solve plane, or None when the pole sits on the
    start-target line (no plane - the solver would have to guess)."""
    n = _cross(_sub(target, start), _sub(pole, start))
    length = math.sqrt(_dot(n, n))
    if length < 1e-9:
        return None
    return [v / length for v in n]


def local_components(vec, matrix16: List[float]) -> List[float]:
    """A world vector expressed in a joint's local frame. Maya's xform
    matrix is row-major with rows 0..2 = the local axes in world space;
    joints in this project are identity-scale (the export gate's rule), so
    projecting onto the normalized rows IS the inverse rotation."""
    out = []
    for row in range(3):
        axis = matrix16[row * 4:row * 4 + 3]
        length = math.sqrt(_dot(axis, axis)) or 1.0
        out.append(_dot(vec, axis) / length)
    return out


def prebend_rotations(positions, matrices: Dict[int, List[float]], target,
                      pole, angle_deg: float) -> Dict[int, List[float]]:
    """Per-interior-joint local euler nudges (DEGREES) that fold a straight
    chain so its bend lands on the pole's side of the solve plane.

    Sign, derived and pinned by test_prebend_folds_the_knee_toward_the_pole:
    folding a mid joint by +t about the plane normal moves the EFFECTOR
    along cross(normal, child - mid); the solver's compensation at the
    start joint then pushes the mid joint the OPPOSITE way - so bend
    against that direction to end up pole-side.
    """
    normal = plane_normal(positions[0], target, pole)
    if normal is None:
        return {}
    out: Dict[int, List[float]] = {}
    for i in range(1, len(positions) - 1):
        mid, child = positions[i], positions[i + 1]
        swing = _cross(normal, _sub(child, mid))
        sign = -1.0 if _dot(swing, _sub(pole, mid)) > 0 else 1.0
        out[i] = [angle_deg * sign * c
                  for c in local_components(normal, matrices[i])]
    return out


# --- #732: bind-pose rotation decomposition ---------------------------------


def _rot3_axis(axis: str, deg: float):
    """Row-vector rotation matrix about one axis (Maya's convention:
    row-major matrices, v' = v . M)."""
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    if axis == "x":
        return [[1.0, 0.0, 0.0], [0.0, c, s], [0.0, -s, c]]
    if axis == "y":
        return [[c, 0.0, -s], [0.0, 1.0, 0.0], [s, 0.0, c]]
    return [[c, s, 0.0], [-s, c, 0.0], [0.0, 0.0, 1.0]]


def _mat3_mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)]
            for i in range(3)]


def _euler_xyz_deg(m) -> List[float]:
    """Euler XYZ (degrees) of a row-vector rotation matrix M = Rx.Ry.Rz."""
    sy = -m[0][2]
    cy = math.hypot(m[0][0], m[0][1])
    if cy < 1e-9:  # gimbal: pick rz = 0
        return [math.degrees(math.atan2(-m[2][1], m[1][1])),
                math.degrees(math.atan2(sy, cy)), 0.0]
    return [math.degrees(math.atan2(m[1][2], m[2][2])),
            math.degrees(math.atan2(sy, cy)),
            math.degrees(math.atan2(m[0][1], m[0][0]))]


def bind_rotation_deg(xform16: List[float], joint_orient_deg: List[float],
                      rotate_axis_deg: List[float],
                      rotate_order: int) -> Optional[List[float]]:
    """The `.rotate` euler (DEGREES, XYZ) stored inside a dagPose local
    xformMatrix, with jointOrient and rotateAxis stripped (#732).

    A joint's local rotation composes as Rot = RA . R . JO in Maya's
    row-vector convention, so R = RA^-1 . Rot . JO^-1; both strippers are
    orthonormal, so inverse = transpose. Only the default XYZ rotate order
    (0) is composed - anything else returns None rather than guessing
    (the fbxbytes._rotation precedent: a wrong assumption would record a
    wrong rest value silently)."""
    if rotate_order != 0:
        return None
    rows = [[float(xform16[i * 4 + j]) for j in range(3)] for i in range(3)]
    normalized = []
    for row in rows:
        norm = math.sqrt(sum(v * v for v in row))
        if norm < 1e-12:
            return None
        normalized.append([v / norm for v in row])

    def _xyz(t):
        return _mat3_mul(_mat3_mul(_rot3_axis("x", t[0]),
                                   _rot3_axis("y", t[1])),
                         _rot3_axis("z", t[2]))

    def _t(m):
        return [[m[j][i] for j in range(3)] for i in range(3)]

    r = _mat3_mul(_mat3_mul(_t(_xyz(rotate_axis_deg)), normalized),
                  _t(_xyz(joint_orient_deg)))
    return _euler_xyz_deg(r)
