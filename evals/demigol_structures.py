"""Four Demigol structures, built to the STRUCTURE MODEL CONTRACT.

These are not sculptures that get cut up later. The game destroys buildings cell
by cell, flood-fills what is still connected and drops the rest as rigid bodies,
so a welded building mesh is indestructible scenery - the one thing the game must
not contain. Every building here is therefore authored AS a set of chunk meshes
on a 3 m lattice from the first line.

Contract conformance, point by point:

  units      metres, Y-up. The scene is switched to linear='m' before anything
             is created, so 1 unit IS 1 metre and the FBX carries it.
  lattice    cell = 3 m. Every chunk is an axis-aligned box whose bounds land on
             cell boundaries by construction - sizes are whole cell counts and
             positions are computed from cell indices, so straddling is not
             expressible rather than merely avoided.
  footprint  every horizontal axis is (bays * 3 + 1) cells.
  chunks     every chunk is a polyCube: closed, watertight, 12 triangles, well
             under the 200-triangle budget for a 1-cell chunk.
  pivots     polyCube builds centred on the origin and is then MOVED, never
             scaled, so each transform's pivot is already the chunk's own centre
             and scale is left at (1,1,1). Nothing needs freezing because
             nothing is ever non-uniformly scaled.
  history    created with ch=False; no construction history exists to delete.
  limits     max 48 cells, max 6 cells span, max 4 storeys - asserted per chunk
             at emit time, so a violating design fails here rather than in a
             build.
  names      <role>_x##_y##_z##, generated from the same cell indices that place
             the geometry, so a name cannot disagree with its position.
  materials  one flat colour per role, procedural, no textures, no authored
             material assets.

Run:  set MAYA_MCP_PORT=9878 && .venv/Scripts/python.exe evals/demigol_structures.py
Package: evals/demigol_structures/  (4 fbx + manifest.json + README.md + pngs)
"""

from __future__ import annotations

import ast
import base64
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from live_call import call  # noqa: E402
from maya_mcp import images  # noqa: E402

OUT_DIR = os.path.join(_HERE, "demigol_structures")

CELL = 3.0
BAY = 3               # cells between structural column lines (9 m)
MAX_CELLS = 48
MAX_SPAN = 6
MAX_STOREYS = 4

ROLES = ("steel", "concrete", "brick", "infill", "glass")

# A colour per role and nothing else - the contract asks for procedural colour,
# so these are values for the game's own shader to consume, not a look.
ROLE_COLOUR = {
    "steel":    [0.34, 0.37, 0.42],
    "concrete": [0.62, 0.61, 0.58],
    "brick":    [0.45, 0.24, 0.18],
    "infill":   [0.74, 0.72, 0.66],
    "glass":    [0.36, 0.55, 0.62],
}


class Chunk:
    """One breakable box, addressed in CELLS and only ever in cells.

    Metres are derived at the end. Nothing in a building definition is allowed
    to speak in metres, which is what makes straddling a cell boundary
    impossible to express rather than merely discouraged.
    """

    __slots__ = ("role", "x", "y", "z", "sx", "sy", "sz")

    def __init__(self, role, x, y, z, sx=1, sy=1, sz=1):
        if role not in ROLES:
            raise ValueError("unknown role %r (valid: %s)" % (role, ", ".join(ROLES)))
        cells = sx * sy * sz
        if cells > MAX_CELLS:
            raise ValueError("chunk %s at %d,%d,%d is %d cells (max %d)"
                             % (role, x, y, z, cells, MAX_CELLS))
        if max(sx, sz) > MAX_SPAN:
            raise ValueError("chunk %s at %d,%d,%d spans %dx%d cells (max %d)"
                             % (role, x, y, z, sx, sz, MAX_SPAN))
        if sy > MAX_STOREYS:
            raise ValueError("chunk %s at %d,%d,%d is %d storeys (max %d)"
                             % (role, x, y, z, sy, MAX_STOREYS))
        self.role, self.x, self.y, self.z = role, x, y, z
        self.sx, self.sy, self.sz = sx, sy, sz

    @property
    def name(self):
        # Multi-cell chunks are named for their MIN-CORNER cell. See the
        # deviations note in the manifest - the contract defines x/z as "cell
        # coords from the min corner" for a chunk, and min-corner is the only
        # reading that stays well defined once a chunk spans cells.
        return "%s_x%02d_y%02d_z%02d" % (self.role, self.x, self.y, self.z)

    def as_dict(self):
        # Cell i's centre sits at i*CELL, so a run of n cells starting at i is
        # centred half a cell past its midpoint. Bounds then land exactly on
        # cell boundaries (i*CELL - CELL/2) for every chunk, at every size.
        return dict(
            name=self.name, role=self.role,
            cell=[self.x, self.y, self.z], size_cells=[self.sx, self.sy, self.sz],
            pos=[CELL * self.x + CELL * (self.sx - 1) / 2.0,
                 CELL * self.y + CELL * (self.sy - 1) / 2.0,
                 CELL * self.z + CELL * (self.sz - 1) / 2.0],
            dim=[CELL * self.sx, CELL * self.sy, CELL * self.sz],
        )


def check_footprint(nx, nz, label):
    for axis, n in (("x", nx), ("z", nz)):
        if n < 4 or (n - 1) % BAY != 0:
            raise ValueError("%s: %s footprint of %d cells is not (bays*3+1)"
                             % (label, axis, n))


def perimeter_runs(nx, nz, span):
    """Wall panel runs around a footprint, as (x, z, sx, sz) in cells.

    Corners are emitted once, as part of the runs along x, so no cell is
    covered twice - a doubled chunk is two rigid bodies in one place, which
    reads as a flicker rather than as a wall.
    """
    runs = []
    for z in (0, nz - 1):
        x = 0
        while x < nx:
            w = min(span, nx - x)
            runs.append((x, z, w, 1))
            x += w
    for x in (0, nx - 1):
        z = 1
        while z < nz - 1:
            d = min(span, nz - 1 - z)
            runs.append((x, z, 1, d))
            z += d
    return runs


def floor_slabs(nx, nz, y, role="concrete", span=5):
    """Tile a storey's floor with slabs no wider than `span` cells."""
    out, x = [], 0
    while x < nx:
        w = min(span, nx - x)
        z = 0
        while z < nz:
            d = min(span, nz - z)
            out.append(Chunk(role, x, y, z, w, 1, d))
            z += d
        x += w
    return out


# ================================================================== buildings
# Character comes from MASSING and role distribution, because it has to: a
# tapered or curved chunk cannot have bounds on cell boundaries, so the
# vocabulary here is deliberately boxes, arranged.

def campanile():
    """4x4 cells, 14 storeys - 12 x 12 x 42 m. Slender; topples as one piece.

    One bay square. The character is the belfry: the top two storeys swap brick
    for steel and open up to glass, so the silhouette has a lantern on it and
    the shear line is somewhere a player can read.
    """
    nx = nz = 4
    storeys = 14
    check_footprint(nx, nz, "campanile")
    chunks = []
    for y in range(storeys):
        belfry = y >= storeys - 2
        corner_role = "steel" if belfry else "brick"
        wall_role = "glass" if belfry else "brick"
        for x, z in ((0, 0), (nx - 1, 0), (0, nz - 1), (nx - 1, nz - 1)):
            chunks.append(Chunk(corner_role, x, y, z))
        for x, z, sx, sz in perimeter_runs(nx, nz, span=2):
            if (x, z) in ((0, 0), (nx - 1, 0), (0, nz - 1), (nx - 1, nz - 1)) and sx == 1 and sz == 1:
                continue
            # Trim runs that would re-cover a corner already placed above.
            if sz == 1 and sx > 1:
                if x == 0:
                    x, sx = x + 1, sx - 1
                if x + sx == nx:
                    sx -= 1
            if sx <= 0 or sz <= 0:
                continue
            chunks.append(Chunk(wall_role, x, y, z, sx, 1, sz))
        chunks.extend(floor_slabs(nx, nz, y, "concrete", span=4))
    return dict(nx=nx, nz=nz, storeys=storeys, chunks=chunks,
                note="Belfry: top two storeys are steel corners with glass infill.")


def framed_tower():
    """10x10 cells, 12 storeys - 30 x 30 x 36 m. The canonical framed block.

    Steel columns on the 9 m bay lines, concrete floors, curtain infill hung
    between - so cutting a column line drops everything the frame was carrying,
    which is the whole point of the archetype.
    """
    nx = nz = 10
    storeys = 12
    check_footprint(nx, nz, "framed_tower")
    bay_lines = list(range(0, nx, BAY)) + [nx - 1]
    bay_lines = sorted(set(bay_lines))
    chunks = []
    for y in range(storeys):
        for x in bay_lines:
            for z in bay_lines:
                chunks.append(Chunk("steel", x, y, z))
        for x, z, sx, sz in perimeter_runs(nx, nz, span=BAY):
            if sx == 1 and sz == 1 and x in bay_lines and z in bay_lines:
                continue
            # Every third storey is a glazed band: it reads as a floor line
            # from outside and it is the weakest ring in the elevation.
            role = "glass" if y % 3 == 2 else "infill"
            chunks.append(Chunk(role, x, y, z, sx, 1, sz))
        chunks.extend(floor_slabs(nx, nz, y, "concrete", span=5))
    return dict(nx=nx, nz=nz, storeys=storeys, chunks=chunks,
                note="Glazed band every third storey; steel on 9 m bay lines.")


def warehouse():
    """19x10 cells, 4 storeys - 57 x 30 x 12 m. Long, low, brick, industrial.

    A sawtooth roof on the top storey gives it a profile that is not a box, and
    gives the game a row of light chunks that come off first.
    """
    nx, nz = 19, 10
    storeys = 4
    check_footprint(nx, nz, "warehouse")
    bay_x = sorted(set(list(range(0, nx, BAY)) + [nx - 1]))
    bay_z = sorted(set(list(range(0, nz, BAY)) + [nz - 1]))
    chunks = []
    for y in range(storeys):
        for x in bay_x:
            for z in bay_z:
                chunks.append(Chunk("steel", x, y, z))
        for x, z, sx, sz in perimeter_runs(nx, nz, span=BAY):
            if sx == 1 and sz == 1 and x in bay_x and z in bay_z:
                continue
            role = "glass" if (y == storeys - 2 and sx > 1) else "brick"
            chunks.append(Chunk(role, x, y, z, sx, 1, sz))
        chunks.extend(floor_slabs(nx, nz, y, "concrete", span=5))
    # Sawtooth: alternating ridges along the long axis, one storey above the
    # roof slab. Each is a single cell, so they shed individually.
    for x in range(0, nx, 2):
        for z in range(0, nz, 3):
            chunks.append(Chunk("steel", x, storeys, z))
            if z + 1 < nz:
                chunks.append(Chunk("glass", x, storeys, z + 1))
    return dict(nx=nx, nz=nz, storeys=storeys + 1, chunks=chunks,
                note="Sawtooth roof ridges on the storey above the roof slab.")


def gatehouse():
    """19x7 cells, 5 storeys - 57 x 21 x 15 m. Wide, with a void driven through.

    The ground floor carries a 3-cell arch void on the centre bay, so the mass
    above it is supported at only two points. It is the only one of the four
    whose failure is not straight down: take a flanking pier and the span over
    the void comes with it.
    """
    nx, nz = 19, 7
    storeys = 5
    check_footprint(nx, nz, "gatehouse")
    bay_x = sorted(set(list(range(0, nx, BAY)) + [nx - 1]))
    bay_z = sorted(set(list(range(0, nz, BAY)) + [nz - 1]))
    void_x = range(8, 11)          # the opening, centre bay of the long axis
    chunks = []
    for y in range(storeys):
        for x in bay_x:
            for z in bay_z:
                if y == 0 and x in void_x:
                    continue
                chunks.append(Chunk("steel", x, y, z))
        for x, z, sx, sz in perimeter_runs(nx, nz, span=BAY):
            if sx == 1 and sz == 1 and x in bay_x and z in bay_z:
                continue
            if y == 0 and any(cx in void_x for cx in range(x, x + sx)):
                continue
            role = "glass" if y == storeys - 1 else "brick"
            chunks.append(Chunk(role, x, y, z, sx, 1, sz))
        if y == 0:
            # Floor at ground level exists only outside the opening.
            for slab in floor_slabs(nx, nz, y, "concrete", span=5):
                if any(cx in void_x for cx in range(slab.x, slab.x + slab.sx)):
                    continue
                chunks.append(slab)
        else:
            chunks.extend(floor_slabs(nx, nz, y, "concrete", span=5))
    # The lintel over the void. Authored first as a single 3x7 beam, which the
    # Chunk guard rejected at emit time: 7 cells is over the 6-cell span limit.
    # Split along the short axis into two beams that each fall as their own
    # body - which is also better destruction than one 21-cell slab would be.
    z = 0
    while z < nz:
        depth = min(MAX_SPAN - 2, nz - z)
        chunks.append(Chunk("concrete", 8, 1, z, 3, 1, depth))
        z += depth
    return dict(nx=nx, nz=nz, storeys=storeys, chunks=chunks,
                note="3-cell ground-floor void on the centre bay, spanned by a "
                     "concrete lintel at storey 1.")


BUILDINGS = [
    ("campanile", campanile, 1.35),
    ("framed_tower", framed_tower, 1.35),
    ("warehouse", warehouse, 1.3),
    ("gatehouse", gatehouse, 1.3),
]


# =============================================================== Maya bridge

def ok(resp, what):
    if resp.get("status") != "ok":
        print("FAILED %s: %s" % (what, json.dumps(resp.get("error", resp))[:500]))
        sys.exit(1)
    return resp["result"]


def run(code, what, timeout=900.0):
    out = ok(call("execute_python", {"code": code}, timeout), what)
    if out.get("traceback"):
        print("PYTHON FAILED (%s):\n%s" % (what, out["traceback"][:1500]))
        sys.exit(1)
    return out


# Built inside Maya: one pass creates every chunk, one pass verifies the
# contract against the geometry that actually exists rather than against the
# intent that produced it.
BUILD_CODE = r'''
import json, maya.cmds as cmds
spec = json.loads(SPEC)
label = spec["label"]
cmds.currentUnit(linear="m")

by_role = {}
for c in spec["chunks"]:
    node = cmds.polyCube(w=c["dim"][0], h=c["dim"][1], d=c["dim"][2],
                         name=c["name"], ch=False)[0]
    cmds.move(c["pos"][0], c["pos"][1], c["pos"][2], node, absolute=True)
    by_role.setdefault(c["role"], []).append(node)

for role, colour in spec["colours"].items():
    if role not in by_role:
        continue
    shader = cmds.shadingNode("lambert", asShader=True, name=role)
    cmds.setAttr(shader + ".color", colour[0], colour[1], colour[2], type="double3")
    sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name=role + "SG")
    cmds.connectAttr(shader + ".outColor", sg + ".surfaceShader", force=True)
    cmds.sets(by_role[role], edit=True, forceElement=sg)

grp = cmds.group([n for nodes in by_role.values() for n in nodes], name=label)
cmds.xform(grp, worldSpace=True, pivots=(0, 0, 0))
result = {"group": grp, "chunks": sum(len(v) for v in by_role.values())}
result
'''

CHECK_CODE = r'''
import maya.cmds as cmds
CELL, EPS = 3.0, 1e-4
label = LABEL
kids = cmds.listRelatives("|" + label, children=True, fullPath=True) or []
fails, tris = [], 0

def on_lattice(v):
    # Cell boundaries sit at i*CELL - CELL/2, so a bound is legal exactly when
    # (v + CELL/2) is a whole number of cells.
    return abs(((v + CELL / 2.0) / CELL) - round((v + CELL / 2.0) / CELL)) < EPS

for node in kids:
    short = node.split("|")[-1]
    shapes = cmds.listRelatives(node, shapes=True, fullPath=True) or []
    if not shapes:
        fails.append((short, "no shape")); continue
    tris += cmds.polyEvaluate(shapes[0], triangle=True)

    # closed: a watertight box has no boundary edges
    edges = cmds.polyEvaluate(shapes[0], edge=True)
    faces = cmds.polyEvaluate(shapes[0], face=True)
    verts = cmds.polyEvaluate(shapes[0], vertex=True)
    if verts - edges + faces != 2:
        fails.append((short, "not closed (V-E+F=%d)" % (verts - edges + faces)))

    if [round(s, 6) for s in cmds.getAttr(node + ".scale")[0]] != [1.0, 1.0, 1.0]:
        fails.append((short, "non-uniform/left-over scale"))
    if [round(r, 6) for r in cmds.getAttr(node + ".rotate")[0]] != [0.0, 0.0, 0.0]:
        fails.append((short, "unfrozen rotation"))

    bb = cmds.exactWorldBoundingBox(node)
    if not all(on_lattice(v) for v in bb):
        fails.append((short, "bounds off the 3 m lattice: %s"
                      % [round(v, 4) for v in bb]))

    centre = [(bb[i] + bb[i + 3]) / 2.0 for i in range(3)]
    pivot = cmds.xform(node, query=True, worldSpace=True, rotatePivot=True)
    if any(abs(pivot[i] - centre[i]) > 1e-3 for i in range(3)):
        fails.append((short, "pivot not at chunk centre"))

    # name must parse AND agree with where the chunk actually is
    try:
        role, sx, sy, sz = short.split("_")[0], *[int(p[1:]) for p in short.split("_")[1:4]]
    except Exception:
        fails.append((short, "name does not parse")); continue
    want = [sx * CELL - CELL / 2.0, sy * CELL - CELL / 2.0, sz * CELL - CELL / 2.0]
    if any(abs(bb[i] - want[i]) > 1e-3 for i in range(3)):
        fails.append((short, "name disagrees with position: min corner %s vs %s"
                      % ([round(bb[i], 3) for i in range(3)],
                         [round(w, 3) for w in want])))

    cells = [int(round((bb[i + 3] - bb[i]) / CELL)) for i in range(3)]
    if cells[0] * cells[1] * cells[2] > 48 or max(cells[0], cells[2]) > 6 or cells[1] > 4:
        fails.append((short, "over chunk limits: %s cells" % cells))

bb = cmds.exactWorldBoundingBox("|" + label)
result = {"chunks": len(kids), "tris": tris, "fails": fails[:25],
          "fail_count": len(fails),
          "bbox_min": [round(v, 3) for v in bb[:3]],
          "bbox_max": [round(v, 3) for v in bb[3:]]}
result
'''

EXPORT_CODE = r'''
import maya.cmds as cmds
cmds.loadPlugin("fbxmaya", quiet=True)
try:
    import maya.mel as mel
    mel.eval('FBXExportFileVersion -v FBX202000')
    mel.eval('FBXExportUpAxis y')
    mel.eval('FBXExportConvertUnitString m')
    mel.eval('FBXExportSmoothingGroups -v true')
    mel.eval('FBXExportInputConnections -v false')
except Exception:
    pass
cmds.select("|" + LABEL, replace=True, hierarchy=True)
cmds.file(FBX, force=True, type="FBX export", pr=True, es=True)
result = FBX
result
'''


def build_one(label, builder, zoom):
    spec = builder()
    chunks = spec["chunks"]
    payload = json.dumps({
        "label": label,
        "colours": ROLE_COLOUR,
        "chunks": [c.as_dict() for c in chunks],
    })

    ok(call("new_scene", {"confirm": True}, 240.0), "new_scene")
    run("SPEC = %r\n%s" % (payload, BUILD_CODE), "build %s" % label)
    check = ast.literal_eval(
        run("LABEL = %r\n%s" % (label, CHECK_CODE), "check %s" % label)["result_repr"])

    fbx = os.path.join(OUT_DIR, "%s.fbx" % label).replace("\\", "/")
    run("LABEL = %r\nFBX = %r\n%s" % (label, fbx, EXPORT_CODE), "export %s" % label)

    # A render, so a human can see what the numbers describe. Lighting is added
    # after the check so it can never be mistaken for part of the asset.
    # Flat lambert role colours are much brighter than the shaded stone these
    # rigs were tuned against - the first run measured clipped_fraction 0.10-0.14
    # where anything over ~0.15 has lost its detail outright.
    ok(call("setup_lighting", {"preset": "three_point", "intensity": 1.5,
                               "replace_existing": True}, 180.0), "lighting")
    shot = ok(call("render_scene", {
        "angles": ["three_quarter"], "renderer": "arnold", "resolution": 768,
        "samples": 3, "zoom": zoom, "target": ["|" + label]}, 900.0),
        "render %s" % label)["images"][0]
    png = base64.b64decode(shot["png_b64"])
    with open(os.path.join(OUT_DIR, "%s.png" % label), "wb") as fh:
        fh.write(png)

    size = [round(check["bbox_max"][i] - check["bbox_min"][i], 2) for i in range(3)]
    roles = {}
    for c in chunks:
        roles[c.role] = roles.get(c.role, 0) + 1
    return dict(
        name=label, footprint_cells=[spec["nx"], spec["nz"]],
        storeys=spec["storeys"], size_m=size,
        bbox_min=check["bbox_min"], bbox_max=check["bbox_max"],
        chunks=check["chunks"], triangles=check["tris"],
        tris_per_chunk=round(check["tris"] / max(1, check["chunks"]), 1),
        roles=roles, note=spec["note"],
        files=["%s.fbx" % label, "%s.png" % label],
        chunk_list=[c.as_dict() for c in chunks],
    ), check, images.pixel_stats(png)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    entries, all_ok = [], True
    for label, builder, zoom in BUILDINGS:
        entry, check, stats = build_one(label, builder, zoom)
        status = "OK" if check["fail_count"] == 0 else "FAIL"
        print("%-14s %-4s %4d chunks  %6d tris (%.1f/chunk)  %s m  render %s"
              % (label, status, entry["chunks"], entry["triangles"],
                 entry["tris_per_chunk"], entry["size_m"],
                 json.dumps({k: stats[k] for k in ("opaque_px", "clipped_fraction")})))
        if check["fail_count"]:
            all_ok = False
            for short, why in check["fails"]:
                print("    %-28s %s" % (short, why))
        entries.append(entry)

    manifest = {
        "contract": "Demigol STRUCTURE MODEL CONTRACT",
        "units": "metres, Y-up, 1 unit = 1 m, cell = 3 m",
        "origin": "min-corner cell CENTRE at local (0,0,0); the floor plane is "
                  "therefore at y = -1.5",
        "naming": "<role>_x##_y##_z##; x/z are cell indices from the min corner, "
                  "y is the storey (0 = ground)",
        "roles": list(ROLES),
        "role_colours": ROLE_COLOUR,
        "self_check": "every chunk verified in-scene after build: closed "
                      "(V-E+F=2), bounds on 3 m boundaries, pivot at chunk "
                      "centre, scale (1,1,1) and rotation zero, name parses and "
                      "agrees with measured position, within 48 cells / 6 span / "
                      "4 storeys",
        "deviations": [
            {"item": "multi-cell chunk naming",
             "what": "A chunk spanning several cells is named for its MIN-CORNER "
                     "cell, not its centre.",
             "why": "The contract defines x/z as 'cell coords from the min "
                    "corner', which is unambiguous for a 1-cell chunk and needs "
                    "a choice once a chunk spans cells. Min-corner is the only "
                    "reading consistent with that wording, and the self-check "
                    "asserts each name against the chunk's measured min corner, "
                    "so if you want centre-naming instead it is a one-line "
                    "change and the check will enforce it."},
            {"item": "vertical sense of the origin",
             "what": "The min-corner cell CENTRE is at local y = 0, so the floor "
                     "plane sits at y = -1.5.",
             "why": "'Model origin = the MIN-CORNER CELL CENTRE, at y = 1.5 "
                    "(half a cell above the floor)' reads as the origin being "
                    "that cell centre, with the parenthetical saying where it "
                    "sits relative to the floor. The other reading puts the "
                    "floor at y = 0 and the origin 1.5 above it. If that is the "
                    "one you meant, every building needs a single +1.5 m Y "
                    "offset - no regeneration."},
            {"item": "flare / taper not used",
             "what": "None of the four uses the taper deformer, though the "
                     "toolset has it.",
             "why": "A tapered or curved chunk cannot have bounds that land on "
                    "cell boundaries. Lattice conformance outranks ornament, so "
                    "the vocabulary here is boxes, arranged - character comes "
                    "from massing and role distribution instead."},
            {"item": "materials",
             "what": "Five flat lambert colours named exactly for the roles. No "
                     "authored materials, no textures, nothing to flag.",
             "why": "Contract point 8 - procedural colour per role."},
        ],
        "structures": entries,
    }
    with open(os.path.join(OUT_DIR, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2)
    print("\nwrote manifest.json  (self-check: %s)"
          % ("all four clean" if all_ok else "FAILURES ABOVE"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
