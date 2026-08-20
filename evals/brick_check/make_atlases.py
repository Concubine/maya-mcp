"""Variant albedo/normal atlases at three brick pitches, for the #652 look-check.

Reuses demigol_kit.build_atlas_maps verbatim by rebinding COURSES_PER_PATCH, so
the ONLY thing that differs between the three sets is the brick course pitch.
Everything else - grain seed, blur, colour, every other patch - is identical.
"""
import os, sys, shutil
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, os.path.dirname(_HERE) + "/evals")
import importlib.util
spec = importlib.util.spec_from_file_location(
    "dk", os.path.join(os.path.dirname(_HERE), "evals", "demigol_kit.py"))

# import WITHOUT running main(): the module only calls main() under __main__
dk = importlib.util.module_from_spec(spec)
sys.modules["dk"] = dk
spec.loader.exec_module(dk)

OUT = os.path.join(_HERE)
for cpm in (6.0, 9.0, 13.0):
    d = os.path.join(OUT, "atlas_%02d" % int(cpm))
    os.makedirs(d, exist_ok=True)
    dk.COURSES_PER_METRE = cpm
    dk.COURSES_PER_PATCH = cpm * dk.WORLD_SCALE
    paths = dk.build_atlas_maps(d)
    print(cpm, "courses/m ->", d,
          " course px = %.1f" % (dk.PATCH_PX / dk.COURSES_PER_PATCH),
          " bed px = %.1f" % (dk.PATCH_PX / dk.COURSES_PER_PATCH * 0.16),
          " course mm = %.0f" % (1000.0 / cpm))
