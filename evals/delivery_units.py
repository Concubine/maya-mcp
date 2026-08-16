"""The delivery unit invariant, checked against the artifact.

Three independent assertions, because each catches a different way of being
wrong and the delivery has historically satisfied some while failing others:

  scale     a compensating node scale makes a wrong vertex magnitude render
            correctly, which is how a 100x error shipped three times looking
            fine - the prefab was the right size, the bare mesh was not
  lattice   chunk translations sit on the 3 m grid. NOTE this one cannot tell
            metres from centimetres on its own - 150 is a multiple of 1.5 too -
            so it is a grid-integrity check, not a unit check. Measured: it
            passes clean on the centimetre deliveries.
  pitch     the SPACING between adjacent occupied grid positions, which IS a
            unit discriminator: 1.5 m in metres, 150 in centimetres, and it
            needs no manifest to agree with
  ceiling   no vertex may exceed the contract's own envelope, in metres

Sibling import, not a package import: evals/ has no __init__.py and callers put
it on sys.path (see tests/test_demigol_generators.py).
"""
import fbx_probe

KIT_CEILING_M = 2.0     # cell half-face 1.5 + outset allowance 0.5
HERO_CEILING_M = 6.5    # MAX_RUN 4 cells x 3 m / 2 + outset 0.5
TOL = 1e-3

# A rig has no lattice to check and its chunks are all small, so the unit
# discriminator has to be the composed height - see check_rig_delivery.
GOLEM_HEIGHT_M = 4.02173   # 5.027162 modelled units x the pinned 0.8 m/unit
GOLEM_CEILING_M = 4.5      # a chunk's own vertices, in ITS space; the pelvis
                           # sits at the origin so its span is nearly the figure


def check_delivery(path, ceiling_m, lattice_m=1.5):
    """Return a list of human-readable violations; empty means metre-true."""
    facts = fbx_probe.read_fbx(path)
    label = getattr(path, "name", str(path))
    out = []

    for node in facts.nodes:
        if any(abs(s - 1.0) > TOL for s in node.scaling):
            out.append(
                "%s: node %r has scale %s, expected identity - a compensating "
                "node scale hides a wrong vertex magnitude"
                % (label, node.name, tuple(round(s, 6) for s in node.scaling)))

    for node in facts.nodes:
        for axis, value in zip("xyz", node.translation):
            if value and abs(value / lattice_m - round(value / lattice_m)) > TOL:
                out.append(
                    "%s: node %r translation %s=%.4f is not a multiple of the "
                    "%.1f m half-cell - the file is not in metres"
                    % (label, node.name, axis, value, lattice_m))

    # Spacing between adjacent occupied positions. Unlike divisibility above,
    # this scales with the unit, so it catches a x100 file even if every other
    # number happens to stay self-consistent. Skipped when a delivery puts all
    # its roots at the origin (the kit does - each piece is its own root).
    for axis, index in zip("xyz", range(3)):
        seen = sorted({round(n.translation[index], 6) for n in facts.nodes})
        gaps = [b - a for a, b in zip(seen, seen[1:]) if b - a > TOL]
        if not gaps:
            continue
        pitch = min(gaps)
        if abs(pitch - lattice_m) > TOL:
            out.append(
                "%s: %s-axis grid pitch measures %.4f, expected %.1f m - the "
                "file is out by a factor of %.4g"
                % (label, axis, pitch, lattice_m, pitch / lattice_m))

    # The declaration must agree with the numbers. Metre vertices declared as
    # centimetres is not a lesser error than the original - it is the same
    # class, just inverted, and Demigol measures unit scale on import.
    if facts.unit_scale_factor != fbx_probe.DECLARES_METRES:
        out.append(
            "%s: header declares UnitScaleFactor %r, expected %g (metres) - the "
            "vertices are metres, so the file contradicts itself"
            % (label, facts.unit_scale_factor, fbx_probe.DECLARES_METRES))

    out.extend(_scale_and_ceiling(facts, label, ceiling_m))
    return out


def _scale_and_ceiling(facts, label, ceiling_m):
    out = []
    biggest = 0.0
    for verts in facts.meshes:
        for v in verts:
            if abs(v) > biggest:
                biggest = abs(v)
    if biggest > ceiling_m:
        out.append(
            "%s: largest vertex coordinate %.4f m exceeds ceiling %.1f m%s"
            % (label, biggest, ceiling_m,
               " - this is a x100 unit error" if biggest > ceiling_m * 50 else ""))
    return out


def check_rig_delivery(path, height_m, ceiling_m, height_tol=1e-3):
    """The same invariant for an ARTICULATED delivery. Same list-of-strings
    contract as check_delivery.

    A rig defeats two of the three assertions above: there is no lattice to
    divide by, and every chunk's own vertices are small whatever the unit, so
    per-vertex magnitude no longer discriminates - a 4 m creature and a 4 cm one
    both have sub-metre chunks. What replaces them is the COMPOSED height,
    walked through the parent chain from the bytes, asserted against the figure
    the manifest states. That is the number a consumer sees on import.

    The scale assertion survives unchanged and matters more here, not less: 21
    of the golem's 33 transforms carried non-uniform scale in the scene, which
    is exactly the shape of the compensating-scale defect of maya-mcp #629.
    """
    facts = fbx_probe.read_fbx(path)
    label = getattr(path, "name", str(path))
    out = []

    for node in facts.nodes:
        if any(abs(s - 1.0) > TOL for s in node.scaling):
            out.append(
                "%s: node %r has scale %s, expected identity - a rigged chunk "
                "that carries scale deforms wrong the moment its parent turns, "
                "and hides a wrong vertex magnitude besides"
                % (label, node.name, tuple(round(s, 6) for s in node.scaling)))

    if facts.unit_scale_factor != fbx_probe.DECLARES_METRES:
        out.append(
            "%s: header declares UnitScaleFactor %r, expected %g (metres) - the "
            "vertices are metres, so the file contradicts itself"
            % (label, facts.unit_scale_factor, fbx_probe.DECLARES_METRES))

    roots = [n for n in facts.nodes if n.parent is None]
    if len(roots) != 1:
        out.append(
            "%s: %d root nodes %s, expected exactly one - a rig is one tree, and "
            "a detached chunk would measure as if it were parented"
            % (label, len(roots), [n.name for n in roots[:6]]))

    out.extend(_scale_and_ceiling(facts, label, ceiling_m))

    lo, hi = fbx_probe.world_vertex_bounds(facts)
    measured = hi[1] - lo[1]
    if abs(measured - height_m) > height_tol:
        out.append(
            "%s: composed height measures %.5f m, expected %.5f m - out by a "
            "factor of %.5g" % (label, measured, height_m, measured / height_m))

    return out


def check_poses(path, poses, height_tol=1e-3):
    """Assert every pose in `poses` reproduces the height it declares.

    A pose is per-chunk rotations and nothing else, so it can be applied to the
    delivered bytes and measured there - which is the only check that covers
    both files at once. It catches a pose naming a chunk the FBX does not have,
    a pose that quietly carries a translation, and a poses file left behind by
    a re-export.
    """
    facts = fbx_probe.read_fbx(path)
    known = {n.name for n in facts.nodes}
    label = getattr(path, "name", str(path))
    out = []

    for name in sorted(poses):
        pose = poses[name]
        rotations = pose["rotations_deg"]
        missing = sorted(set(rotations) - known)
        if missing:
            out.append("%s: pose %r names %d chunks the file does not have: %s"
                       % (label, name, len(missing), missing[:4]))
            continue
        absent = sorted(known - set(rotations))
        if absent:
            out.append("%s: pose %r leaves %d chunks unstated: %s - a pose must "
                       "be complete, or a consumer inherits whatever was there"
                       % (label, name, len(absent), absent[:4]))
        lo, hi = fbx_probe.world_vertex_bounds(facts, rotations)
        measured = hi[1] - lo[1]
        if abs(measured - pose["bbox_height_m"]) > height_tol:
            out.append("%s: pose %r composes to %.5f m, but declares %.5f m"
                       % (label, name, measured, pose["bbox_height_m"]))

    return out
