"""#714 phase 2: what maya_bake_textures refuses, before it touches anything.

Every refusal here is grounded in a MEASURED probe finding, not caution:
convertSolidTx does not raise on a UV-less mesh (it writes a flat, useless
image), so the tool must catch that itself; and a normal slot with no
bump2d in the chain has no measured surviving wiring shape.
"""

import os

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import texbake


def _fake_bake(fake):
    """Stand in for convertSolidTx: write a real (tiny) PNG at the path the
    tool asked for, so the part-file/commit machinery is exercised for
    real while the pixels come from the monkeypatched uniformity check."""
    def _bake(cmds, source_plug, target, path, resolution):
        with open(path, "wb") as fh:
            fh.write(b"\x89PNG\r\n\x1a\n" + b"x" * 64)
        fake.baked_calls.append((source_plug, target, path, resolution))
    return _bake


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
    """|body (shape |bodyShape) wears bodySG -> skin_mat; a noise drives
    baseColor. UV count and shading graph are per-test knobs."""

    def __init__(self, uv_count=64):
        self.uv_count = uv_count
        self.meshes = {"|body": "|bodyShape"}
        self.types = {"skin_mat": "standardSurface", "mcpTex_noise": "noise"}
        self.shape_sgs = {"|bodyShape": ["bodySG"]}
        self.sg_members = {"bodySG": ["|bodyShape"]}
        self.conns = {"bodySG.surfaceShader": ["skin_mat.outColor"],
                      "skin_mat.baseColor": ["mcpTex_noise.outColor"]}
        self.existing_attrs = {"skin_mat.baseColor"}
        # plug -> value. Real getAttr answers the attribute's value; the
        # fake used to answer "" for EVERY plug on EVERY name, which is a
        # method that can never fail a test (#799 contract 3).
        self.attrs = {}
        # Plugs a rigger locked by hand: the other half of contract 2's
        # "locked or connected" refusal, which no path in this module
        # produces on its own.
        self.locked = set()
        self.connected = []
        self.deleted = []
        self.checkpoints = []
        self.baked_calls = []
        self.created = []
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
        said ""), and that is precisely the shape that let #796 ship a
        blocking defect: code asking `nodeType` about a node it had just
        deleted got a plausible answer here and a RuntimeError in Maya.
        This module rewires and DELETES shading nodes on its commit path,
        so a query about a consumed node is the live risk in this file.

        Deletion is modelled by `delete` REMOVING the node from the
        registries `_exists` reads, NOT by a name tombstone: #799 round 2
        found that consulting `self.deleted` here made a name that was
        deleted and then re-created (this suite's bake shaders are created
        and deleted once per mesh) simultaneously present in `types` and
        absent to every query - a scene Maya cannot have. `self.deleted`
        is a RECORD for assertions, never an existence oracle.
        """
        if not self._exists(node):
            raise RuntimeError("No object matches name: %s" % node)

    def _compound_parent(self, plug):
        """`skin_mat.baseColorR` -> `skin_mat.baseColor`, or None."""
        node, _, attr = plug.rpartition(".")
        if len(attr) > 1 and attr[-1] in "RGBXYZ":
            return "%s.%s" % (node, attr[:-1])
        return None

    def _static_write_blocker(self, plug):
        """The connection or lock that makes `setAttr(plug, ...)` raise,
        or None - #799 contract 2. Maya refuses a static write to a plug
        something feeds, to a COMPOUND whose CHILD is fed, AND to a CHILD
        whose parent compound is fed. Round 1 modelled only the middle
        one, which left a write to `skin_mat.baseColorR` permitted while
        `mcpTex_noise.outColor` feeds `skin_mat.baseColor`.
        """
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
    def ls(self, name=None, long=False, uuid=False, **kw):
        """Resolves transforms AND shapes: a shading group's members are
        SHAPES, and #796's canonicalisation sends every one of them
        through here. Partial paths resolve the way Maya resolves them
        (_resolve_dag) - that is the form cmds.sets actually answers with
        on the mirrored rig this ticket is about.

        `uuid=True` answers with the NODE instead of its paths, which is
        what the guard compares now: the two paths of an instanced shape
        are one node and must come back as one identity, while a mirrored
        pair is two nodes and must not."""
        paths = _resolve_dag(list(self.meshes) + list(self.meshes.values()),
                             name, self.node_of)
        if not uuid:
            return paths
        ids = []
        for path in paths:
            node = self.node_of.get(path, "uuid:" + path)
            if node not in ids:
                ids.append(node)
        return ids

    def objExists(self, name):
        # The one query #799 exempts: objExists ANSWERS for a vanished
        # node, it does not raise. Shapes count too - they did not before,
        # which made objExists disagree with every other method here.
        return self._exists(name)

    def listRelatives(self, node, shapes=False, fullPath=False, **kw):
        self._require(node)
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
        self._require(node)
        return self.uv_count if uvcoord else 0

    # graph -----------------------------------------------------------
    def listSets(self, object=None, type=None):
        self._require(object)
        return list(self.shape_sgs.get(object, []))

    def sets(self, name, query=False, **kw):
        """Query-mode only - this fake never needs the edit/create forms
        the real bake tool does not use."""
        if query:
            # An empty list used to be the answer for a set that does not
            # EXIST, which reads as "worn by nobody" - Maya raises, and
            # _outside_wearers' own degrade-not-crash guard is what a test
            # must then be able to exercise (#799 contract 1/3).
            #
            # An EMPTY set is a different thing and Maya answers it: round
            # 1 refused every name absent from `sg_members`, which made
            # this fake strict where Maya is not. Existence is the test.
            self._require(name)
            return list(self.sg_members.get(name, []))
        raise NotImplementedError("FakeCmds.sets only supports query=True")

    def listConnections(self, plug, source=False, destination=True,
                        plugs=False, **kw):
        """`source=True` (any destination value - real callers in this
        codebase never rely on destination when source is True): what
        feeds `plug`, upstream. A bare node (no '.') matches ANY of its
        attrs by scanning conns keys, which is what lets a walk continue
        onto a plain node name (texclaim's pass-through continuation,
        _has_placement) and is otherwise inert for the exact-plug lookups
        every pre-existing caller uses.

        `source=False, destination=True`: the opposite direction - what
        does `plug` (or a bare node's any attr) feed, downstream. Added
        for the two-phase bake's post-rewire orphan sweep, which is the
        only caller that ever asks this; nothing upstream-only (texclaim's
        walk) uses this branch.
        """
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
        if not dsts:
            return None
        return dsts if plugs else [d.split(".")[0] for d in dsts]

    def attributeQuery(self, attr, node=None, exists=False):
        self._require(node)
        return ("%s.%s" % (node, attr)) in self.existing_attrs

    def getAttr(self, plug):
        """The plug's value. "" is the modelled answer for an attribute
        this fake has no value for - Maya answers a string attr's default
        the same way - but it is reached only AFTER the node is known to
        exist, which is the half that used to be missing (#799)."""
        self._require(plug.split(".")[0])
        return self.attrs.get(plug, "")

    # mutation (two-phase bake) ---------------------------------------
    def shadingNode(self, node_type, name=None, asTexture=False,
                    asUtility=False, **kw):
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
        self.attrs[plug] = values[0] if len(values) == 1 else list(values)

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
            # Maya, and this module re-creates its bake nodes per mesh.
            self.types.pop(n, None)
            self.sg_members.pop(n, None)
            self.shape_sgs.pop(n, None)
            if n in self.meshes:
                self.shape_sgs.pop(self.meshes.pop(n), None)
            # Sever every connection touching the deleted node, mirroring
            # real Maya severing edges on delete - without this, a later
            # orphan check on a node that fed the just-deleted one would
            # see a "live" connection to a node that no longer exists.
            for dst in list(self.conns.keys()):
                if dst.split(".")[0] == n:
                    del self.conns[dst]
                    continue
                kept = [s for s in self.conns[dst] if s.split(".")[0] != n]
                if kept:
                    self.conns[dst] = kept
                else:
                    del self.conns[dst]


@pytest.fixture
def fake(monkeypatch):
    cmds = FakeCmds()
    monkeypatch.setattr(texbake, "_cmds", lambda: cmds)
    monkeypatch.setattr(texbake.session, "auto_checkpoint",
                        lambda reason: (cmds.checkpoints.append(reason)
                                        or {"checkpoint_id": "cp",
                                            "path": "cp.ma"}))
    return cmds


def _params(tmp_path, **kw):
    base = {"meshes": ["|body"], "out_dir": str(tmp_path)}
    base.update(kw)
    return base


class TestValidation:
    def test_meshes_is_required(self, fake, tmp_path):
        with pytest.raises(HandlerError, match="meshes"):
            texbake.validate({"out_dir": str(tmp_path)}, fake)

    def test_out_dir_must_exist(self, fake, tmp_path):
        params = _params(tmp_path, out_dir=str(tmp_path / "nope"))
        with pytest.raises(HandlerError, match="does not exist"):
            texbake.validate(params, fake)

    def test_out_dir_must_be_absolute(self, fake, tmp_path):
        with pytest.raises(HandlerError, match="absolute"):
            texbake.validate(_params(tmp_path, out_dir="relative/dir"), fake)

    def test_resolution_must_be_a_supported_power_of_two(self, fake, tmp_path):
        with pytest.raises(HandlerError, match="resolution"):
            texbake.validate(_params(tmp_path, resolution=1000), fake)

    def test_an_unknown_slot_refuses(self, fake, tmp_path):
        with pytest.raises(HandlerError, match="slot"):
            texbake.validate(_params(tmp_path, slots=["shininess"]), fake)

    def test_defaults_are_1024_and_every_slot(self, fake, tmp_path):
        out = texbake.validate(_params(tmp_path), fake)
        assert out["resolution"] == 1024
        assert out["slots"] is None
        assert out["meshes"] == ["|bodyShape"]


class TestRefusals:
    def test_a_mesh_with_no_uvs_refuses_naming_uv_atlas(self, fake, tmp_path):
        # MEASURED: convertSolidTx does NOT raise here - it writes a flat,
        # useless image. Maya will not catch this for us.
        fake.uv_count = 0
        params = texbake.validate(_params(tmp_path), fake)
        with pytest.raises(HandlerError, match="no UVs"):
            texbake.plan_bakes(fake, params["meshes"], params["slots"])

    def test_the_no_uv_refusal_hint_names_the_fix(self, fake, tmp_path):
        fake.uv_count = 0
        params = texbake.validate(_params(tmp_path), fake)
        try:
            texbake.plan_bakes(fake, params["meshes"], params["slots"])
        except HandlerError as exc:
            assert "maya_uv_atlas" in (exc.hint or "")
        else:
            pytest.fail("expected a refusal")

    def test_a_procedural_normal_without_a_bump2d_refuses(self, fake, tmp_path):
        fake.existing_attrs = {"skin_mat.normalCamera"}
        fake.conns = {"bodySG.surfaceShader": ["skin_mat.outColor"],
                      "skin_mat.normalCamera": ["mcpTex_noise.outColor"]}
        params = texbake.validate(_params(tmp_path), fake)
        with pytest.raises(HandlerError, match="bump2d"):
            texbake.plan_bakes(fake, params["meshes"], params["slots"])

    def test_a_file_backed_slot_is_skipped_not_baked(self, fake, tmp_path):
        fake.types["mcpTex_file"] = "file"
        fake.conns["skin_mat.baseColor"] = ["mcpTex_file.outColor"]
        params = texbake.validate(_params(tmp_path), fake)
        jobs, warnings = texbake.plan_bakes(fake, params["meshes"],
                                            params["slots"])
        assert jobs == []
        assert any("already file-backed" in w for w in warnings)

    def test_nothing_to_bake_refuses_rather_than_no_opping(self, fake,
                                                           tmp_path):
        fake.conns.pop("skin_mat.baseColor")
        params = texbake.validate(_params(tmp_path), fake)
        with pytest.raises(HandlerError, match="no procedural"):
            texbake.plan_bakes(fake, params["meshes"], params["slots"])


class TestPlan:
    def test_a_procedural_colour_slot_becomes_one_job(self, fake, tmp_path):
        params = texbake.validate(_params(tmp_path), fake)
        jobs, _warnings = texbake.plan_bakes(fake, params["meshes"],
                                             params["slots"])
        assert len(jobs) == 1
        job = jobs[0]
        assert job["material"] == "skin_mat"
        assert job["slot"] == "color"
        assert job["attr"] == "baseColor"
        assert job["kind"] == "color"
        assert job["terminal_plug"] == "mcpTex_noise.outColor"
        assert job["bump_node"] is None
        assert job["basename"] == "skin_mat_color_baked.png"

    def test_the_slots_filter_narrows_the_jobs(self, fake, tmp_path):
        params = texbake.validate(_params(tmp_path, slots=["roughness"]), fake)
        with pytest.raises(HandlerError, match="no procedural"):
            texbake.plan_bakes(fake, params["meshes"], params["slots"])


class TestOutsideWearerWarning:
    """The rewire is material-level: a mesh the caller never named still
    gets its look changed if it wears the same shading group. The warning
    must fire on THAT mesh, not on a second mesh the caller explicitly
    asked to bake alongside the first (the backwards behaviour the review
    caught - `claim["meshes"]` only ever accumulates wearers among the
    REQUESTED shapes, so it cannot see an outside wearer at all)."""

    def test_a_mesh_outside_the_request_that_shares_the_sg_is_named(
            self, fake, tmp_path):
        fake.meshes["|other"] = "|otherShape"
        fake.sg_members["bodySG"] = ["|bodyShape", "|otherShape"]

        params = texbake.validate(_params(tmp_path), fake)  # only |body
        _jobs, warnings = texbake.plan_bakes(fake, params["meshes"],
                                             params["slots"])

        assert any("also worn by" in w and "|otherShape" in w
                  for w in warnings)

    def test_a_second_requested_mesh_does_not_trigger_the_outside_warning(
            self, fake, tmp_path):
        fake.meshes["|other"] = "|otherShape"
        fake.shape_sgs["|otherShape"] = ["bodySG"]
        fake.sg_members["bodySG"] = ["|bodyShape", "|otherShape"]

        params = texbake.validate(
            _params(tmp_path, meshes=["|body", "|other"]), fake)
        _jobs, warnings = texbake.plan_bakes(fake, params["meshes"],
                                             params["slots"])

        assert not any("also worn by" in w for w in warnings)
        assert any("worn by 2 meshes" in w for w in warnings)

    def test_an_unqueryable_sg_degrades_to_no_warning_not_a_crash(
            self, fake, tmp_path, monkeypatch):
        def boom(name, query=False, **kw):
            raise RuntimeError("kMFnSet: object does not exist")

        monkeypatch.setattr(fake, "sets", boom)
        params = texbake.validate(_params(tmp_path), fake)

        jobs, warnings = texbake.plan_bakes(fake, params["meshes"],
                                            params["slots"])

        assert len(jobs) == 1
        assert not any("also worn by" in w for w in warnings)


class TestOutsideWearerIdentityIsTheNode:
    """#796 defect 3: Maya enforces name uniqueness per PARENT only, so a
    mirrored rig routinely carries |left|limb and |right|limb. The guard
    used to fall back to comparing SHORT names, which made those two
    mirrors indistinguishable - baking one limb silently skipped the
    warning that the OTHER limb's look had just been changed by the same
    material-level rewire. A guard that exists to warn about an unnamed
    mesh stopped warning about exactly the meshes a mirrored rig has.

    Identity is the NODE now, on both sides of the comparison. Round 2
    canonicalised to the full DAG path instead, which is still a path
    string: an INSTANCED shape is one node under several paths, so the
    guard reported a path of the very shape the caller had named - and
    only when Maya happened to answer with a name that resolved to more
    than one path, which is Maya's choice and not ours.

    Round 3 then asked the node question per MEMBER instead of per SHAPE,
    which is only the same question while a member name means one node -
    and nothing here has measured that `cmds.sets` never answers with an
    ambiguous name. Every name form Maya can pick is therefore pinned
    below, on both fixtures: absolute, partial, and short-and-ambiguous.
    """

    def _mirrored(self, fake, members=None):
        """|left|limb and |right|limb, both wearing bodySG: TWO shape
        nodes that share a short name, which must BOTH be reported.

        The members default to PARTIAL paths: cmds.sets(query=True)
        answers with the shortest UNIQUE name, and for these two shapes
        that is neither 'limbShape' (ambiguous) nor the full path - it is
        'left|limbShape'. Which form arrives is Maya's call, and this repo
        has never measured whether an AMBIGUOUS one can arrive, so all
        three are pinned: partial, absolute, and 'limbShape' meaning both
        nodes at once (#796 round 4).
        """
        fake.meshes = {"|left|limb": "|left|limbShape",
                       "|right|limb": "|right|limbShape"}
        fake.shape_sgs = {"|left|limbShape": ["bodySG"],
                          "|right|limbShape": ["bodySG"]}
        fake.sg_members["bodySG"] = list(
            members or ["left|limbShape", "right|limbShape"])

    def test_the_mirrored_twin_of_the_requested_mesh_is_named(self, fake,
                                                              tmp_path):
        self._mirrored(fake)
        params = texbake.validate(_params(tmp_path, meshes=["|left|limb"]),
                                  fake)
        _jobs, warnings = texbake.plan_bakes(fake, params["meshes"],
                                             params["slots"])

        assert any("also worn by" in w and "|right|limbShape" in w
                   for w in warnings)

    def test_the_mirrored_twin_is_named_when_the_member_is_absolute(
            self, fake):
        """The other half of node identity, and what keeps the instance
        skip below honest: a mirrored pair is TWO shape nodes, so no name
        form may collapse them into one."""
        self._mirrored(fake, ["|left|limbShape", "|right|limbShape"])

        assert texbake._outside_wearers(
            fake, "bodySG", ["|left|limbShape"]) == ["|right|limbShape"]

    def test_an_ambiguous_member_still_names_the_twin_it_is_not(self, fake):
        """#796 round 4, defect A: the decision is per SHAPE, never per
        MEMBER.

        The skip used to drop the whole member as soon as ONE node it
        resolved to was the caller's own mesh - the instance rationale,
        applied one level too high. `_node_ids` is exactly what tells an
        instance's second PATH from a second NODE, and `any(...)` threw
        that answer away: on a mirrored rig an ambiguous member name
        resolves to BOTH limbs, the left one is requested, and the right
        one - a different node, whose look this rewire changes too - went
        unreported. Whether `cmds.sets` ever answers with an ambiguous
        name is Maya's choice and unmeasured, so the guard must not rest
        on it.
        """
        self._mirrored(fake, ["limbShape"])

        assert texbake._outside_wearers(
            fake, "bodySG", ["|left|limbShape"]) == ["|right|limbShape"]

    def test_a_short_member_name_that_is_the_requested_shape_is_not_outside(
            self, fake):
        """The regression the deleted short-name arm was protecting
        against, kept alive by canonicalising instead: cmds.sets(query=
        True) can answer with a name that is not a full DAG path, and a
        raw long-vs-short comparison would report the caller's OWN mesh."""
        fake.sg_members["bodySG"] = ["bodyShape"]

        assert texbake._outside_wearers(fake, "bodySG", ["|bodyShape"]) == []

    def test_a_transform_member_still_resolves_through_to_its_shape(self,
                                                                    fake):
        fake.meshes["|other"] = "|otherShape"
        fake.sg_members["bodySG"] = ["|body", "|other"]

        assert texbake._outside_wearers(
            fake, "bodySG", ["|bodyShape"]) == ["|otherShape"]

    def test_a_component_suffix_on_a_member_is_still_stripped(self, fake):
        fake.meshes["|other"] = "|otherShape"
        fake.sg_members["bodySG"] = ["|bodyShape.f[0:3]",
                                     "|otherShape.f[4:7]"]

        assert texbake._outside_wearers(
            fake, "bodySG", ["|bodyShape"]) == ["|otherShape"]

    def _instanced(self, fake, members=None):
        """ONE shape node under TWO DAG paths - the instance case.

        Instancing is two distinct TRANSFORMS sharing one shape node, so
        both paths name the same node (fake.node_of) and the shape-level
        material assignment makes both of them wear the SG. `members` is
        what cmds.sets answers with: the node's own name, or one absolute
        path per instance - Maya picks the shortest UNIQUE form and the
        guard has to be right under either.

        Resolving the node's own name lands on ONE of its paths, not on
        every one of them: `cmds.ls(name, long=True)` matches NODES, and
        enumerating an instance's other paths needs `allPaths=True`, which
        nothing here asks for (#796 round 4). So the two member forms give
        the guard genuinely different material - one path, or two - and
        node identity is what has to make them agree.
        """
        fake.meshes = {"|grpA|cube": "|grpA|cube|cubeShape",
                       "|grpB|cube": "|grpB|cube|cubeShape"}
        fake.node_of = {"|grpA|cube|cubeShape": "uuid:cubeShape",
                        "|grpB|cube|cubeShape": "uuid:cubeShape"}
        fake.shape_sgs = {"|grpA|cube|cubeShape": ["bodySG"],
                          "|grpB|cube|cubeShape": ["bodySG"]}
        fake.sg_members["bodySG"] = list(members or ["cubeShape"])

    def test_a_member_resolving_onto_a_requested_shape_skips_that_shape_only(
            self, fake):
        """#796 round 4: a resolved shape that IS one the caller asked for
        is skipped - that SHAPE, and nothing else the member reached.

        The skip itself is round 2's and still stands. Naming a mesh the
        caller already named costs a reviewer one extra look HERE, where
        the answer becomes a warning; at meshmaps.refuse_outside_wearer it
        RAISES, so an instanced mesh had its own second path reported as
        an outside wearer and a legitimate bake was refused, with a hint
        the caller could not follow.

        What round 4 deleted is that skip's REACH. Round 3 dropped the
        whole MEMBER as soon as one shape it resolved to was the caller's,
        which is the same decision only while a member name means one
        node. Below it does not: the requested cube is instanced AND
        shares its short name with an unrelated shape, so the one member
        resolves to two NODES - and `any(...)` threw the second one away,
        leaving a mesh whose look this material-level rewire changes just
        as much unreported. Asked per shape, the instance still skips
        itself and the outsider is still named, whichever name form
        `cmds.sets` chose - a thing this repo has never measured.
        """
        self._instanced(fake)
        # The instance alone. Its member name resolves onto the very path
        # the caller asked for, so there is no outside wearer at all -
        # both rules agree here, which is why this case alone pins
        # neither. It is kept because it is the form round 2 fixed: the
        # skip must not depend on Maya having handed back the path the
        # caller happened to name (the other resolution is
        # test_an_instance_maya_named_by_its_other_path_is_still_the_caller).
        assert texbake._outside_wearers(
            fake, "bodySG", ["|grpA|cube|cubeShape"]) == []

        # Now the same member name also reaches a shape that is NOT the
        # caller's: Maya enforces name uniqueness per PARENT, so
        # |grpA|cube|cubeShape and |deco|cubeShape coexist and 'cubeShape'
        # names both nodes. This is the case that separates the two rules
        # - per member the outsider vanishes along with the instance, per
        # shape it is reported.
        fake.meshes["|deco"] = "|deco|cubeShape"
        fake.shape_sgs["|deco|cubeShape"] = ["bodySG"]

        assert texbake._outside_wearers(
            fake, "bodySG", ["|grpA|cube|cubeShape"]) == ["|deco|cubeShape"]

    def test_an_instance_named_by_its_absolute_path_is_the_same_node(
            self, fake):
        """#796 fix round 3, and the reason identity is the NODE rather
        than the canonical path: round 2 skipped a member only when one of
        its RESOLVED PATHS was a requested path, which needs Maya to have
        answered with a name that resolves to several. Answer with one
        absolute path per instance instead - equally legal, and the form
        cmds.sets picks whenever anything else in the scene makes the
        short name ambiguous - and the caller's own shape node came back
        as an outside wearer under its other path. Two paths of one node
        can never diverge in look, so this can only ever be wrong.
        """
        self._instanced(fake, ["|grpA|cube|cubeShape",
                               "|grpB|cube|cubeShape"])

        assert texbake._outside_wearers(
            fake, "bodySG", ["|grpA|cube|cubeShape"]) == []

    def test_an_instanced_mesh_does_not_warn_about_its_own_other_path(
            self, fake, tmp_path):
        """The same case at THIS call site, where it only ever warned."""
        self._instanced(fake)
        params = texbake.validate(_params(tmp_path, meshes=["|grpA|cube"]),
                                  fake)
        _jobs, warnings = texbake.plan_bakes(fake, params["meshes"],
                                             params["slots"])

        assert not any("also worn by" in w for w in warnings)

    def test_the_absolute_instance_does_not_warn_at_this_call_site_either(
            self, fake, tmp_path):
        """Round 3's case through plan_bakes: a spurious warning here is
        the same defect that REFUSES the bake one module over."""
        self._instanced(fake, ["|grpA|cube|cubeShape",
                               "|grpB|cube|cubeShape"])
        params = texbake.validate(_params(tmp_path, meshes=["|grpA|cube"]),
                                  fake)
        _jobs, warnings = texbake.plan_bakes(fake, params["meshes"],
                                             params["slots"])

        assert not any("also worn by" in w for w in warnings)

    def test_an_unrequested_instance_is_named_once_not_once_per_path(
            self, fake):
        """#796 round 4, defect B: an instanced node is ONE wearer on the
        outside of the request too, not only on the inside.

        Its paths cannot diverge in look, and both remedies the callers
        are offered - name it in the request, give it its own material -
        are moves on the NODE. Naming it twice reads as two meshes to fix,
        and which name form `cmds.sets` answered with is not the caller's
        business, so the answer must be the same under both. Here Maya
        answered with one absolute path per instance.
        """
        self._instanced(fake, ["|grpA|cube|cubeShape",
                               "|grpB|cube|cubeShape"])

        assert texbake._outside_wearers(
            fake, "bodySG", ["|bodyShape"]) == ["|grpA|cube|cubeShape"]

    def test_the_ambiguous_form_names_that_one_instance_once_too(self, fake):
        """The same node, named by `cmds.sets` with the node's own name.

        `cmds.ls(name, long=True)` answers with one path per NODE - the
        several paths of one INSTANCED node need `allPaths=True`, which
        this guard deliberately does not ask for (see _resolve_long) - so
        here the single name arrives by resolution rather than by
        de-duplication. Both routes are pinned because Maya picks between
        them, not us.
        """
        self._instanced(fake)

        assert texbake._outside_wearers(
            fake, "bodySG", ["|bodyShape"]) == ["|grpA|cube|cubeShape"]

    def test_an_instance_maya_named_by_its_other_path_is_still_the_caller(
            self, fake):
        """The UUID arm, isolated. `cmds.ls` hands back one path per node
        and which one is Maya's business, so a member naming the instanced
        node can resolve to the path the caller did NOT name. The path
        comparison misses it; node identity is what keeps a legitimate
        bake of |grpB|cube from being refused one module over."""
        self._instanced(fake)

        assert texbake._outside_wearers(
            fake, "bodySG", ["|grpB|cube|cubeShape"]) == []

    def test_a_member_that_no_longer_resolves_is_skipped_not_fatal(self,
                                                                   fake):
        fake.sg_members["bodySG"] = ["|bodyShape", "|ghostShape"]

        assert texbake._outside_wearers(fake, "bodySG", ["|bodyShape"]) == []

    def test_a_member_whose_resolution_raises_is_skipped_not_fatal(
            self, fake, monkeypatch):
        """One bad member must not cost the warning about the others."""
        real_ls = fake.ls

        def flaky(name=None, long=False, **kw):
            if name == "|brokenShape":
                raise RuntimeError("kFailure: no such node")
            return real_ls(name, long=long, **kw)

        monkeypatch.setattr(fake, "ls", flaky)
        fake.meshes["|other"] = "|otherShape"
        fake.sg_members["bodySG"] = ["|brokenShape", "|otherShape"]

        assert texbake._outside_wearers(
            fake, "bodySG", ["|bodyShape"]) == ["|otherShape"]

    def test_identity_degrades_to_the_path_when_maya_will_not_answer(
            self, fake, monkeypatch):
        """The degradation the guard promises, measured rather than
        assumed: a Maya that will not give a node identity leaves this
        exactly where round 2 left it - matching by resolved path, still
        reporting the genuine outsider - and never crashes the bake it is
        guarding."""
        real_ls = fake.ls

        def no_identity(name=None, long=False, uuid=False, **kw):
            if uuid:
                raise RuntimeError("kFailure: no identity for that node")
            return real_ls(name, long=long, **kw)

        monkeypatch.setattr(fake, "ls", no_identity)
        fake.meshes["|other"] = "|otherShape"
        fake.sg_members["bodySG"] = ["bodyShape", "|otherShape"]

        assert texbake._outside_wearers(
            fake, "bodySG", ["|bodyShape"]) == ["|otherShape"]

    def test_an_unqueryable_sg_returns_nothing_rather_than_raising(
            self, fake, monkeypatch):
        def boom(name, query=False, **kw):
            raise RuntimeError("kMFnSet: object does not exist")

        monkeypatch.setattr(fake, "sets", boom)

        assert texbake._outside_wearers(fake, "bodySG", ["|bodyShape"]) == []


class TestGuardStructure:
    """## Fix round 1: the empty-jobs refusal is gated on the explicit
    `skipped_file_backed` flag, not on `warnings` being non-empty -
    `warnings` is a bag other paths (placement, shared-mesh) write into
    too, always alongside a job. No claim shape in plan_bakes today can
    produce "a warning but no job for a reason other than file-backed", so
    this pins the guard function directly with synthetic inputs rather
    than trying to fabricate a claim that reaches it.
    """

    def test_no_jobs_and_no_file_backed_skip_refuses(self):
        with pytest.raises(HandlerError, match="no procedural"):
            texbake._refuse_if_nothing_to_bake([], False, None)

    def test_no_jobs_but_a_file_backed_skip_does_not_refuse(self):
        texbake._refuse_if_nothing_to_bake([], True, None)  # must not raise

    def test_a_job_present_does_not_refuse_even_without_the_flag(self):
        texbake._refuse_if_nothing_to_bake(
            [{"material": "m"}], False, None)  # must not raise


class TestUnknownSlotRefuses:
    def test_an_unknown_slot_on_the_claim_refuses_rather_than_guessing(
            self, fake, tmp_path, monkeypatch):
        # Synthetic: no real texclaim walk produces a slot outside
        # pbr.SLOTS today (SLOT_FOR_ATTR is derived from the same tables),
        # but a future material.SHADER_SLOTS entry could. Fabricate the
        # claim material_claims would then hand back, and pin the refusal
        # that replaced a silent "color" default (which would have baked
        # outColor where a scalar/normal slot needs outColorR).
        def fake_claims(cmds, shapes):
            return [{
                "mesh": "|bodyShape", "meshes": ["|bodyShape"],
                "material": "skin_mat", "sg": "bodySG", "attr": "shininess",
                "slot": "shininess", "classification": "procedural",
                "terminals": [{"node": "mcpTex_noise", "type": "noise",
                               "file_path": None, "basename": None,
                               "on_disk": None, "colorspace": None}],
                "via": [], "semantics_lost": [],
            }]

        monkeypatch.setattr(texbake.texclaim, "material_claims", fake_claims)
        params = texbake.validate(_params(tmp_path), fake)
        with pytest.raises(HandlerError, match="shininess"):
            texbake.plan_bakes(fake, params["meshes"], params["slots"])


class TestUVCountFailureIsReported:
    def test_a_polyevaluate_failure_is_not_diagnosed_as_no_uvs(
            self, fake, tmp_path, monkeypatch):
        def boom(node, uvcoord=False, **kw):
            raise RuntimeError("kMFnMesh: object does not exist")

        monkeypatch.setattr(fake, "polyEvaluate", boom)
        params = texbake.validate(_params(tmp_path), fake)
        with pytest.raises(HandlerError, match="could not determine"):
            texbake.plan_bakes(fake, params["meshes"], params["slots"])


class TestMeshesRobustness:
    def test_a_non_iterable_meshes_value_refuses_cleanly(self, fake, tmp_path):
        with pytest.raises(HandlerError, match="meshes"):
            texbake.validate(_params(tmp_path, meshes=5), fake)

    def test_a_bool_meshes_value_refuses_cleanly(self, fake, tmp_path):
        with pytest.raises(HandlerError, match="meshes"):
            texbake.validate(_params(tmp_path, meshes=True), fake)


class TestTwoPhaseBake:
    """Phase A writes and verifies with ZERO scene mutation; phase B
    rewires only if every bake verified. A caller is therefore always in
    one of exactly two states."""

    def test_a_failed_bake_leaves_the_scene_untouched(self, fake, tmp_path,
                                                       monkeypatch):
        monkeypatch.setattr(texbake, "_convert_solid_tx",
                            lambda *a, **kw: None)   # writes no file
        with pytest.raises(HandlerError, match="produced no file"):
            texbake.bake_textures(_params(tmp_path))
        assert fake.connected == []          # nothing rewired
        assert fake.deleted == []            # nothing deleted
        assert fake.checkpoints == []        # not even a checkpoint

    def test_a_degenerate_bake_refuses_before_rewiring(self, fake, tmp_path,
                                                        monkeypatch):
        # MEASURED failure mode: a flat image is what a UV-less mesh bakes.
        # The UV guard catches that case; this proves the pixel check is a
        # real second net, not decoration.
        monkeypatch.setattr(texbake, "_convert_solid_tx", _fake_bake(fake))
        monkeypatch.setattr(texbake.pngprobe, "uniformity",
                            lambda _p: {"pixel_count": 1024,
                                        "distinct_values": 1,
                                        "non_uniform": False,
                                        "unavailable_reason": None})
        with pytest.raises(HandlerError, match="flat") as excinfo:
            texbake.bake_textures(_params(tmp_path))
        assert fake.connected == []
        # Review fix: the flat bake IS evidence, and its hint names the
        # file - so unlike an ordinary failed attempt, it is deliberately
        # left on disk rather than swept.
        parts = list(tmp_path.glob("*.part.png"))
        assert len(parts) == 1
        assert str(parts[0]) in (excinfo.value.hint or "")

    def test_an_unmeasurable_bakes_part_file_is_kept_for_inspection(
            self, fake, tmp_path, monkeypatch):
        monkeypatch.setattr(texbake, "_convert_solid_tx", _fake_bake(fake))
        monkeypatch.setattr(texbake.pngprobe, "uniformity",
                            lambda _p: {"pixel_count": 0,
                                        "distinct_values": 0,
                                        "non_uniform": None,
                                        "unavailable_reason": "unreadable"})
        with pytest.raises(HandlerError, match="could not be measured") as excinfo:
            texbake.bake_textures(_params(tmp_path))
        assert fake.connected == []
        parts = list(tmp_path.glob("*.part.png"))
        assert len(parts) == 1
        assert str(parts[0]) in (excinfo.value.hint or "")

    def test_a_no_file_bakes_part_path_is_still_swept(self, fake, tmp_path,
                                                       monkeypatch):
        # The keep_evidence exemption is specific to the unmeasurable/flat
        # cases, where the bake actually wrote something worth looking at.
        # A bake that produced no file at all has nothing to keep.
        monkeypatch.setattr(texbake, "_convert_solid_tx",
                            lambda *a, **kw: None)   # writes no file
        with pytest.raises(HandlerError, match="produced no file"):
            texbake.bake_textures(_params(tmp_path))
        assert not list(tmp_path.glob("*.part.png"))

    def test_a_good_bake_rewires_and_commits(self, fake, tmp_path,
                                             monkeypatch):
        monkeypatch.setattr(texbake, "_convert_solid_tx", _fake_bake(fake))
        monkeypatch.setattr(texbake.pngprobe, "uniformity",
                            lambda _p: {"pixel_count": 1024,
                                        "distinct_values": 186,
                                        "non_uniform": True,
                                        "unavailable_reason": None})
        out = texbake.bake_textures(_params(tmp_path))

        assert len(out["baked"]) == 1
        entry = out["baked"][0]
        assert entry["basename"] == "skin_mat_color_baked.png"
        assert os.path.isfile(entry["file"])          # committed, not .part
        assert not list(tmp_path.glob("*.part.png"))  # nothing left behind
        assert entry["pixel_check"]["non_uniform"] is True
        assert out["checkpoint_id"]                   # checkpointed first
        # the shader now reads the baked file, and the old noise is gone
        assert any(dst == "skin_mat.baseColor" for _src, dst in fake.connected)
        assert "mcpTex_noise" in fake.deleted

    def test_an_unmeasurable_bake_refuses_rather_than_shipping(
            self, fake, tmp_path, monkeypatch):
        monkeypatch.setattr(texbake, "_convert_solid_tx", _fake_bake(fake))
        monkeypatch.setattr(texbake.pngprobe, "uniformity",
                            lambda _p: {"pixel_count": 0,
                                        "distinct_values": 0,
                                        "non_uniform": None,
                                        "unavailable_reason": "unreadable"})
        with pytest.raises(HandlerError, match="could not be measured"):
            texbake.bake_textures(_params(tmp_path))
        assert fake.connected == []


class TestFixRound1:
    """Review found five issues in the two-phase bake, all present verbatim
    in the plan's own code: a destructive orphan-delete false positive, a
    phase-A sweep that could touch a job it never attempted, a checkpoint
    taken for a pure no-op, and phase-B failures that reach the caller
    without saying the scene was already modified."""

    def test_a_terminal_feeding_two_slots_survives_baking_only_one(
            self, fake, tmp_path, monkeypatch):
        # mcpTex_noise ALSO drives metalness (an ordinary shared-terminal
        # topology - one noise, two channels). Baking only color must not
        # destroy metalness's still-live wiring.
        fake.conns["skin_mat.metalness"] = ["mcpTex_noise.outColorR"]
        fake.existing_attrs.add("skin_mat.metalness")
        monkeypatch.setattr(texbake, "_convert_solid_tx", _fake_bake(fake))
        monkeypatch.setattr(texbake.pngprobe, "uniformity",
                            lambda _p: {"pixel_count": 1024,
                                        "distinct_values": 186,
                                        "non_uniform": True,
                                        "unavailable_reason": None})

        out = texbake.bake_textures(_params(tmp_path, slots=["color"]))

        assert "mcpTex_noise" not in fake.deleted
        assert fake.conns["skin_mat.metalness"] == ["mcpTex_noise.outColorR"]
        assert any("mcpTex_noise" in w and "still used" in w
                  for w in out["warnings"])

    def test_a_via_intermediate_that_becomes_orphaned_is_deleted(
            self, fake, tmp_path, monkeypatch):
        # skin_mat.baseColor <- mcpTex_inv (reverse) <- mcpTex_noise: a
        # hand-built invert sitting between the terminal and the slot.
        # job["via"] records only the TYPE "reverse", not this node's
        # name - the fix must still find and delete it (finding #5: via
        # nodes used to accumulate as permanent orphans).
        fake.types["mcpTex_inv"] = "reverse"
        fake.conns["skin_mat.baseColor"] = ["mcpTex_inv.output"]
        fake.conns["mcpTex_inv.input"] = ["mcpTex_noise.outColor"]
        monkeypatch.setattr(texbake, "_convert_solid_tx", _fake_bake(fake))
        monkeypatch.setattr(texbake.pngprobe, "uniformity",
                            lambda _p: {"pixel_count": 1024,
                                        "distinct_values": 186,
                                        "non_uniform": True,
                                        "unavailable_reason": None})

        texbake.bake_textures(_params(tmp_path))

        assert "mcpTex_inv" in fake.deleted
        assert "mcpTex_noise" in fake.deleted

    def test_a_phase_a_failure_never_touches_an_unattempted_jobs_part_file(
            self, fake, tmp_path, monkeypatch):
        # Three procedural slots - AUTHORED_ATTRS sorts their attrs
        # baseColor < metalness < specularRoughness, so this is
        # deterministically color(1) -> metalness(2) -> roughness(3).
        fake.types["mcpTex_noise2"] = "noise"
        fake.types["mcpTex_noise3"] = "noise"
        fake.conns["skin_mat.metalness"] = ["mcpTex_noise2.outColorR"]
        fake.conns["skin_mat.specularRoughness"] = ["mcpTex_noise3.outColorR"]
        fake.existing_attrs.add("skin_mat.metalness")
        fake.existing_attrs.add("skin_mat.specularRoughness")

        stray = tmp_path / "skin_mat_roughness_baked.png.part.png"
        stray.write_bytes(b"PRE-EXISTING")
        color_part = tmp_path / "skin_mat_color_baked.png.part.png"

        def _bake(cmds, source_plug, target, path, resolution):
            if "metalness" in path:
                return  # writes no file - job 2 of 3 fails
            with open(path, "wb") as fh:
                fh.write(b"\x89PNG\r\n\x1a\n" + b"x" * 64)
            fake.baked_calls.append((source_plug, target, path, resolution))

        monkeypatch.setattr(texbake, "_convert_solid_tx", _bake)
        monkeypatch.setattr(texbake.pngprobe, "uniformity",
                            lambda _p: {"pixel_count": 1024,
                                        "distinct_values": 186,
                                        "non_uniform": True,
                                        "unavailable_reason": None})

        with pytest.raises(HandlerError, match="produced no file"):
            texbake.bake_textures(_params(tmp_path))

        assert stray.read_bytes() == b"PRE-EXISTING"  # untouched - never attempted
        assert not color_part.exists()                # job 1's part IS swept

    def test_the_file_backed_only_case_takes_no_checkpoint(self, fake,
                                                            tmp_path):
        fake.types["mcpTex_file"] = "file"
        fake.conns["skin_mat.baseColor"] = ["mcpTex_file.outColor"]

        out = texbake.bake_textures(_params(tmp_path))

        assert out["checkpoint_id"] is None
        assert out["baked"] == []
        assert any("already file-backed" in w for w in out["skipped_file_backed"])
        assert fake.checkpoints == []

    def test_a_phase_b_failure_names_the_checkpoint_and_says_modified(
            self, fake, tmp_path, monkeypatch):
        monkeypatch.setattr(texbake, "_convert_solid_tx", _fake_bake(fake))
        monkeypatch.setattr(texbake.pngprobe, "uniformity",
                            lambda _p: {"pixel_count": 1024,
                                        "distinct_values": 186,
                                        "non_uniform": True,
                                        "unavailable_reason": None})

        def boom(cmds, job, final_path):
            raise RuntimeError("boom")

        monkeypatch.setattr(texbake, "_rewire", boom)

        with pytest.raises(HandlerError, match="modified") as excinfo:
            texbake.bake_textures(_params(tmp_path))

        assert "cp" in str(excinfo.value)              # names the checkpoint
        assert excinfo.value.__cause__ is not None      # chained with `from exc`

    def test_a_postcondition_walk_failure_names_the_checkpoint_and_says_modified(
            self, fake, tmp_path, monkeypatch):
        # fix round 2: material_claims is called TWICE - once inside
        # plan_bakes (must succeed, or nothing would ever get planned) and
        # once as the postcondition re-walk AFTER the scene is fully
        # rewired. Only the second call is made to fail here.
        monkeypatch.setattr(texbake, "_convert_solid_tx", _fake_bake(fake))
        monkeypatch.setattr(texbake.pngprobe, "uniformity",
                            lambda _p: {"pixel_count": 1024,
                                        "distinct_values": 186,
                                        "non_uniform": True,
                                        "unavailable_reason": None})

        real_claims = texbake.texclaim.material_claims
        calls = []

        def flaky_claims(cmds, shapes):
            calls.append(1)
            if len(calls) >= 2:
                raise RuntimeError("boom")
            return real_claims(cmds, shapes)

        monkeypatch.setattr(texbake.texclaim, "material_claims", flaky_claims)

        with pytest.raises(HandlerError, match="modified") as excinfo:
            texbake.bake_textures(_params(tmp_path))

        assert "postcondition" in str(excinfo.value)
        assert "cp" in str(excinfo.value)               # names the checkpoint
        assert excinfo.value.__cause__ is not None       # chained with `from exc`
        # the scene WAS rewired before the postcondition walk blew up
        assert any(dst == "skin_mat.baseColor" for _src, dst in fake.connected)


class TestNormalSlotWithAnIndirectBump:
    """#799: a normal slot whose bump2d is not the DIRECT source of
    normalCamera passes every refusal and then has nowhere to land.

    `plan_bakes` gates the normal-slot refusal on `"bump2d" in claim["via"]`
    - which the WALK fills in from anywhere in the chain - and then asks
    `_bump_node_for` for the node itself, which looks only at the direct
    sources of `material.attr`. Wire the chain the walk already accepts,
    `normalCamera <- reverse <- bump2d <- noise`, and those two disagree:
    via carries "bump2d" so the refusal passes, and bump_node comes back
    None. Nothing downstream is written for that combination.

    Found by driving the hardened fake rather than by reading: the fake
    could always crash on this input, but no fixture had ever built a
    normal slot the walk reaches through a pass-through node. Both halves
    are pinned, NOT fixed - which of the three cures is right (refuse in
    plan_bakes, widen _bump_node_for to walk, or refuse in _rewire) is a
    call for a ticket with a live Maya behind it.
    """

    def _indirect_bump(self, fake):
        fake.existing_attrs = {"skin_mat.normalCamera"}
        fake.types["mcpTex_bump"] = "bump2d"
        fake.types["mcpTex_inv"] = "reverse"
        fake.conns = {
            "bodySG.surfaceShader": ["skin_mat.outColor"],
            "skin_mat.normalCamera": ["mcpTex_inv.output"],
            "mcpTex_inv.input": ["mcpTex_bump.outNormal"],
            "mcpTex_bump.bumpValue": ["mcpTex_noise.outColorR"],
        }

    @pytest.mark.xfail(strict=True, reason=(
        "#799: the bake is planned, the image is committed to disk, and "
        "then _orphan_candidates hands cmds.listConnections a bump_node of "
        "None as if it were a node name (start = job['bump_node'] for "
        "kind=='normal'). The caller is told 'the scene has been modified "
        "while committing' and pointed at a checkpoint, when in fact this "
        "job never reached _rewire at all - the diagnosis, the checkpoint "
        "and the burned checkpoint slot are all wrong. Maya rejects a None "
        "object name the same way; nothing about this depends on the fake"))
    def test_a_normal_slot_reached_through_a_reverse_is_diagnosed_not_crashed(
            self, fake, tmp_path, monkeypatch):
        self._indirect_bump(fake)
        monkeypatch.setattr(texbake, "_convert_solid_tx", _fake_bake(fake))
        monkeypatch.setattr(texbake.pngprobe, "uniformity",
                            lambda _p: {"pixel_count": 1024,
                                        "distinct_values": 186,
                                        "non_uniform": True,
                                        "unavailable_reason": None})

        # Either refusal is honest - "no bump2d this tool can rewire" at
        # plan time is the cheap one. What is not honest is baking, then
        # crashing on an internal None, then blaming the scene.
        with pytest.raises(HandlerError, match="bump2d"):
            texbake.bake_textures(_params(tmp_path))
        assert fake.checkpoints == []      # refused before any mutation

    @pytest.mark.xfail(strict=True, reason=(
        "#799: _rewire's normal arm is gated on `job['bump_node']` being "
        "truthy, so a normal job that arrived without one falls through to "
        "the COLOUR arm and connects file.outColor straight into "
        "material.normalCamera - the bump2d bypassed, an image baked from "
        "outColorR (a scalar height) read back as an RGB normal vector, "
        "and kept_intermediates reported as []. Both plugs are float3, so "
        "Maya ACCEPTS that connection: there is no error anywhere, the "
        "render is just wrong. Today the _orphan_candidates crash above "
        "fires first and hides it"))
    def test_rewire_never_wires_a_normal_slot_as_if_it_were_colour(
            self, fake, tmp_path):
        # Synthetic job, the TestGuardStructure idiom: the crash pinned
        # above means no real plan_bakes claim can carry this arm its
        # input today, so it is handed in directly.
        self._indirect_bump(fake)
        job = {"material": "skin_mat", "sg": "bodySG", "attr": "normalCamera",
               "slot": "normal", "kind": "normal", "bump_node": None,
               "via": ["reverse", "bump2d"], "mesh": "|bodyShape",
               "meshes": ["|bodyShape"],
               "terminal_plug": "mcpTex_noise.outColorR",
               "basename": "skin_mat_normal_baked.png"}

        wiring = texbake._rewire(fake, job, str(tmp_path / "n.png"))

        assert wiring["wired_plug"] != "outColor", (
            "a normal slot was wired as a colour slot: %s" % (wiring,))


class TestTheFakeRefusesWhatMayaRefuses:
    """#799 round 2: the regression barrier for THIS file's FakeCmds.

    Round 1 hardened four of the five look-group fakes and an adversarial
    reviewer measured the result: reverting every behavioural change left
    the suite at 184 passed / 2 xfailed / 0 failed. Not one test put a
    fake in a state where the new refusals fire, so 562 lines of modelled
    Maya behaviour carried no barrier at all - the ticket's own premise
    ("a green suite proves nothing") reproduced one level up.

    Everything below asserts a contract point THIS fake models, so that
    loosening it back has to go red. Nothing here scaffolds a call the
    bake handler does not make.
    """

    # contract 1 - a name the scene does not hold ---------------------
    def test_a_query_about_a_deleted_node_raises(self):
        cmds = FakeCmds()
        cmds.delete("mcpTex_noise")
        for call in (lambda: cmds.nodeType("mcpTex_noise"),
                     lambda: cmds.getAttr("mcpTex_noise.outColor"),
                     lambda: cmds.listConnections("mcpTex_noise.outColor",
                                                  source=True),
                     lambda: cmds.attributeQuery("outColor",
                                                 node="mcpTex_noise",
                                                 exists=True),
                     lambda: cmds.listRelatives("mcpTex_noise", shapes=True),
                     lambda: cmds.polyEvaluate("mcpTex_noise", uvcoord=True),
                     lambda: cmds.listSets(object="mcpTex_noise")):
            with pytest.raises(RuntimeError, match="No object matches name"):
                call()

    def test_a_query_about_a_node_that_never_existed_raises(self):
        cmds = FakeCmds()
        with pytest.raises(RuntimeError, match="No object matches name"):
            cmds.nodeType("never_made")
        with pytest.raises(RuntimeError, match="No object matches name"):
            cmds.getAttr("never_made.outColor")

    def test_objExists_answers_for_a_vanished_node_instead_of_raising(self):
        cmds = FakeCmds()
        assert cmds.objExists("mcpTex_noise") is True
        cmds.delete("mcpTex_noise")
        assert cmds.objExists("mcpTex_noise") is False
        assert cmds.objExists("never_made") is False

    def test_a_deleted_name_re_created_exists_again(self):
        """The round-2 BLOCKING defect: `self.deleted` was a permanent
        tombstone, so a name deleted and then re-created was present in
        `types` and absent to every query at once - a scene Maya cannot
        have, on a path this module walks every time it bakes a second
        mesh."""
        cmds = FakeCmds()
        cmds.delete("mcpTex_noise")
        cmds.shadingNode("noise", name="mcpTex_noise", asTexture=True)
        assert cmds.objExists("mcpTex_noise") is True
        assert cmds.nodeType("mcpTex_noise") == "noise"
        cmds.setAttr("mcpTex_noise.threshold", 0.5)   # must not raise
        assert cmds.deleted == ["mcpTex_noise"]       # still a RECORD

    # contract 1, strict direction ------------------------------------
    def test_an_existing_but_empty_shading_group_answers_rather_than_raises(
            self):
        """A set that does not EXIST raises; a set that exists and holds
        nothing answers []. Round 1 refused both, which is the
        strict-direction defect the round-2 brief names: a fake that is
        wrong toward strictness produces spurious failures the next agent
        'fixes' by weakening it back."""
        cmds = FakeCmds()
        # An SG that EXISTS but has no members: registered as a node,
        # absent from the membership registry. Round 1 keyed the
        # refusal on membership, so this - a real, empty set - raised.
        cmds.types["emptySG"] = "shadingEngine"
        assert cmds.objExists("emptySG") is True
        assert cmds.sets("emptySG", query=True) == []
        assert cmds.sets("bodySG", query=True) == ["|bodyShape"]
        with pytest.raises(RuntimeError, match="No object matches name"):
            cmds.sets("noSuchSG", query=True)

    # contract 2 - locked or connected --------------------------------
    def test_setAttr_refuses_a_plug_a_connection_feeds(self):
        cmds = FakeCmds()      # mcpTex_noise.outColor -> skin_mat.baseColor
        with pytest.raises(RuntimeError, match="locked or connected"):
            cmds.setAttr("skin_mat.baseColor", 1.0, 1.0, 1.0)

    def test_setAttr_refuses_a_child_of_a_fed_compound(self):
        """Both compound directions. Round 1 modelled only the
        compound-with-a-fed-child arm; Maya refuses the mirror too."""
        cmds = FakeCmds()      # the COMPOUND skin_mat.baseColor is fed
        with pytest.raises(RuntimeError, match="locked or connected"):
            cmds.setAttr("skin_mat.baseColorR", 1.0)

    def test_setAttr_refuses_a_compound_whose_child_is_fed(self):
        cmds = FakeCmds()
        cmds.conns["skin_mat.emissionColorG"] = ["mcpTex_noise.outAlpha"]
        with pytest.raises(RuntimeError, match="locked or connected"):
            cmds.setAttr("skin_mat.emissionColor", 0.0, 0.0, 0.0)

    def test_setAttr_refuses_a_locked_plug_in_both_compound_directions(self):
        cmds = FakeCmds()
        cmds.locked.add("skin_mat.specularRoughness")
        with pytest.raises(RuntimeError, match="locked or connected"):
            cmds.setAttr("skin_mat.specularRoughness", 0.4)
        cmds.locked.add("skin_mat.coatColor")
        with pytest.raises(RuntimeError, match="locked or connected"):
            cmds.setAttr("skin_mat.coatColorB", 0.4)     # child of a lock
        cmds.locked.add("skin_mat.subsurfaceColorR")
        with pytest.raises(RuntimeError, match="locked or connected"):
            cmds.setAttr("skin_mat.subsurfaceColor", 1.0, 1.0, 1.0)

    def test_setAttr_to_a_free_plug_is_what_getAttr_reads_back(self):
        """getAttr used to answer "" for every plug on every name - a
        method that can never fail a test. It is a stored value now."""
        cmds = FakeCmds()
        cmds.setAttr("skin_mat.specularRoughness", 0.25)
        assert cmds.getAttr("skin_mat.specularRoughness") == 0.25
        assert cmds.getAttr("skin_mat.metalness") == ""   # modelled default

    def test_connectAttr_refuses_an_occupied_destination_unless_forced(self):
        cmds = FakeCmds()
        cmds.types["mcpTex_other"] = "noise"
        with pytest.raises(RuntimeError, match="already connected"):
            cmds.connectAttr("mcpTex_other.outColor", "skin_mat.baseColor")
        cmds.connectAttr("mcpTex_other.outColor", "skin_mat.baseColor",
                         force=True)
        assert cmds.conns["skin_mat.baseColor"] == ["mcpTex_other.outColor"]

    def test_connectAttr_refuses_a_node_that_is_not_in_the_scene(self):
        cmds = FakeCmds()
        with pytest.raises(RuntimeError, match="No object matches name"):
            cmds.connectAttr("ghost.outColor", "skin_mat.emissionColor")
        with pytest.raises(RuntimeError, match="No object matches name"):
            cmds.connectAttr("mcpTex_noise.outColor", "ghost.baseColor")
