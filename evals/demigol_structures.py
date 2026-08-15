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
generated district rather than something that has to be placed by hand. Since
revision 3 a storey has a footprint of its own, so a hero is a PROFILE rather
than a box, and each one steps back to a different rhythm:

  tower  10x10 -> 7x7 -> 4x4 over 28 storeys   30 x 87 x 30 m
  block  19x19 with a 13x13 attic, 6 storeys   57 x 21 x 57 m
  slab   10x19 stepping to 10x13, 8 storeys    30 x 27 x 57 m
  stump  10x10 under a 4x4 bulkhead, 5 storeys 30 x 18 x 30 m

The base footprint never grew, so nothing in the city layout has to move.

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

import delivery_units  # noqa: E402 - the artifact-level unit gate
import demigol_kit as kit  # noqa: E402 - shared atlas, patches and density
import maya_export  # noqa: E402 - one place the delivery unit is decided
from live_call import call  # noqa: E402
from maya_mcp import images  # noqa: E402

MAPS = {}   # filled by main(): the same three maps the kit ships

OUT_DIR = os.path.join(_HERE, "demigol_structures")

CELL = 3.0
BAY = 3                      # cells between column lines (9 m)
MAX_CELLS, MAX_SPAN, MAX_STOREYS = 48, 6, 4

STRUCTURAL = ("steel", "concrete")
CLADDING = ("brick", "infill", "glass")
ROLES = STRUCTURAL + CLADDING

# --------------------------------------------------------------- revision 2
# Two ceilings went up. The budget is 200 triangles per 1-cell chunk and this
# delivery used 12 - every chunk a plain box, so four hero buildings rendered
# as the same graybox cubes the city already draws. And render geometry may now
# outset 0.5 m past the cell face, because the lattice constrains which CELLS a
# chunk occupies, never its mesh.
#
# Detail is spent where it is seen: a chunk's EXPOSED faces. Interior and
# hidden frame chunks stay cheap, because they are invisible until the golem
# opens the building up - at which point silhouette matters less than the fact
# that something came off.
INSET = 0.005
MAX_OUTSET = 0.5
TRI_BUDGET_PER_CELL = 200
TRIS_PER_BOX = 12

# Heroes sample the SAME atlas as the kit, so a hero and its kit-dressed
# neighbours sit in the same light (contract rev 2 section 8).
KIT_DIR = os.path.join(_HERE, "demigol_kit")
ROLE_PATCH = {
    "steel": "steel", "concrete": "concrete", "brick": "brick",
    "infill": "infill", "glass": "glass",
}
TRIM_PATCH = {
    "steel": "steel_dark", "concrete": "concrete_dark", "brick": "concrete",
    "infill": "infill_dark", "glass": "steel_dark",
}

# --------------------------------------------------------------- palette (r3)
# #600 item 7: all four heroes were the same blue-glass/grey/rust, because all
# four drew from the same five patches. The atlas has carried `amber`, `rust`,
# `trim`, `grime`, `brick_dark`, `glass_bright` and `sky_glass` since revision 2
# and no hero has ever touched one of them.
#
# So this is the table edit item 7 asked for, and it costs NOTHING downstream:
# same atlas, same material, same draw call, no kit rebuild. A role absent from
# a palette falls back to ROLE_PATCH/TRIM_PATCH, so a palette states only what
# it changes.
PALETTES = {
    "default": {},
    # tower - corporate, cold. Pale spandrels against sky-coloured glazing.
    "cool": {
        "glass":    ("sky_glass", "steel_dark"),
        "infill":   ("trim", "concrete_dark"),
        "concrete": ("concrete", "trim"),
    },
    # block - warm masonry. The amber is the industrial warning amber the art
    # direction calls for, spent on string courses where it reads as a band.
    "warm": {
        "brick":    ("brick", "amber"),
        "glass":    ("glass_bright", "steel_dark"),
        "concrete": ("concrete", "trim"),
    },
    # slab - pale and rusting. Rust on every trim, so the decay reads at
    # distance as a colour rather than as texture detail that mips away.
    "industrial": {
        "infill":   ("infill", "rust"),
        "glass":    ("glass", "steel_dark"),
        "concrete": ("concrete_dark", "rust"),
        "steel":    ("steel_dark", "rust"),
    },
    # stump - grimy. Dark brick and soot; the one that should look derelict.
    "grimy": {
        "brick":    ("brick_dark", "grime"),
        "glass":    ("glass", "grime"),
        "concrete": ("concrete_dark", "grime"),
        "steel":    ("steel_dark", "grime"),
    },
}


def patches_for(role, palette=None):
    """The (body, trim) atlas patches this role uses under this palette."""
    table = PALETTES[palette or "default"]
    if role in table:
        return table[role]
    return ROLE_PATCH[role], TRIM_PATCH[role]


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

    def __init__(self, label, nx, nz, storeys, note="", tiers=None,
                 palette=None):
        for axis, n in (("x", nx), ("z", nz)):
            if n < 4 or (n - 1) % BAY != 0:
                raise ValueError("%s: %s axis of %d cells is not (bays*3+1)"
                                 % (label, axis, n))
        self.label, self.nx, self.nz, self.storeys = label, nx, nz, storeys
        self.note = note
        self.bx, self.bz = bay_lines(nx), bay_lines(nz)
        self.cells = {}                     # (x, y, z) -> role
        self.roofed = set()                 # cells roof() claimed
        self.palette = palette or "default"
        self.tiers = self._check_tiers(tiers)

    # ------------------------------------------------------------- footprint
    def _check_tiers(self, tiers):
        """Validate the per-storey footprint, or invent the trivial one.

        #600 item 2. Every rule here is a load path: a tier that breaks one
        would produce a building that renders correctly and collapses the
        moment the game's solver looks at it, which is the worst kind of
        delivery. They are checked at construction so a bad tier cannot reach
        an FBX.
        """
        full = (0, self.nx - 1, 0, self.nz - 1)
        if not tiers:
            return [(0, full)]
        if tiers[0][0] != 0:
            raise ValueError("%s: the first tier must start at the ground"
                             % self.label)
        out, prev, last = [], full, -1
        for frm, rect in tiers:
            if frm <= last:
                raise ValueError("%s: tiers must ascend, %d follows %d"
                                 % (self.label, frm, last))
            last = frm
            x0, x1, z0, z1 = rect
            for axis, lo, hi, lines, plo, phi in (
                    ("x", x0, x1, self.bx, prev[0], prev[1]),
                    ("z", z0, z1, self.bz, prev[2], prev[3])):
                n = hi - lo + 1
                if n < 4 or (n - 1) % BAY != 0:
                    raise ValueError(
                        "%s: tier at storey %d is %d cells on %s - not (bays*3+1)"
                        % (self.label, frm, n, axis))
                if lo < plo or hi > phi:
                    raise ValueError(
                        "%s: tier at storey %d does not nest on %s (%d-%d "
                        "outside %d-%d) - that is a cantilever"
                        % (self.label, frm, axis, lo, hi, plo, phi))
                own = [lo + i for i in bay_lines(n)]
                missing = [v for v in own if v not in lines]
                if missing:
                    raise ValueError(
                        "%s: tier at storey %d puts a column line at %s on %s, "
                        "where there is none below"
                        % (self.label, frm, missing, axis))
            out.append((frm, tuple(rect)))
            prev = tuple(rect)
        return out

    def foot(self, y):
        """The (x0, x1, z0, z1) cell rect this storey occupies."""
        rect = self.tiers[0][1]
        for frm, r in self.tiers:
            if y >= frm:
                rect = r
        return rect

    def foot_cells(self, y):
        """The footprint as a set of (x, z), empty above the top storey."""
        if y < 0 or y >= self.storeys:
            return set()
        x0, x1, z0, z1 = self.foot(y)
        return {(x, z) for x in range(x0, x1 + 1) for z in range(z0, z1 + 1)}

    def foot_lines(self, y):
        """This storey's column lines, in the building's own coordinates."""
        x0, x1, z0, z1 = self.foot(y)
        return ([x0 + i for i in bay_lines(x1 - x0 + 1)],
                [z0 + i for i in bay_lines(z1 - z0 + 1)])

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
            rect = self.foot(y)
            x0, x1, z0, z1 = rect
            bx, bz = self.foot_lines(y)
            for x in bx:
                for z in bz:
                    self.put("steel", x, y, z)
            for x in range(x0, x1 + 1):
                for z in range(z0, z1 + 1):
                    on_x, on_z = x in bx, z in bz
                    if on_x and on_z:
                        continue                      # column, already placed
                    if on_x != on_z and self._interior(x, z, rect):
                        self.put("concrete", x, y, z)  # beam grid
            for x, z in self._corner_spandrels(rect):
                self.put("concrete", x, y, z)

    def _interior(self, x, z, rect):
        x0, x1, z0, z1 = rect
        return x0 < x < x1 and z0 < z < z1

    def _corner_spandrels(self, rect):
        x0, x1, z0, z1 = rect
        return [(x0 + 1, z0), (x1 - 1, z0), (x0 + 1, z1), (x1 - 1, z1)]

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
            x0, x1, z0, z1 = self.foot(y)
            for x in range(x0, x1 + 1):
                for z in range(z0, z1 + 1):
                    if not (x in (x0, x1) or z in (z0, z1)):
                        continue
                    if (x, y, z) in self.cells:
                        continue
                    self.put(role, x, y, z)

    # ------------------------------------------------------------------ roof
    def roof(self):
        """Frame the roof: a beam grid on the bay lines, and the deck it carries.

        #600 item 1, the top-ranked miss - every revision 2 render is an open
        egg-crate seen from above, and the golem roof-slams, so a rooftop is a
        primary play surface that did not exist. The cause was total: nothing
        was ever claimed above the top storey, so the building simply stopped.

        THE ROOF IS A STOREY, not a hat. It occupies real cells at
        `y == storeys`, and that matters for more than bookkeeping: collision
        is generated from the grid and never from the art, so a deck modelled
        as ornament over an empty cell would be visually right and physically
        absent - the golem would fall through a floor it can see.

        Built from STRUCTURAL roles only. Per the division agreed with the
        Demigol side, the hero frames the roof and the kit sheathes it: beams
        and substrate here collapse when destroyed, while the finish, parapet
        and rooftop plant come off without dropping the building. That is the
        existing frame/cladding split rotated into the horizontal.

        Steel is deliberately absent. A column's run merges vertically, and
        continuing it into the roof would make the deck part of the column
        segment rather than a thing the column carries.

        REVISION 3 generalises the rule to: cap every cell a storey occupies
        that the storey above does not. At the top that is the whole footprint,
        which is what it always did. At a setback it is a TERRACE - so the
        several decks at several heights that a roof-slamming golem wants come
        out of the silhouette instead of being a second feature bolted on.

        A terrace ring carries: it sits on the wider tier's perimeter, which
        holds bay-line columns, and the ring is contiguous concrete, so the
        flood fill in `structural_report` reaches all of it from the ground.
        """
        for y in range(self.storeys):
            for (x, z) in sorted(self.foot_cells(y) - self.foot_cells(y + 1)):
                self.put("concrete", x, y + 1, z)
                self.roofed.add((x, y + 1, z))

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

    def as_dict(self, outset_m=0.0):
        return dict(
            name=self.name, role=self.role,
            cell=[self.x, self.y, self.z], size_cells=[self.sx, self.sy, self.sz],
            pos=[CELL * self.x + CELL * (self.sx - 1) / 2.0,
                 CELL * self.y + CELL * (self.sy - 1) / 2.0,
                 CELL * self.z + CELL * (self.sz - 1) / 2.0],
            dim=[CELL * self.sx, CELL * self.sy, CELL * self.sz],
            outset_m=float(outset_m),
        )


def chunk_outset(boxes, sx, sy, sz):
    """Metres this chunk's render mesh oversails its own cell block.

    The kit has declared this per piece since revision 2 and the heroes never
    have, while using up to 0.47 m of the 0.5 allowance - #600 item 4, and
    2,034 importer warnings.

    The kit's version compares against CELL/2 because a piece is always one
    cell centred on the origin. A chunk is sx x sy x sz cells, so the half
    extent scales; comparing a 4-storey chunk against CELL/2 would report 4.5 m
    of oversail on a mesh that fits perfectly.

    Boxes are in the chunk's own local space, centred on the chunk centre.
    Taper is ignored, exactly as the kit ignores it: a tapered box never
    reaches past its untapered footprint, so the declared value stays
    conservative.
    """
    if not boxes:
        return 0.0
    half = (CELL * sx / 2.0, CELL * sy / 2.0, CELL * sz / 2.0)
    reach = max(abs(b["pos"][i]) + b["dim"][i] / 2.0 - half[i]
                for b in boxes for i in range(3))
    return round(max(0.0, reach), 4)


def hero_material_block():
    """What atlas the heroes sample, said in the manifest rather than a README.

    #600 item 5: the delivery names no material at all, so an importer cannot
    wire one without hardcoding the knowledge that heroes borrow the kit's.

    Shape is constrained by the consumer: `DeliveryManifest` is a
    [Serializable] DTO parsed with plain JsonUtility and no Newtonsoft, which
    cannot deserialize dictionaries. Objects and numeric arrays only.

    Wiring this is Demigol's side (#612) - `CatalogBaker` reads
    `root.IsKit ? MaterialBaker.Bake(...) : null` and `SharedMaterial` is
    documented kit-only, so a cross-delivery reference is new to their
    validator.
    """
    return {
        "shared_with": "demigol_kit",
        "shared": True,
        "shader": "kit_material (standardSurface)",
        "maps": {
            "albedo": "kit_albedo.png",
            "normal": "kit_normal.png",
            "mask": "kit_mask.png",
        },
        "mask_channels": {
            "metallic": "R",
            # URP Lit's _MetallicGlossMap reads R = metallic, A = smoothness.
            # G carries a duplicate so the map stays readable by eye; it is
            # inert under URP and would be read as ambient occlusion under
            # HDRP, which is one reason Demigol did not go there.
            "smoothness": "A (duplicated in G, inert)",
        },
        "atlas_px": kit.ATLAS_PX,
        "atlas_grid": [kit.ATLAS_COLS, kit.ATLAS_ROWS],
        "world_scale": kit.WORLD_SCALE,
        "px_per_metre": round(kit.PX_PER_METRE, 2),
        "note": "One standardSurface per building, sampling the kit's shared "
                "atlas at the same density, so a hero standing among "
                "kit-dressed neighbours belongs to the same city.",
    }


# ============================================================ detail (rev 2)
# A chunk's geometry, as boxes in its own local space. 12 triangles each, so
# the budget stays arithmetic: an 8-box chunk is 96 against 200 per cell.

def _exposure(ch, occupied, storeys):
    """Which of a chunk's faces can actually be seen from outside.

    `storeys` is retained for callers but is no longer what decides `top`.
    Revision 2 computed it as `(ch.y + ch.sy) >= storeys` - arithmetic on the
    storey count rather than a look at the neighbours - which was true while
    nothing was ever built above the top storey. Now that `Building.roof()`
    claims a storey of its own, that test would call BOTH the roof and the
    storey underneath it "top" and crown them each.

    Probing +Y against the occupied set is the same question the four vertical
    faces already ask, and it stays right whatever is built above.
    """
    faces = {}
    for axis, sign, key in (("x", -1, "nx"), ("x", 1, "px"),
                            ("z", -1, "nz"), ("z", 1, "pz"),
                            ("y", 1, "top")):
        exposed = False
        idx = {"x": 0, "y": 1, "z": 2}[axis]
        for cell in ch.cells_occupied():
            probe = list(cell)
            probe[idx] += sign
            if tuple(probe) not in occupied:
                exposed = True
                break
        faces[key] = exposed
    faces["ground"] = ch.y == 0
    return faces


def _face_boxes(ch, key, patch, trim, expo):
    """Relief on one exposed vertical face, in chunk-local coordinates."""
    axis = 0 if key in ("nx", "px") else 2
    sign = -1 if key in ("nx", "nz") else 1
    half = CELL * (ch.sx if axis == 0 else ch.sz) / 2.0
    hy = CELL * ch.sy / 2.0
    across = CELL * (ch.sz if axis == 0 else ch.sx) - 2 * INSET

    def place(offset_from_face, thickness, y_centre, height, wide, p):
        """A slab lying against the face; offset is measured OUTWARD."""
        centre = sign * (half + offset_from_face - thickness / 2.0)
        pos = [0.0, y_centre, 0.0]
        dim = [wide, height, wide]
        pos[axis] = centre
        dim[axis] = thickness
        dim[2 if axis == 0 else 0] = wide
        return {"pos": pos, "dim": dim, "patch": p}

    def upright(offset_from_face, thickness, across_centre, width, p):
        """A vertical rib the full height of the chunk. `place` lays slabs
        horizontally; a mullion is the same slab stood on its end."""
        centre = sign * (half + offset_from_face - thickness / 2.0)
        pos = [0.0, 0.0, 0.0]
        dim = [0.0, CELL * ch.sy - 2 * INSET, 0.0]
        pos[axis] = centre
        dim[axis] = thickness
        other = 2 if axis == 0 else 0
        pos[other] = across_centre
        dim[other] = width
        return {"pos": pos, "dim": dim, "patch": p}

    # #600 item 6: revision 2.5 spent 73-78 triangles of a 200-per-cell budget
    # and declined geometry on budget grounds while sitting on the headroom.
    # What follows is the headroom, spent on verticals - a facade of horizontal
    # bands alone reads as a stack of shelves, and it is the vertical rhythm
    # that makes a curtain wall look like a curtain wall from 30 m.
    cells_across = ch.sz if axis == 0 else ch.sx
    out = []
    if ch.role == "brick":
        # string courses, a sill under the head of each storey, and a pilaster
        # at each end of the face
        for i in range(ch.sy):
            base = -hy + CELL * (i + 0.5)
            out.append(place(0.10, 0.28, base + 0.95, 0.26, across, trim))
            out.append(place(0.06, 0.20, base - 0.95, 0.16, across * 0.78, trim))
        for i in range(cells_across):
            edge = -across / 2.0 + CELL * (i + 0.5)
            out.append(upright(0.07, 0.22, edge - CELL / 2.0 + 0.22, 0.44, patch))
            out.append(upright(0.07, 0.22, edge + CELL / 2.0 - 0.22, 0.44, patch))
    elif ch.role == "infill":
        for i in range(ch.sy):
            base = -hy + CELL * (i + 0.5)
            out.append(place(0.05, 0.16, base + 1.2, 0.22, across, trim))
            out.append(place(0.05, 0.16, base - 1.2, 0.22, across, trim))
        for i in range(cells_across):
            out.append(upright(0.05, 0.14, -across / 2.0 + CELL * (i + 0.5),
                               0.30, trim))       # panel joint, one per cell
    elif ch.role == "glass":
        for i in range(ch.sy):
            base = -hy + CELL * (i + 0.5)
            out.append(place(0.07, 0.18, base + 1.28, 0.30, across, trim))
            out.append(place(0.07, 0.18, base - 1.28, 0.30, across, trim))
        for i in range(cells_across):
            mid = -across / 2.0 + CELL * (i + 0.5)
            for off in (-0.9, 0.0, 0.9):
                out.append(upright(0.09, 0.20, mid + off, 0.20, trim))  # mullions
    else:  # steel / concrete frame, seen wherever cladding is gone
        out.append(place(0.07, 0.20, 0.0, CELL * ch.sy - 2 * INSET,
                         across * 0.55, trim))
        # the flanges either side of that web: an I-section read, which is what
        # says "steel frame" when the cladding has come off it
        for edge in (-1, 1):
            out.append(upright(0.16, 0.14, edge * across * 0.30, across * 0.18,
                               trim))
    return out


def chunk_boxes(ch, occupied, storeys, palette=None):
    """The chunk as a list of boxes. One box is the old behaviour; the rest is
    relief on faces that are actually visible."""
    hx = CELL * ch.sx / 2.0 - INSET
    hy = CELL * ch.sy / 2.0 - INSET
    hz = CELL * ch.sz / 2.0 - INSET
    patch, trim = patches_for(ch.role, palette)
    boxes = [{"pos": [0.0, 0.0, 0.0], "dim": [2 * hx, 2 * hy, 2 * hz],
              "patch": patch}]

    expo = _exposure(ch, occupied, storeys)
    faces = [k for k in ("nx", "px", "nz", "pz") if expo[k]]
    budget_boxes = max(1, (ch.sx * ch.sy * ch.sz * TRI_BUDGET_PER_CELL)
                       // TRIS_PER_BOX) - 1

    for key in faces:
        for b in _face_boxes(ch, key, patch, trim, expo):
            if len(boxes) - 1 >= budget_boxes:
                break
            boxes.append(b)

    # The crown and the plinth: the two pieces of silhouette that read from
    # across the district, and the two revision 1 could not author at all.
    if expo["top"] and faces:
        for key in faces:
            axis = 0 if key in ("nx", "px") else 2
            sign = -1 if key in ("nx", "nz") else 1
            half = (hx if axis == 0 else hz) + INSET
            pos = [0.0, hy - 0.22, 0.0]
            dim = [2 * hx, 0.30, 2 * hz]
            pos[axis] = sign * (half + 0.16)
            dim[axis] = 0.62
            if len(boxes) - 1 < budget_boxes:
                boxes.append({"pos": pos, "dim": dim, "patch": trim})
    if expo["ground"] and faces and ch.role in CLADDING:
        for key in faces:
            axis = 0 if key in ("nx", "px") else 2
            sign = -1 if key in ("nx", "nz") else 1
            half = (hx if axis == 0 else hz) + INSET
            pos = [0.0, -hy + 0.42, 0.0]
            dim = [2 * hx, 0.84, 2 * hz]
            pos[axis] = sign * (half + 0.09)
            dim[axis] = 0.40
            if len(boxes) - 1 < budget_boxes:
                boxes.append({"pos": pos, "dim": dim,
                              "patch": patches_for("concrete", palette)[0]})
    return split_oversized(boxes)


def split_oversized(boxes):
    """Cut every box down to at most one cell on each axis.

    Found by the LIVE gate and by nothing else. The roof rendered with teal
    stripes across it - the glass patch, bleeding in from two columns over -
    because a 4-cell roof deck is a single 11.99 m box.

    Boxes are already packed one at a time, before combine, at a fixed
    `world_scale`, which makes texel density a constant instead of a function
    of object size. The cost of that choice is that a box BIGGER than the
    envelope cannot be made to fit: its projection simply lays out wider than
    one patch and spills into its neighbours. Measured, packing single boxes
    into the concrete patch (u 0.5075-0.7425, v 0.7575-0.9925):

        3.00 x 3.00 x 3.00   ->  u 0.513-0.737   inside
        3.00 x 0.84 x 0.40   ->  u 0.582-0.668   inside
       12.00 x 3.00 x 3.00   ->  u 0.444-0.806   SPILLS, both sides

    So it is size, not shape - non-cubic boxes pack correctly, oversized ones
    do not. Kit pieces never hit this because a piece is one cell.

    Splitting at cell boundaries costs nothing else. Density is untouched,
    `MAX_RUN` is untouched - which matters, because the Demigol side explicitly
    rejected granulating chunks - and the pieces combine straight back into one
    mesh, so the destruction unit is exactly what it was. Only the triangle
    count moves, 44-54 to 73-78 against a 200-per-cell budget.

    NOTE for anyone re-measuring this: a COMBINED chunk legitimately spans more
    than one patch, because its body and its trim use different patches. Checking
    a chunk's overall UV bbox against a single patch width therefore reports
    every chunk as overflowing and means nothing. Measure per box, before
    combine, or measure against the union of the patches the chunk actually
    uses.
    """
    out = []
    for b in boxes:
        counts = [max(1, int(round(b["dim"][i] / CELL - 1e-6 + 0.5))) or 1
                  for i in range(3)]
        counts = [c if b["dim"][i] > CELL + 1e-9 else 1
                  for i, c in enumerate(counts)]
        if counts == [1, 1, 1]:
            out.append(b)
            continue
        step = [b["dim"][i] / counts[i] for i in range(3)]
        start = [b["pos"][i] - b["dim"][i] / 2.0 for i in range(3)]
        for i in range(counts[0]):
            for j in range(counts[1]):
                for k in range(counts[2]):
                    idx = (i, j, k)
                    out.append({
                        "pos": [start[a] + step[a] * (idx[a] + 0.5)
                                for a in range(3)],
                        "dim": list(step),
                        "patch": b["patch"],
                    })
    return out


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
    """30 m base, 84 m tall, stepping 10x10 -> 7x7 -> 4x4. The Tower.

    Revision 2's tower was 13x13 cells by 14 storeys - 39.9 x 42.0 x 39.9 m, a
    cube, which is #600 item 2's headline complaint. Two things fix it and only
    together: the base SHRINKS to 10x10, so it still fits any plot the old one
    fitted and needs no coordination with the city layout, and the height is
    not capped by anything in the contract.

    The 7x7 tier is offset rather than centred (x 0-6, z 3-9). A centred
    setback reads as a wedding cake; an offset one gives the shaft a shoulder,
    and the two terraces it produces are at different corners.
    """
    b = Building("tower", 10, 10, 28,
                 tiers=[(0, (0, 9, 0, 9)), (12, (0, 6, 3, 9)), (22, (3, 6, 3, 6))],
                 note="Ground storey is an open lobby: cladding omitted, columns "
                      "present. Two setbacks with terraces at 36 m and 66 m; the "
                      "top tier is glazed as a crown.",
                 palette="cool")
    b.frame()
    b.clad(lambda y: "glass" if (y >= 22 or y % 3 == 2) else "infill",
           skip_storeys=(0,))
    b.roof()
    return b


def block():
    """19x19x6 with a 13x13 attic - the Block. Wide, squat, stepped crown."""
    b = Building("block", 19, 19, 6,
                 tiers=[(0, (0, 18, 0, 18)), (5, (3, 15, 3, 15))],
                 note="Brick perimeter with a glazed attic set back 9 m on all "
                      "four sides, leaving a perimeter terrace; open colonnade "
                      "at ground level.",
                 palette="warm")
    b.frame()
    b.clad(lambda y: "glass" if y == b.storeys - 1 else "brick", skip_storeys=(0,))
    b.roof()
    return b


def slab():
    """10x19x8, the upper third stepping back on ONE end - the Slab.

    The asymmetry is the point. A slab that steps back on both ends is a
    smaller slab; stepping one end gives it a front and a back, which is what
    stops a row of them reading as a wall.
    """
    b = Building("slab", 10, 19, 8,
                 tiers=[(0, (0, 9, 0, 18)), (5, (0, 9, 0, 12))],
                 note="Alternating glazed and infill storeys the full height; no "
                      "open lobby. The last three storeys step back 18 m on the "
                      "+z end, leaving a long terrace over the low block.",
                 palette="industrial")
    b.frame()
    b.clad(lambda y: "glass" if y % 2 == 1 else "infill")
    b.roof()
    return b


def stump():
    """10x10x4 under a 4x4 bulkhead - the Stump. Deliberately plain.

    A skyline needs plain boxes or the stepped ones stop reading as stepped.
    What separates this from a graybox is the stair headhouse: one storey, a
    quarter of the footprint, and a step the golem can take onto the main deck.
    """
    b = Building("stump", 10, 10, 5,
                 tiers=[(0, (0, 9, 0, 9)), (4, (3, 6, 3, 6))],
                 note="All brick except a glazed band under the roof. The fifth "
                      "storey is a 12 m stair bulkhead on the main deck.",
                 palette="grimy")
    b.frame()
    b.clad(lambda y: "glass" if y == 3 else "brick")
    b.roof()
    return b


# The third value is render zoom. The tower is 87 m on a 30 m base now, so it
# needs the whole frame; a 1.3 that suited a cube crops a tower.
BUILDINGS = [("tower", tower, 1.0), ("block", block, 1.25),
             ("slab", slab, 1.2), ("stump", stump, 1.25)]


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
import importlib, json
import maya.cmds as cmds
from maya_plugin.handlers import combine as _combine
from maya_plugin.handlers import uvatlas as _uvatlas
importlib.reload(_uvatlas); importlib.reload(_combine)

spec = json.loads(SPEC)
label = spec["label"]
# METRE-NATIVE: 1 Maya unit = 1 metre, so the FBX carries metres in its
# vertices. Every number below is unchanged; only the unit label moves.
cmds.currentUnit(linear=AUTHORING_UNIT)

# ONE material for the building, on the SAME atlas the kit uses, so a hero and
# its kit-dressed neighbours sit in the same light.
shader = cmds.shadingNode("standardSurface", asShader=True, name=label + "_mat")
cmds.setAttr(shader + ".base", 1.0)
sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True,
               name=label + "_matSG")
cmds.connectAttr(shader + ".outColor", sg + ".surfaceShader", force=True)


def _file_node(path, name, raw=False):
    node = cmds.shadingNode("file", asTexture=True, name=name)
    cmds.setAttr(node + ".fileTextureName", path, type="string")
    cmds.setAttr(node + ".filterType", 0)
    if raw:
        try:
            cmds.setAttr(node + ".colorSpace", "Raw", type="string")
            cmds.setAttr(node + ".ignoreColorSpaceFileRules", True)
        except Exception:
            pass
    return node


alb = _file_node(spec["maps"]["albedo"], label + "_albedo")
cmds.connectAttr(alb + ".outColor", shader + ".baseColor", force=True)
msk = _file_node(spec["maps"]["mask"], label + "_mask", raw=True)
cmds.connectAttr(msk + ".outColorR", shader + ".metalness", force=True)
inv = cmds.shadingNode("reverse", asUtility=True, name=label + "_s2r")
cmds.connectAttr(msk + ".outColorG", inv + ".inputX", force=True)
cmds.connectAttr(inv + ".outputX", shader + ".specularRoughness", force=True)
nrm = _file_node(spec["maps"]["normal"], label + "_normal", raw=True)
bmp = cmds.shadingNode("bump2d", asUtility=True, name=label + "_bump")
cmds.setAttr(bmp + ".bumpInterp", 1)
cmds.connectAttr(nrm + ".outAlpha", bmp + ".bumpValue", force=True)
cmds.connectAttr(bmp + ".outNormal", shader + ".normalCamera", force=True)

made = []
for c in spec["chunks"]:
    parts = []
    for i, b in enumerate(c["boxes"]):
        node = cmds.polyCube(w=b["dim"][0], h=b["dim"][1], d=b["dim"][2],
                             name="%s_b%d" % (c["name"], i), ch=False)[0]
        # LOCAL space: boxes are placed around the chunk's own centre, the
        # chunk is assembled there, and only then moved onto the grid. That
        # keeps the pivot exactly at the chunk centre even when ornament
        # oversails asymmetrically - bbox centre would drift.
        cmds.move(b["pos"][0], b["pos"][1], b["pos"][2], node, absolute=True)
        node = (cmds.ls(node, long=True) or [node])[0]
        _uvatlas.uv_atlas({"names": [node], "cols": spec["cols"],
                           "rows": spec["rows"], "patch": b["patch"],
                           "margin": spec["margin"],
                           "world_scale": spec["world_scale"],
                           "uv_per_metre": UV_PER_METRE})
        parts.append(node)
    if len(parts) == 1:
        node = parts[0]
        cmds.xform(node, worldSpace=True, pivots=(0, 0, 0))
        cmds.makeIdentity(node, apply=True, translate=True, rotate=True, scale=True)
        node = (cmds.ls(cmds.rename(node, c["name"]), long=True) or [""])[0]
    else:
        node = _combine.combine({"names": parts, "name": c["name"],
                                 "pivot": "origin", "freeze": True})["name"]
    cmds.move(c["pos"][0], c["pos"][1], c["pos"][2], node, absolute=True)
    shape = cmds.listRelatives(node, shapes=True, fullPath=True)[0]
    cmds.sets(shape, edit=True, forceElement=sg)
    made.append((cmds.ls(node, long=True) or [node])[0])

grp = cmds.group(made, name=label)
cmds.xform(grp, worldSpace=True, pivots=(0, 0, 0))
result = {"chunks": len(made)}
result
'''

CHECK_CODE = r'''
import maya.cmds as cmds
from maya_plugin.handlers import meshcheck as _meshcheck
CELL = 3.0
MAX_OUTSET = 0.5
kids = cmds.listRelatives("|" + LABEL, children=True, fullPath=True) or []
fails, tris, worst_outset, over_budget = [], 0, 0.0, []
for node in kids:
    short = node.split("|")[-1]
    shapes = cmds.listRelatives(node, shapes=True, fullPath=True) or []
    if not shapes:
        fails.append((short, "no shape")); continue
    stats = _meshcheck.mesh_stats(shapes[0])
    tris += stats["tris"]
    # Watertight is zero boundary / zero non-manifold edges (contract rev 2
    # section 4). Per-chunk Euler is NOT required and is not checked: a chunk
    # built from several closed boxes fails Euler while being perfectly closed.
    if stats["boundary_edges"]:
        fails.append((short, "open: %d boundary edges" % stats["boundary_edges"]))
    if stats["nonmanifold_edges"]:
        fails.append((short, "non-manifold"))
    if [round(s, 6) for s in cmds.getAttr(node + ".scale")[0]] != [1.0, 1.0, 1.0]:
        fails.append((short, "left-over scale"))
    try:
        parts = short.split("_")
        cx, cy, cz = (int(p[1:]) for p in parts[1:4])
    except Exception:
        fails.append((short, "name does not parse")); continue

    # The PIVOT is what must sit at the chunk's own centre - not the bounding
    # box centre, which now drifts whenever ornament oversails one face only.
    piv = cmds.xform(node, query=True, worldSpace=True, rotatePivot=True)
    bb = cmds.exactWorldBoundingBox(node)
    span = [round((bb[i + 3] - bb[i]) / CELL) for i in range(3)]
    want = [CELL * cx + CELL * (span[0] - 1) / 2.0,
            CELL * cy + CELL * (span[1] - 1) / 2.0,
            CELL * cz + CELL * (span[2] - 1) / 2.0]
    if any(abs(piv[i] - want[i]) > 0.55 for i in range(3)):
        fails.append((short, "pivot %s is not the chunk centre %s"
                      % ([round(p, 3) for p in piv], [round(w, 3) for w in want])))

    # Occupied CELLS must sit on the lattice; the mesh may leave that box by up
    # to MAX_OUTSET. Measured against the cell block the name declares.
    lo = [cx * CELL - CELL / 2.0, cy * CELL - CELL / 2.0, cz * CELL - CELL / 2.0]
    for i in range(3):
        out_lo = lo[i] - bb[i]
        out_hi = bb[i + 3] - (lo[i] + CELL * span[i])
        worst_outset = max(worst_outset, out_lo, out_hi)
        if out_lo > MAX_OUTSET + 1e-3 or out_hi > MAX_OUTSET + 1e-3:
            fails.append((short, "outset %.3f exceeds %.2f m"
                          % (max(out_lo, out_hi), MAX_OUTSET)))
            break

    cells = max(1, span[0] * span[1] * span[2])
    if stats["tris"] > 200 * cells:
        over_budget.append((short, stats["tris"], 200 * cells))

bb = cmds.exactWorldBoundingBox("|" + LABEL)
result = {"chunks": len(kids), "tris": tris, "fails": fails[:20],
          "fail_count": len(fails),
          "worst_outset": round(worst_outset, 4),
          "over_budget": over_budget[:10], "over_budget_count": len(over_budget),
          "bbox_min": [round(q, 3) for q in bb[:3]],
          "bbox_max": [round(q, 3) for q in bb[3:]]}
result
'''

EXPORT_CODE = maya_export.EXPORT_PREAMBLE + r'''
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

    occupied = set()
    for c in chunks:
        occupied.update(c.cells_occupied())
    chunk_dicts = []
    outsets = {}
    for c in chunks:
        boxes = chunk_boxes(c, occupied, b.storeys, b.palette)
        # Declared from the SAME boxes Maya is about to build, so the manifest
        # cannot drift from the mesh. The manifest entry drops `boxes` - 2,034
        # chunks of box lists would dwarf everything a consumer reads.
        outsets[c.name] = chunk_outset(boxes, c.sx, c.sy, c.sz)
        d = c.as_dict(outset_m=outsets[c.name])
        d["boxes"] = [dict(bx, patch=kit.PATCH[bx["patch"]][0]) for bx in boxes]
        chunk_dicts.append(d)

    payload = json.dumps({"label": label, "maps": MAPS,
                          "cols": kit.ATLAS_COLS, "rows": kit.ATLAS_ROWS,
                          "margin": 0.03, "world_scale": kit.WORLD_SCALE,
                          "chunks": chunk_dicts})
    ok(call("new_scene", {"confirm": True}, 300.0), "new_scene")
    run("SPEC = %r\nAUTHORING_UNIT = %r\nUV_PER_METRE = %r\n%s"
        % (payload, maya_export.AUTHORING_UNIT, maya_export.UV_PER_METRE,
           BUILD_CODE), "build %s" % label)
    check = ast.literal_eval(
        run("LABEL = %r\n%s" % (label, CHECK_CODE), "check %s" % label)["result_repr"])
    fbx = os.path.join(OUT_DIR, "%s.fbx" % label).replace("\\", "/")
    run("LABEL = %r\nFBX = %r\nEXPORT_SCALE_FACTOR = %r\n%s"
        % (label, fbx, maya_export.EXPORT_SCALE_FACTOR, EXPORT_CODE),
        "export %s" % label)

    # The artifact is the deliverable, so the artifact is what gets asserted.
    # An in-Maya check cannot see this class of defect at all: the scene reads
    # 3.0 m at scale [1,1,1] frozen and exports as 300.0 (maya-mcp #629).
    violations = delivery_units.check_delivery(fbx, delivery_units.HERO_CEILING_M)
    if violations:
        print("DELIVERY IS NOT METRE-TRUE - refusing to ship %s:" % fbx)
        for v in violations:
            print("    " + v)
        sys.exit(1)

    # 1.0 = a surface facing the key reads its own albedo (#617). The old
    # 1.5 was dialled in against images that were also 2.2 gamma too dark
    # (#615), so it is not a number worth converting - only re-judging.
    ok(call("setup_lighting", {"preset": "three_point", "intensity": 1.0,
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
    used = sorted({bx["patch"] for d in chunk_dicts for bx in d["boxes"]})
    return dict(
        name=label, archetype_footprint_cells=[b.nx, b.nz], storeys=b.storeys,
        palette=b.palette, patch_indices=used,
        footprint_by_storey=[list(b.foot(y)) for y in range(b.storeys)],
        size_m=size, bbox_min=check["bbox_min"], bbox_max=check["bbox_max"],
        chunks=check["chunks"], triangles=check["tris"],
        tris_per_chunk=round(check["tris"] / max(1, check["chunks"]), 1),
        roles=roles, frame_chunks=report["frame_chunks"],
        stilt_columns=report["stilts"], note=b.note,
        max_outset_m=round(max(outsets.values() or [0.0]), 4),
        files=["%s.fbx" % label, "%s.png" % label],
        chunk_list=[c.as_dict(outset_m=outsets[c.name]) for c in chunks],
    ), check, report, images.pixel_stats(png)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    # The heroes share the kit's atlas. Regenerating it here rather than
    # depending on the kit package having been built keeps this script
    # runnable on its own; the maps are deterministic, so it is the same file.
    global MAPS
    os.makedirs(KIT_DIR, exist_ok=True)
    MAPS = kit.build_atlas_maps(KIT_DIR)
    print("atlas %d px, %.1f px/m (shared with the kit)"
          % (kit.ATLAS_PX, kit.PX_PER_METRE))

    wanted = sys.argv[1:] or None
    entries, clean = [], True
    for label, builder, zoom in BUILDINGS:
        if wanted and label not in wanted:
            continue
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
        "material": hero_material_block(),
        "envelope": {
            "cell_m": CELL,
            "inset_m": INSET,
            "max_outset_m": MAX_OUTSET,
            "outset_note":
                "Ornament may oversail a chunk's cell block by up to 0.5 m, "
                "declared per chunk as outset_m. The lattice constrains which "
                "CELLS a chunk occupies, never its render mesh, because "
                "collision is generated from the grid.",
        },
        "destruction_unit":
            "A CHUNK is the unit of destruction - detach it whole, never "
            "subdivide it per cell. MAX_RUN is what tunes this: glass 1 so a "
            "pane cannot come off in pairs, steel 4 so the frame falls in "
            "large sections, brick/infill 2, concrete 4. Steel merges "
            "vertically; everything else along X, trying Z only when the X run "
            "was length 1.",
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
            "every chunk re-measured in-scene: ZERO BOUNDARY and zero "
            "non-manifold edges (not per-chunk Euler, which a box-built chunk "
            "fails while being perfectly closed), pivot at the chunk's own "
            "centre rather than its bounding-box centre (they differ once "
            "ornament oversails one face), occupied cells on 3 m boundaries "
            "with the mesh allowed 0.5 m past them, scale (1,1,1), name parses "
            "and agrees with measured position, triangles within 200 per cell",
        "deviations": [
            {"item": "corner spandrels",
             "what": "One cell beside each corner column is concrete, not "
                     "cladding.",
             "why": "A corner column's only two face-adjacent cells are both on "
                    "the perimeter ring. With cladding there it touches nothing "
                    "structural and is a stilt by your own definition. The "
                    "spandrel gives it a tie; the stilt count in the manifest "
                    "is the evidence."},
            {"item": "budget used, not exhausted",
             "what": "45-54 triangles per chunk against the 200 allowed.",
             "why": "Revision 1 spent 12. Detail is placed only on faces a "
                    "chunk can actually be SEEN from - interior and buried "
                    "frame chunks stay one box, because they are invisible "
                    "until the golem opens the building, at which point what "
                    "matters is that something came off, not its cornice. "
                    "Headroom remains if these want another pass."},
            {"item": "no curves",
             "what": "Every chunk is axis-aligned boxes; tapers are available "
                     "and used on the kit, not here.",
             "why": "A curve needs a cylinder segment and real triangles. The "
                    "bounds rule that forbade it is gone, so this is now a "
                    "budget choice rather than a constraint - worth revisiting "
                    "on a silhouette pass."},
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
