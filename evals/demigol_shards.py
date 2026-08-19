"""Demigol SHARD LIBRARY - fracture patterns, not buildings and not pieces.

Third delivery, after the hero buildings and the kit of parts. Contract:
Demigol `docs/superpowers/specs/2026-08-16-shard-library-contract.md`,
redmine #664.

A pattern is one 3 m cell PRE-SHATTERED. When the golem hits a wall the game
swaps that cell from its intact kit mesh to a pattern's worth of loose shards
and deletes the ones the impact reached, so the wall erodes at roughly 1 m
instead of a 3 m cube blinking out. The complaint this answers, verbatim from
the playtest: "the pieces of the houses are still those cubes right?"

WHERE THE WORK ACTUALLY IS. The geometry is in `shard_fracture.py`, deliberately
Maya-free, because the rule the contract rejects rather than flags - a pattern
must FILL its cell - is a mathematical property and not a thing to discover in a
viewport. There it is true by construction (a Voronoi seed set partitions the
box) and the audit measures the clipper rather than the design. This file is the
delivery around it: the second material, the UVs, the scene, the gate, the
proofs and the manifest.

THE TWO THINGS THAT DECIDED THE SHAPE OF THIS DELIVERY, both measured:

  * The kit's pieces are SOLID CELLS. `kit_glass_facade_a` is a full-cell body
    with a pane on the front, not a sheet of glass in empty air. That is what
    makes "the union fills 27 m3" and "assembled, it looks like the mesh it
    replaced" the same requirement instead of contradictory ones, and it is why
    the glass pattern shatters finely only in the front 0.4 m.
  * Only 9 of the 41 kit pieces oversail their cell at all, and the largest is
    0.34 m. So contract 1c's outset is delivered per role at the size the
    NEIGHBOURS actually have (brick 0.22, concrete 0.20, steel 0.24, glass 0.16,
    infill none) rather than at the 0.5 m allowance, and it is delivered as its
    own band shards so nothing else has to bend to carry it.

Run:  set MAYA_MCP_PORT=9878 && .venv/Scripts/python.exe evals/demigol_shards.py
Package: evals/demigol_shards/

9878, NOT 9877. This script opens with `new_scene`, and 9877 is the user's own
Maya session under the two-Maya policy (#577/#579): a `new_scene` there discards
whatever is open, and the last run of this generator found that session holding
an UNSAVED scene of 34 meshes. Launch a disposable Maya instead:

    MAYA_MCP_PORT=9878 "E:/Autodesk/Maya2027/bin/maya.exe" &
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

import delivery_units  # noqa: E402
import fbx_probe  # noqa: E402
import maya_export  # noqa: E402
import shard_fracture as sf  # noqa: E402
from live_call import call  # noqa: E402
from maya_mcp import images  # noqa: E402

OUT_DIR = os.path.join(_HERE, "demigol_shards")
KIT_DIR = os.path.join(_HERE, "demigol_kit")


# ------------------------------------------------ the submesh order, MEASURED
# #664 ask 3 wants the per-shard submesh order DECLARED. Declaring it from the
# builder would only restate an intention; what the consumer binds against is
# the FBX, so the manifest's claim is checked against the exported bytes.
#
# The plugin's reader (maya_plugin/handlers/fbxbytes.py) is deliberately not
# extended for this: it decodes only double arrays and knows nothing about
# materials, it is shared with the two earlier deliveries and their tests, and
# a delivery script is the wrong place from which to widen it. This walker is
# self-contained and reads nothing the units gate already reads.
_FBX_SCALARS = {b"Y": ("<h", 2), b"C": ("<?", 1), b"I": ("<i", 4),
                b"F": ("<f", 4), b"D": ("<d", 8), b"L": ("<q", 8)}
_FBX_ARRAYS = {b"f": ("f", 4), b"d": ("d", 8), b"l": ("q", 8),
               b"i": ("i", 4), b"b": ("b", 1)}


def _fbx_scan(path):
    """(materials, models, ordered connections, per-polygon material indices)."""
    import struct
    import zlib

    with open(path, "rb") as fh:
        data = fh.read()
    if not data.startswith(b"Kaydara FBX Binary"):
        raise ValueError("%s is not a binary FBX" % path)
    version = struct.unpack_from("<I", data, 23)[0]
    wide = version >= 7500
    off_fmt, off_size = ("<QQQ", 24) if wide else ("<III", 12)

    materials, models, connections, poly_mats = {}, {}, [], {}

    def prop(pos):
        code = data[pos:pos + 1]
        pos += 1
        if code in _FBX_SCALARS:
            fmt, size = _FBX_SCALARS[code]
            return struct.unpack_from(fmt, data, pos)[0], pos + size
        if code in (b"S", b"R"):
            n = struct.unpack_from("<I", data, pos)[0]
            pos += 4
            raw = data[pos:pos + n]
            return (raw.decode("utf-8", "replace") if code == b"S" else raw), pos + n
        if code in _FBX_ARRAYS:
            fmt, size = _FBX_ARRAYS[code]
            length, encoding, comp = struct.unpack_from("<III", data, pos)
            pos += 12
            payload = data[pos:pos + comp]
            pos += comp
            if encoding == 1:
                payload = zlib.decompress(payload)
            return list(struct.unpack("<%d%s" % (length, fmt), payload)), pos
        raise ValueError("unknown FBX typecode %r at %d" % (code, pos))

    def walk(pos, end, geometry_uid):
        while pos < end:
            end_off, nprops, _ = struct.unpack_from(off_fmt, data, pos)
            if end_off == 0:
                return pos + off_size + 1
            pos += off_size
            nlen = data[pos]
            pos += 1
            name = data[pos:pos + nlen].decode("utf-8", "replace")
            pos += nlen
            values = []
            for _ in range(nprops):
                val, pos = prop(pos)
                values.append(val)

            child_geo = geometry_uid
            if name in ("Model", "Material", "Geometry"):
                uid = values[0] if values and isinstance(values[0], int) else None
                strs = [v for v in values if isinstance(v, str)]
                label = strs[0].split("\x00")[0] if strs else "?"
                if name == "Model":
                    models[uid] = label
                elif name == "Material":
                    materials[uid] = label
                else:
                    child_geo = uid
            elif name == "C" and len(values) >= 3:
                connections.append((values[1], values[2]))
            elif name == "Materials" and geometry_uid is not None \
                    and isinstance(values[0], list):
                poly_mats[geometry_uid] = values[0]

            if pos < end_off:
                walk(pos, end_off, child_geo)
            pos = end_off
        return pos

    walk(27, len(data), None)
    return materials, models, connections, poly_mats


def interior_point(poly):
    """A point guaranteed INSIDE the shard, and how much room it has.

    Contract 6 makes `seed` the point the game samples its damage field at, and
    for 16 of 611 shards that point is not in the shard - up to 0.421 m outside
    it. Those are legal Voronoi seeds (a seed may sit outside the clip box and
    still own a cell inside it), so the self-check "every seed is its true
    Voronoi seed" was honestly satisfied and still useless to the consumer.

    Returned as a SEPARATE field rather than by correcting `seed`, because the
    contract asks for the true seed and the shell may want both: `seed` says
    where the cell's generator was, `sample_point` says where to sample.

    The radius is the largest sphere about that point that stays inside, so
    (sample_point, inscribed_radius_m) and (seed, bound_radius_m) BRACKET the
    shard - one never over-reaches, the other never misses.
    """
    tris = [t for f in poly.faces for t in sf.triangulate(f["loop"], poly.verts)]

    def clearance(p):
        if not _inside(p, poly.verts, tris):
            return -1.0
        return min(_point_triangle_distance(p, poly.verts[t[0]], poly.verts[t[1]],
                                            poly.verts[t[2]]) for t in tris)

    # Candidates: the vertex average, then a coarse grid over the AABB. The
    # average is interior for a convex body and usually for these unions, but
    # "usually" is what the 16 seeds were, so it is never trusted - only
    # measured.
    n = float(len(poly.verts))
    best = tuple(sum(v[k] for v in poly.verts) / n for k in range(3))
    score = clearance(best)
    lo = [min(v[k] for v in poly.verts) for k in range(3)]
    hi = [max(v[k] for v in poly.verts) for k in range(3)]
    for i in range(1, 6):
        for j in range(1, 6):
            for k in range(1, 6):
                q = (lo[0] + (hi[0] - lo[0]) * i / 6.0,
                     lo[1] + (hi[1] - lo[1]) * j / 6.0,
                     lo[2] + (hi[2] - lo[2]) * k / 6.0)
                c = clearance(q)
                if c > score:
                    best, score = q, c
    if score <= 0.0:
        raise AssertionError("no interior point found for a shard - the shell "
                             "would have nowhere to sample")
    # local refinement: shrink steps around the winner
    step = max(hi[k] - lo[k] for k in range(3)) / 6.0
    for _ in range(6):
        moved = False
        for axis in range(3):
            for sign in (+1, -1):
                q = list(best)
                q[axis] += sign * step
                c = clearance(tuple(q))
                if c > score:
                    best, score, moved = tuple(q), c, True
        if not moved:
            step *= 0.5
    return best, score


BITE_STRIKE = (0.35, -0.25, 1.5)
BITE_RADIUS = 1.15


def _point_triangle_distance(p, a, b, c):
    """Shortest distance from a point to a triangle. Ericson, region tables."""
    ab, ac, ap = sf.sub(b, a), sf.sub(c, a), sf.sub(p, a)
    d1, d2 = sf.dot(ab, ap), sf.dot(ac, ap)
    if d1 <= 0 and d2 <= 0:
        return sf.norm(ap)
    bp = sf.sub(p, b)
    d3, d4 = sf.dot(ab, bp), sf.dot(ac, bp)
    if d3 >= 0 and d4 <= d3:
        return sf.norm(bp)
    vc = d1 * d4 - d3 * d2
    if vc <= 0 and d1 >= 0 and d3 <= 0:
        v = d1 / (d1 - d3) if d1 != d3 else 0.0
        return sf.norm(sf.sub(p, sf.add(a, sf.mul(ab, v))))
    cp = sf.sub(p, c)
    d5, d6 = sf.dot(ab, cp), sf.dot(ac, cp)
    if d6 >= 0 and d5 <= d6:
        return sf.norm(cp)
    vb = d5 * d2 - d1 * d6
    if vb <= 0 and d2 >= 0 and d6 <= 0:
        w = d2 / (d2 - d6) if d2 != d6 else 0.0
        return sf.norm(sf.sub(p, sf.add(a, sf.mul(ac, w))))
    va = d3 * d6 - d5 * d4
    if va <= 0 and (d4 - d3) >= 0 and (d5 - d6) >= 0:
        w = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        return sf.norm(sf.sub(p, sf.add(b, sf.mul(sf.sub(c, b), w))))
    denom = 1.0 / (va + vb + vc)
    v, w = vb * denom, vc * denom
    return sf.norm(sf.sub(p, sf.add(a, sf.add(sf.mul(ab, v), sf.mul(ac, w)))))


def _inside(p, verts, tris):
    """Ray parity along +X. Only ever asked about closed shells."""
    hits = 0
    for t in tris:
        a, b, c = (verts[i] for i in t)
        if (a[1] > p[1]) == (b[1] > p[1]) == (c[1] > p[1]):
            continue
        # Moller-Trumbore against the +X ray
        e1, e2 = sf.sub(b, a), sf.sub(c, a)
        h = sf.cross((1.0, 0.0, 0.0), e2)
        det = sf.dot(e1, h)
        if abs(det) < 1e-12:
            continue
        s = sf.sub(p, a)
        u = sf.dot(s, h) / det
        if u < 0.0 or u > 1.0:
            continue
        q = sf.cross(s, e1)
        v = sf.dot((1.0, 0.0, 0.0), q) / det
        if v < 0.0 or u + v > 1.0:
            continue
        if sf.dot(e2, q) / det > 1e-9:
            hits += 1
    return hits % 2 == 1


def measure_bite_rules(entries, patterns):
    """The same strike, scored three ways, per role. Pure arithmetic.

    `seed` is the rule the shell runs today: |seed - strike| <= radius.
    `bound` adds the shard's own extent: <= radius + bound_radius_m.
    `solid` is GROUND TRUTH - the strike sphere really reaches the shard.

    The first draft of this used the shard's AABB as ground truth and it was
    wrong in a way worth keeping written down: an AABB is a SUPERSET of the
    shard, so it counted hits on empty corner space and made the conservative
    `bound` rule look like it MISSED three concrete shards. A bounding volume
    cannot be the ground truth for a test about bounding volumes. This measures
    the real surface - point-to-triangle distance over every face, plus an
    inside test so a sphere buried in a large shard still counts.

    `bound` is a superset of `solid` BY CONSTRUCTION (the bounding sphere
    contains the shard), so bound < solid would mean an arithmetic error rather
    than a design trade-off. It is asserted, not assumed.
    """
    geom = {}
    for p in patterns:
        for m in p["meshes"]:
            verts = [tuple(v) for v in m["verts"]]
            tris = m["tris"]
            d = min(_point_triangle_distance(BITE_STRIKE, verts[t[0]],
                                             verts[t[1]], verts[t[2]])
                    for t in tris)
            geom[m["name"]] = (d <= BITE_RADIUS
                               or _inside(BITE_STRIKE, verts, tris))

    out = {}
    for role in sf.ROLES:
        rows = [e for e in entries if e["role"] == role and not e["ornament"]]
        seed = bound = solid = 0
        for e in rows:
            d = sf.norm(sf.sub(tuple(e["seed"]), BITE_STRIKE))
            hit_bound = d <= BITE_RADIUS + e["bound_radius_m"]
            hit_solid = geom[e["name"]]
            if hit_solid and not hit_bound:
                raise AssertionError(
                    "%s: the strike reaches the shard but the bounding-sphere "
                    "rule missed it - bound_radius_m is wrong" % e["name"])
            seed += 1 if d <= BITE_RADIUS else 0
            bound += 1 if hit_bound else 0
            solid += 1 if hit_solid else 0
        out[role] = {"shards": len(rows), "seed": seed, "bound": bound,
                     "solid": solid}
    return out


def verify_submesh_order(path, entries):
    """Prove the manifest's `submeshes` array is what the FBX actually says.

    Two independent things are checked, because either alone can be true while
    the delivery is wrong:

    1. The ORDER of material connections on each model - that is what becomes
       submesh 0, 1 on import.
    2. The per-polygon material indices - that the faces claimed for the
       building atlas really carry index 0 (or, on a single-material shard,
       that every face carries the one index there is).

    Returns (rows, failures).
    """
    materials, models, connections, poly_mats = _fbx_scan(path)
    per_model, geo_of = {}, {}
    for child, parent in connections:
        if child in materials and parent in models:
            per_model.setdefault(parent, []).append(materials[child])
        elif child in poly_mats and parent in models:
            geo_of[parent] = child

    by_name = {}
    for uid, label in models.items():
        if label in by_name:
            continue
        by_name[label] = uid

    fails, seen = [], 0
    for e in entries:
        uid = by_name.get(e["name"])
        if uid is None:
            fails.append("%s: no Model in the FBX" % e["name"])
            continue
        seen += 1
        got = per_model.get(uid, [])
        if got != e["submeshes"]:
            fails.append("%s: FBX submesh order %s, manifest says %s"
                         % (e["name"], got, e["submeshes"]))
            continue
        indices = poly_mats.get(geo_of.get(uid), [])
        want = e["triangles_per_submesh"]
        if len(indices) == 1:
            continue                        # AllSame mapping, one material
        if len(indices) != sum(want):
            fails.append("%s: %d per-polygon material indices, %d triangles"
                         % (e["name"], len(indices), sum(want)))
            continue
        expect = [slot for slot, n in enumerate(want) for _ in range(n)]
        if indices != expect:
            first = next(k for k, (a, b) in enumerate(zip(indices, expect))
                         if a != b)
            fails.append("%s: polygon %d carries material %d, expected %d"
                         % (e["name"], first, indices[first], expect[first]))
    return {"models_matched": seen, "shards": len(entries),
            "materials_in_file": sorted(set(materials.values())),
            "failures": len(fails)}, fails

# ------------------------------------------------------------- the two atlases
# 1. The BUILDING atlas is the kit's, unchanged and not re-authored: a shard
#    face that was part of the original outer surface has to line up with the
#    intact cells beside it, which means the same atlas, the same patch and the
#    same texel density. Its three maps are copied into this package so the
#    delivery renders standalone; they are byte copies, not a second authority.
# 2. The FRACTURE atlas is new, and it is what contract 5b asks for: the
#    freshly-broken faces are the majority of every shard's surface and the kit
#    atlas is 16/16 full with nowhere to put them.
KIT_ATLAS_PX, KIT_COLS, KIT_ROWS = 4096, 4, 4
KIT_WORLD_SCALE = 9.0            # the kit's own, so density matches exactly
KIT_PATCH = {"brick": 0, "concrete": 2, "steel": 4, "glass": 6, "infill": 8,
             # the game lays roof decks as STEEL and dresses them as concrete
             # plate (#611 rule S3b), so a deck's surviving outer face must
             # match the concrete cells it sits among, not the steel ones.
             "deck": 2}

FRAC_PX, FRAC_COLS, FRAC_ROWS = 4096, 4, 4
FRAC_PATCH_PX = FRAC_PX // FRAC_COLS
MARGIN = 0.03

# index, albedo rgb, style, metallic, smoothness
FRACTURE = {
    "concrete_core":   (0,  (150, 146, 138), "aggregate", 0.0, 0.16),
    "concrete_dark":   (1,  (108, 105, 99),  "aggregate", 0.0, 0.13),
    "concrete_coarse": (2,  (163, 158, 147), "coarse",    0.0, 0.18),
    "brick_core":      (3,  (152, 78, 54),   "clay",      0.0, 0.15),
    "brick_dark":      (4,  (112, 57, 40),   "clay",      0.0, 0.12),
    "mortar":          (5,  (178, 172, 160), "mortar",    0.0, 0.10),
    "infill_core":     (6,  (208, 203, 190), "board",     0.0, 0.20),
    "infill_dark":     (7,  (156, 151, 140), "board",     0.0, 0.17),
    "glass_edge":      (8,  (176, 206, 208), "glassedge", 0.0, 0.93),
    "glass_green":     (9,  (146, 186, 180), "glassedge", 0.0, 0.95),
    "steel_torn":      (10, (176, 182, 190), "torn",      1.0, 0.55),
    "steel_dark":      (11, (126, 132, 142), "torn",      1.0, 0.44),
    "rebar":           (12, (122, 68, 40),   "rust",      0.9, 0.22),
    "rust":            (13, (128, 74, 44),   "rust",      0.8, 0.18),
    "board_dark":      (14, (132, 126, 114), "board",     0.0, 0.14),
    "grime":           (15, (78, 76, 71),    "coarse",    0.0, 0.09),
}

# Which fracture patches a role's broken faces may draw from. A single patch per
# role would make every fracture surface in the city identical; the shard picks
# one deterministically from its own name, so a punched wall shows a spread of
# broken concrete rather than one repeated swatch.
FRACTURE_FOR = {
    "concrete": ("concrete_core", "concrete_dark", "concrete_coarse"),
    "brick": ("brick_core", "brick_dark", "mortar"),
    "infill": ("infill_core", "infill_dark", "board_dark"),
    "glass": ("glass_edge", "glass_green"),
    "steel": ("steel_torn", "steel_dark", "rust"),
    "deck": ("concrete_core", "concrete_dark", "concrete_coarse"),
}

# Relative weight of each patch above. Absent => equal weights.
#
# Steel is weighted because an even pick put `rust` on 35% of freshly TORN
# sections (measured: torn 16, rust 14, dark 10 of 40), and rust is what
# already-exposed steel looks like - a section opened a second ago should be
# bright bare metal. Dropped to 10% by the contract owner's call: enough to
# break up a grey block and read as decayed plant, not enough to claim every
# third tear is old.
FRACTURE_WEIGHTS = {
    "steel": {"steel_torn": 0.55, "steel_dark": 0.35, "rust": 0.10},
}


def pick_fracture(role, rng):
    """Weighted deterministic patch choice. Equal weights unless declared."""
    keys = FRACTURE_FOR[role]
    weights = FRACTURE_WEIGHTS.get(role)
    if not weights:
        return rng.pick(keys)
    total = sum(weights[k] for k in keys)
    t = rng.uniform(0.0, total)
    for k in keys:
        t -= weights[k]
        if t <= 0.0:
            return k
    return keys[-1]
REBAR_PATCH = "rebar"

# The two material names, in one place, because the manifest now DECLARES the
# per-shard submesh order (#664 ask 3) and a name that disagrees between the
# scene and the manifest is exactly the silent-mismatch class that field exists
# to close.
BUILDING_MATERIAL = "shard_building"
FRACTURE_MATERIAL = "shard_fracture"

# Budgets (contract 5a). Reported as utilisation, not as a pass mark. The
# per-shard cap is PER ROLE: steel is 200 by the contract owner's decision on
# #664 - see shard_fracture.TRI_CAP for the measurement behind it.
TRI_PER_PATTERN = sf.TRI_CAP_PATTERN

REBAR_UV_SCALE = 0.35            # a 0.3 m stub, projected about its own base


# --------------------------------------------------------------- the new atlas
def build_fracture_atlas(out_dir):
    """Albedo, normal and metallic/smoothness for the freshly-broken faces.

    Same three-maps-one-layout discipline as the kit, for the same reason: one
    extra draw call for the whole city and not one more. The styles are the
    materials' fracture behaviour rather than their weathered face - broken
    concrete shows aggregate the outer surface never does, snapped brick shows
    clay body that is brighter than its own weathered face, and torn steel
    shows bright drawn metal.
    """
    import numpy as np
    from PIL import Image

    px, cell = FRAC_PX, FRAC_PATCH_PX
    albedo = np.zeros((px, px, 3), np.float32)
    height = np.zeros((px, px), np.float32)
    metal = np.zeros((px, px), np.float32)
    smooth = np.zeros((px, px), np.float32)
    yy, xx = np.mgrid[0:cell, 0:cell].astype(np.float32)

    def blobs(rng, density, size, sharpness=6.0):
        """Rounded lumps - the shape aggregate and clay grog actually make.

        Value noise upscaled and blurred, then pushed through a soft threshold.
        Per-pixel noise was the kit's mistake and it is the same mistake here:
        it reads as dither and it is a PNG compressor's worst case.

        THE UPSCALE IS BICUBIC, and that is not a detail. The first version
        block-repeated the coarse grid and leaned on two box blurs to hide the
        steps, which works when a cell is 6 px and does not when it is 26: the
        rendered aggregate came out as a visible CHECKERBOARD of square tiles,
        not as stones. Blur cannot remove a step it is narrower than.
        """
        n = max(4, int(cell / size))
        coarse = rng.random((n, n), dtype=np.float32)
        f = np.asarray(
            Image.fromarray(coarse).resize((cell, cell), Image.BICUBIC),
            dtype=np.float32)
        for _ in range(2):
            f = (f + np.roll(f, 1, 0) + np.roll(f, -1, 0)
                 + np.roll(f, 1, 1) + np.roll(f, -1, 1)) / 5.0
        return 1.0 / (1.0 + np.exp(-(f - density) * sharpness * 4.0))

    for _name, (index, rgb, style, mtl, smt) in FRACTURE.items():
        col, row = index % FRAC_COLS, index // FRAC_COLS
        x0, y0 = col * cell, row * cell
        rng = np.random.default_rng(7000 + index)

        fine = blobs(rng, 0.5, 6)
        k = 1.0 + (fine - 0.5) * 0.10
        h = 0.5 + (fine - 0.5) * 0.10

        if style in ("aggregate", "coarse"):
            # stones sitting proud of a matrix, which is what a fracture through
            # concrete exposes: the crack runs round the aggregate, not through it
            big = blobs(rng, 0.56, 26 if style == "aggregate" else 46, 9.0)
            mid = blobs(rng, 0.52, 13, 8.0)
            stone = np.clip(big + mid * 0.55, 0.0, 1.0)
            # Wide contrast on purpose. A fracture through concrete is the one
            # surface in the delivery that has to sell "this is rubble, not a
            # grey polygon", and the stones only read if they are clearly
            # lighter than the matrix they sit in.
            k = k * (0.76 + 0.48 * stone)
            h = 0.28 + 0.62 * stone + (fine - 0.5) * 0.08
        elif style == "clay":
            # a snapped brick is a conchoidal face: broad shallow steps
            step = blobs(rng, 0.5, 34, 3.0)
            k = k * (0.90 + 0.20 * step)
            h = 0.40 + 0.34 * step
        elif style == "mortar":
            k = k * (0.94 + 0.12 * blobs(rng, 0.5, 9, 5.0))
            h = 0.30 + 0.24 * fine
        elif style == "board":
            # crushed board/plaster: fibrous, directional, low relief
            fib = np.repeat(rng.random((cell, 1), dtype=np.float32), cell, axis=1)
            fib = (fib + np.roll(fib, 3, 0) + np.roll(fib, -3, 0)) / 3.0
            k = k * (0.93 + 0.14 * fib)
            h = 0.44 + 0.16 * fib
        elif style == "glassedge":
            # a glass fracture is nearly featureless, with hackle lines running
            # away from the origin - almost flat, and that is the whole read
            band = np.sin(xx * 0.06 + yy * 0.013) * 0.5 + 0.5
            hackle = (np.abs(((xx * 0.9 + yy * 0.35) % 190.0) - 95.0) < 3.0)
            k = k * (0.97 + 0.06 * band)
            k = np.where(hackle, k * 1.10, k)
            h = np.where(hackle, 0.62, 0.5 + (band - 0.5) * 0.06)
        elif style == "torn":
            # drawn metal: the tear necks down and leaves striations along it
            stri = rng.random((1, cell), dtype=np.float32)
            stri = np.repeat(stri, cell, axis=0)
            for _ in range(2):
                stri = (stri + np.roll(stri, 1, 1) + np.roll(stri, -1, 1)) / 3.0
            neck = np.clip(1.0 - np.abs(yy / float(cell) - 0.5) * 1.6, 0.0, 1.0)
            k = k * (0.88 + 0.26 * stri) * (0.92 + 0.16 * neck)
            h = 0.42 + 0.30 * stri
        elif style == "rust":
            scale = blobs(rng, 0.5, 18, 7.0)
            pit = blobs(rng, 0.72, 7, 10.0)
            k = k * (0.82 + 0.32 * scale) * (1.0 - 0.30 * pit)
            h = 0.46 + 0.28 * scale - 0.30 * pit

        albedo[y0:y0 + cell, x0:x0 + cell] = np.stack(
            [np.clip(k * c, 0, 255) for c in rgb], axis=-1)
        height[y0:y0 + cell, x0:x0 + cell] = np.clip(h, 0.0, 1.0)
        metal[y0:y0 + cell, x0:x0 + cell] = mtl
        smooth[y0:y0 + cell, x0:x0 + cell] = smt

    # Gradients are edge-clamped and the patch borders flattened, exactly as in
    # the kit: a normal that leaks across a patch seam draws a bright line on an
    # unrelated material.
    gx, gy = np.zeros_like(height), np.zeros_like(height)
    gx[:, 1:-1] = (height[:, 2:] - height[:, :-2]) * 0.5
    gy[1:-1, :] = (height[2:, :] - height[:-2, :]) * 0.5
    for edge in range(0, FRAC_PX + 1, FRAC_PATCH_PX):
        for arr in (gx, gy):
            arr[max(0, edge - 1):edge + 1, :] = 0.0
            arr[:, max(0, edge - 1):edge + 1] = 0.0

    strength = 3.0
    nx, ny = -gx * strength, -gy * strength
    nz = np.ones_like(nx)
    length = np.sqrt(nx * nx + ny * ny + nz * nz)
    normal = ((np.stack([nx / length, ny / length, nz / length], axis=-1)
               * 0.5) + 0.5) * 255.0

    paths = {}
    paths["albedo"] = os.path.join(out_dir, "fracture_albedo.png").replace("\\", "/")
    Image.fromarray(albedo.astype(np.uint8), "RGB").save(paths["albedo"])
    paths["normal"] = os.path.join(out_dir, "fracture_normal.png").replace("\\", "/")
    Image.fromarray(normal.astype(np.uint8), "RGB").save(paths["normal"])
    mask = np.stack([metal * 255.0, np.clip(smooth, 0, 1) * 255.0,
                     np.zeros_like(metal), np.clip(smooth, 0, 1) * 255.0],
                    axis=-1)
    paths["mask"] = os.path.join(out_dir, "fracture_mask.png").replace("\\", "/")
    Image.fromarray(mask.astype(np.uint8), "RGBA").save(paths["mask"])
    return paths


def kit_maps():
    """The kit's three maps, REFERENCED where they live - never copied.

    They used to be byte copies, so the package rendered standalone. That was
    the wrong trade and #664 ask 4 says so, for three reasons in order of
    weight. Vendored as its own copies the delivery gets its own material and
    its own 4096 atlas set, so shard debris would NOT BATCH with the kit
    buildings it broke out of and ~40 MB of texture would be resident twice.
    Second, a kit re-author leaves the copies silently stale and nothing fails.
    Third, ~7 MB off the package.

    The manifest declares `shared_with: demigol_kit` instead, which is the shape
    the heroes delivery already uses, so the consumer resolves one material for
    the kit wall and the shard that came off it.

    The maps are still read HERE, because the proof renders have to show the
    real surface - a proof of a two-material split rendered against a stand-in
    proves nothing. Reading them and not shipping them is the whole point.
    """
    out = {}
    for kind, name in (("albedo", "kit_albedo.png"), ("normal", "kit_normal.png"),
                       ("mask", "kit_mask.png")):
        src = os.path.join(KIT_DIR, name)
        if not os.path.exists(src):
            print("MISSING KIT MAP %s - the building atlas is the kit's and "
                  "this delivery does not re-author it" % src)
            sys.exit(1)
        out[kind] = src.replace("\\", "/")
    return out


def drop_stale_kit_copies(out_dir):
    """Remove the byte copies a previous revision of this generator shipped."""
    gone = []
    for name in ("kit_albedo.png", "kit_normal.png", "kit_mask.png"):
        path = os.path.join(out_dir, name)
        if os.path.exists(path):
            os.remove(path)
            gone.append(name)
    if gone:
        print("dropped %d stale kit byte-copies: %s" % (len(gone), ", ".join(gone)))


# ------------------------------------------------------------------------- UVs
# Every projection that left its patch, with how far. A clamp on its own would
# make an out-of-range UV LOOK correct while quietly stacking texels on the
# patch edge - and the edge of a patch is the next material along. The clamp is
# still applied so a bad run produces something inspectable, but the excursion
# is recorded and the run fails on it.
UV_EXCURSION = []


def _patch_uv(u, v, index, cols, rows, where=""):
    """Place a 0..1 pair inside one atlas patch, inside the margin."""
    if not (0.0 <= u <= 1.0 and 0.0 <= v <= 1.0):
        UV_EXCURSION.append((where, round(u, 4), round(v, 4)))
    # THE V FLIP, and it is not cosmetic. Both atlases are written with numpy,
    # whose row 0 is the TOP of the PNG, and both are indexed row-major from
    # the top-left because that is how the image reads in a viewer. UV v = 0 is
    # the BOTTOM. Without this line every patch samples its vertical mirror:
    # measured on the first full run, glass drew the amber warning patch, steel
    # drew infill, infill drew steel and brick's fractures came out pale blue.
    # Nothing caught it - the UVs were inside 0..1, the triangles were in
    # budget, the shells were closed and all 611 shards passed every gate while
    # every single one of them wore the wrong material. Only the contact sheet
    # showed it.
    col, row = index % cols, (rows - 1) - (index // cols)
    u = MARGIN + max(0.0, min(1.0, u)) * (1.0 - 2.0 * MARGIN)
    v = MARGIN + max(0.0, min(1.0, v)) * (1.0 - 2.0 * MARGIN)
    return ((col + u) / cols, (row + v) / rows)


def stable_hash(*parts):
    """FNV-1a. `hash()` is salted per process, so it cannot seed a delivery."""
    h = 0xcbf29ce484222325
    for part in parts:
        for byte in str(part).encode("utf-8") + b"\x1f":
            h = ((h ^ byte) * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
    return h


def face_uvs(poly, face, surface, role, patch_index, interior_scale):
    """One UV per face-vertex.

    Outer faces project in WORLD space at the kit's own 9 m per patch, because
    they have to line up with the intact cells beside them - a broken brick cell
    whose surviving face carries a different course pitch from its neighbour is
    worse than no texture at all.

    Broken faces project LOCALLY, about the face's own centre, on a basis built
    from its normal. Two reasons, and the second is the one that matters: a
    world projection would stretch badly on faces near-parallel to its axis, and
    a fracture face has no continuity to preserve - it did not exist a moment
    ago. Local projection also bounds the UV range, which is what lets the scale
    be pushed for density instead of being sized by the worst case.
    """
    pts = [poly.verts[i] for i in face["loop"]]
    if surface == "outer":
        n = sf.face_normal(poly, face)
        axis = max(range(3), key=lambda a: abs(n[a]))
        a1, a2 = [a for a in range(3) if a != axis]
        return [_patch_uv(p[a1] / KIT_WORLD_SCALE + 0.5,
                          p[a2] / KIT_WORLD_SCALE + 0.5,
                          patch_index, KIT_COLS, KIT_ROWS,
                          "%s outer" % role) for p in pts]
    c = sf.mul((sum(p[0] for p in pts), sum(p[1] for p in pts),
                sum(p[2] for p in pts)), 1.0 / len(pts))
    n = sf.face_normal(poly, face)
    t = sf.unit(sf._any_perp(n))
    b = sf.cross(n, t)
    scale = REBAR_UV_SCALE if surface == "rebar" else interior_scale
    return [_patch_uv(sf.dot(sf.sub(p, c), t) / scale + 0.5,
                      sf.dot(sf.sub(p, c), b) / scale + 0.5,
                      patch_index, FRAC_COLS, FRAC_ROWS,
                      "%s %s" % (role, surface)) for p in pts]


def surface_of(face):
    tag = face["tag"][0]
    return {"box": "outer", "cut": "interior", "rebar": "rebar"}[tag]


def interior_scales():
    """Per-role UV scale for broken faces, DERIVED from the geometry.

    A fixed number here would be a number that silently stops fitting the first
    time a seed distribution changes, and the failure would be UVs walking out
    of their patch into a neighbouring material. This measures the widest broken
    face each role actually produces and sizes the projection to it, so the
    texel density in the manifest is a consequence of the shapes rather than a
    hope about them. It also means the roles do not share a worst case: concrete
    breaks small and gets the finest aggregate.
    """
    worst = {r: 0.0 for r in sf.ROLES}
    for role in sf.ROLES:
        for variant in sf.VARIANTS:
            for shard in sf.build_pattern(role, variant):
                p = shard["poly"]
                for f in p.faces:
                    if surface_of(f) != "interior":
                        continue
                    pts = [p.verts[i] for i in f["loop"]]
                    c = sf.mul((sum(q[0] for q in pts), sum(q[1] for q in pts),
                                sum(q[2] for q in pts)), 1.0 / len(pts))
                    worst[role] = max(worst[role],
                                      2.0 * max(sf.norm(sf.sub(q, c)) for q in pts))
    # 0.85 leaves the projection inside the patch with room for the margin
    return {r: round(w / 0.85 + 0.049, 1) for r, w in worst.items()}


# ------------------------------------------------------------------- the spec
def shard_name(role, variant, index):
    return "shard_%s_%s_%02d" % (role, variant, index)


def parse_name(name):
    parts = name.split("_")
    if len(parts) != 4 or parts[0] != "shard":
        return None
    if parts[1] not in sf.ROLES or parts[2] not in sf.VARIANTS:
        return None
    if len(parts[3]) != 2 or not parts[3].isdigit():
        return None
    return parts[1], parts[2], int(parts[3])


def build_spec(scales):
    """Every shard, fully resolved: triangles, UVs, material split, manifest row.

    Triangles are emitted here rather than left as n-gons for the exporter to
    split, and that is deliberate for the steel: a warped tear wall is not
    planar, two sections share it, and if each side is triangulated
    independently they can disagree and open a crack down the middle of a
    section. `shard_fracture.triangulate` fans from the loop's lowest vertex, so
    both sides pick the same apex and the surfaces match exactly.
    """
    patterns, entries = [], []
    for role in sf.ROLES:
        for variant in sf.VARIANTS:
            shards = sf.build_pattern(role, variant)
            meshes = []
            for index, shard in enumerate(shards):
                name = shard_name(role, variant, index)
                poly = shard["poly"]
                rng = sf.Rng(stable_hash(role, variant, index))
                frac_key = pick_fracture(role, rng)
                frac_patch = FRACTURE[frac_key][0]

                # material 0 = the building atlas, material 1 = the fracture
                # atlas. Triangles are emitted grouped so the scene can assign
                # each material to one contiguous face range.
                tris = {0: [], 1: []}
                uvs = {0: [], 1: []}
                for f in poly.faces:
                    surface = surface_of(f)
                    if surface == "outer" and not shard.get("ornament"):
                        slot, patch = 0, KIT_PATCH[role]
                    elif surface == "outer":
                        # the band's own outward faces are building surface too
                        slot, patch = 0, KIT_PATCH[role]
                    elif surface == "rebar":
                        slot, patch = 1, FRACTURE[REBAR_PATCH][0]
                    else:
                        slot, patch = 1, frac_patch
                    uv = face_uvs(poly, f, surface, role, patch, scales[role])
                    pos = {v: k for k, v in enumerate(f["loop"])}
                    for tri in sf.triangulate(f["loop"], poly.verts):
                        tris[slot].append(tri)
                        uvs[slot].extend(uv[pos[i]] for i in tri)

                verts = [[round(q, 6) for q in v] for v in poly.verts]
                flat = tris[0] + tris[1]
                # The submesh order the consumer will see, stated rather than
                # left to be inferred (#664 ask 3). 576 of 611 shards carry both
                # materials and 35 are fully interior and carry ONE - so
                # materials[0] means shard_building on most shards and
                # shard_fracture on the rest, and a consumer that assumes index
                # 0 is always the building atlas puts the fracture texture on
                # the outside of 35 shards with nothing failing. That is the
                # same shape as #596 (626 catalog entries silently bound to
                # another building's mesh) and #630 (a 4096 atlas silently
                # importing at 2048): individually valid data, one wrong global
                # assumption, no error. VERIFIED against the exported FBX by
                # `verify_submesh_order`, not asserted from this code.
                submeshes = ([BUILDING_MATERIAL] if tris[0] else []) \
                    + ([FRACTURE_MATERIAL] if tris[1] else [])
                meshes.append({
                    "name": name,
                    "verts": verts,
                    "tris": [list(t) for t in flat],
                    "uvs": [[round(u, 6), round(v, 6)]
                            for u, v in (uvs[0] + uvs[1])],
                    "split": len(tris[0]),      # first N triangles = atlas 0
                    "submeshes": submeshes,
                })

                sample_pt, inscribed = interior_point(poly)
                _tris = [t for f in poly.faces
                         for t in sf.triangulate(f["loop"], poly.verts)]
                seed_inside = _inside(tuple(shard["seed"]), poly.verts, _tris)

                cell_body = shard.get("cell") or poly
                entries.append({
                    "name": name, "role": role, "variant": variant,
                    "index": index,
                    "seed": [round(q, 6) for q in shard["seed"]],
                    "seed_members": [[round(q, 6) for q in m]
                                     for m in shard["seed_members"]],
                    "volume_m3": round(sf.volume(cell_body), 6),
                    "triangles": len(flat),
                    "outset_m": round(shard.get("outset", 0.0), 4),
                    "surface": ("outer" if any(surface_of(f) == "outer"
                                               for f in poly.faces)
                                else "interior"),
                    "convex": bool(sf.is_convex(poly)),
                    # What it takes to test a SHARD rather than a POINT. The
                    # delivered `seed` is one point; a shard is up to 4.7 m3 of
                    # solid around it, and `|seed - strike| <= radius` therefore
                    # misses shards the strike plainly touches - measured below
                    # in bite_proof.rules, and worst on exactly the biggest
                    # shards. `|seed - strike| <= radius + bound_radius_m` is
                    # the sphere-sphere form and never misses one.
                    "bound_radius_m": round(
                        max(sf.norm(sf.sub(v, shard["seed"]))
                            for v in poly.verts), 5),
                    "sample_point": [round(q, 6) for q in sample_pt],
                    "inscribed_radius_m": round(inscribed, 5),
                    "seed_inside": bool(seed_inside),
                    "aabb": [[round(min(v[k] for v in poly.verts), 5)
                              for k in range(3)],
                             [round(max(v[k] for v in poly.verts), 5)
                              for k in range(3)]],
                    "submeshes": submeshes,
                    "triangles_per_submesh": [n for n in (len(tris[0]),
                                                          len(tris[1])) if n],
                    "rebar_stubs": shard.get("rebar_stubs", 0),
                    "ornament": bool(shard.get("ornament")),
                    "fracture_patch": frac_key,
                })
            patterns.append({"role": role, "variant": variant,
                             "meshes": meshes,
                             "audit": sf.audit_pattern(role, variant, shards)})
    return patterns, entries


# ------------------------------------------------------------- maya bridge
def ok(resp, what):
    if resp.get("status") != "ok":
        print("FAILED %s: %s" % (what, json.dumps(resp.get("error", resp))[:600]))
        sys.exit(1)
    return resp["result"]


def run(code, what, timeout=3600.0):
    out = ok(call("execute_python", {"code": code}, timeout), what)
    if out.get("traceback"):
        print("PYTHON FAILED (%s):\n%s" % (what, out["traceback"][:2500]))
        sys.exit(1)
    return out


BUILD_CODE = r'''
import json
import maya.cmds as cmds
import maya.api.OpenMaya as om

with open(SPEC_PATH) as fh:
    spec = json.load(fh)

cmds.currentUnit(linear=AUTHORING_UNIT)


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
    place = cmds.shadingNode("place2dTexture", asUtility=True, name=name + "_p")
    for a, b in (("coverage", "coverage"), ("repeatUV", "repeatUV"),
                 ("offset", "offset"), ("outUV", "uvCoord"),
                 ("outUvFilterSize", "uvFilterSize")):
        try:
            cmds.connectAttr(place + "." + a, node + "." + b, force=True)
        except Exception:
            pass
    return node


def _material(label, maps):
    shader = cmds.shadingNode("standardSurface", asShader=True, name=label)
    cmds.setAttr(shader + ".base", 1.0)
    sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True,
                   name=label + "SG")
    cmds.connectAttr(shader + ".outColor", sg + ".surfaceShader", force=True)
    alb = _file_node(maps["albedo"], label + "_albedo")
    cmds.connectAttr(alb + ".outColor", shader + ".baseColor", force=True)
    msk = _file_node(maps["mask"], label + "_mask", raw=True)
    cmds.connectAttr(msk + ".outColorR", shader + ".metalness", force=True)
    inv = cmds.shadingNode("reverse", asUtility=True, name=label + "_s2r")
    cmds.connectAttr(msk + ".outColorG", inv + ".inputX", force=True)
    cmds.connectAttr(inv + ".outputX", shader + ".specularRoughness", force=True)
    nrm = _file_node(maps["normal"], label + "_normal", raw=True)
    bump = cmds.shadingNode("bump2d", asUtility=True, name=label + "_bump")
    cmds.setAttr(bump + ".bumpInterp", 1)
    cmds.connectAttr(nrm + ".outAlpha", bump + ".bumpValue", force=True)
    cmds.connectAttr(bump + ".outNormal", shader + ".normalCamera", force=True)
    return sg


# EXACTLY TWO materials for the whole library (contract 5b). The building atlas
# is the kit's own, so a surviving outer face matches the intact cells beside
# it; the fracture atlas is this delivery's new one.
sg_building = _material(BUILDING_MATERIAL, spec["kit_maps"])
sg_fracture = _material(FRACTURE_MATERIAL, spec["fracture_maps"])

built = 0
for pattern in spec["patterns"]:
    for mesh in pattern["meshes"]:
        pts = [om.MPoint(v[0], v[1], v[2]) for v in mesh["verts"]]
        conn = [i for t in mesh["tris"] for i in t]
        counts = [3] * len(mesh["tris"])
        fn = om.MFnMesh()
        obj = fn.create(pts, counts, conn)
        node = om.MFnDagNode(obj).fullPathName()

        # UVs are per FACE-VERTEX, not per vertex: a shard's corner belongs to
        # an outer face and a broken face at once, and those read from two
        # different atlases. One UV per vertex cannot express that.
        us = [uv[0] for uv in mesh["uvs"]]
        vs = [uv[1] for uv in mesh["uvs"]]
        fn.setUVs(us, vs)
        fn.assignUVs(counts, list(range(len(us))))

        node = cmds.rename(node, mesh["name"])
        node = (cmds.ls(node, long=True) or [node])[0]

        # EVERY EDGE HARD. A mesh built through MFnMesh comes out fully
        # smoothed, and a shard's outer face shares its vertices with two or
        # three fracture walls - so the averaged vertex normal bulges a flat
        # wall surface into a dome. Assembled, that turned a 3 m cell into an
        # obvious heap of pillowed stones while the geometry underneath was an
        # exact cube, which is contract 1b failing on the only thing 1b is
        # about. A fracture face is a crease by definition; none of these edges
        # should ever have been soft.
        cmds.polySoftEdge(node, angle=0, constructionHistory=False)
        cmds.xform(node, worldSpace=True, pivots=(0, 0, 0))
        shape = cmds.listRelatives(node, shapes=True, fullPath=True)[0]
        split = mesh["split"]
        total = len(mesh["tris"])
        if split:
            cmds.sets("%s.f[0:%d]" % (shape, split - 1), edit=True,
                      forceElement=sg_building)
        if split < total:
            cmds.sets("%s.f[%d:%d]" % (shape, split, total - 1), edit=True,
                      forceElement=sg_fracture)
        built += 1

result = {"shards": built,
          "materials": [sg_building, sg_fracture]}
result
'''


CHECK_CODE = r'''
import maya.cmds as cmds
from maya_plugin.handlers import meshcheck as _meshcheck

LIMIT = 2.0 + 1e-3        # cell half-face 1.5 + the 0.5 m outset allowance
fails, rows = [], []
sgs = set()
for name in NAMES:
    node = (cmds.ls(name, long=True) or [None])[0]
    if not node:
        fails.append((name, "missing")); continue
    shape = (cmds.listRelatives(node, shapes=True, fullPath=True) or [None])[0]
    if not shape:
        fails.append((name, "no shape")); continue
    stats = _meshcheck.mesh_stats(shape)
    bb = cmds.exactWorldBoundingBox(node)
    scale = [round(s, 6) for s in cmds.getAttr(node + ".scale")[0]]
    piv = cmds.xform(node, query=True, worldSpace=True, rotatePivot=True)
    uvbb = cmds.polyEvaluate(shape, boundingBox2d=True)
    for s in cmds.listSets(object=shape, type=1) or []:
        sgs.add(s)

    if any(abs(q) > LIMIT for q in bb):
        fails.append((name, "outside cell + outset: %s"
                      % [round(q, 4) for q in bb]))
    if stats["boundary_edges"]:
        fails.append((name, "open: %d boundary edges" % stats["boundary_edges"]))
    if stats["nonmanifold_edges"]:
        fails.append((name, "non-manifold"))
    if scale != [1.0, 1.0, 1.0]:
        fails.append((name, "left-over scale %s" % scale))
    if any(abs(p) > 1e-3 for p in piv):
        fails.append((name, "pivot off cell centre %s" % [round(p, 4) for p in piv]))
    if not (-1e-4 <= uvbb[0][0] and uvbb[0][1] <= 1.0001
            and -1e-4 <= uvbb[1][0] and uvbb[1][1] <= 1.0001):
        fails.append((name, "UVs outside the atlas %s" % uvbb))
    rows.append((name, stats["tris"], stats["verts"],
                 max(abs(q) for q in bb),
                 min(uvbb[0][0], uvbb[1][0]), max(uvbb[0][1], uvbb[1][1])))

# Compact on purpose: 611 rows of geometry blow past the response repr cap and
# come back as an unparseable string (the kit learned this at 37).
result = {
    "tris": sum(r[1] for r in rows),
    "tris_max": max([r[1] for r in rows] or [0]),
    "verts_total": sum(r[2] for r in rows),
    "measured": len(rows),
    "max_abs_extent": round(max([r[3] for r in rows] or [0]), 5),
    "uv_min": round(min([r[4] for r in rows] or [0]), 5),
    "uv_max": round(max([r[5] for r in rows] or [0]), 5),
    "fails": fails[:20],
    "fail_count": len(fails),
    "shading_groups": sorted(sgs),
}
result
'''


EXPORT_CODE = maya_export.EXPORT_PREAMBLE + r'''
cmds.select(NAMES, replace=True)
cmds.file(FBX, force=True, type="FBX export", pr=True, es=True)
result = FBX
'''


# The reassembly proof (contract 7): the single most useful thing to send, and
# the visual form of 1b. Assembled, a pattern must be indistinguishable from an
# intact 3 m cell; exploded, it must obviously be many separate loose pieces.
PROOF_CODE = r'''
import json
import maya.cmds as cmds

plan = json.loads(PLAN)
made = []
for item in plan["names"]:
    dup = cmds.duplicate("|" + item, name="proof_" + item,
                         returnRootsOnly=True)[0]
    dup = (cmds.ls(dup, long=True) or [dup])[0]
    made.append(dup)
grp = cmds.group(made, name=plan["group"])
grp = (cmds.ls(grp, long=True) or [grp])[0]
# GROUPING REPARENTS, so every full path captured above is now stale and
# resolves to nothing. Rebuild them under the group, keeping the original
# order - the bite test zips these against the delivered seeds.
made = [grp + "|" + n.split("|")[-1] for n in made]

if plan.get("explode"):
    # push every shard out along its own direction from the cell centre, so the
    # pieces separate without changing their orientation
    for node in made:
        bb = cmds.exactWorldBoundingBox(node)
        c = [(bb[0] + bb[3]) / 2.0, (bb[1] + bb[4]) / 2.0, (bb[2] + bb[5]) / 2.0]
        n = max(1e-6, (c[0] ** 2 + c[1] ** 2 + c[2] ** 2) ** 0.5)
        k = plan["explode"] / n
        cmds.move(c[0] * k, c[1] * k, c[2] * k, node, relative=True)

if plan.get("bite"):
    # what the game will actually do: delete the shards whose SEED lies inside
    # the strike radius. Same test the shell will run, on the delivered seeds.
    bx, by, bz, radius = plan["bite"]
    killed = 0
    for node, seed in zip(made, plan["seeds"]):
        d = ((seed[0] - bx) ** 2 + (seed[1] - by) ** 2 + (seed[2] - bz) ** 2) ** 0.5
        if d <= radius:
            cmds.delete(node)
            killed += 1
    result = {"group": grp, "pieces": len(made), "removed": killed,
              "bbox": [round(q, 4) for q in cmds.exactWorldBoundingBox(grp)]}
else:
    result = {"group": grp, "pieces": len(made), "removed": 0,
              "bbox": [round(q, 4) for q in cmds.exactWorldBoundingBox(grp)]}
result
'''


# The control for the reassembly proof: a plain 3 m cube wearing the same
# building material, rendered from the same camera. "Assembled, it looks like an
# intact cell" is a claim about a COMPARISON, and a proof that shows only the
# assembled pattern asks the reader to hold the other half in their head. It is
# also what caught the smoothing defect: side by side, the domed facets were
# obvious against a flat cube in a way they were not on their own.
REFERENCE_CODE = r'''
import maya.cmds as cmds
node = cmds.polyCube(w=3.0, h=3.0, d=3.0, name="proof_reference", ch=False)[0]
node = (cmds.ls(node, long=True) or [node])[0]
shape = cmds.listRelatives(node, shapes=True, fullPath=True)[0]
# The cube's own default UVs, shrunk into the role's patch and centred on it,
# so the comparison is of SHADING and SILHOUETTE rather than of two different
# texel densities.
maps = shape + ".map[0:%d]" % (cmds.polyEvaluate(shape, uv=True) - 1)
cmds.polyEditUV(maps, pivotU=0.5, pivotV=0.5, scaleU=SCALE_U, scaleV=SCALE_U)
cmds.polyEditUV(maps, uValue=U0 - 0.5, vValue=V0 - 0.5)
cmds.sets(shape, edit=True, forceElement=BUILDING_MATERIAL + "SG")
cmds.polySoftEdge(node, angle=0, constructionHistory=False)
result = {"node": node}
result
'''


def render(names, target, label, resolution=520, samples=3, zoom=1.0,
           angle="three_quarter"):
    shot = ok(call("render_scene", {
        "angles": [angle], "renderer": "arnold", "resolution": resolution,
        "samples": samples, "zoom": zoom,
        "isolate": names, "target": target}, 1800.0), "render %s" % label)
    return base64.b64decode(shot["images"][0]["png_b64"])


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    # ---------------------------------------------------------- the geometry
    scales = interior_scales()
    patterns, entries = build_spec(scales)
    names = [m["name"] for p in patterns for m in p["meshes"]]

    print("interior UV scale per role (metres of layout per patch), derived "
          "from the widest broken face each role makes:")
    for role in sf.ROLES:
        print("    %-9s %.1f m -> %.0f px/m"
              % (role, scales[role], FRAC_PATCH_PX / scales[role]))

    bad = []
    for p in patterns:
        fails = sf.check_pattern(p["role"], p["audit"])
        if fails:
            bad.append((p["role"], p["variant"], fails))
        for name in [m["name"] for m in p["meshes"]]:
            if not parse_name(name):
                bad.append((p["role"], p["variant"], ["NAME %s" % name]))
    if bad:
        for role, variant, fails in bad:
            print("PATTERN FAILS %s %s: %s" % (role, variant, "; ".join(fails)))
        sys.exit(1)
    if UV_EXCURSION:
        print("UVs LEFT THEIR PATCH (%d face-vertices) - the edge of a patch is "
              "the next material along:" % len(UV_EXCURSION))
        for row in UV_EXCURSION[:12]:
            print("    %s u=%.4f v=%.4f" % row)
        sys.exit(1)
    print("UVs: %d face-vertices, none outside their patch"
          % sum(len(m["uvs"]) for p in patterns for m in p["meshes"]))

    # ---------------------------------------------------------- the materials
    frac_maps = build_fracture_atlas(OUT_DIR)
    kit = kit_maps()
    drop_stale_kit_copies(OUT_DIR)
    for kind, path in list(frac_maps.items()):
        print("  fracture %-7s %s (%.1f MB)"
              % (kind, os.path.basename(path),
                 os.path.getsize(path) / 1024.0 / 1024.0))

    spec = {"patterns": patterns, "kit_maps": kit,
            "fracture_maps": frac_maps}
    spec_path = os.path.join(OUT_DIR, "_build_spec.json").replace("\\", "/")
    with open(spec_path, "w") as fh:
        json.dump(spec, fh)
    print("spec %.1f MB, %d shards" % (os.path.getsize(spec_path) / 1024.0 / 1024.0,
                                       len(names)))

    # ---------------------------------------------------------------- the scene
    ok(call("new_scene", {"confirm": True}, 300.0), "new_scene")
    build = ast.literal_eval(
        run("SPEC_PATH = %r\nAUTHORING_UNIT = %r\nBUILDING_MATERIAL = %r\n"
            "FRACTURE_MATERIAL = %r\n%s"
            % (spec_path, maya_export.AUTHORING_UNIT, BUILDING_MATERIAL,
               FRACTURE_MATERIAL, BUILD_CODE),
            "build")["result_repr"])
    print("built %d shards, materials %s" % (build["shards"], build["materials"]))

    check = ast.literal_eval(
        run("NAMES = %r\n%s" % (names, CHECK_CODE), "check")["result_repr"])

    fbx = os.path.join(OUT_DIR, "demigol_shards.fbx").replace("\\", "/")
    run("NAMES = %r\nFBX = %r\nEXPORT_SCALE_FACTOR = %r\n%s"
        % (names, fbx, maya_export.EXPORT_SCALE_FACTOR, EXPORT_CODE), "export")
    fbx_probe.set_unit_scale_factor(fbx)

    violations = delivery_units.check_delivery(fbx, delivery_units.KIT_CEILING_M)
    if violations:
        print("DELIVERY IS NOT METRE-TRUE - refusing to ship %s:" % fbx)
        for v in violations:
            print("    " + v)
        sys.exit(1)

    submesh_check, submesh_fails = verify_submesh_order(fbx, entries)
    if submesh_fails:
        print("SUBMESH ORDER DISAGREES WITH THE MANIFEST (%d shards) - the "
              "consumer binds materials by this index:" % len(submesh_fails))
        for row in submesh_fails[:12]:
            print("    " + row)
        sys.exit(1)
    submesh_counts = {
        "outer_two_submeshes": sum(1 for e in entries if len(e["submeshes"]) == 2),
        "interior_one_submesh": sum(1 for e in entries if len(e["submeshes"]) == 1),
    }
    print("submesh order: %d/%d models matched the manifest, materials in file "
          "%s" % (submesh_check["models_matched"], submesh_check["shards"],
                  ", ".join(submesh_check["materials_in_file"])))

    # ------------------------------------------------------------- the proofs
    ok(call("setup_lighting", {"preset": "three_point", "intensity": 1.0,
                               "replace_existing": True}, 180.0), "lighting")

    proofs, blanks = [], []
    for p in patterns:
        if p["variant"] != "a":
            continue
        role = p["role"]
        pat_names = [m["name"] for m in p["meshes"]]
        seeds = [e["seed"] for e in entries
                 if e["role"] == role and e["variant"] == "a"]
        # the control tile: a plain 3 m cube in the same material, same camera
        patch = KIT_PATCH[role]
        u0, v0 = _patch_uv(0.5, 0.5, patch, KIT_COLS, KIT_ROWS)
        ref = ast.literal_eval(
            run("SCALE_U = %r\nU0 = %r\nV0 = %r\nBUILDING_MATERIAL = %r\n%s"
                % (0.9 / KIT_COLS, u0, v0, BUILDING_MATERIAL, REFERENCE_CODE),
                "reference %s" % role)["result_repr"])
        ref_png = render([ref["node"]], [ref["node"]], "reference %s" % role,
                         resolution=560, samples=3, zoom=1.0)
        if images.pixel_stats(ref_png)["blank"]:
            blanks.append("reference_%s" % role)
        run("import maya.cmds as cmds\ncmds.delete(%r)\nresult = 1" % ref["node"],
            "clear reference %s" % role)

        pair = [ref_png]
        for kind, explode in (("assembled", 0.0), ("exploded", 0.55)):
            plan = {"names": pat_names, "group": "proof_%s_%s" % (role, kind),
                    "explode": explode, "seeds": seeds}
            info = ast.literal_eval(
                run("PLAN = %r\n%s" % (json.dumps(plan), PROOF_CODE),
                    "proof %s %s" % (role, kind))["result_repr"])
            png = render(["|" + info["group"]], ["|" + info["group"]],
                         "%s %s" % (role, kind), resolution=560, samples=3,
                         zoom=0.95 if explode else 1.0)
            if images.pixel_stats(png)["blank"]:
                blanks.append("%s_%s" % (role, kind))
            pair.append(png)
            run("import maya.cmds as cmds\ncmds.delete(%r)\nresult = 1"
                % info["group"], "clear %s %s" % (role, kind))
        sheet = images.contact_sheet(pair, cols=3)
        path = os.path.join(OUT_DIR, "reassembly_%s.png" % role)
        with open(path, "wb") as fh:
            fh.write(sheet)
        proofs.append(path)

    # Contact sheet: every variant of every role AS THE GAME WILL SHOW IT -
    # a strike has landed and the shards whose seeds it reached are gone. A
    # sheet of intact cells would prove the fill and hide the whole point.
    tiles, bites = [], []
    for p in patterns:
        role, variant = p["role"], p["variant"]
        pat_names = [m["name"] for m in p["meshes"]]
        seeds = [e["seed"] for e in entries
                 if e["role"] == role and e["variant"] == variant]
        plan = {"names": pat_names, "group": "bite_%s_%s" % (role, variant),
                "explode": 0.0, "seeds": seeds,
                "bite": [0.35, -0.25, 1.5, 1.15]}
        info = ast.literal_eval(
            run("PLAN = %r\n%s" % (json.dumps(plan), PROOF_CODE),
                "bite %s %s" % (role, variant))["result_repr"])
        bites.append((role, variant, info["pieces"], info["removed"]))
        png = render(["|" + info["group"]], ["|" + info["group"]],
                     "bite %s %s" % (role, variant), resolution=380, samples=2)
        if images.pixel_stats(png)["blank"]:
            blanks.append("bite_%s_%s" % (role, variant))
        tiles.append(png)
        run("import maya.cmds as cmds\ncmds.delete(%r)\nresult = 1"
            % info["group"], "clear bite %s %s" % (role, variant))

    sheet_png = images.contact_sheet(tiles, cols=4)
    with open(os.path.join(OUT_DIR, "contact_sheet.png"), "wb") as fh:
        fh.write(sheet_png)

    # Rebar close-up. "5 shards per concrete pattern carry a stub" is a number
    # in a manifest, and a number in a manifest is not a bar - the only way to
    # know a 24 mm rod 0.2 m long survived authoring, export and shading is to
    # point a camera at one. It also proves the two-material split at the scale
    # it matters: smooth kit concrete on the outer faces, exposed aggregate on
    # the broken ones, on the same mesh.
    bar_names = [e["name"] for e in entries if e["rebar_stubs"]][:6]
    bar_tiles = []
    for name in bar_names:
        png = render(["|" + name], ["|" + name], "rebar %s" % name,
                     resolution=420, samples=3)
        if images.pixel_stats(png)["blank"]:
            blanks.append("rebar_%s" % name)
        bar_tiles.append(png)
    if bar_tiles:
        with open(os.path.join(OUT_DIR, "rebar_detail.png"), "wb") as fh:
            fh.write(images.contact_sheet(bar_tiles, cols=3))
    print("rebar detail: %d of %d stub-carrying shards rendered"
          % (len(bar_tiles), sum(1 for e in entries if e["rebar_stubs"])))

    # ------------------------------------------------------------ the numbers
    per_role = {}
    for role in sf.ROLES:
        rows = [p["audit"] for p in patterns if p["role"] == role]
        shards = [e for e in entries if e["role"] == role]
        per_role[role] = {
            "patterns": len(rows),
            "shards": sum(r["shards"] for r in rows),
            "shards_per_pattern": [r["shards"] for r in rows],
            "cell_shards_per_pattern": [r["cell_shards"] for r in rows],
            "ornament_shards_per_pattern": [r["ornament_shards"] for r in rows],
            "fill_volume_m3": [round(r["volume"], 6) for r in rows],
            "fill_error_m3": max(abs(r["fill_error"]) for r in rows),
            "ornament_volume_m3": round(
                sum(r["ornament_volume"] for r in rows) / len(rows), 4),
            "outset_m": rows[0]["outset"],
            "min_shard_volume_m3": round(min(r["min_volume"] for r in rows), 5),
            "max_shard_volume_m3": round(max(r["max_volume"] for r in rows), 5),
            "triangles_per_pattern": [r["tris_total"] for r in rows],
            "max_triangles_per_shard": max(r["tris_max"] for r in rows),
            "triangle_cap_per_shard": sf.tri_cap(role),
            "shard_budget_utilisation_pct": round(
                100.0 * max(r["tris_max"] for r in rows) / sf.tri_cap(role), 1),
            "pattern_budget_utilisation_pct": round(
                100.0 * max(r["tris_total"] for r in rows) / TRI_PER_PATTERN, 1),
            "convex_bodies": "%d/%d" % (sum(r["convex"] for r in rows),
                                        sum(r["shards"] for r in rows)),
            "convex_as_delivered": "%d/%d"
                                   % (sum(1 for s in shards if s["convex"]),
                                      len(shards)),
            "rebar_stubs": sum(s["rebar_stubs"] for s in shards),
            "seed_distribution": sf.DISTRIBUTION[role],
            "seed_count_per_pattern": [r["cell_shards"] for r in rows],
            "min_seed_separation_m": sf.SEPARATION[role],
            "interior_uv_scale_m": scales[role],
            "interior_px_per_metre": round(FRAC_PATCH_PX / scales[role], 1),
        }

    print("\n%-9s %8s %8s %10s %11s %9s %9s %7s"
          % ("role", "patterns", "shards", "fill m3", "fill err", "tris/pat",
             "max/shard", "util %"))
    for role in sf.ROLES:
        r = per_role[role]
        print("%-9s %8d %8d %10.5f %11.2e %9s %9d %7.1f"
              % (role, r["patterns"], r["shards"], r["fill_volume_m3"][0],
                 r["fill_error_m3"],
                 "%d-%d" % (min(r["triangles_per_pattern"]),
                            max(r["triangles_per_pattern"])),
                 r["max_triangles_per_shard"], r["shard_budget_utilisation_pct"]))

    print("\nbite proof (shards removed by one 1.15 m strike at the +Z face):")
    for role, variant, total, removed in bites:
        print("    %-9s %s  %3d shards, %2d removed (%.0f%%)"
              % (role, variant, total, removed, 100.0 * removed / total))

    bite_rules = measure_bite_rules(entries, patterns)
    print("\nthe same strike under three removal rules (seed / seed+bound / "
          "solid) - `seed` is what the shell does today:")
    for role in sf.ROLES:
        r = bite_rules[role]
        print("    %-9s seed %2d   bound %2d   solid %2d   of %2d   "
              "seed finds %.0f%% of what the strike actually reaches"
              % (role, r["seed"], r["bound"], r["solid"], r["shards"],
                 100.0 * r["seed"] / r["solid"] if r["solid"] else 100.0))

    print("\n%d shards measured in scene, %d triangles, max %d per shard"
          % (check["measured"], check["tris"], check["tris_max"]))
    print("shading groups: %s" % ", ".join(check["shading_groups"]))
    print("widest extent %.5f m (cell half 1.5 + outset)" % check["max_abs_extent"])
    print("UV range %.5f .. %.5f (atlas is 0..1)" % (check["uv_min"], check["uv_max"]))
    print("geometry failures: %d" % check["fail_count"])
    for name, why in check["fails"]:
        print("    %-24s %s" % (name, why))
    if blanks:
        print("BLANK RENDERS (a camera pointed at nothing): %s" % ", ".join(blanks))

    manifest = {
        "contract": "Demigol SHARD LIBRARY (redmine #664)",
        "contract_document":
            "docs/superpowers/specs/2026-08-16-shard-library-contract.md, "
            "revision 1",
        "scope": "fracture patterns - one 3 m cell pre-shattered into loose "
                 "shards, keyed to material role and cell, never to a building",
        "units": "metres, Y-up, 1 unit = 1 m, cell = 3 m",
        "units_gate": maya_export.UNITS_GATE,
        "origin": "every shard's pivot is the CELL CENTRE (0,0,0) with its "
                  "geometry in place, so surviving shards assemble by straight "
                  "combination with no transforms",
        "authored_facing": "+Z, the same convention as the kit. The surface "
                           "seed bias and the ornament band are both on +Z.",
        "roles": list(sf.ROLES),
        "variants": list(sf.VARIANTS),
        "envelope": {
            "cell_m": sf.CELL,
            "min_shard_volume_m3": sf.MIN_SHARD_VOLUME,
            "min_shard_volume_waived_for": ["glass"],
            "max_outset_m": sf.MAX_OUTSET,
            "outset_per_role_m": {r: sf.ORNAMENT[r][0] for r in sf.ROLES},
            "band_is_opt_in":
                "THE BAND IS A SET THE CONSUMER SELECTS, NOT A FIXTURE. Only 9 "
                "of the 41 kit pieces oversail at all, so for the other 32 an "
                "unconditional band ADDS a cornice the intact cell never had - "
                "the mirror image of the shrink 1c exists to prevent. Every "
                "band shard carries `ornament: true` and they are always the "
                "trailing indices of a pattern; cell fill is exactly 27 m3 "
                "without them. Include them for a cell whose kit piece "
                "oversails, drop them otherwise.",
            "outset_note":
                "outward through the +Z cell face for the five WALL roles, and "
                "around all four vertical faces for `deck` (a roof's oversail "
                "is a perimeter eaves). Carried by dedicated "
                "ornament-band shards rather than welded onto the cell shards. "
                "Sized per role against the kit's MEASURED oversail (9 of 41 "
                "pieces, max 0.34 m), not against the 0.5 m allowance.",
            "measured_widest_extent_m": check["max_abs_extent"],
        },
        "fill": {
            "rule": "the union of a pattern's cell shards is exactly the 3 m cell",
            "how": "TRUE BY CONSTRUCTION, not by measurement: the shards are the "
                   "Voronoi cells of a seed set clipped to the box, and every "
                   "point of the box is nearest exactly one seed. The volumes "
                   "below therefore test the clipper, not the design.",
            "target_m3": 27.0,
            "worst_error_m3": max(per_role[r]["fill_error_m3"] for r in sf.ROLES),
            "ornament_excess_note":
                "the ornament band sits OUTSIDE the cell and is counted apart, "
                "so it can never make a shortfall in the fill look correct",
        },
        "materials": {
            "count": 2,
            "building": {
                "name": "shard_building",
                "atlas": "the kit's, unchanged",
                "shared_with": "demigol_kit",
                "shared": True,
                "maps": [],
                "maps_note":
                    "DELIBERATELY EMPTY. This delivery ships NO copy of the kit "
                    "atlas: resolve the material from the demigol_kit delivery "
                    "(kit_albedo.png, kit_normal.png, kit_mask.png live there). "
                    "Earlier revisions shipped byte copies and that was wrong - "
                    "copies give the shards their own material, so shard debris "
                    "would not batch with the kit wall it broke out of, ~40 MB "
                    "of texture would be resident twice, and a kit re-author "
                    "would leave the copies silently stale with nothing failing.",
                "px": KIT_ATLAS_PX, "grid": [KIT_COLS, KIT_ROWS],
                "world_scale_m_per_patch": KIT_WORLD_SCALE,
                "px_per_metre": round(KIT_ATLAS_PX / KIT_COLS / KIT_WORLD_SCALE, 1),
                "patches": KIT_PATCH,
                "why": "a shard face that was part of the original outer "
                       "surface must line up with the intact cells beside it, "
                       "which means the same atlas, patch and texel density - "
                       "and therefore the same MATERIAL, not a copy of it.",
            },
            "fracture": {
                "name": "shard_fracture",
                "maps": ["fracture_albedo.png", "fracture_normal.png",
                         "fracture_mask.png"],
                "px": FRAC_PX, "grid": [FRAC_COLS, FRAC_ROWS],
                "patch_px": FRAC_PATCH_PX,
                "patches_used": len(FRACTURE), "patches_available":
                    FRAC_COLS * FRAC_ROWS,
                "patches": {k: {"index": v[0], "rgb": list(v[1]), "style": v[2],
                                "metallic": v[3], "smoothness": v[4]}
                            for k, v in FRACTURE.items()},
                "per_role_choices": {k: list(v) for k, v in FRACTURE_FOR.items()},
                "why": "the freshly-broken faces are the majority of every "
                       "shard's surface and the kit atlas is 16/16 full",
            },
            "assignment": "per FACE, not per object: a shard's outer faces read "
                          "the building atlas and its broken faces the fracture "
                          "atlas, so one mesh carries both. UVs are per "
                          "face-vertex for the same reason.",
            "submesh_order": {
                "rule": "every shard declares its own `submeshes` array, in FBX "
                        "submesh order. Bind materials BY INDEX from that array "
                        "- do not derive it from `surface` and do not assume "
                        "index 0 is the building atlas.",
                "outer": [BUILDING_MATERIAL, FRACTURE_MATERIAL],
                "interior": [FRACTURE_MATERIAL],
                "counts": submesh_counts,
                "why": "%d of %d shards are fully interior and carry ONE "
                       "submesh, so index 0 means %s on them and %s on the "
                       "other %d. Verified by re-reading the exported FBX, not "
                       "asserted from the builder."
                       % (submesh_counts.get("interior_one_submesh", 0),
                          len(entries), FRACTURE_MATERIAL, BUILDING_MATERIAL,
                          submesh_counts.get("outer_two_submeshes", 0)),
                "verified_against_fbx": submesh_check,
            },
        },
        "texel_density": {
            "outer_px_per_metre": round(
                KIT_ATLAS_PX / KIT_COLS / KIT_WORLD_SCALE, 1),
            "outer_note": "identical to the kit by construction - same atlas, "
                          "same world projection, same 9 m per patch",
            "interior_px_per_metre": {r: round(FRAC_PATCH_PX / scales[r], 1)
                                      for r in sf.ROLES},
            "interior_note":
                "broken faces project LOCALLY about their own centre, so the "
                "scale is set by the widest broken face a role makes rather "
                "than by the worst case across all roles. Concrete breaks "
                "smallest and gets the finest aggregate. Verified against real "
                "feature scale: aggregate reads 10-30 mm, which at %.0f px/m is "
                "%.1f-%.1f px - above the 2 px floor the kit's brick pitch "
                "established as the point where detail turns into aliasing."
                % (FRAC_PATCH_PX / scales["concrete"],
                   FRAC_PATCH_PX / scales["concrete"] * 0.010,
                   FRAC_PATCH_PX / scales["concrete"] * 0.030),
            "rebar_uv_scale_m": REBAR_UV_SCALE,
        },
        "budgets": {
            "triangles_per_shard": {r: sf.tri_cap(r) for r in sf.ROLES},
            "triangles_per_shard_note":
                "PER ROLE. steel is 200 and every other role is 80, decided on "
                "#664: an 80-triangle per-shard cap is the wrong shape for the "
                "one role the contract defines by having FEW LARGE pieces. 200 "
                "buys 7 sub-cells a section and 37.8 mean tear facets against "
                "15.1 at 80; it does not buy more, because the next lattice "
                "step measured 230.",
            "triangles_per_pattern": TRI_PER_PATTERN,
            "utilisation_pct_per_shard": {
                r: per_role[r]["shard_budget_utilisation_pct"] for r in sf.ROLES},
            "utilisation_pct_per_pattern": {
                r: per_role[r]["pattern_budget_utilisation_pct"] for r in sf.ROLES},
        },
        "totals": {
            "patterns": len(patterns),
            "shards": len(entries),
            "triangles": check["tris"],
            "max_triangles_per_shard": check["tris_max"],
            "vertices": check["verts_total"],
            "vertices_note":
                "the count in the scene. Unity will import MORE: every edge is "
                "hard and UVs are per face-vertex, so vertices split per face. "
                "Size any rubble merge against the SPLIT count "
                "(triangles x 3 upper bound), not this one - #662's UInt16 "
                "merge ceiling is 65,535 and it was already hit on M1.",
            "vertices_split_upper_bound": check["tris"] * 3,
            "shading_groups": check["shading_groups"],
            "uv_range": [check["uv_min"], check["uv_max"]],
        },
        "roles_detail": per_role,
        "self_check": {
            "fill": "computed per pattern in shard_fracture.audit_pattern and "
                    "rejected, not flagged, above 1e-4 m3",
            "convexity": "re-derived from the built faces of every shard",
            "closed": "boundary_edges == 0 and no non-manifold edges, both in "
                      "pure Python and again on the built Maya mesh",
            "names": "every name re-parsed as four tokens with a contiguous "
                     "two-digit index",
            "uv": "every shard's UV bbox measured inside 0..1 in scene",
            "units": "the exported FBX BYTES re-read and gated",
            "failures": check["fail_count"],
        },
        "bite_proof": {
            "what": "one 1.15 m strike at (0.35, -0.25, 1.5), the +Z face - the "
                    "same test the shell will run, against the delivered seeds",
            "removed": {"%s_%s" % (r, v): {"shards": t, "removed": k}
                        for r, v, t, k in bites},
            "rules": bite_rules,
            "rules_note":
                "THE SAME STRIKE UNDER THREE REMOVAL RULES, and the gap between "
                "them is a finding for the shell. `seed` is the point test "
                "|seed - strike| <= radius. `bound` is the sphere-sphere test "
                "|seed - strike| <= radius + bound_radius_m. `solid` is ground "
                "truth, measured against the real surface (point-to-triangle "
                "distance over every face, plus an inside test) rather than "
                "against a bounding volume - a bounding volume cannot be the "
                "ground truth for a question about bounding volumes. `bound` is "
                "a superset of `solid` by construction, and that is asserted at "
                "build time rather than assumed. `seed` under-removes "
                "EVERYWHERE - 12 to 66% of what a strike actually reaches - so "
                "the per-role erosion spread reported earlier is measured "
                "through a lossy instrument. What that spread is NOT is a "
                "simple function of shard size: concrete and brick have "
                "effectively the same mean shard volume (0.864 vs 0.900 m3) "
                "and differ 2.5x, because what decides the miss rate is where "
                "a role's seeds sit RELATIVE TO THE STRUCK FACE - concrete's 6 "
                "surface-biased seeds in the +Z 0.55 m against brick's "
                "bed-centre seeding. That part is authored, so it is partly a "
                "property of the role after all. Under `solid` the roles "
                "converge to a much tighter band than under `seed`. "
                "`sample_point`/`inscribed_radius_m` and `seed`/`bound_radius_m` "
                "bracket the truth from inside and outside, so the shell can "
                "pick its rule with the numbers in front of it.",
        },
        "deviations": DEVIATIONS,
        "shards": entries,
        "files": ["demigol_shards.fbx", "fracture_albedo.png",
                  "fracture_normal.png", "fracture_mask.png", "manifest.json",
                  "contact_sheet.png", "rebar_detail.png"]
                 + [os.path.basename(p) for p in proofs] + ["README.md"],
    }
    with open(os.path.join(OUT_DIR, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2)
    os.remove(spec_path)

    # Arnold writes a .tx beside every texture it reads. They are a render
    # cache, they regenerate on demand, and here they are 35 MB of a 50 MB
    # package - so they do not ship. The kit delivery left its own in place;
    # that is the thing being corrected, not a precedent.
    #
    # BEST EFFORT, deliberately: Arnold keeps them open for the life of the
    # Maya session that rendered them, so the last few are still locked when
    # this runs. A delivery is not unsound because a render cache survived it,
    # and failing the run over one would throw away 611 verified shards.
    dropped, locked = 0, []
    for name in sorted(os.listdir(OUT_DIR)):
        if not name.endswith(".tx"):
            continue
        try:
            os.remove(os.path.join(OUT_DIR, name))
            dropped += 1
        except OSError:
            locked.append(name)
    print("Arnold .tx caches: %d removed, %d still held by the open Maya "
          "session%s" % (dropped, len(locked),
                         " (delete after closing it)" if locked else ""))

    write_readme(manifest, per_role, bites, check, scales, entries,
                 submesh_counts, submesh_check, bite_rules)

    print("\n%d patterns, %d shards, %d triangles"
          % (len(patterns), len(entries), check["tris"]))
    return 0 if check["fail_count"] == 0 and not blanks else 1


DEVIATIONS = [
    {
        "rule": "8.3 - every shard convex",
        "role": "steel",
        "what": "the 8 steel sections are unions of ~7 Voronoi cells and are "
                "not convex; they are also bent by a smooth warp",
        "why": "contract 2 requires steel to read as torn plate with ragged "
               "tear edges and explicitly NOT to shatter, and a convex lump is "
               "the one shape a torn section cannot be. The two rules cannot "
               "both hold for this role, so the artistic requirement wins. "
               "Every other role is convex by construction and checked. A "
               "convex-hull collider on a steel section is a close fit - the "
               "sections are large and slab-like, not concave shells.",
    },
    {
        "rule": "8.3 - every shard convex",
        "role": "concrete",
        "what": "5 shards per concrete pattern carry a rebar stub as a second "
                "shell, which makes those meshes non-convex",
        "why": "contract 2 asks for rebar stubs protruding from a few shards. "
               "The stub grows out of a BROKEN face into the neighbouring "
               "shard, where it is fully enclosed until that neighbour is "
               "removed - which is exactly when a bar should appear. It cannot "
               "open a gap and cannot be seen early. The alternative, taking "
               "the bar out through the cell face, is a bar sticking into the "
               "street: a different and much rarer read.",
    },
    {
        "rule": "1b - no overlaps",
        "role": "concrete",
        "what": "a rebar stub interpenetrates the shard it points into, by "
                "about 0.0005 m3",
        "why": "1b exists so that an assembled pattern looks like an intact "
               "cell. A stub sealed inside a neighbour cannot affect the union "
               "or the silhouette. The fill volume is measured on the Voronoi "
               "bodies alone, so the overlap cannot flatter the number either.",
    },
    {
        "rule": "the kit's 5 mm inset",
        "role": "all",
        "what": "shards reach the cell face exactly, where kit pieces stop "
                "5 mm short",
        "why": "1b requires the union to fill the cell, and an inset would fail "
               "it. The consequence is that a pattern sits 5 mm PROUD of its "
               "neighbours rather than coplanar with them, which avoids "
               "z-fighting instead of causing it. Worth knowing on the game "
               "side; it is not something to correct here.",
    },
]


def write_readme(manifest, per_role, bites, check, scales, entries,
                 submesh_counts, submesh_check, bite_rules):
    lines = []
    add = lines.append
    add("# demigol_shards - the fracture pattern library\n")
    add("Third Demigol art delivery. Contract: "
        "`docs/superpowers/specs/2026-08-16-shard-library-contract.md` "
        "(revision 1), redmine #664.\n")
    add("**%d patterns, %d shards, %d triangles, 2 materials.** Five roles x "
        "four variants; a pattern is one 3 m cell pre-shattered into loose "
        "meshes, keyed to material and cell and never to a building, so this "
        "one library dresses all 50 city buildings and every one generated "
        "later.\n" % (manifest["totals"]["patterns"], manifest["totals"]["shards"],
                      manifest["totals"]["triangles"]))

    add("## The rule everything rests on\n")
    add("Contract 1b: assembled, a pattern must be indistinguishable from the "
        "intact cell it replaces. Here that is **true by construction rather "
        "than by measurement** - the shards are the Voronoi cells of a seed set "
        "clipped to the 3 m box, and every point of the box is nearest exactly "
        "one seed, so they tile it with no gap and no overlap. The measured "
        "volumes therefore test the clipper, not the design. Worst error across "
        "all %d patterns: **%.2e m3** against 27 m3.\n"
        % (manifest["totals"]["patterns"], manifest["fill"]["worst_error_m3"]))
    add("See `reassembly_*.png`, one per role: **a plain 3 m cube in the same "
        "material, the pattern assembled, and the same pattern exploded.** The "
        "control cube is there because the claim is a comparison, and because "
        "it is what caught the one defect a green gate could not - built "
        "through `MFnMesh` every edge comes out SOFT, so each flat outer facet "
        "was shaded as a dome and an exact cube rendered as a heap of pillowed "
        "stones. Every edge is hard now; a fracture face is a crease by "
        "definition.\n")

    add("## How the five roles break\n")
    add("| role | shards/pattern | how it breaks | seeds |")
    add("|---|---|---|---|")
    how = {
        "concrete": "blocky lumps, aggregate faces, rebar stubs on 5 shards",
        "brick": "along its courses - shards are brick-multiples with flat bed joints",
        "infill": "plate-like, thin in depth: a curtain panel delaminating",
        "glass": "a shower of splinters, radial from the impact point on the pane",
        "steel": "does NOT shatter - few large torn, bent sections",
        "deck": "a roof slab: blocky like concrete, spalling at the TOP face",
    }
    for role in sf.ROLES:
        r = per_role[role]
        add("| `%s` | %s | %s | %s |"
            % (role, "-".join(str(q) for q in sorted(
                {min(r["shards_per_pattern"]), max(r["shards_per_pattern"])})),
               how[role], r["seed_distribution"]))
    add("")
    add("The differences are entirely in **where the seeds go** - the clipper is "
        "the same for all five. That is why the distribution is declared per "
        "role in the manifest (contract 2a): it is the dial, and it is meant to "
        "be re-runnable. Ask for a different one and it is a parameter change "
        "and a re-run, not a re-model.\n")

    add("## Budget utilisation\n")
    add("| role | tris/pattern | cap | max tris/shard | cap | per-shard used |")
    add("|---|---|---|---|---|---|")
    for role in sf.ROLES:
        r = per_role[role]
        add("| `%s` | %d-%d | %d | %d | %d | **%.0f%%** |"
            % (role, min(r["triangles_per_pattern"]),
               max(r["triangles_per_pattern"]), TRI_PER_PATTERN,
               r["max_triangles_per_shard"], sf.tri_cap(role),
               r["shard_budget_utilisation_pct"]))
    add("")
    add("The per-shard cap is **per role**: 80 everywhere, 200 for `steel`, "
        "raised by the contract owner on #664. The next section is why.\n")
    add("### Steel, re-run at the raised cap\n")
    add("The first delivery of this library reported steel as its weak spot and "
        "asked for exactly this: its *pattern* budget sat at 27%% while every "
        "section was pinned at 95%% of the 80-triangle *per-shard* cap, so the "
        "binding constraint was the one that had nothing to do with cost - and "
        "it is what made steel read diced rather than torn. It now sits at "
        "**%d of %d pattern triangles (%.0f%%)** with sections at **%.0f%% of "
        "the 200 cap**.\n"
        % (max(per_role["steel"]["triangles_per_pattern"]), TRI_PER_PATTERN,
           per_role["steel"]["pattern_budget_utilisation_pct"],
           per_role["steel"]["shard_budget_utilisation_pct"]))
    add("**The re-run does not spend the new cap the way the ask assumed, and "
        "that is the one thing to read here.** The ask was phrased as *~4.5 "
        "Voronoi cells per section, ~192 triangles*, carrying forward the first "
        "delivery's own counterfactual. But cells-per-section is a proxy. What "
        "the eye reads is how many angled planes the torn boundary turns "
        "through, so the re-run measured **tear facets** directly:\n")
    add("| lattice | cells/section | mean tear facets | max tris/shard | section volumes |")
    add("|---|---|---|---|---|")
    add("| `2x5x2` (shipped before) | 2.5 | 15.1 | 76 | 2.34-4.34 m3 |")
    add("| `3x4x3` (the ask, converted) | 4.5 | 27.2 | 194 | 1.51-6.57 m3 |")
    add("| **`2x14x2` (ships now)** | **7.0** | **37.8** | **194** | **2.40-4.72 m3** |")
    add("| `2x16x2` | 8.0 | 40.3 | 230 | over cap |")
    add("")
    add("A Y-dense lattice is far more triangle-efficient, because cells stacked "
        "along one axis merge into a section that gains volume without gaining "
        "many outward walls. Same triangle price as the converted ask, **39% "
        "more tear**, and the sections stay comparable in size - `3x4x3` came "
        "out lopsided at 1.5 to 6.6 m3, which reads as a broken block rather "
        "than as eight severed sections.\n")
    add("The cap and the lattice are therefore **one decision**: 200 buys 7 "
        "cells a section and nothing more, since the next step measured 230. "
        "Moving either without re-measuring the other is a bug.\n")
    add("What is NOT available at any budget, and is worth saying so it is not "
        "re-litigated: **long** members. Eight sections dividing a 3 m cube are "
        "about 1.5 m across whatever the metric does - measured height/width "
        "stayed 1.09-1.23 across every setting tried, including a strongly "
        "anisotropic gather. Torn is reachable; long is not, at 8 pieces. The "
        "contract owner has accepted this and ruled long members out of this "
        "library.\n")
    add("There is a second, structural limit on the same role. **1b requires "
        "the assembled pattern to be an exact cube**, so every shard's outer "
        "face is flat and axis-aligned by definition. A torn read can therefore "
        "only live on the fracture walls - which is why the bend deforms the "
        "interior and vanishes at the cell surface. 1b and the steel row of 2 "
        "pull against each other, and 1b wins because it is the one that is "
        "rejected rather than flagged.\n")

    add("## The two materials\n")
    add("1. **`shard_building`** - the kit's atlas, unchanged. A surviving outer "
        "face must line up with the intact cells beside it, so it uses the same "
        "atlas, the same patch and the same %s px/m.\n"
        % manifest["materials"]["building"]["px_per_metre"])
    add("   **This delivery ships no copy of it.** The manifest declares "
        "`shared_with: demigol_kit` and the three `kit_*.png` byte copies "
        "earlier revisions carried are gone. Resolve the material from the kit "
        "delivery. Copies gave the shards their own material, which means shard "
        "debris would *not batch with the kit wall it broke out of*, ~40 MB of "
        "texture would be resident twice, and a kit re-author would leave the "
        "copies silently stale with nothing failing.\n")
    add("2. **`shard_fracture`** - new, %d px, %d of %d patches used. The "
        "freshly-broken faces are the majority of every shard's surface and the "
        "kit atlas is 16/16 full. Albedo, normal and metallic/smoothness on one "
        "layout, so it costs one extra draw call for the whole city and not one "
        "more.\n" % (FRAC_PX, len(FRACTURE), FRAC_COLS * FRAC_ROWS))
    add("Assignment is **per face**, not per object, and UVs are per "
        "face-vertex: a shard corner belongs to an outer face and a broken face "
        "at once, and those read from different atlases.\n")
    add("### Submesh order is DECLARED, not derivable\n")
    add("Every shard carries a `submeshes` array in the manifest, in FBX "
        "submesh order. **Bind materials by index from that array.** Do not "
        "assume index 0 is the building atlas:\n")
    add("| shards | submeshes | index 0 is |")
    add("|---|---|---|")
    add("| %d | `[\"%s\", \"%s\"]` | `%s` |"
        % (submesh_counts["outer_two_submeshes"], BUILDING_MATERIAL,
           FRACTURE_MATERIAL, BUILDING_MATERIAL))
    add("| %d | `[\"%s\"]` | `%s` |"
        % (submesh_counts["interior_one_submesh"], FRACTURE_MATERIAL,
           FRACTURE_MATERIAL))
    add("")
    add("%d of %d shards are fully interior - they have no face that was ever "
        "part of the wall's outer surface - so they carry ONE submesh and index "
        "0 means the fracture atlas on them. A consumer that derives the order "
        "from `surface`, or assumes two submeshes everywhere, puts the fracture "
        "texture on the outside of those %d shards and nothing fails. That is "
        "the shape of the two defects this project has already paid for: #596's "
        "626 catalog entries bound to another building's mesh, and #630's 4096 "
        "atlas importing at 2048 - individually valid data, one wrong global "
        "assumption, no error.\n"
        % (submesh_counts["interior_one_submesh"], len(entries),
           submesh_counts["interior_one_submesh"]))
    add("The claim is checked against the **exported FBX bytes**, not against "
        "the builder that wrote them: material connection order per model, and "
        "the per-polygon material indices underneath it. `%d/%d` models "
        "matched.\n" % (submesh_check["models_matched"], submesh_check["shards"]))
    add("Interior texel density, per role, derived from the widest broken face "
        "each role actually makes:\n")
    add("| role | m of layout per patch | px/m | 20 mm feature |")
    add("|---|---|---|---|")
    for role in sf.ROLES:
        d = FRAC_PATCH_PX / scales[role]
        add("| `%s` | %.1f | %.0f | %.1f px |" % (role, scales[role], d, d * 0.02))
    add("")

    add("### The steel patch mix\n")
    add("An even pick among steel's three fracture patches put `rust` on "
        "35%% of freshly TORN sections (measured: torn 16, rust 14, dark 10 "
        "of 40). Rust is what already-exposed steel looks like; a section "
        "opened a second ago should be bright bare metal. Weighted to "
        "**%.0f%%** by the contract owner's call - enough to break up a "
        "grey block and read as decayed plant, not enough to claim every "
        "third tear is old.\n"
        % (100.0 * FRACTURE_WEIGHTS["steel"]["rust"]))

    add("## The outset (contract 1c)\n")
    add("Sized against the kit rather than against the allowance. **Measured in "
        "`demigol_kit/manifest.json`: only 9 of the 41 kit pieces oversail at "
        "all, and the largest is 0.34 m** - brick facades 0.14-0.22, brick and "
        "concrete roofs 0.30-0.34, a concrete base 0.15, a glass sill 0.16, a "
        "steel column 0.24, and infill never. A uniform 0.5 m lip would be "
        "wrong against 32 of 41 neighbours.\n")
    add("So the band is per role (%s) and it is delivered as **its own shards** "
        "rather than welded onto the cell shards behind it. That keeps every "
        "band piece convex, keeps the cell's union at exactly 27 m3, and lets a "
        "cornice break off independently the way a cornice does.\n"
        % ", ".join("%s %.2f m" % (r, sf.ORNAMENT[r][0]) for r in sf.ROLES))

    add("## The bite proof\n")
    add("`contact_sheet.png` does not show intact cells - it shows every pattern "
        "**after a strike**, because a sheet of intact cells would prove the "
        "fill and hide the point. One 1.15 m strike at the +Z face, removing the "
        "shards whose delivered `seed` falls inside it, which is the same test "
        "the shell will run:\n")
    add("| pattern | shards | removed |")
    add("|---|---|---|")
    for role, variant, total, removed in bites:
        add("| `%s_%s` | %d | %d (%.0f%%) |"
            % (role, variant, total, removed, 100.0 * removed / total))
    add("")
    add("### The spread is mostly the RULE, not the material\n")
    add("Last round this delivery reported the spread above - 36-44%% of a "
        "glass pattern against 3-9%% of a brick one - as *erosion per hit is a "
        "property of the material*, and handed it over as a decision. That was "
        "half right, and the half that was wrong matters more. Scoring the same "
        "strike three ways:\n")
    add("| role | `seed` | `seed + bound` | `solid` | shards | `seed` finds |")
    add("|---|---|---|---|---|---|")
    for role in sf.ROLES:
        r = bite_rules[role]
        add("| `%s` | %d | %d | %d | %d | **%.0f%%** |"
            % (role, r["seed"], r["bound"], r["solid"], r["shards"],
               100.0 * r["seed"] / r["solid"] if r["solid"] else 100.0))
    add("")
    add("- `seed` - the point test, `|seed - strike| <= radius`. What the shell "
        "does today and what the contact sheet shows.\n"
        "- `seed + bound` - `<= radius + bound_radius_m`, the sphere-sphere "
        "form. A superset of `solid` by construction, so it never misses a "
        "shard the strike reaches; it over-includes instead, most on the "
        "shards whose bounding sphere fits them worst.\n"
        "- `solid` - ground truth, measured against the real surface: "
        "point-to-triangle distance over every face, plus an inside test.\n")
    add("**One point cannot stand for a shard of up to %.1f m3.** The point "
        "test finds only 12-66%% of what a strike actually reaches, so the "
        "per-role spread above is measured through a lossy instrument.\n"
        % max(e["volume_m3"] for e in entries))
    add("What that spread is **not** is a simple function of shard size, and "
        "an earlier revision of this README said it was. Concrete and brick "
        "have effectively the same mean shard volume - **0.864 against 0.900 "
        "m3** - and differ 2.5x in what the point test finds. What actually "
        "drives the miss rate is where a role's seeds sit *relative to the "
        "struck face*: concrete puts 6 surface-biased seeds in the +Z 0.55 m, "
        "brick seeds at bed centres. That is authored, so it is partly a "
        "property of the role after all - the correction is to the reasoning, "
        "not to the recommendation.\n")
    add("Nothing here is a change to the geometry, and no rule is imposed. "
        "Four fields ship per shard so the shell can choose: `seed` + "
        "`bound_radius_m` never misses and over-includes; `sample_point` + "
        "`inscribed_radius_m` never over-reaches. Together they bracket it. The per-role multiplier the "
        "consumer planned is still the right lever for taste - this just means "
        "it starts from a corrected baseline rather than compensating for a "
        "measurement error.\n")

    add("`rebar_detail.png` is six of the %d stub-carrying shards at close "
        "range. It doubles as the proof of the two-material split at the scale "
        "that matters: smooth kit concrete on the outer faces, exposed "
        "aggregate on the broken ones, on the same mesh.\n"
        % sum(v["rebar_stubs"] for v in per_role.values()))
    add("## Deviations, with reasons\n")
    for d in manifest["deviations"]:
        add("- **%s** (`%s`): %s\n  %s\n" % (d["rule"], d["role"], d["what"], d["why"]))

    add("## Regenerating\n")
    add("```")
    add("MAYA_MCP_PORT=9878 \"E:/Autodesk/Maya2027/bin/maya.exe\" &")
    add("set MAYA_MCP_PORT=9878 && .venv/Scripts/python.exe evals/demigol_shards.py")
    add("```")
    add("**9878, not 9877.** This generator opens with `new_scene`, and 9877 is "
        "the user's own Maya session under the two-Maya policy - a `new_scene` "
        "there discards whatever is open, unsaved.\n")
    add("The geometry is in `evals/shard_fracture.py` and has no Maya in it: "
        "`python evals/shard_fracture.py` prints the full fill/convexity/budget "
        "audit for all %d patterns in about a second, with no scene open.\n"
        % manifest["totals"]["patterns"])

    with open(os.path.join(OUT_DIR, "README.md"), "w") as fh:
        fh.write("\n".join(lines))


if __name__ == "__main__":
    sys.exit(main())
