"""Four whole destructible HERO buildings for Demigol.

The model IS the building, structurally as well as visually. Nothing is
generated underneath to hold the art up: the chunk manifest defines the
simulation grid, so a building that looks right but has no continuous path to
the ground collapses the moment the level loads.

That inverts the usual authoring order. Here the FRAME is designed first and
the cladding is hung on what is left, and the generator refuses to emit a
building that would not stand:

  * steel columns run continuously from storey 0 up, on the 9 m bay lattice
  * every storey ties its columns together with a concrete beam grid - a
    column touching no concrete at its own storey is a stilt and is reported
  * infill / brick / glass carry nothing and are placed only in cells the
    frame does not need
  * glass is emitted one cell at a time, so no glass span can ever exceed the
    2-cell limit that would leave the course above it unsupported

THE ONE-ACTION SELF-CHECK IS IMPLEMENTED, not asserted. After building, every
infill/brick/glass chunk is discarded and the remaining steel+concrete is
flood-filled from the ground through face-adjacency. Anything unreached is an
unsupported chunk and fails the build. This is the same question the game's
solver asks on load, asked here first.

Footprints match the four archetypes, so each is a drop-in replacement in the
generated district rather than something that has to be placed by hand:

  tower  13x13x14   block  19x19x6   slab  10x19x8   stump  10x10x4

Run:  set MAYA_MCP_PORT=9878 && .venv/Scripts/python.exe evals/demigol_structures.py
Package: evals/demigol_structures/
"""

from __future__ import annotations

import ast
import base64
import json
import os
import sys
from collections import deque

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from live_call import call  # noqa: E402
from maya_mcp import images  # noqa: E402

OUT_DIR = os.path.join(_HERE, "demigol_structures")

CELL = 3.0
BAY = 3                      # cells between column lines (9 m)
MAX_CELLS, MAX_SPAN, MAX_STOREYS = 48, 6, 4

STRUCTURAL = ("steel", "concrete")
CLADDING = ("brick", "infill", "glass")
ROLES = STRUCTURAL + CLADDING

ROLE_COLOUR = {
    "steel":    [0.34, 0.37, 0.42],
    "concrete": [0.62, 0.61, 0.58],
    "brick":    [0.45, 0.24, 0.18],
    "infill":   [0.74, 0.72, 0.66],
    "glass":    [0.36, 0.55, 0.62],
}

# Glass carries nothing, so a glass run wider than 2 cells leaves the course
# above it unsupported. Emitting glass one cell at a time makes that
# unreachable rather than merely checked.
MAX_RUN = {"steel": 4, "concrete": 4, "brick": 2, "infill": 2, "glass": 1}


def bay_lines(n):
    """Column lines for an n-cell axis: every 3rd cell, and the far edge."""
    return sorted(set(list(range(0, n, BAY)) + [n - 1]))


class Building:
    """A cell grid that becomes chunks, never the other way round.

    Cells are claimed one at a time and a second claim on the same cell is an
    error, so the manifest is an unambiguous statement of what each cell is
    made of - which is what the solver reads it as.
    """

    def __init__(self, label, nx, nz, storeys, note=""):
        for axis, n in (("x", nx), ("z", nz)):
            if n < 4 or (n - 1) % BAY != 0:
                raise ValueError("%s: %s axis of %d cells is not (bays*3+1)"
                                 % (label, axis, n))
        self.label, self.nx, self.nz, self.storeys = label, nx, nz, storeys
        self.note = note
        self.bx, self.bz = bay_lines(nx), bay_lines(nz)
        self.cells = {}                     # (x, y, z) -> role

    def put(self, role, x, y, z):
        if role not in ROLES:
            raise ValueError("unknown role %r" % role)
        key = (x, y, z)
        if key in self.cells:
            raise ValueError("%s: cell %s claimed twice (%s then %s)"
                             % (self.label, key, self.cells[key], role))
        self.cells[key] = role

    # ---------------------------------------------------------------- frame
    def frame(self, storeys=None, lobby_open=()):
        """Columns on every bay-line intersection, tied by a beam grid.

        The beam grid is the tie: at each storey, every cell with exactly one
        coordinate on a bay line becomes a concrete beam, so each column is
        face-adjacent to the grid that joins it to its neighbours.

        Corner columns are the exception and need care. A corner's only two
        face-adjacent cells are both on the perimeter ring, so if the ring
        between columns is cladding the corner touches nothing structural and
        is a stilt. One cell beside each corner is therefore a concrete
        spandrel rather than cladding.
        """
        storeys = self.storeys if storeys is None else storeys
        for y in range(storeys):
            for x in self.bx:
                for z in self.bz:
                    self.put("steel", x, y, z)
            for x in range(self.nx):
                for z in range(self.nz):
                    on_x, on_z = x in self.bx, z in self.bz
                    if on_x and on_z:
                        continue                      # column, already placed
                    if on_x != on_z and self._interior(x, z):
                        self.put("concrete", x, y, z)  # beam grid
            for x, z in self._corner_spandrels():
                self.put("concrete", x, y, z)

    def _interior(self, x, z):
        return 0 < x < self.nx - 1 and 0 < z < self.nz - 1

    def _corner_spandrels(self):
        return [(1, 0), (self.nx - 2, 0), (1, self.nz - 1), (self.nx - 2, self.nz - 1)]

    # -------------------------------------------------------------- cladding
    def clad(self, role_for, storeys=None, skip_storeys=()):
        """Hang cladding in every perimeter cell the frame did not take.

        `role_for(y)` picks the material per storey. Skipping a storey leaves
        an open colonnade - allowed explicitly, because the columns are still
        there; only the curtain is missing.
        """
        storeys = self.storeys if storeys is None else storeys
        for y in range(storeys):
            if y in skip_storeys:
                continue
            role = role_for(y)
            for x in range(self.nx):
                for z in range(self.nz):
                    if not (x in (0, self.nx - 1) or z in (0, self.nz - 1)):
                        continue
                    if (x, y, z) in self.cells:
                        continue
                    self.put(role, x, y, z)

    # ---------------------------------------------------------------- chunks
    def chunks(self):
        """Merge runs of like cells into chunks, then emit them.

        Columns merge VERTICALLY into segments of up to 4 storeys, which is
        both the contract's storey ceiling and the behaviour the roles imply -
        a steel frame should fall as large bent sections, not as a shower of
        1 m cubes. Everything else merges along X then Z within its own run
        limit.
        """
        remaining = dict(self.cells)
        out = []

        def take(x, y, z, role):
            if remaining.get((x, y, z)) == role:
                del remaining[(x, y, z)]
                return True
            return False

        for (x, y, z) in sorted(self.cells, key=lambda k: (k[1], k[0], k[2])):
            role = remaining.get((x, y, z))
            if role is None:
                continue
            del remaining[(x, y, z)]
            sx = sy = sz = 1
            if role == "steel":
                while sy < MAX_RUN[role] and take(x, y + sy, z, role):
                    sy += 1
            else:
                limit = MAX_RUN[role]
                while sx < limit and take(x + sx, y, z, role):
                    sx += 1
                if sx == 1:
                    while sz < limit and take(x, y, z + sz, role):
                        sz += 1
            out.append(Chunk(role, x, y, z, sx, sy, sz))
        return out


class Chunk:
    __slots__ = ("role", "x", "y", "z", "sx", "sy", "sz")

    def __init__(self, role, x, y, z, sx=1, sy=1, sz=1):
        cells = sx * sy * sz
        if cells > MAX_CELLS or max(sx, sz) > MAX_SPAN or sy > MAX_STOREYS:
            raise ValueError("chunk %s at %d,%d,%d is %dx%dx%d cells - over limits"
                             % (role, x, y, z, sx, sy, sz))
        self.role, self.x, self.y, self.z = role, x, y, z
        self.sx, self.sy, self.sz = sx, sy, sz

    @property
    def name(self):
        return "%s_x%02d_y%02d_z%02d" % (self.role, self.x, self.y, self.z)

    def cells_occupied(self):
        for i in range(self.sx):
            for j in range(self.sy):
                for k in range(self.sz):
                    yield (self.x + i, self.y + j, self.z + k)

    def as_dict(self):
        return dict(
            name=self.name, role=self.role,
            cell=[self.x, self.y, self.z], size_cells=[self.sx, self.sy, self.sz],
            pos=[CELL * self.x + CELL * (self.sx - 1) / 2.0,
                 CELL * self.y + CELL * (self.sy - 1) / 2.0,
                 CELL * self.z + CELL * (self.sz - 1) / 2.0],
            dim=[CELL * self.sx, CELL * self.sy, CELL * self.sz],
        )


# ====================================================== the structural check
# The contract's one-action self-check, executed rather than asserted.

def structural_report(chunks):
    """Delete all cladding; can the rest stand on its own?

    Support is flood-fill from the ground through face-adjacency between
    structural chunks - the same question the game's solver asks every tick.
    A chunk is grounded if it holds a cell at storey 0; everything else must
    be reachable from something that is.
    """
    frame = [c for c in chunks if c.role in STRUCTURAL]
    owner = {}
    for i, c in enumerate(frame):
        for cell in c.cells_occupied():
            owner[cell] = i

    adj = {i: set() for i in range(len(frame))}
    for i, c in enumerate(frame):
        for (x, y, z) in c.cells_occupied():
            for nb in ((x + 1, y, z), (x - 1, y, z), (x, y + 1, z),
                       (x, y - 1, z), (x, y, z + 1), (x, y, z - 1)):
                j = owner.get(nb)
                if j is not None and j != i:
                    adj[i].add(j)
                    adj[j].add(i)

    grounded = [i for i, c in enumerate(frame) if c.y == 0]
    seen, queue = set(grounded), deque(grounded)
    while queue:
        i = queue.popleft()
        for j in adj[i]:
            if j not in seen:
                seen.add(j)
                queue.append(j)

    floating = [frame[i].name for i in range(len(frame)) if i not in seen]

    # A column touching no concrete at its own storey is a stilt: it stands,
    # but it is tied to nothing and the storey has no diaphragm.
    concrete_cells = {cell for c in frame if c.role == "concrete"
                      for cell in c.cells_occupied()}
    stilts = []
    for c in frame:
        if c.role != "steel":
            continue
        tied = False
        for (x, y, z) in c.cells_occupied():
            if any(nb in concrete_cells for nb in
                   ((x + 1, y, z), (x - 1, y, z), (x, y, z + 1), (x, y, z - 1))):
                tied = True
                break
        if not tied:
            stilts.append(c.name)

    # Every bay-line column must reach the ground without a gap.
    columns = {}
    for c in frame:
        if c.role != "steel":
            continue
        for (x, y, z) in c.cells_occupied():
            columns.setdefault((x, z), set()).add(y)
    broken = []
    for (x, z), ys in sorted(columns.items()):
        if 0 not in ys:
            broken.append("column x%02d z%02d does not reach the ground" % (x, z))
        elif sorted(ys) != list(range(min(ys), max(ys) + 1)):
            broken.append("column x%02d z%02d has a gap in it" % (x, z))

    wide_glass = [c.name for c in chunks
                  if c.role == "glass" and max(c.sx, c.sz) > 2]

    return dict(frame_chunks=len(frame), floating=floating, stilts=stilts,
                broken_columns=broken, wide_glass=wide_glass,
                standing=not (floating or broken or wide_glass))


# ================================================================= buildings

def tower():
    """13x13x14 - the Tower archetype. Full frame, glazed shaft, open lobby."""
    b = Building("tower", 13, 13, 14,
                 note="Ground storey is an open lobby: cladding omitted, columns "
                      "present. Top two storeys glazed as a crown.")
    b.frame()
    b.clad(lambda y: "glass" if (y >= b.storeys - 2 or y % 3 == 2) else "infill",
           skip_storeys=(0,))
    return b


def block():
    """19x19x6 - the Block archetype. Heavy brick perimeter, wide and squat."""
    b = Building("block", 19, 19, 6,
                 note="Brick perimeter with a glazed top storey; open colonnade "
                      "at ground level on all four sides.")
    b.frame()
    b.clad(lambda y: "glass" if y == b.storeys - 1 else "brick", skip_storeys=(0,))
    return b


def slab():
    """10x19x8 - the Slab archetype. Long glazed flanks, solid ends."""
    b = Building("slab", 10, 19, 8,
                 note="Alternating glazed and infill storeys the full height; "
                      "no open lobby, so the ground storey is fully clad.")
    b.frame()
    b.clad(lambda y: "glass" if y % 2 == 1 else "infill")
    return b


def stump():
    """10x10x4 - the Stump archetype. Industrial brick, minimal glazing."""
    b = Building("stump", 10, 10, 4,
                 note="All brick except a glazed band at the top storey.")
    b.frame()
    b.clad(lambda y: "glass" if y == b.storeys - 1 else "brick")
    return b


BUILDINGS = [("tower", tower, 1.3), ("block", block, 1.3),
             ("slab", slab, 1.3), ("stump", stump, 1.25)]


# =============================================================== Maya bridge

def ok(resp, what):
    if resp.get("status") != "ok":
        print("FAILED %s: %s" % (what, json.dumps(resp.get("error", resp))[:500]))
        sys.exit(1)
    return resp["result"]


def run(code, what, timeout=1800.0):
    out = ok(call("execute_python", {"code": code}, timeout), what)
    if out.get("traceback"):
        print("PYTHON FAILED (%s):\n%s" % (what, out["traceback"][:1500]))
        sys.exit(1)
    return out


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
result = {"chunks": sum(len(v) for v in by_role.values())}
result
'''

CHECK_CODE = r'''
import maya.cmds as cmds
CELL, EPS = 3.0, 1e-4
kids = cmds.listRelatives("|" + LABEL, children=True, fullPath=True) or []
fails, tris = [], 0
def on_lattice(v):
    t = (v + CELL / 2.0) / CELL
    return abs(t - round(t)) < EPS
for node in kids:
    short = node.split("|")[-1]
    shapes = cmds.listRelatives(node, shapes=True, fullPath=True) or []
    if not shapes:
        fails.append((short, "no shape")); continue
    tris += cmds.polyEvaluate(shapes[0], triangle=True)
    v = cmds.polyEvaluate(shapes[0], vertex=True)
    e = cmds.polyEvaluate(shapes[0], edge=True)
    f = cmds.polyEvaluate(shapes[0], face=True)
    if v - e + f != 2:
        fails.append((short, "not closed (V-E+F=%d)" % (v - e + f)))
    if [round(s, 6) for s in cmds.getAttr(node + ".scale")[0]] != [1.0, 1.0, 1.0]:
        fails.append((short, "left-over scale"))
    bb = cmds.exactWorldBoundingBox(node)
    if not all(on_lattice(q) for q in bb):
        fails.append((short, "bounds off lattice"))
    centre = [(bb[i] + bb[i + 3]) / 2.0 for i in range(3)]
    piv = cmds.xform(node, query=True, worldSpace=True, rotatePivot=True)
    if any(abs(piv[i] - centre[i]) > 1e-3 for i in range(3)):
        fails.append((short, "pivot not centred"))
    try:
        parts = short.split("_")
        cx, cy, cz = (int(p[1:]) for p in parts[1:4])
    except Exception:
        fails.append((short, "name does not parse")); continue
    want = [cx * CELL - CELL / 2.0, cy * CELL - CELL / 2.0, cz * CELL - CELL / 2.0]
    if any(abs(bb[i] - want[i]) > 1e-3 for i in range(3)):
        fails.append((short, "name disagrees with position"))
bb = cmds.exactWorldBoundingBox("|" + LABEL)
result = {"chunks": len(kids), "tris": tris, "fails": fails[:20],
          "fail_count": len(fails),
          "bbox_min": [round(q, 3) for q in bb[:3]],
          "bbox_max": [round(q, 3) for q in bb[3:]]}
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
    mel.eval('FBXExportInputConnections -v false')
except Exception:
    pass
cmds.select("|" + LABEL, replace=True, hierarchy=True)
cmds.file(FBX, force=True, type="FBX export", pr=True, es=True)
result = FBX
result
'''


def build_one(label, builder, zoom):
    b = builder()
    chunks = b.chunks()
    report = structural_report(chunks)
    if not report["standing"]:
        print("%s WOULD COLLAPSE ON LOAD:" % label)
        for key in ("broken_columns", "floating", "wide_glass"):
            for item in report[key][:12]:
                print("    %-18s %s" % (key, item))
        sys.exit(1)

    payload = json.dumps({"label": label, "colours": ROLE_COLOUR,
                          "chunks": [c.as_dict() for c in chunks]})
    ok(call("new_scene", {"confirm": True}, 300.0), "new_scene")
    run("SPEC = %r\n%s" % (payload, BUILD_CODE), "build %s" % label)
    check = ast.literal_eval(
        run("LABEL = %r\n%s" % (label, CHECK_CODE), "check %s" % label)["result_repr"])
    fbx = os.path.join(OUT_DIR, "%s.fbx" % label).replace("\\", "/")
    run("LABEL = %r\nFBX = %r\n%s" % (label, fbx, EXPORT_CODE), "export %s" % label)

    ok(call("setup_lighting", {"preset": "three_point", "intensity": 1.5,
                               "replace_existing": True}, 180.0), "lighting")
    shot = ok(call("render_scene", {
        "angles": ["three_quarter"], "renderer": "arnold", "resolution": 768,
        "samples": 3, "zoom": zoom, "target": ["|" + label]}, 1200.0),
        "render %s" % label)["images"][0]
    png = base64.b64decode(shot["png_b64"])
    with open(os.path.join(OUT_DIR, "%s.png" % label), "wb") as fh:
        fh.write(png)

    roles = {}
    for c in chunks:
        roles[c.role] = roles.get(c.role, 0) + 1
    size = [round(check["bbox_max"][i] - check["bbox_min"][i], 2) for i in range(3)]
    return dict(
        name=label, archetype_footprint_cells=[b.nx, b.nz], storeys=b.storeys,
        size_m=size, bbox_min=check["bbox_min"], bbox_max=check["bbox_max"],
        chunks=check["chunks"], triangles=check["tris"],
        tris_per_chunk=round(check["tris"] / max(1, check["chunks"]), 1),
        roles=roles, frame_chunks=report["frame_chunks"],
        stilt_columns=report["stilts"], note=b.note,
        files=["%s.fbx" % label, "%s.png" % label],
        chunk_list=[c.as_dict() for c in chunks],
    ), check, report, images.pixel_stats(png)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    entries, clean = [], True
    for label, builder, zoom in BUILDINGS:
        entry, check, report, stats = build_one(label, builder, zoom)
        geom_ok = check["fail_count"] == 0
        clean = clean and geom_ok
        print("%-7s %-4s %4d chunks (%d frame)  %6d tris  %s m  stilts %d  "
              "render clip %.4f"
              % (label, "OK" if geom_ok else "FAIL", entry["chunks"],
                 entry["frame_chunks"], entry["triangles"], entry["size_m"],
                 len(report["stilts"]), stats["clipped_fraction"]))
        for short, why in check["fails"]:
            print("    %-26s %s" % (short, why))
        entries.append(entry)

    manifest = {
        "contract": "Demigol STRUCTURE MODEL CONTRACT",
        "scope": "four whole destructible hero buildings; not a parts library",
        "units": "metres, Y-up, 1 unit = 1 m, cell = 3 m",
        "origin": "min-corner cell CENTRE at local (0,0,0); floor plane at y = -1.5",
        "naming": "<role>_x##_y##_z##; x/z cell indices from the min corner, "
                  "y = storey (0 = ground). Multi-cell chunks are named for "
                  "their min-corner cell.",
        "roles": list(ROLES),
        "role_colours": ROLE_COLOUR,
        "structural_model":
            "Columns are steel on every bay-line intersection, merged into "
            "segments of up to 4 storeys so the frame falls as large sections. "
            "Every storey carries a concrete beam grid on the bay lines, which "
            "is what ties the columns. Cladding is hung only in perimeter cells "
            "the frame does not need, so no cell is ever claimed twice and the "
            "manifest is an unambiguous statement of what each cell is made of.",
        "one_action_self_check":
            "IMPLEMENTED IN THE GENERATOR, not asserted. All brick/infill/glass "
            "is discarded and the remaining steel+concrete is flood-filled from "
            "storey 0 through face-adjacency. A build with any unreachable "
            "frame chunk, any column that does not reach the ground or has a "
            "gap, or any glass wider than 2 cells, exits non-zero and produces "
            "no FBX. All four pass.",
        "geometry_self_check":
            "every chunk re-measured in-scene: closed (V-E+F=2), bounds on 3 m "
            "boundaries, pivot at chunk centre, scale (1,1,1), name parses and "
            "agrees with measured position",
        "deviations": [
            {"item": "vertical sense of the origin",
             "what": "min-corner cell CENTRE at local y = 0, so the floor plane "
                     "is at y = -1.5.",
             "why": "'Model origin = the MIN-CORNER CELL CENTRE, at y = 1.5' "
                    "reads as the origin being that cell centre, with the "
                    "parenthetical locating it above the floor. If you meant "
                    "the floor at y = 0, every building needs one +1.5 m Y "
                    "offset - no regeneration."},
            {"item": "corner spandrels",
             "what": "One cell beside each corner column is concrete, not "
                     "cladding.",
             "why": "A corner column's only two face-adjacent cells are both on "
                    "the perimeter ring. With cladding there it touches nothing "
                    "structural and is a stilt by your own definition. The "
                    "spandrel gives it a tie; the stilt count in the manifest "
                    "is the evidence."},
            {"item": "no taper or curve",
             "what": "Every chunk is an axis-aligned box.",
             "why": "A tapered chunk cannot have bounds on cell boundaries. "
                    "Lattice conformance outranks ornament; character comes "
                    "from massing, glazing pattern and open lobbies instead."},
            {"item": "coplanar faces",
             "what": "Adjacent chunks share exact faces and will z-fight.",
             "why": "Bounds must land on cell boundaries, which forces it. "
                    "Point 4 encourages deep interpenetration as the escape, "
                    "but that conflicts with exact bounds. Cheapest fix is "
                    "shrinking the RENDER mesh a few mm inside the lattice "
                    "bounds. Wants a decision before more buildings."},
        ],
        "structures": entries,
    }
    with open(os.path.join(OUT_DIR, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2)
    print("\nmanifest.json written - geometry check: %s"
          % ("all four clean" if clean else "FAILURES ABOVE"))
    return 0 if clean else 1


if __name__ == "__main__":
    sys.exit(main())
