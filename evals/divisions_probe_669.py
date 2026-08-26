"""#669 measurement probe: what `divisions` actually buys, per kind, per axis.

The ticket says a cylinder cannot buy rows ALONG its length without paying for
an absurd circumference, and proposes two fixes from theory. Before choosing
one, measure the thing itself in a real Maya:

1. Is `modeling.projected_faces` exact for every kind, at several divisions?
   The whole face BUDGET rests on it, and it is arithmetic written from
   measurements taken once - if it has drifted, the ceiling is a guess.
2. What does an INDEPENDENT pair of subdivision counts cost, versus the
   coupled multiplier, for the same number of rows along the axis? That is the
   size of the defect, in faces.
3. What are the real MINIMUMS? Maya may clamp a subdivision flag below some
   value rather than refuse it, and a validator that permits what Maya then
   silently changes is a validator that lies. Measured per flag, per kind.
4. Does `polyCube` really spend its three flags independently, and do
   prism/pyramid ignore everything but height?

Nothing here asserts a fix. It prints a table; the numbers decide the shape.

Usage:

    set MAYA_MCP_PORT=9877
    python evals/divisions_probe_669.py

MUTATES THE ANSWERING MAYA'S CURRENT SCENE (new_scene, then many throwaway
primitives). Point MAYA_MCP_PORT at a disposable Maya you launched yourself -
never the user's live modelling session.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from live_call import call, structured_result  # noqa: E402
from maya_plugin.handlers import modeling  # noqa: E402


def python(code: str, what: str, timeout_s: float = 120.0):
    frame = call("execute_python", {"code": code, "timeout_s": timeout_s},
                 timeout_s=timeout_s + 30)
    if frame.get("status") != "ok":
        raise SystemExit("execute_python(%s) failed: %r"
                         % (what, frame.get("error")))
    return structured_result(frame.get("result") or {}, what)


def new_scene() -> None:
    frame = call("new_scene", {"confirm": True})
    if frame.get("status") != "ok":
        raise SystemExit("new_scene failed: %r" % (frame.get("error"),))


# ---------------------------------------------------------------- claim 1
def projected_faces_is_exact() -> None:
    """Build every kind at several divisions; compare to the pure function."""
    print("\n=== 1. projected_faces vs a real Maya ===")
    cases = []
    for kind in modeling.PRIMITIVE_KINDS:
        for d in (1, 2, 4):
            cases.append((kind, d))
    code = [
        "import maya.cmds as cmds",
        "from maya_plugin.handlers import modeling",
        "out = []",
        "for kind, d in %r:" % (cases,),
        "    cmds.file(new=True, force=True)",
        "    name = modeling.build_unit_primitive(cmds, kind, 'probe', d)",
        "    out.append((kind, d, cmds.polyEvaluate(name, face=True)))",
        "out",
    ]
    measured = python("\n".join(code), "projected_faces sweep")
    bad = 0
    for kind, d, faces in measured:
        predicted = modeling.projected_faces(kind, d)
        flag = "" if predicted == faces else "   <-- MISMATCH"
        if predicted != faces:
            bad += 1
        print("  %-12s d=%-3d maya=%-8d projected=%-8d%s"
              % (kind, d, faces, predicted, flag))
    print("  mismatches: %d" % bad)


# ---------------------------------------------------------------- claim 2
def the_coupling_costs() -> None:
    """The serpent case: rows along the axis, and what they cost either way."""
    print("\n=== 2. what a row along the axis costs ===")
    wanted_rows = (8, 16, 24)
    code = [
        "import maya.cmds as cmds",
        "out = []",
        "for rows in %r:" % (wanted_rows,),
        "    cmds.file(new=True, force=True)",
        # coupled: what create_primitive builds today for `divisions=rows`
        "    a = cmds.polyCylinder(name='coupled', constructionHistory=False,",
        "                          radius=0.5, height=1.0,",
        "                          subdivisionsAxis=20 * rows,",
        "                          subdivisionsHeight=rows)[0]",
        # independent: the same rows, a circumference a limb actually needs
        "    b = cmds.polyCylinder(name='free', constructionHistory=False,",
        "                          radius=0.5, height=1.0,",
        "                          subdivisionsAxis=12,",
        "                          subdivisionsHeight=rows)[0]",
        "    out.append((rows, cmds.polyEvaluate(a, face=True),",
        "                cmds.polyEvaluate(a, vertex=True),",
        "                cmds.polyEvaluate(b, face=True),",
        "                cmds.polyEvaluate(b, vertex=True)))",
        "out",
    ]
    for rows, cf, cv, ff, fv in python("\n".join(code), "coupling cost"):
        print("  %2d rows along: coupled(20x%d around) %6d faces / %6d verts"
              "   |   free(12 around) %4d faces / %4d verts   ratio %.1fx"
              % (rows, rows, cf, cv, ff, fv, float(cf) / float(ff)))


# ---------------------------------------------------------------- claim 3
def the_real_minimums() -> None:
    """Ask for 0, 1, 2, 3 on each flag and read back what Maya actually built.

    A flag Maya silently clamps is a flag whose validator must refuse the
    value, not pass it on - otherwise the caller's number and the mesh's
    number differ with nothing said.
    """
    print("\n=== 3. what Maya does with a too-small subdivision count ===")
    probes = [
        ("polyCylinder axis", "cmds.polyCylinder(name='p', "
         "constructionHistory=False, radius=0.5, height=1.0, "
         "subdivisionsAxis=v, subdivisionsHeight=1)"),
        ("polyCylinder height", "cmds.polyCylinder(name='p', "
         "constructionHistory=False, radius=0.5, height=1.0, "
         "subdivisionsAxis=12, subdivisionsHeight=v)"),
        ("polySphere axis", "cmds.polySphere(name='p', "
         "constructionHistory=False, radius=0.5, subdivisionsAxis=v, "
         "subdivisionsHeight=8)"),
        ("polySphere height", "cmds.polySphere(name='p', "
         "constructionHistory=False, radius=0.5, subdivisionsAxis=12, "
         "subdivisionsHeight=v)"),
        ("polyCube width", "cmds.polyCube(name='p', "
         "constructionHistory=False, width=1.0, height=1.0, depth=1.0, "
         "subdivisionsWidth=v, subdivisionsHeight=1, subdivisionsDepth=1)"),
        ("polyPlane width", "cmds.polyPlane(name='p', "
         "constructionHistory=False, width=1.0, height=1.0, "
         "subdivisionsWidth=v, subdivisionsHeight=1)"),
        ("polyPrism height", "cmds.polyPrism(name='p', "
         "constructionHistory=False, sideLength=1.0, length=1.0, "
         "numberOfSides=3, subdivisionsHeight=v, subdivisionsCaps=0)"),
    ]
    code = [
        "import maya.cmds as cmds",
        "out = []",
        "for label, expr in %r:" % (probes,),
        "    for v in (0, 1, 2, 3):",
        "        cmds.file(new=True, force=True)",
        "        try:",
        "            n = eval(expr)[0]",
        "            out.append((label, v, cmds.polyEvaluate(n, face=True),",
        "                        cmds.polyEvaluate(n, edge=True), ''))",
        "        except Exception as exc:",
        "            out.append((label, v, None, None, str(exc)[:60]))",
        "out",
    ]
    for label, v, faces, edges, err in python("\n".join(code), "minimums"):
        print("  %-22s asked %d -> %s"
              % (label, v, err or "%d faces, %d edges" % (faces, edges)))


# ---------------------------------------------------------------- claim 4
def per_axis_independence() -> None:
    """Do the multi-flag kinds really spend each flag on its own axis?"""
    print("\n=== 4. per-axis independence ===")
    probes = [
        ("cube 4x1x1", "cmds.polyCube(name='p', constructionHistory=False, "
         "width=1.0, height=1.0, depth=1.0, subdivisionsWidth=4, "
         "subdivisionsHeight=1, subdivisionsDepth=1)"),
        ("cube 1x4x1", "cmds.polyCube(name='p', constructionHistory=False, "
         "width=1.0, height=1.0, depth=1.0, subdivisionsWidth=1, "
         "subdivisionsHeight=4, subdivisionsDepth=1)"),
        ("plane 8x2", "cmds.polyPlane(name='p', constructionHistory=False, "
         "width=1.0, height=1.0, subdivisionsWidth=8, subdivisionsHeight=2)"),
        ("cone 12 around x 6", "cmds.polyCone(name='p', "
         "constructionHistory=False, radius=0.5, height=1.0, "
         "subdivisionsAxis=12, subdivisionsHeight=6)"),
        ("torus 12 x 6", "cmds.polyTorus(name='p', "
         "constructionHistory=False, radius=0.3333, sectionRadius=0.1667, "
         "subdivisionsAxis=12, subdivisionsHeight=6)"),
        ("prism h=6", "cmds.polyPrism(name='p', constructionHistory=False, "
         "sideLength=1.0, length=1.0, numberOfSides=3, "
         "subdivisionsHeight=6, subdivisionsCaps=0)"),
        ("pyramid h=6", "cmds.polyPyramid(name='p', "
         "constructionHistory=False, sideLength=0.7071, numberOfSides=4, "
         "subdivisionsHeight=6, subdivisionsCaps=0)"),
    ]
    code = [
        "import maya.cmds as cmds",
        "out = []",
        "for label, expr in %r:" % (probes,),
        "    cmds.file(new=True, force=True)",
        "    n = eval(expr)[0]",
        "    out.append((label, cmds.polyEvaluate(n, face=True),",
        "                cmds.polyEvaluate(n, vertex=True)))",
        "out",
    ]
    for label, faces, verts in python("\n".join(code), "independence"):
        print("  %-22s %5d faces, %5d verts" % (label, faces, verts))


# ---------------------------------------------------------------- claim 5
def radial_minimums_everywhere() -> None:
    """Claim 3 measured cylinder and sphere. Do cone and torus agree?

    Claim 3's finding is the one that decides a validator: below 3, Maya does
    not clamp and does not raise - it silently substitutes its own default of
    20. A caller asking for 2 sides gets 20. Before refusing `< 3` on every
    radial kind, measure that every radial kind behaves that way.
    """
    print("\n=== 5. the radial minimum, on every radial kind ===")
    probes = [
        ("cone around", "cmds.polyCone(name='p', constructionHistory=False, "
         "radius=0.5, height=1.0, subdivisionsAxis=v, subdivisionsHeight=2)"),
        ("cone along", "cmds.polyCone(name='p', constructionHistory=False, "
         "radius=0.5, height=1.0, subdivisionsAxis=12, subdivisionsHeight=v)"),
        ("torus around", "cmds.polyTorus(name='p', constructionHistory=False, "
         "radius=0.3333, sectionRadius=0.1667, subdivisionsAxis=v, "
         "subdivisionsHeight=6)"),
        ("torus along", "cmds.polyTorus(name='p', constructionHistory=False, "
         "radius=0.3333, sectionRadius=0.1667, subdivisionsAxis=12, "
         "subdivisionsHeight=v)"),
    ]
    code = [
        "import maya.cmds as cmds",
        "out = []",
        "for label, expr in %r:" % (probes,),
        "    for v in (1, 2, 3, 4):",
        "        cmds.file(new=True, force=True)",
        "        try:",
        "            n = eval(expr)[0]",
        "            out.append((label, v, cmds.polyEvaluate(n, face=True), ''))",
        "        except Exception as exc:",
        "            out.append((label, v, None, str(exc)[:60]))",
        "out",
    ]
    for label, v, faces, err in python("\n".join(code), "radial minimums"):
        print("  %-14s asked %d -> %s" % (label, v, err or "%d faces" % faces))


def main() -> int:
    new_scene()
    projected_faces_is_exact()
    the_coupling_costs()
    the_real_minimums()
    per_axis_independence()
    radial_minimums_everywhere()
    print("\nprobe complete - the numbers above decide the fix, not the ticket.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
