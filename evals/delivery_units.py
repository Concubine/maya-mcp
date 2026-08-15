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
