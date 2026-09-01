"""#770: what maya_bake_mesh_maps refuses, bakes, and composites.

Every refusal and shape here is grounded in a MEASURED probe finding
(evals/meshmaps_probe_770*.py), not caution:
- a UV-less mesh does not fail at bake time - arnoldRenderToTexture returns
  normally and writes a CORRUPT EXR that only fails later, at read (P Q5);
- the -shader flag bakes without assigning, so the bake phase mutates
  nothing (Q2);
- a flat map can be HONEST (concave curvature on a beveled cube is all-zero,
  Q3; a lone convex mesh's AO is all-white) - so flat is a warning here,
  never the refusal it is in texbake;
- MImage's EXR->PNG conversion is LINEAR (0.5 lands on 127/128, T1), so the
  AO composite decodes sRGB bases but takes AO values straight.
"""

import os
import struct
import zlib

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import meshmaps, pngprobe


def _png(path, rows, colour_type=2):
    """A real PNG with arbitrary colour type (RGBA models what MImage
    actually writes for a converted bake - measured colour_type 6)."""
    raw = bytearray()
    for row in rows:
        raw.append(0)
        for px in row:
            raw.extend(px)

    def chunk(tag, payload):
        body = tag + payload
        return (struct.pack(">I", len(payload)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    width, height = len(rows[0]), len(rows)
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8,
                                        colour_type, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(bytes(raw)))
           + chunk(b"IEND", b""))
    with open(str(path), "wb") as fh:
        fh.write(png)
    return str(path)


def _rich_rgba_rows(size=4, alpha=255):
    return [[(x * 60 % 256, y * 60 % 256, 128, alpha) for x in range(size)]
            for y in range(size)]


def _resolve_dag(known, name, node_of=None):
    """Maya's own name resolution - the half of #796 a short-name-only fake
    could not see.

    `cmds.sets(sg, query=True)` answers with the SHORTEST UNIQUE name. For
    the two mirrored shapes this ticket is about that is NEITHER the bare
    short name NOR the full path: it is a PARTIAL path, 'right|limbShape'.
    Maya matches a partial path as a SUFFIX of a full path, anchored at a
    '|' component boundary; a LEADING '|' makes the name absolute, so it
    means one full path or nothing.

    The fake used to match `n.split('|')[-1] == name`, which resolves the
    partial form to [] - so the member was SKIPPED and the fake reproduced
    the exact silent miss #796 fixes, while the new tests read as passing.

    ONE PATH PER NODE (#796 round 4). `cmds.ls(name, long=True)` matches
    NODES: an ambiguous name answers with one path for each node it hits,
    but an INSTANCED node - several paths, ONE node - answers with one of
    its paths and no more. Enumerating the rest is what `allPaths=True` is
    for, and this guard does not ask for it. Modelling ls as an all-paths
    expansion made the instance tests assert a resolution Maya never
    performs - the round-2 defect class exactly: a fake feeding an answer
    Maya does not give.
    """
    if not name:
        return []
    if name.startswith("|"):
        matched = [n for n in known if n == name]  # absolute: that path
    else:
        wanted = name.split("|")
        matched = []
        for n in known:
            comps = n.split("|")  # '|a|b' -> ['', 'a', 'b']
            if len(wanted) <= len(comps) and comps[-len(wanted):] == wanted:
                matched.append(n)
    out, seen = [], set()
    for n in matched:
        node = (node_of or {}).get(n, n)
        if node in seen:  # another path of a node already named
            continue
        seen.add(node)
        out.append(n)
    return out


class FakeCmds:
    """|limb (shape |limbShape) wears limbSG -> limb_mat (standardSurface),
    baseColor unconnected (a plain value). Per-test knobs mirror
    tests/test_texbake.py's fake - model Maya, never dodge it."""

    def __init__(self):
        self.meshes = {"|limb": "|limbShape"}
        self.uv_counts = {"|limbShape": 64}
        self.types = {"limb_mat": "standardSurface"}
        self.shape_sgs = {"|limbShape": ["limbSG"]}
        self.sg_members = {"limbSG": ["|limbShape"]}
        self.conns = {"limbSG.surfaceShader": ["limb_mat.outColor"]}
        self.existing_attrs = {"limb_mat.baseColor"}
        self.attr_values = {"limb_mat.baseColor": [(1.0, 1.0, 1.0)]}
        # Plugs a rigger locked by hand: the other half of #799 contract
        # 2's "locked or connected" refusal, which no path in this module
        # produces on its own.
        self.locked = set()
        self.connected = []
        self.deleted = []
        self.created = []
        self.checkpoints = []
        self.selection = ["|limb"]
        self.plugins_loaded = ["mtoa"]
        # #796 round 3: NODE identity, the thing a DAG path is not. An
        # INSTANCED mesh is ONE shape node hanging under several paths -
        # those paths share an entry here; everything else gets its own
        # node by default. A fake that models instancing as two separate
        # shapes cannot tell an instance from a mirrored twin, which is
        # where round 2's defect hid.
        self.node_of = {}

    # existence -------------------------------------------------------
    def _exists(self, node):
        """Every name this scene holds: mesh transforms, mesh shapes,
        shading groups, and every DG node in `types` (which `delete` pops
        from)."""
        return (node in self.meshes or node in self.meshes.values()
                or node in self.types or node in self.sg_members)

    def _require(self, node):
        """Raise the way real Maya does for a node that was deleted or
        never created - #799 contract 1.

        Every query below funnels through here. The fake used to answer a
        DEFAULT for an unknown name (nodeType said "transform", getAttr
        said "", polyEvaluate said "no UVs"), which is exactly the shape
        that hid one of #796's blocking defects: code asking about a node
        it had just deleted got a plausible answer here and a RuntimeError
        in Maya. This module creates a bake shader per (mesh, map) and
        DELETES it in a finally, then rewires and sweeps the colour
        network - a query about a consumed node is the live risk here.

        Deletion is modelled by `delete` REMOVING the node from the
        registries `_exists` reads, NOT by a name tombstone. #799 round 2
        found the tombstone here first: `_make_bake_shader` builds
        `mcpBake_<map>` and deletes it in a `finally` on EVERY (mesh, map)
        iteration, so a two-mesh bake re-creates a deleted name and the
        tombstoned fake raised "No object matches name" on a node it had
        created one line earlier. `self.deleted` is a RECORD for
        assertions, never an existence oracle.
        """
        if not self._exists(node):
            raise RuntimeError("No object matches name: %s" % node)

    def _compound_parent(self, plug):
        """`limb_mat.baseColorR` -> `limb_mat.baseColor`, or None."""
        node, _, attr = plug.rpartition(".")
        if len(attr) > 1 and attr[-1] in "RGBXYZ":
            return "%s.%s" % (node, attr[:-1])
        return None

    def _static_write_blocker(self, plug):
        """The connection or lock that makes `setAttr(plug, ...)` raise,
        or None - #799 contract 2. Maya refuses a static write to a plug
        something feeds, to a COMPOUND whose CHILD is fed, AND to a CHILD
        whose parent compound is fed - round 1 modelled only the middle
        one."""
        parent = self._compound_parent(plug)
        for candidate in (plug, parent):
            if candidate is None:
                continue
            if candidate in self.locked:
                return candidate
            if candidate in self.conns:
                return self.conns[candidate][0]
        node, _, attr = plug.rpartition(".")
        for dst, srcs in self.conns.items():
            dnode, _, dattr = dst.rpartition(".")
            if dnode == node and dattr[:-1] == attr and dattr[-1:] in tuple(
                    "RGBXYZ"):
                return srcs[0]
        for locked in self.locked:
            lnode, _, lattr = locked.rpartition(".")
            if lnode == node and lattr[:-1] == attr and lattr[-1:] in tuple(
                    "RGBXYZ"):
                return locked
        return None

    # resolution ------------------------------------------------------
    def ls(self, *args, **kw):
        """Resolves transforms AND shapes: a shading group's members are
        SHAPES, and #796's canonicalisation sends every one of them
        through here. Partial paths resolve the way Maya resolves them
        (_resolve_dag) - that is the form cmds.sets actually answers with
        on the mirrored rig this ticket is about.

        `uuid=True` answers with the NODE instead of its paths, which is
        what the guard compares now: the two paths of an instanced shape
        are one node and must come back as one identity, while a mirrored
        pair is two nodes and must not."""
        if kw.get("selection"):
            return list(self.selection)
        name = args[0] if args else kw.get("name")
        paths = _resolve_dag(list(self.meshes) + list(self.meshes.values()),
                             name, self.node_of)
        if not kw.get("uuid"):
            return paths
        ids = []
        for path in paths:
            node = self.node_of.get(path, "uuid:" + path)
            if node not in ids:
                ids.append(node)
        return ids

    def objExists(self, name):
        # The one query #799 exempts: objExists ANSWERS for a vanished
        # node, it does not raise.
        return self._exists(name)

    def listRelatives(self, node, shapes=False, fullPath=False,
                      parent=False, **kw):
        """Both directions. The shape -> transform one is what #796's hint
        needs: whether naming every wearer would walk into validate()'s
        short-name collision refusal, which compares TRANSFORM names."""
        self._require(node)
        if parent:
            for transform, shape in self.meshes.items():
                if shape == node:
                    return [transform]
            return None
        return [self.meshes[node]] if shapes and node in self.meshes else None

    def nodeType(self, node):
        self._require(node)
        if node in self.meshes.values():
            return "mesh"
        if node in self.types:
            return self.types[node]
        if node in self.sg_members:
            return "shadingEngine"
        return "transform"   # _require leaves only self.meshes keys here

    def polyEvaluate(self, node, uvcoord=False, **kw):
        # A node that is not there is NOT "a mesh with no UVs": that
        # conflation is what _uv_count's own comment refuses to make, and
        # the fake used to make it for every unknown name (#799).
        self._require(node)
        return self.uv_counts.get(node, 0) if uvcoord else 0

    # graph -----------------------------------------------------------
    def listSets(self, object=None, type=None):
        self._require(object)
        return list(self.shape_sgs.get(object, []))

    def sets(self, name, query=False, **kw):
        if query:
            # An empty list used to be the answer for a set that does not
            # EXIST, which reads as "worn by nobody" - Maya raises, and
            # _outside_wearers' degrade-not-crash guard is what has to
            # absorb that (#799). An EMPTY set is a different thing and
            # Maya answers it, so existence - not membership - is the test.
            self._require(name)
            return list(self.sg_members.get(name, []))
        raise NotImplementedError("query only")

    def listConnections(self, plug, source=False, destination=True,
                        plugs=False, **kw):
        node = plug.split(".")[0]
        self._require(node)
        has_attr = "." in plug
        if source:
            if has_attr:
                srcs = list(self.conns.get(plug) or [])
            else:
                srcs = []
                for dst, srclist in self.conns.items():
                    if dst.split(".")[0] == node:
                        srcs.extend(srclist)
            if not srcs:
                return None
            return srcs if plugs else [s.split(".")[0] for s in srcs]
        dsts = []
        for dst, srclist in self.conns.items():
            for src in srclist:
                matched = (src == plug) if has_attr else (
                    src.split(".")[0] == node)
                if matched:
                    dsts.append(dst)
                    break
        return (dsts if plugs else [d.split(".")[0] for d in dsts]) or None

    def attributeQuery(self, attr, node=None, exists=False):
        self._require(node)
        return ("%s.%s" % (node, attr)) in self.existing_attrs

    def getAttr(self, plug, **kw):
        """The plug's value. "" is the modelled answer for an attribute
        this fake has no value for - Maya answers the attribute's default
        the same way - but it is reached only AFTER the node is known to
        exist, which is the half that used to be missing (#799)."""
        self._require(plug.split(".")[0])
        return self.attr_values.get(plug, "")

    # mutation --------------------------------------------------------
    def shadingNode(self, node_type, name=None, **kw):
        self.types[name] = node_type
        self.created.append(name)
        return name

    def setAttr(self, plug, *values, **kw):
        self._require(plug.split(".")[0])
        blocker = self._static_write_blocker(plug)
        if blocker:
            raise RuntimeError(
                "setAttr: The attribute '%s' is locked or connected and "
                "cannot be modified (%s feeds it)" % (plug, blocker))
        self.attr_values[plug] = list(values) if len(values) > 1 else (
            values[0] if values else None)

    def connectAttr(self, src, dst, force=False):
        self._require(src.split(".")[0])
        self._require(dst.split(".")[0])
        if dst in self.conns and not force:
            raise RuntimeError(
                "connectAttr: The destination attribute '%s' cannot be "
                "connected because it is already connected." % dst)
        self.connected.append((src, dst))
        self.conns[dst] = [src]

    def delete(self, *nodes):
        for n in nodes:
            self.deleted.append(n)
            # Deletion is REGISTRY removal, not a tombstone (#799 round
            # 2): a name re-created afterwards exists again, exactly as in
            # Maya - and this module re-creates `mcpBake_<map>` once per
            # mesh.
            self.types.pop(n, None)
            self.sg_members.pop(n, None)
            self.shape_sgs.pop(n, None)
            if n in self.meshes:
                self.shape_sgs.pop(self.meshes.pop(n), None)
            for dst in list(self.conns):
                if dst.split(".")[0] == n:
                    del self.conns[dst]
                    continue
                self.conns[dst] = [s for s in self.conns[dst]
                                   if s.split(".")[0] != n]
                if not self.conns[dst]:
                    del self.conns[dst]

    def select(self, *args, **kw):
        if kw.get("clear"):
            self.selection = []
        elif args:
            arg = args[0]
            self.selection = list(arg) if isinstance(arg, list) else [arg]

    def pluginInfo(self, name, query=False, loaded=False, path=False):
        if path:
            return getattr(self, "plugin_path", "")
        return name in self.plugins_loaded

    def loadPlugin(self, name, quiet=False):
        self.plugins_loaded.append(name)
        return [name]


def _fake_bake(fake, exr_name="bakeShape.exr"):
    """Stand in for arnoldRenderToTexture: drop one EXR-named file into the
    private folder, the way the real command was measured to."""
    def _bake(cmds, shape, folder, resolution, shader, extend_edges):
        with open(os.path.join(folder, exr_name), "wb") as fh:
            fh.write(b"exr")
        fake.baked_calls.append((shape, resolution, shader, extend_edges))
    fake.baked_calls = []
    return _bake


def _fake_convert(rows=None, colour_type=6):
    """Stand in for the MImage EXR->PNG conversion: write a REAL png so the
    stats machinery runs for real."""
    def _convert(cmds, src, dst):
        _png(dst, rows or _rich_rgba_rows(), colour_type=colour_type)
    return _convert


@pytest.fixture
def fake(monkeypatch):
    cmds = FakeCmds()
    monkeypatch.setattr(meshmaps, "_cmds", lambda: cmds)
    monkeypatch.setattr(meshmaps, "_ensure_mtoa", lambda c: None)
    monkeypatch.setattr(meshmaps, "_arnold_bake", _fake_bake(cmds))
    monkeypatch.setattr(meshmaps, "_exr_to_png", _fake_convert())
    monkeypatch.setattr(meshmaps.session, "auto_checkpoint",
                        lambda reason: (cmds.checkpoints.append(reason)
                                        or {"checkpoint_id": "cp",
                                            "path": "cp.ma"}))
    return cmds


def _params(tmp_path, **kw):
    base = {"meshes": ["|limb"], "out_dir": str(tmp_path)}
    base.update(kw)
    return base


class TestValidation:
    def test_meshes_is_required(self, fake, tmp_path):
        with pytest.raises(HandlerError, match="meshes"):
            meshmaps.validate({"out_dir": str(tmp_path)}, fake)

    def test_out_dir_must_exist(self, fake, tmp_path):
        with pytest.raises(HandlerError, match="does not exist"):
            meshmaps.validate(_params(tmp_path,
                                      out_dir=str(tmp_path / "nope")), fake)

    def test_out_dir_must_be_absolute(self, fake, tmp_path):
        with pytest.raises(HandlerError, match="absolute"):
            meshmaps.validate(_params(tmp_path, out_dir="rel/dir"), fake)

    def test_resolution_must_be_supported(self, fake, tmp_path):
        with pytest.raises(HandlerError, match="resolution"):
            meshmaps.validate(_params(tmp_path, resolution=1000), fake)

    def test_an_unknown_map_refuses(self, fake, tmp_path):
        with pytest.raises(HandlerError, match="tangent_normal"):
            meshmaps.validate(_params(tmp_path, maps=["tangent_normal"]),
                              fake)

    def test_an_unknown_param_refuses_with_the_764_guard(self, fake,
                                                         tmp_path):
        with pytest.raises(HandlerError, match="map"):
            meshmaps.validate(_params(tmp_path, map=["ao"]), fake)

    def test_defaults(self, fake, tmp_path):
        out = meshmaps.validate(_params(tmp_path), fake)
        assert out["maps"] == ["ao", "curvature", "world_normal"]
        assert out["resolution"] == 1024
        assert out["apply_ao"] is False
        assert out["curvature_output"] == "convex"
        assert out["meshes"] == [("|limb", "|limbShape")]

    def test_a_uv_less_mesh_refuses_naming_the_fix(self, fake, tmp_path):
        # MEASURED (Q5): the bake RETURNS NORMALLY and writes a corrupt EXR
        # that only fails at read - Maya raises in the wrong place, too late.
        fake.uv_counts["|limbShape"] = 0
        with pytest.raises(HandlerError, match="no UVs") as exc:
            meshmaps.validate(_params(tmp_path), fake)
        assert "maya_uv_atlas" in (exc.value.hint or "")

    def test_short_name_collisions_refuse(self, fake, tmp_path):
        # MEASURED (Q4): Arnold names the output file itself, and renames on
        # collision - this tool refuses rather than parsing that rule.
        fake.meshes["|left|limb"] = "|left|limbShape"
        fake.uv_counts["|left|limbShape"] = 8
        with pytest.raises(HandlerError, match="short name"):
            meshmaps.validate(_params(tmp_path,
                                      meshes=["|limb", "|left|limb"]), fake)

    def test_curvature_output_must_be_an_enum_value(self, fake, tmp_path):
        with pytest.raises(HandlerError, match="curvature_output"):
            meshmaps.validate(_params(tmp_path, curvature_output="edges"),
                              fake)


class TestRequireSoleWearers:
    """The material-level guard, factored out of plan_apply so the callers
    that rewire a SHADER rather than a colour slot run it too (#767 minor
    M1: apply_surface_detail's grain-only path wires bump into
    shader.normalCamera and was bypassing every one of these)."""

    def test_it_groups_the_wearers_under_their_shader(self, fake, tmp_path):
        fake.meshes["|collar"] = "|collarShape"
        fake.uv_counts["|collarShape"] = 8
        fake.shape_sgs["|collarShape"] = ["limbSG"]
        fake.sg_members["limbSG"] = ["|limbShape", "|collarShape"]
        wearers = meshmaps.require_sole_wearers(
            fake, [("|limb", "|limbShape"), ("|collar", "|collarShape")])
        assert list(wearers) == ["limb_mat"]
        assert wearers["limb_mat"]["sg"] == "limbSG"
        assert [w[0] for w in wearers["limb_mat"]["wearers"]] == ["|limb",
                                                                  "|collar"]

    def test_a_multi_sg_mesh_refuses(self, fake, tmp_path):
        fake.shape_sgs["|limbShape"] = ["limbSG", "trimSG"]
        with pytest.raises(HandlerError, match="shading groups"):
            meshmaps.require_sole_wearers(fake, [("|limb", "|limbShape")])

    def test_a_shading_group_without_a_surface_shader_refuses(self, fake,
                                                              tmp_path):
        del fake.conns["limbSG.surfaceShader"]
        with pytest.raises(HandlerError, match="no surface shader") as exc:
            meshmaps.require_sole_wearers(fake, [("|limb", "|limbShape")])
        assert "maya_assign_material" in (exc.value.hint or "")

    def test_a_wearer_outside_the_request_refuses(self, fake, tmp_path):
        fake.meshes["|other"] = "|otherShape"
        fake.uv_counts["|otherShape"] = 8
        fake.sg_members["limbSG"] = ["|limbShape", "|otherShape"]
        with pytest.raises(HandlerError, match="otherShape"):
            meshmaps.require_sole_wearers(fake, [("|limb", "|limbShape")])

    def _mirrored(self, fake):
        """|left|limb and |right|limb, two shape nodes, one material."""
        fake.meshes = {"|left|limb": "|left|limbShape",
                       "|right|limb": "|right|limbShape"}
        fake.uv_counts = {"|left|limbShape": 64, "|right|limbShape": 64}
        fake.shape_sgs = {"|left|limbShape": ["limbSG"],
                          "|right|limbShape": ["limbSG"]}
        # PARTIAL paths: cmds.sets(query=True) answers with the shortest
        # UNIQUE name, which for these two mirrors is 'left|limbShape' -
        # not the bare short name and not the full path.
        fake.sg_members["limbSG"] = ["left|limbShape", "right|limbShape"]

    def _instanced(self, fake, members=None):
        """ONE shape node under TWO DAG paths, wearing one material.

        Two distinct TRANSFORMS share one shape node (fake.node_of), and
        the assignment sits on that node, so both paths wear the SG.
        `members` is what cmds.sets answers with: the node's own name -
        which `cmds.ls(long=True)` resolves to ONE of its paths, since
        enumerating the rest needs `allPaths=True` and nothing asks for it
        (#796 round 4) - or one absolute path per instance. Maya picks the
        shortest UNIQUE form, and at THIS call site guessing wrong is a
        hard refusal, not a warning.
        """
        fake.meshes = {"|grpA|cube": "|grpA|cube|cubeShape",
                       "|grpB|cube": "|grpB|cube|cubeShape"}
        fake.node_of = {"|grpA|cube|cubeShape": "uuid:cubeShape",
                        "|grpB|cube|cubeShape": "uuid:cubeShape"}
        fake.uv_counts = {"|grpA|cube|cubeShape": 64,
                          "|grpB|cube|cubeShape": 64}
        fake.shape_sgs = {"|grpA|cube|cubeShape": ["limbSG"],
                          "|grpB|cube|cubeShape": ["limbSG"]}
        fake.sg_members["limbSG"] = list(members or ["cubeShape"])

    def test_the_mirrored_twin_of_the_requested_mesh_refuses(self, fake,
                                                             tmp_path):
        """#796 defect 3 at this call site: |left|limb and |right|limb
        share a short name (uniqueness is per PARENT), so the guard's old
        short-name arm let the unnamed mirror through - the exact mesh a
        mirrored rig has, and its look changes too."""
        self._mirrored(fake)

        with pytest.raises(HandlerError, match=r"\|right\|limbShape"):
            meshmaps.require_sole_wearers(
                fake, [("|left|limb", "|left|limbShape")])

    def test_an_instanced_mesh_is_not_an_outside_wearer_of_itself(
            self, fake, tmp_path):
        """#796 fix round 2 at the call site that RAISES: reporting an
        ambiguous member under every path it resolves to refused a
        legitimate bake, because an instance's other path is the very
        shape node the caller named. This is the case the warning-only
        call site in texbake could not make visible."""
        self._instanced(fake)

        wearers = meshmaps.require_sole_wearers(
            fake, [("|grpA|cube", "|grpA|cube|cubeShape")])

        assert list(wearers) == ["limb_mat"]

    def test_an_instance_named_by_absolute_path_still_bakes(self, fake,
                                                            tmp_path):
        """#796 fix round 3 at the raising site. Round 2 skipped a member
        only when one of its RESOLVED PATHS was a requested path, so the
        refusal survived whenever cmds.sets answered with one absolute
        path per instance instead of the ambiguous node name - and then a
        legitimate bake was refused, naming a path of the very shape node
        the caller had asked for, with a hint (rename it, or give it its
        own material) that cannot be followed because there is only one
        node to rename. Identity is the node now, so neither name form
        can produce this.
        """
        self._instanced(fake, ["|grpA|cube|cubeShape",
                               "|grpB|cube|cubeShape"])

        wearers = meshmaps.require_sole_wearers(
            fake, [("|grpA|cube", "|grpA|cube|cubeShape")])

        assert list(wearers) == ["limb_mat"]

    def test_the_mirrored_twin_is_refused_when_the_member_is_ambiguous(
            self, fake, tmp_path):
        """#796 round 4, defect A, at the call site that RAISES.

        The member skip used to drop every node a member name resolved to
        as soon as ONE of them was the caller's own mesh. An ambiguous
        member name on a mirrored rig resolves to BOTH limbs, so the right
        limb - a different NODE, about to have its look changed by a
        material-level edit nobody asked for on its behalf - stopped being
        refused. Which name form `cmds.sets` answers with is Maya's choice
        and unmeasured; the refusal must not depend on it.
        """
        self._mirrored(fake)
        fake.sg_members["limbSG"] = ["limbShape"]

        with pytest.raises(HandlerError, match=r"\|right\|limbShape"):
            meshmaps.require_sole_wearers(
                fake, [("|left|limb", "|left|limbShape")])

    def test_the_mirrored_twin_is_still_refused_when_the_member_is_absolute(
            self, fake, tmp_path):
        """The other half: a mirrored pair is TWO shape nodes, so the
        absolute name form must not buy an instance's skip. Without this
        the round-3 fix could 'pass' by never refusing anything."""
        self._mirrored(fake)
        fake.sg_members["limbSG"] = ["|left|limbShape", "|right|limbShape"]

        with pytest.raises(HandlerError, match=r"\|right\|limbShape"):
            meshmaps.require_sole_wearers(
                fake, [("|left|limb", "|left|limbShape")])

    def test_the_mirrored_refusal_hint_is_followable(self, fake, tmp_path):
        """#796 fix round 2, D4. This refusal only started firing on
        MIRRORED rigs with the canonicalisation fix - and mirrored
        transforms share their short name BY DEFINITION, which validate()
        refuses outright (#770: Arnold renames colliding outputs by a rule
        this tool will not guess). So the hint's "name every wearer"
        branch was a dead end on exactly the rig that makes the guard
        fire. BOTH refusals are measured here, so the two guards cannot
        drift back into contradiction.
        """
        self._mirrored(fake)

        with pytest.raises(HandlerError) as outside:
            meshmaps.require_sole_wearers(
                fake, [("|left|limb", "|left|limbShape")])
        hint = outside.value.hint or ""

        # The dead end, measured rather than assumed: taking the advice
        # this hint used to give runs straight into the #770 guard.
        with pytest.raises(HandlerError, match="share the short name"):
            meshmaps.validate({"meshes": ["|left|limb", "|right|limb"],
                               "out_dir": str(tmp_path)}, fake)

        assert "name every wearer" not in hint
        assert "maya_rename" in hint
        assert "own material" in hint

    def test_the_hint_still_offers_both_routes_when_the_names_do_not_collide(
            self, fake, tmp_path):
        """The unfollowable branch is dropped only where it IS
        unfollowable - naming every wearer is the cheaper fix otherwise."""
        fake.meshes["|other"] = "|otherShape"
        fake.uv_counts["|otherShape"] = 8
        fake.sg_members["limbSG"] = ["|limbShape", "|otherShape"]

        with pytest.raises(HandlerError) as exc:
            meshmaps.require_sole_wearers(fake, [("|limb", "|limbShape")])

        assert "name every wearer" in (exc.value.hint or "")

    def test_the_refusal_names_the_edit_the_caller_actually_asked_for(
            self, fake, tmp_path):
        """The guard is shared, so the harm has to be described in the
        caller's terms - a grain call told about "compositing AO" is being
        read an effect it never asked for, and apply_ao is not even one of
        its params."""
        fake.meshes["|other"] = "|otherShape"
        fake.uv_counts["|otherShape"] = 8
        fake.sg_members["limbSG"] = ["|limbShape", "|otherShape"]
        with pytest.raises(HandlerError) as exc:
            meshmaps.require_sole_wearers(
                fake, [("|limb", "|limbShape")], "adding grain to it")
        assert "adding grain to it" in str(exc.value)
        assert "AO" not in str(exc.value)

    def test_plan_apply_reports_an_unusable_shader_before_a_shared_one(
            self, fake, tmp_path):
        """Order matters when a material is BOTH unmapped and shared.

        A shader type this tool cannot composite into is unusable no matter
        who else wears it, so it is the more useful thing to say first;
        reporting the shared wearer instead sends the caller off to split
        materials before they meet the real blocker. plan_apply therefore
        keeps the colour-slot check BETWEEN the two halves of the guard.
        """
        fake.meshes["|other"] = "|otherShape"
        fake.uv_counts["|otherShape"] = 8
        fake.sg_members["limbSG"] = ["|limbShape", "|otherShape"]
        fake.types["limb_mat"] = "openPBR_shader"
        settings = meshmaps.validate(_params(tmp_path, apply_ao=True), fake)
        with pytest.raises(HandlerError) as exc:
            meshmaps.plan_apply(fake, settings["meshes"])
        assert "no colour-slot mapping" in str(exc.value)


class TestPlanApply:
    def test_a_plain_colour_material_is_a_value_base(self, fake, tmp_path):
        settings = meshmaps.validate(_params(tmp_path, apply_ao=True), fake)
        jobs, warnings = meshmaps.plan_apply(fake, settings["meshes"])
        assert len(jobs) == 1
        job = jobs[0]
        assert job["material"] == "limb_mat"
        assert job["attr"] == "baseColor"
        assert job["base"]["kind"] == "value"
        assert job["base"]["rgb"] == (1.0, 1.0, 1.0)
        assert [w[0] for w in job["wearers"]] == ["|limb"]

    def test_a_png_backed_colour_is_a_file_base(self, fake, tmp_path):
        base = _png(tmp_path / "albedo.png", [[(200, 100, 50)]])
        fake.types["kit_file"] = "file"
        fake.conns["limb_mat.baseColor"] = ["kit_file.outColor"]
        fake.attr_values["kit_file.fileTextureName"] = base
        fake.attr_values["kit_file.colorSpace"] = "sRGB"
        settings = meshmaps.validate(_params(tmp_path, apply_ao=True), fake)
        jobs, _w = meshmaps.plan_apply(fake, settings["meshes"])
        assert jobs[0]["base"]["kind"] == "file"
        assert jobs[0]["base"]["path"] == base
        assert jobs[0]["base"]["colorspace"] == "sRGB"
        assert jobs[0]["base"]["file_node"] == "kit_file"

    def test_a_procedural_colour_refuses_naming_bake_textures(self, fake,
                                                              tmp_path):
        fake.types["mcpTex_noise"] = "noise"
        fake.conns["limb_mat.baseColor"] = ["mcpTex_noise.outColor"]
        settings = meshmaps.validate(_params(tmp_path, apply_ao=True), fake)
        with pytest.raises(HandlerError, match="procedural") as exc:
            meshmaps.plan_apply(fake, settings["meshes"])
        assert "maya_bake_textures" in (exc.value.hint or "")

    def test_a_wearer_outside_the_request_refuses(self, fake, tmp_path):
        fake.meshes["|other"] = "|otherShape"
        fake.uv_counts["|otherShape"] = 8
        fake.sg_members["limbSG"] = ["|limbShape", "|otherShape"]
        settings = meshmaps.validate(_params(tmp_path, apply_ao=True), fake)
        with pytest.raises(HandlerError, match="otherShape"):
            meshmaps.plan_apply(fake, settings["meshes"])

    def test_a_shared_material_becomes_one_masked_job(self, fake, tmp_path):
        fake.meshes["|collar"] = "|collarShape"
        fake.uv_counts["|collarShape"] = 8
        fake.shape_sgs["|collarShape"] = ["limbSG"]
        fake.sg_members["limbSG"] = ["|limbShape", "|collarShape"]
        settings = meshmaps.validate(
            _params(tmp_path, apply_ao=True, meshes=["|limb", "|collar"]),
            fake)
        jobs, _w = meshmaps.plan_apply(fake, settings["meshes"])
        assert len(jobs) == 1
        assert sorted(w[0] for w in jobs[0]["wearers"]) == ["|collar",
                                                            "|limb"]
        assert jobs[0]["masked"] is True

    def test_a_non_png_file_base_refuses(self, fake, tmp_path):
        fake.types["kit_file"] = "file"
        fake.conns["limb_mat.baseColor"] = ["kit_file.outColor"]
        fake.attr_values["kit_file.fileTextureName"] = str(
            tmp_path / "albedo.jpg")
        settings = meshmaps.validate(_params(tmp_path, apply_ao=True), fake)
        with pytest.raises(HandlerError, match="cannot be read"):
            meshmaps.plan_apply(fake, settings["meshes"])


class TestBake:
    def test_a_bake_lands_files_and_stats(self, fake, tmp_path):
        out = meshmaps.bake_mesh_maps(_params(tmp_path, maps=["ao"]))
        assert len(out["baked"]) == 1
        entry = out["baked"][0]
        assert entry["mesh"] == "|limb"
        assert entry["map"] == "ao"
        assert entry["basename"] == "limb_ao.png"
        assert os.path.isfile(entry["file"])
        assert entry["stats"]["non_uniform"] is True
        assert entry["stats"]["blank"] is False
        assert not list(tmp_path.glob("*.part*"))
        assert out["checkpoint_id"] is None  # nothing applied, no mutation

    def test_every_requested_map_bakes(self, fake, tmp_path):
        out = meshmaps.bake_mesh_maps(_params(tmp_path))
        assert [b["map"] for b in out["baked"]] == ["ao", "curvature",
                                                    "world_normal"]

    def test_temp_shader_nodes_are_deleted(self, fake, tmp_path):
        meshmaps.bake_mesh_maps(_params(tmp_path, maps=["ao", "curvature"]))
        assert fake.created  # shaders were made...
        for node in fake.created:
            assert node in fake.deleted  # ...and none survive

    def test_a_flat_map_warns_but_ships(self, fake, tmp_path, monkeypatch):
        # MEASURED (Q3): concave curvature on convex-only geometry is
        # honestly all-zero; refusing a flat map here would refuse the truth.
        monkeypatch.setattr(
            meshmaps, "_exr_to_png",
            _fake_convert(rows=[[(0, 0, 0, 255)] * 4] * 4))
        out = meshmaps.bake_mesh_maps(
            _params(tmp_path, maps=["curvature"],
                    curvature_output="concave"))
        assert len(out["baked"]) == 1
        assert out["baked"][0]["stats"]["non_uniform"] is False
        assert any("flat" in w for w in out["warnings"])

    def test_a_bake_that_writes_nothing_refuses(self, fake, tmp_path,
                                                monkeypatch):
        monkeypatch.setattr(meshmaps, "_arnold_bake",
                            lambda *a, **kw: None)
        with pytest.raises(HandlerError, match="no EXR"):
            meshmaps.bake_mesh_maps(_params(tmp_path, maps=["ao"]))
        assert not list(tmp_path.glob("*"))  # nothing committed

    def test_an_unreadable_bake_refuses_and_sweeps(self, fake, tmp_path,
                                                   monkeypatch):
        # MEASURED (Q5): this is where a UV-less-style corrupt EXR actually
        # surfaces - the conversion, not the bake.
        def _boom(cmds, src, dst):
            raise RuntimeError("(kFailure): Unexpected Internal Failure")
        monkeypatch.setattr(meshmaps, "_exr_to_png", _boom)
        with pytest.raises(HandlerError, match="could not be read"):
            meshmaps.bake_mesh_maps(_params(tmp_path, maps=["ao"]))
        assert not list(tmp_path.glob("*.part*"))

    def test_selection_is_restored(self, fake, tmp_path):
        fake.selection = ["|somethingElse"]
        meshmaps.bake_mesh_maps(_params(tmp_path, maps=["ao"]))
        assert fake.selection == ["|somethingElse"]


class TestConversionTooling:
    """MEASURED (live gate, first run): MImage.writeToFile('png') zeroes
    the ALPHA CHANNEL in a GUI Maya session while the same call on the
    same EXR is correct under maya.standalone - every headless test was
    green while the live bake read as 'drew nothing'. The conversion
    therefore runs through Arnold's own oiiotool, a subprocess that
    behaves identically everywhere (byte-identical output measured)."""

    def test_oiiotool_is_found_next_to_the_mtoa_plugin(self, fake, tmp_path):
        plugin_dir = tmp_path / "Arnold" / "plug-ins"
        bin_dir = tmp_path / "Arnold" / "bin"
        plugin_dir.mkdir(parents=True)
        bin_dir.mkdir(parents=True)
        exe = bin_dir / ("oiiotool.exe" if os.name == "nt" else "oiiotool")
        exe.write_bytes(b"")
        fake.plugin_path = str(plugin_dir / "mtoa.mll")
        assert meshmaps._find_oiiotool(fake) == str(exe)

    def test_a_missing_oiiotool_refuses_rather_than_falling_back(
            self, fake, tmp_path):
        # The MImage path is measured BROKEN in GUI sessions - silently
        # falling back to it would resurrect the exact defect the live
        # gate caught.
        fake.plugin_path = str(tmp_path / "nowhere" / "mtoa.mll")
        with pytest.raises(HandlerError, match="oiiotool"):
            meshmaps._find_oiiotool(fake)


class TestEvidenceKeeping:
    def test_a_blank_bake_keeps_its_part_file_for_inspection(
            self, fake, tmp_path, monkeypatch):
        # The refusal hint names the part file as left on disk - so it
        # must actually BE left (live gate, first run: the hint promised
        # a file the sweep had already deleted).
        monkeypatch.setattr(
            meshmaps, "_exr_to_png",
            _fake_convert(rows=[[(9, 9, 9, 0)] * 4] * 4))
        with pytest.raises(HandlerError, match="drew nothing"):
            meshmaps.bake_mesh_maps(_params(tmp_path, maps=["ao"]))
        assert list(tmp_path.glob("*.part.png"))  # evidence kept

    def test_earlier_good_parts_are_still_swept_on_a_later_refusal(
            self, fake, tmp_path, monkeypatch):
        calls = {"n": 0}
        good = _fake_convert()

        def _convert(cmds_arg, src, dst):
            calls["n"] += 1
            if calls["n"] == 2:
                _png(dst, [[(9, 9, 9, 0)] * 4] * 4, colour_type=6)
            else:
                good(cmds_arg, src, dst)
        monkeypatch.setattr(meshmaps, "_exr_to_png", _convert)
        with pytest.raises(HandlerError, match="drew nothing"):
            meshmaps.bake_mesh_maps(_params(tmp_path,
                                            maps=["ao", "curvature"]))
        parts = [p.name for p in tmp_path.glob("*.part.png")]
        assert parts == ["limb_curvature.png.part.png"]  # only the evidence


class TestCompositeMath:
    def test_half_ao_on_a_white_value_base_encodes_srgb(self):
        # MEASURED (T1): the AO png holds LINEAR values - 127 is 0.5. A
        # white base at half AO must come out sRGB-encoded (~188), not 127:
        # multiplying display bytes directly would double-darken every
        # contact shadow.
        ao = {"pixels": [(127, 0, 0, 255)], "width": 1, "height": 1,
              "masked": False}
        out = meshmaps.composite_ao({"kind": "value", "rgb": (1.0, 1.0, 1.0)},
                                    [ao], 1)
        assert out["overlap_fraction"] == 0.0
        r = out["pixels"][0][0]
        assert 185 <= r <= 191

    def test_full_ao_leaves_an_srgb_file_base_untouched(self, tmp_path):
        base_png = _png(tmp_path / "b.png", [[(200, 100, 50)]])
        base = meshmaps.load_base_pixels({"kind": "file", "path": base_png,
                                          "colorspace": "sRGB"})
        ao = {"pixels": [(255, 0, 0, 255)], "width": 1, "height": 1,
              "masked": False}
        out = meshmaps.composite_ao(base, [ao], 1)
        assert out["pixels"][0] == (200, 100, 50)

    def test_masked_layers_apply_only_where_opaque(self):
        # Two wearers of one atlas: each bake's alpha marks its own shells
        # (MEASURED: unpadded bakes keep alpha honest; extend_edges floods
        # it to 1.0, which is why masked layers bake unpadded).
        # left claims the left column (opaque, AO=0), right the right
        # column (opaque, AO=127); each is transparent over the other's.
        left = {"pixels": [(0, 0, 0, 255), (0, 0, 0, 0)] * 2, "width": 2,
                "height": 2, "masked": True}
        right = {"pixels": [(0, 0, 0, 0), (127, 0, 0, 255)] * 2, "width": 2,
                 "height": 2, "masked": True}
        out = meshmaps.composite_ao({"kind": "value", "rgb": (1.0, 1.0, 1.0)},
                                    [left, right], 2)
        assert out["pixels"][0] == (0, 0, 0)       # left's zone: fully dark
        assert 185 <= out["pixels"][1][0] <= 191   # right's zone: half AO
        assert out["overlap_fraction"] == 0.0

    def test_overlapping_masks_are_reported(self):
        both = {"pixels": [(127, 0, 0, 255)], "width": 1, "height": 1,
                "masked": True}
        out = meshmaps.composite_ao({"kind": "value", "rgb": (1.0, 1.0, 1.0)},
                                    [both, dict(both)], 1)
        assert out["overlap_fraction"] == 1.0


class TestApply:
    def test_apply_rewires_and_checkpoints(self, fake, tmp_path):
        out = meshmaps.bake_mesh_maps(_params(tmp_path, maps=["ao"],
                                              apply_ao=True))
        assert fake.checkpoints == ["bake_mesh_maps"]
        assert out["checkpoint_id"] == "cp"
        assert len(out["applied"]) == 1
        applied = out["applied"][0]
        assert applied["material"] == "limb_mat"
        assert os.path.isfile(applied["file"])
        assert applied["basename"] == "limb_mat_color_ao.png"
        # the slot now reads the composite through a file node
        assert any(dst == "limb_mat.baseColor"
                   for _src, dst in fake.connected)

    def test_apply_replaces_a_file_base_and_sweeps_the_old_node(
            self, fake, tmp_path):
        base = _png(tmp_path / "albedo.png", [[(200, 100, 50)]])
        fake.types["kit_file"] = "file"
        fake.conns["limb_mat.baseColor"] = ["kit_file.outColor"]
        fake.attr_values["kit_file.fileTextureName"] = base
        fake.attr_values["kit_file.colorSpace"] = "sRGB"
        out = meshmaps.bake_mesh_maps(_params(tmp_path, maps=["ao"],
                                              apply_ao=True))
        assert "kit_file" in fake.deleted
        assert os.path.isfile(base)  # the input atlas is NEVER overwritten
        assert out["applied"][0]["replaced_file"] == base

    def test_apply_refusals_fire_before_any_bake(self, fake, tmp_path):
        fake.types["mcpTex_noise"] = "noise"
        fake.conns["limb_mat.baseColor"] = ["mcpTex_noise.outColor"]
        with pytest.raises(HandlerError, match="procedural"):
            meshmaps.bake_mesh_maps(_params(tmp_path, maps=["ao"],
                                            apply_ao=True))
        assert fake.baked_calls == []  # planned refusal, no wasted bake
        assert not list(tmp_path.glob("*"))

    def test_apply_without_ao_in_maps_refuses(self, fake, tmp_path):
        with pytest.raises(HandlerError, match="apply_ao"):
            meshmaps.validate(_params(tmp_path, maps=["curvature"],
                                      apply_ao=True), fake)


class TestTheFakeRefusesWhatMayaRefuses:
    """#799 round 2: the regression barrier for THIS file's FakeCmds.

    Round 1's hardening was measured to be INERT with respect to the
    suite - neutering every new refusal left 184 passed / 2 xfailed / 0
    failed across the five look-group files, so the ticket's own premise
    ("a green suite proves nothing") was reproduced one level up. These
    tests are the barrier: loosening any modelled refusal below has to go
    red.
    """

    # contract 1 - a name the scene does not hold ---------------------
    def test_a_query_about_a_deleted_node_raises(self, fake):
        fake.shadingNode("aiAmbientOcclusion", name="mcpBake_ao")
        fake.delete("mcpBake_ao")
        for call in (lambda: fake.nodeType("mcpBake_ao"),
                     lambda: fake.getAttr("mcpBake_ao.output"),
                     lambda: fake.setAttr("mcpBake_ao.samples", 4),
                     lambda: fake.listConnections("mcpBake_ao.output",
                                                  source=True),
                     lambda: fake.attributeQuery("output", node="mcpBake_ao",
                                                 exists=True),
                     lambda: fake.polyEvaluate("mcpBake_ao", uvcoord=True),
                     lambda: fake.listSets(object="mcpBake_ao")):
            with pytest.raises(RuntimeError, match="No object matches name"):
                call()

    def test_a_query_about_a_node_that_never_existed_raises(self, fake):
        with pytest.raises(RuntimeError, match="No object matches name"):
            fake.nodeType("never_made")
        with pytest.raises(RuntimeError, match="No object matches name"):
            fake.polyEvaluate("never_made", uvcoord=True)

    def test_objExists_answers_for_a_vanished_node_instead_of_raising(
            self, fake):
        fake.shadingNode("aiAmbientOcclusion", name="mcpBake_ao")
        assert fake.objExists("mcpBake_ao") is True
        fake.delete("mcpBake_ao")
        assert fake.objExists("mcpBake_ao") is False
        assert fake.objExists("never_made") is False

    def test_a_deleted_name_re_created_exists_again(self, fake):
        """The round-2 BLOCKING defect, in miniature. `self.deleted` was a
        permanent tombstone `shadingNode` could not clear, so a re-created
        name was present in `types` and absent to `_require` at once."""
        fake.shadingNode("aiAmbientOcclusion", name="mcpBake_ao")
        fake.delete("mcpBake_ao")
        fake.shadingNode("aiAmbientOcclusion", name="mcpBake_ao")
        assert fake.objExists("mcpBake_ao") is True
        assert fake.nodeType("mcpBake_ao") == "aiAmbientOcclusion"
        fake.setAttr("mcpBake_ao.output", 1.0)       # must not raise
        assert fake.deleted == ["mcpBake_ao"]        # still a RECORD

    def test_two_meshes_bake_end_to_end_through_the_same_shader_name(
            self, fake, tmp_path):
        """The defect as the reviewer found it, driven through the REAL
        handler. `_make_bake_shader` builds `mcpBake_<map>` and deletes it
        in a `finally` on every (mesh, map) iteration, so the second mesh
        re-creates a name the first deleted; a tombstoned fake died with
        "No object matches name: mcpBake_curvature" on a node created one
        line earlier - and it died inside the handler bare `except
        Exception` guards, the direction that gets swallowed."""
        fake.meshes["|collar"] = "|collarShape"
        fake.uv_counts["|collarShape"] = 64
        fake.types["collar_mat"] = "standardSurface"
        fake.shape_sgs["|collarShape"] = ["collarSG"]
        fake.sg_members["collarSG"] = ["|collarShape"]
        fake.conns["collarSG.surfaceShader"] = ["collar_mat.outColor"]
        fake.existing_attrs.add("collar_mat.baseColor")
        fake.attr_values["collar_mat.baseColor"] = [(1.0, 1.0, 1.0)]

        result = meshmaps.bake_mesh_maps(
            _params(tmp_path, meshes=["|limb", "|collar"],
                    maps=["curvature"]))

        assert [b["mesh"] for b in result["baked"]] == ["|limb", "|collar"]
        # the same name, created and consumed once per mesh
        assert fake.created == ["mcpBake_curvature"] * 2
        assert fake.deleted == ["mcpBake_curvature"] * 2

    # contract 1, strict direction ------------------------------------
    def test_an_existing_but_empty_shading_group_answers_rather_than_raises(
            self, fake):
        """A set that does not EXIST raises; a set that exists and holds
        nothing answers []. Round 1 refused both - wrong in the STRICT
        direction, which produces spurious failures the next agent fixes
        by weakening the fake back."""
        # An SG that EXISTS but has no members: registered as a node,
        # absent from the membership registry. Round 1 keyed the
        # refusal on membership, so this - a real, empty set - raised.
        fake.types["emptySG"] = "shadingEngine"
        assert fake.objExists("emptySG") is True
        assert fake.sets("emptySG", query=True) == []
        assert fake.sets("limbSG", query=True) == ["|limbShape"]
        with pytest.raises(RuntimeError, match="No object matches name"):
            fake.sets("noSuchSG", query=True)

    # contract 2 - locked or connected --------------------------------
    def test_setAttr_refuses_a_plug_a_connection_feeds(self, fake):
        fake.types["someFile"] = "file"
        fake.conns["limb_mat.baseColor"] = ["someFile.outColor"]
        with pytest.raises(RuntimeError, match="locked or connected"):
            fake.setAttr("limb_mat.baseColor", 1.0, 1.0, 1.0)

    def test_setAttr_refuses_both_compound_directions(self, fake):
        """A child write when the COMPOUND is fed, and a compound write
        when a CHILD is fed. Round 1 modelled only the second."""
        fake.types["someFile"] = "file"
        fake.conns["limb_mat.baseColor"] = ["someFile.outColor"]
        with pytest.raises(RuntimeError, match="locked or connected"):
            fake.setAttr("limb_mat.baseColorR", 1.0)
        fake.conns["limb_mat.emissionColorG"] = ["someFile.outAlpha"]
        with pytest.raises(RuntimeError, match="locked or connected"):
            fake.setAttr("limb_mat.emissionColor", 0.0, 0.0, 0.0)

    def test_setAttr_refuses_a_locked_plug_in_both_compound_directions(
            self, fake):
        fake.locked.add("limb_mat.specularRoughness")
        with pytest.raises(RuntimeError, match="locked or connected"):
            fake.setAttr("limb_mat.specularRoughness", 0.4)
        fake.locked.add("limb_mat.coatColor")
        with pytest.raises(RuntimeError, match="locked or connected"):
            fake.setAttr("limb_mat.coatColorB", 0.4)
        fake.locked.add("limb_mat.subsurfaceColorR")
        with pytest.raises(RuntimeError, match="locked or connected"):
            fake.setAttr("limb_mat.subsurfaceColor", 1.0, 1.0, 1.0)

    def test_setAttr_to_a_free_plug_is_what_getAttr_reads_back(self, fake):
        fake.setAttr("limb_mat.specularRoughness", 0.25)
        assert fake.getAttr("limb_mat.specularRoughness") == 0.25
        assert fake.getAttr("limb_mat.metalness") == ""   # modelled default

    def test_connectAttr_refuses_an_occupied_destination_unless_forced(
            self, fake):
        fake.types["mcpMap_ao"] = "file"
        with pytest.raises(RuntimeError, match="already connected"):
            fake.connectAttr("mcpMap_ao.outColor", "limbSG.surfaceShader")
        fake.connectAttr("mcpMap_ao.outColor", "limbSG.surfaceShader",
                         force=True)
        assert fake.conns["limbSG.surfaceShader"] == ["mcpMap_ao.outColor"]

    def test_connectAttr_refuses_a_node_that_is_not_in_the_scene(self, fake):
        with pytest.raises(RuntimeError, match="No object matches name"):
            fake.connectAttr("ghost.outColor", "limb_mat.emissionColor")
        with pytest.raises(RuntimeError, match="No object matches name"):
            fake.connectAttr("limb_mat.outColor", "ghost.baseColor")

    # contract 3 - answers that used to be constants -------------------
    def test_polyEvaluate_does_not_call_a_missing_node_a_mesh_with_no_uvs(
            self, fake):
        """`_uv_count`'s own comment refuses that conflation; the fake made
        it for every unknown name."""
        assert fake.polyEvaluate("|limbShape", uvcoord=True) == 64
        with pytest.raises(RuntimeError, match="No object matches name"):
            fake.polyEvaluate("|ghostShape", uvcoord=True)

    def test_listRelatives_answers_the_shape_to_transform_direction(
            self, fake):
        """Answering None to `parent=True` unconditionally sent every call
        down _transform_short_name's "a shape that cannot answer stands
        for itself" degrade arm."""
        assert fake.listRelatives("|limbShape", parent=True) == ["|limb"]
        assert fake.listRelatives("|limb", shapes=True) == ["|limbShape"]
