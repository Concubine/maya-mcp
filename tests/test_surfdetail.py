"""#775 task 3: what apply_surface_detail refuses, plans, and applies.

FakeCmds is meshmaps' fake (tests/test_meshmaps.py), copied rather than
imported so this suite does not couple to meshmaps' test internals - the
same call already made for texbake's and meshmaps' own fakes. The
listConnections/connectAttr pair is already generic over any plug
(node.attr), which is what makes it answer `shader.normalCamera` and
`bump2d`/`place2dTexture` connections correctly without any dedicated
bookkeeping: every wire this handler makes is just another entry in the
same `conns` dict.
"""

import os

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import (meshmaps, pngprobe, pngwrite, surfdetail,
                                  surfdetail_math)


class FakeCmds:
    """|limb (shape |limbShape) wears limbSG -> limb_mat (standardSurface),
    baseColor unconnected (a plain white value)."""

    def __init__(self):
        self.meshes = {"|limb": "|limbShape"}
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
        said ""), which is the shape that hid one of #796's blocking
        defects: code asking about a node it had just deleted got a
        plausible answer here and a RuntimeError in Maya. This module's
        rollback path DELETES every node it created and its colour path
        sweeps the base file node, so a query about a consumed node is
        the live risk here.

        Deletion is modelled by `delete` REMOVING the node from the
        registries `_exists` reads, NOT by a name tombstone: #799 round 2
        found that consulting `self.deleted` here made a name that was
        deleted and then re-created present in `types` and absent to every
        query at the same time - a scene Maya cannot have. `self.deleted`
        is a RECORD for assertions, never an existence oracle.
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

    def ls(self, *args, **kw):
        """Resolves transforms AND shapes: a shading group's members are
        SHAPES, and #796's canonicalisation sends every one of them
        through here (this fake reaches it via meshmaps.plan_apply)."""
        if kw.get("selection"):
            return list(self.selection)
        name = args[0] if args else kw.get("name")
        known = list(self.meshes) + list(self.meshes.values())
        if name in known:
            paths = [name]
        else:
            paths = [n for n in known if n.split("|")[-1] == name]
        if not kw.get("uuid"):
            return paths
        # #799: `uuid=True` asks a DIFFERENT question - which NODE - and
        # the old fake answered it with DAG PATHS. Round 2 corrects the
        # rationale round 1 gave for this edit: the old answer was NOT
        # empty and did NOT send `texbake._node_ids` down its degrade arm
        # (that arm is `return set()` on exception, and was never reached
        # either way). The old answer was a non-empty set whose members
        # happened to be paths, and because this fake has no instancing
        # every downstream decision came out the same. The edit stands on
        # its own ground - a path is not an identity, and a fake that
        # conflates them cannot be extended to instancing without lying -
        # not on a dead branch it did not un-deaden. One node per path is
        # the honest model here (test_meshmaps' fake owns instancing), and
        # TestTheFakeRefusesWhatMayaRefuses pins the distinction.
        return ["uuid:" + p for p in paths]

    def objExists(self, name):
        # The one query #799 exempts: objExists ANSWERS for a vanished
        # node, it does not raise.
        return self._exists(name)

    def listRelatives(self, node, shapes=False, fullPath=False,
                      parent=False, **kw):
        """Both directions - the shape -> transform one is what
        meshmaps._transform_short_name asks for, and answering None to it
        unconditionally sent every call down that helper's "a shape that
        cannot answer stands for itself" degrade arm (#799 contract 3)."""
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
            # Maya - and this module's rollback deletes names its next
            # attempt builds again.
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


@pytest.fixture
def fake(monkeypatch):
    cmds = FakeCmds()
    monkeypatch.setattr(surfdetail, "_cmds", lambda: cmds)
    monkeypatch.setattr(surfdetail.session, "auto_checkpoint",
                        lambda reason: (cmds.checkpoints.append(reason)
                                        or {"checkpoint_id": "cp",
                                            "path": "cp.ma"}))
    return cmds


def _varied_png(path, size=4):
    """A real, non-uniform PNG - what a real curvature/ao bake looks like."""
    pixels = [((x * 37 + y * 11) % 256,) * 3
             for y in range(size) for x in range(size)]
    pngwrite.write_png(str(path), size, size, pixels)
    return str(path)


def _flat_png(path, size=4, value=128):
    pixels = [(value, value, value)] * (size * size)
    pngwrite.write_png(str(path), size, size, pixels)
    return str(path)


def _masks(tmp_path, short="limb", size=4, curvature=True, ao=True):
    if curvature:
        _varied_png(tmp_path / ("%s_curvature.png" % short), size)
    if ao:
        _varied_png(tmp_path / ("%s_ao.png" % short), size)


def _params(tmp_path, mesh="|limb", effects=None, **kw):
    base = {"mesh": mesh, "maps_dir": str(tmp_path),
           "effects": effects if effects is not None else [{"kind": "wear"}]}
    base.update(kw)
    return base


# --------------------------------------------------------------------------
# 1-8: TestValidation
# --------------------------------------------------------------------------


class TestValidation:
    # 1: unknown top-level / per-effect key
    def test_unknown_top_level_key_refuses_naming_synonym(self, fake, tmp_path):
        params = _params(tmp_path)
        params["masks_dir"] = params.pop("maps_dir")
        with pytest.raises(HandlerError, match="masks_dir") as exc:
            surfdetail.validate(params, fake)
        assert "'maps_dir'" in (exc.value.hint or "")

    def test_unknown_effect_key_refuses_naming_synonym(self, fake, tmp_path):
        params = _params(tmp_path, effects=[
            {"kind": "wear", "colour": [0.5, 0.5, 0.5]}])
        with pytest.raises(HandlerError, match="colour") as exc:
            surfdetail.validate(params, fake)
        assert "'color'" in (exc.value.hint or "")

    # 2: effects missing/empty/non-list, unknown kind, repeated kind
    def test_effects_missing_refuses(self, fake, tmp_path):
        params = _params(tmp_path)
        del params["effects"]
        with pytest.raises(HandlerError, match="effects"):
            surfdetail.validate(params, fake)

    def test_effects_empty_refuses(self, fake, tmp_path):
        with pytest.raises(HandlerError, match="effects"):
            surfdetail.validate(_params(tmp_path, effects=[]), fake)

    def test_effects_non_list_refuses(self, fake, tmp_path):
        with pytest.raises(HandlerError, match="effects"):
            surfdetail.validate(_params(tmp_path, effects="wear"), fake)

    def test_unknown_kind_refuses(self, fake, tmp_path):
        with pytest.raises(HandlerError, match="kind"):
            surfdetail.validate(_params(tmp_path, effects=[{"kind": "rust"}]),
                                fake)

    def test_repeated_kind_refuses(self, fake, tmp_path):
        params = _params(tmp_path, effects=[{"kind": "wear"},
                                            {"kind": "wear"}])
        with pytest.raises(HandlerError, match="repeats"):
            surfdetail.validate(params, fake)

    # 3: strength/scale ranges + defaults
    def test_strength_zero_refuses(self, fake, tmp_path):
        params = _params(tmp_path, effects=[{"kind": "wear", "strength": 0}])
        with pytest.raises(HandlerError, match="strength"):
            surfdetail.validate(params, fake)

    def test_strength_above_max_refuses(self, fake, tmp_path):
        params = _params(tmp_path,
                         effects=[{"kind": "wear", "strength": 4.5}])
        with pytest.raises(HandlerError, match="strength"):
            surfdetail.validate(params, fake)

    def test_strength_non_numeric_refuses(self, fake, tmp_path):
        params = _params(tmp_path,
                         effects=[{"kind": "wear", "strength": "lots"}])
        with pytest.raises(HandlerError, match="strength"):
            surfdetail.validate(params, fake)

    def test_strength_bool_refuses(self, fake, tmp_path):
        params = _params(tmp_path,
                         effects=[{"kind": "wear", "strength": True}])
        with pytest.raises(HandlerError, match="strength"):
            surfdetail.validate(params, fake)

    def test_scale_zero_refuses(self, fake, tmp_path):
        params = _params(tmp_path, effects=[{"kind": "wear", "scale": 0}])
        with pytest.raises(HandlerError, match="scale"):
            surfdetail.validate(params, fake)

    def test_scale_above_max_refuses(self, fake, tmp_path):
        params = _params(tmp_path, effects=[{"kind": "wear", "scale": 17}])
        with pytest.raises(HandlerError, match="scale"):
            surfdetail.validate(params, fake)

    def test_defaults_strength_and_scale(self, fake, tmp_path):
        # 2.0, not the original 0.5: #775 task 6's look probe measured the
        # old defaults as sub-visible in a render (six 8-bit levels across
        # the whole composite), and a caller who cannot see must get detail
        # that reads from the default.
        out = surfdetail.validate(_params(tmp_path, effects=[{"kind": "wear"}]),
                                  fake)
        assert out["effects"][0]["strength"] == 2.0
        assert out["effects"][0]["scale"] == 1.0

    def test_grime_and_grain_defaults(self, fake, tmp_path):
        grime = surfdetail.validate(
            _params(tmp_path, effects=[{"kind": "grime"}]), fake)
        assert grime["effects"][0]["strength"] == 1.5
        grain = surfdetail.validate(
            _params(tmp_path, effects=[{"kind": "grain"}]), fake)
        assert grain["effects"][0]["strength"] == 2.0

    def test_default_seed_is_zero(self, fake, tmp_path):
        out = surfdetail.validate(_params(tmp_path), fake)
        assert out["seed"] == 0

    # 4: color validation
    def test_color_out_of_range_refuses(self, fake, tmp_path):
        params = _params(tmp_path,
                         effects=[{"kind": "wear", "color": [2.0, 0, 0]}])
        with pytest.raises(HandlerError, match="color"):
            surfdetail.validate(params, fake)

    def test_color_wrong_length_refuses(self, fake, tmp_path):
        params = _params(tmp_path,
                         effects=[{"kind": "wear", "color": [0.1, 0.2]}])
        with pytest.raises(HandlerError, match="color"):
            surfdetail.validate(params, fake)

    def test_color_non_numeric_refuses(self, fake, tmp_path):
        params = _params(tmp_path, effects=[
            {"kind": "wear", "color": ["a", "b", "c"]}])
        with pytest.raises(HandlerError, match="color"):
            surfdetail.validate(params, fake)

    def test_color_defaults_to_measured_wear_color(self, fake, tmp_path):
        out = surfdetail.validate(_params(tmp_path, effects=[{"kind": "wear"}]),
                                  fake)
        assert out["effects"][0]["color"] == list(
            surfdetail_math.DEFAULT_WEAR_COLOR)

    def test_color_defaults_to_measured_grime_color(self, fake, tmp_path):
        out = surfdetail.validate(
            _params(tmp_path, effects=[{"kind": "grime"}]), fake)
        assert out["effects"][0]["color"] == list(
            surfdetail_math.DEFAULT_GRIME_COLOR)

    def test_color_is_stored_linear_not_reencoded(self, fake, tmp_path):
        out = surfdetail.validate(_params(tmp_path, effects=[
            {"kind": "wear", "color": [0.2, 0.2, 0.2]}]), fake)
        assert out["effects"][0]["color"] == [0.2, 0.2, 0.2]

    # F1 (#775 fix wave): grain writes a HEIGHT map - a `color` on it was
    # silently accepted and dropped by _validate_color before this fix.
    def test_grain_with_color_refuses(self, fake, tmp_path):
        params = _params(tmp_path, effects=[
            {"kind": "grain", "color": [0.1, 0.1, 0.1]}])
        with pytest.raises(HandlerError, match="grain") as exc:
            surfdetail.validate(params, fake)
        # names the actual problem (no colour to tint) and redirects the
        # caller, rather than a bare "invalid" - this assertion fails if
        # the refusal is ever swapped back for silent acceptance.
        assert "HEIGHT map" in (exc.value.hint or "")
        assert "wear" in (exc.value.hint or "")
        assert "grime" in (exc.value.hint or "")

    # 5: maps_dir / out_dir
    def test_maps_dir_required(self, fake, tmp_path):
        params = _params(tmp_path)
        del params["maps_dir"]
        with pytest.raises(HandlerError, match="maps_dir"):
            surfdetail.validate(params, fake)

    def test_maps_dir_must_be_absolute(self, fake, tmp_path):
        with pytest.raises(HandlerError, match="absolute"):
            surfdetail.validate(_params(tmp_path, maps_dir="rel/dir"), fake)

    def test_maps_dir_must_exist(self, fake, tmp_path):
        with pytest.raises(HandlerError, match="does not exist"):
            surfdetail.validate(
                _params(tmp_path, maps_dir=str(tmp_path / "nope")), fake)

    def test_out_dir_defaults_to_maps_dir(self, fake, tmp_path):
        out = surfdetail.validate(_params(tmp_path), fake)
        assert out["out_dir"] == str(tmp_path)

    def test_out_dir_given_must_be_absolute(self, fake, tmp_path):
        with pytest.raises(HandlerError, match="absolute"):
            surfdetail.validate(_params(tmp_path, out_dir="rel"), fake)

    def test_out_dir_given_must_exist(self, fake, tmp_path):
        with pytest.raises(HandlerError, match="does not exist"):
            surfdetail.validate(
                _params(tmp_path, out_dir=str(tmp_path / "nope")), fake)

    # 6: mask file resolution (missing)
    def test_missing_curvature_mask_refuses_naming_path(self, tmp_path):
        mesh = ("|limb", "|limbShape")
        effects = [{"kind": "wear", "strength": 0.5, "scale": 1.0,
                   "color": [0, 0, 0]}]
        with pytest.raises(HandlerError) as exc:
            surfdetail._resolve_masks(mesh, effects, str(tmp_path), None)
        assert str(tmp_path / "limb_curvature.png") in str(exc.value)
        assert "maya_bake_mesh_maps" in (exc.value.hint or "")

    def test_missing_ao_mask_for_grime_refuses(self, tmp_path):
        mesh = ("|limb", "|limbShape")
        effects = [{"kind": "grime", "strength": 0.5, "scale": 1.0,
                   "color": [0, 0, 0]}]
        with pytest.raises(HandlerError) as exc:
            surfdetail._resolve_masks(mesh, effects, str(tmp_path), None)
        assert str(tmp_path / "limb_ao.png") in str(exc.value)

    def test_grain_needs_both_masks(self, tmp_path):
        _varied_png(tmp_path / "limb_curvature.png")
        mesh = ("|limb", "|limbShape")
        effects = [{"kind": "grain", "strength": 0.3, "scale": 1.0,
                   "color": None}]
        with pytest.raises(HandlerError) as exc:
            surfdetail._resolve_masks(mesh, effects, str(tmp_path), None)
        assert str(tmp_path / "limb_ao.png") in str(exc.value)

    # 7: flat / unmeasurable
    def test_flat_mask_refuses_naming_distinct_values(self, tmp_path):
        _flat_png(tmp_path / "limb_curvature.png")
        mesh = ("|limb", "|limbShape")
        effects = [{"kind": "wear", "strength": 0.5, "scale": 1.0,
                   "color": [0, 0, 0]}]
        with pytest.raises(HandlerError, match="distinct_values") as exc:
            surfdetail._resolve_masks(mesh, effects, str(tmp_path), None)
        assert "flat" in str(exc.value)

    def test_unmeasurable_mask_refuses(self, tmp_path):
        (tmp_path / "limb_curvature.png").write_bytes(b"not a png")
        mesh = ("|limb", "|limbShape")
        effects = [{"kind": "wear", "strength": 0.5, "scale": 1.0,
                   "color": [0, 0, 0]}]
        with pytest.raises(HandlerError, match="could not be measured"):
            surfdetail._resolve_masks(mesh, effects, str(tmp_path), None)

    # 8: resolution
    def test_resolution_must_be_in_texbake_resolutions(self, fake, tmp_path):
        with pytest.raises(HandlerError, match="resolution"):
            surfdetail.validate(_params(tmp_path, resolution=999), fake)

    def test_resolution_defaults_to_mask_width(self, tmp_path):
        _varied_png(tmp_path / "limb_curvature.png", size=4)
        mesh = ("|limb", "|limbShape")
        effects = [{"kind": "wear", "strength": 0.5, "scale": 1.0,
                   "color": [0, 0, 0]}]
        _masks_out, res = surfdetail._resolve_masks(mesh, effects,
                                                     str(tmp_path), None)
        assert res == 4

    def test_grain_masks_disagreeing_size_refuses(self, tmp_path):
        _varied_png(tmp_path / "limb_curvature.png", size=4)
        _varied_png(tmp_path / "limb_ao.png", size=8)
        mesh = ("|limb", "|limbShape")
        effects = [{"kind": "grain", "strength": 0.3, "scale": 1.0,
                   "color": None}]
        with pytest.raises(HandlerError, match="disagree"):
            surfdetail._resolve_masks(mesh, effects, str(tmp_path), None)

    def test_explicit_resolution_skips_the_grain_size_check(self, tmp_path):
        _varied_png(tmp_path / "limb_curvature.png", size=4)
        _varied_png(tmp_path / "limb_ao.png", size=8)
        mesh = ("|limb", "|limbShape")
        effects = [{"kind": "grain", "strength": 0.3, "scale": 1.0,
                   "color": None}]
        _masks_out, res = surfdetail._resolve_masks(mesh, effects,
                                                     str(tmp_path), 1024)
        assert res == 1024


# --------------------------------------------------------------------------
# 9-10: TestPlanning
# --------------------------------------------------------------------------


class TestPlanning:
    def test_color_effect_routes_through_plan_apply(self, fake, tmp_path,
                                                     monkeypatch):
        _masks(tmp_path)
        calls = []
        real = meshmaps.plan_apply

        def _spy(cmds, meshes):
            calls.append(meshes)
            return real(cmds, meshes)
        monkeypatch.setattr(meshmaps, "plan_apply", _spy)
        surfdetail.apply_surface_detail(_params(tmp_path))
        assert calls == [[("|limb", "|limbShape")]]

    def test_procedural_base_refuses_naming_bake_textures(self, fake,
                                                           tmp_path):
        _masks(tmp_path)
        fake.types["mcpTex_noise"] = "noise"
        fake.conns["limb_mat.baseColor"] = ["mcpTex_noise.outColor"]
        with pytest.raises(HandlerError, match="procedural") as exc:
            surfdetail.apply_surface_detail(_params(tmp_path))
        assert "maya_bake_textures" in (exc.value.hint or "")
        assert fake.checkpoints == []  # refused before any mutation

    def test_a_wearer_outside_the_request_refuses(self, fake, tmp_path):
        _masks(tmp_path)
        fake.meshes["|other"] = "|otherShape"
        fake.sg_members["limbSG"] = ["|limbShape", "|otherShape"]
        with pytest.raises(HandlerError, match="otherShape"):
            surfdetail.apply_surface_detail(_params(tmp_path))
        assert fake.checkpoints == []

    def test_grain_only_skips_plan_apply(self, fake, tmp_path, monkeypatch):
        _masks(tmp_path)

        def _boom(cmds, meshes):
            raise AssertionError("plan_apply must not run for a grain-only call")
        monkeypatch.setattr(meshmaps, "plan_apply", _boom)
        out = surfdetail.apply_surface_detail(
            _params(tmp_path, effects=[{"kind": "grain"}]))
        assert out["color_file"] is None

    def test_grain_refuses_when_shader_already_carries_a_bump_network(
            self, fake, tmp_path):
        _masks(tmp_path)
        # #799: a node named as a connection SOURCE has to exist, now that
        # a query about a name the scene does not hold raises here the way
        # it does in Maya.
        fake.types["someBump"] = "bump2d"
        fake.conns["limb_mat.normalCamera"] = ["someBump.outNormal"]
        with pytest.raises(HandlerError, match="already carries") as exc:
            surfdetail.apply_surface_detail(
                _params(tmp_path, effects=[{"kind": "wear"},
                                          {"kind": "grain"}]))
        assert "maya_bake_textures" in (exc.value.hint or "")
        assert fake.checkpoints == []  # refused before any mutation

    def test_grain_only_resolves_the_shader_the_mesh_wears(self, fake,
                                                            tmp_path):
        _masks(tmp_path)
        fake.types["someBump"] = "bump2d"       # #799: sources exist
        fake.conns["limb_mat.normalCamera"] = ["someBump.outNormal"]
        with pytest.raises(HandlerError, match="limb_mat"):
            surfdetail.apply_surface_detail(
                _params(tmp_path, effects=[{"kind": "grain"}]))

    # #767 minor M1: grain wires bump into shader.normalCamera, which is the
    # same MATERIAL-level edit the colour path makes - so it owes the same
    # two guarantees. Before this fix a grain-only call ran neither: on a
    # multi-SG mesh the bump silently reached one face subset only, and on a
    # shared material it silently changed an unnamed mesh's look.
    def test_grain_only_on_a_multi_sg_mesh_refuses(self, fake, tmp_path):
        _masks(tmp_path)
        fake.shape_sgs["|limbShape"] = ["limbSG", "trimSG"]
        with pytest.raises(HandlerError, match="shading groups"):
            surfdetail.apply_surface_detail(
                _params(tmp_path, effects=[{"kind": "grain"}]))
        assert fake.checkpoints == []  # refused before any mutation
        assert not list(tmp_path.glob("*_height.png"))

    def test_grain_only_on_a_material_worn_outside_the_request_refuses(
            self, fake, tmp_path):
        _masks(tmp_path)
        fake.meshes["|other"] = "|otherShape"
        fake.sg_members["limbSG"] = ["|limbShape", "|otherShape"]
        with pytest.raises(HandlerError, match="otherShape"):
            surfdetail.apply_surface_detail(
                _params(tmp_path, effects=[{"kind": "grain"}]))
        assert fake.checkpoints == []
        assert not list(tmp_path.glob("*_height.png"))

    def test_grain_only_on_a_clean_mesh_still_wires_through(self, fake,
                                                             tmp_path):
        # The guard must refuse the two harmful shapes and NOTHING else -
        # the ordinary single-SG, sole-wearer case reaches the same bump
        # wiring it always did.
        _masks(tmp_path)
        out = surfdetail.apply_surface_detail(
            _params(tmp_path, effects=[{"kind": "grain"}]))
        assert os.path.isfile(out["height_file"])
        assert any(dst == "limb_mat.normalCamera"
                   for _src, dst in fake.connected)


# --------------------------------------------------------------------------
# 11-15: TestApply
# --------------------------------------------------------------------------


class TestApply:
    def test_color_happy_path(self, fake, tmp_path):
        _masks(tmp_path)
        out = surfdetail.apply_surface_detail(_params(tmp_path, effects=[
            {"kind": "wear", "strength": 2.0, "scale": 4.0}]))
        assert fake.checkpoints == ["apply_surface_detail"]
        assert out["checkpoint_id"] == "cp"
        assert out["color_basename"] == "limb_mat_color_detail.png"
        assert out["color_file"] == os.path.join(str(tmp_path),
                                                 "limb_mat_color_detail.png")
        assert os.path.isfile(out["color_file"])
        assert not list(tmp_path.glob("*.part.png"))
        assert out["height_file"] is None
        assert out["height_basename"] is None
        assert any(dst == "limb_mat.baseColor" for _s, dst in fake.connected)
        assert out["mesh"] == "|limb"
        assert out["effects"][0]["kind"] == "wear"

    def test_color_replaces_a_file_base_and_sweeps_the_old_node(
            self, fake, tmp_path):
        _masks(tmp_path)
        base = tmp_path / "albedo.png"
        pngwrite.write_png(str(base), 2, 2, [(200, 100, 50)] * 4)
        fake.types["kit_file"] = "file"
        fake.conns["limb_mat.baseColor"] = ["kit_file.outColor"]
        fake.attr_values["kit_file.fileTextureName"] = str(base)
        fake.attr_values["kit_file.colorSpace"] = "sRGB"
        surfdetail.apply_surface_detail(_params(tmp_path))
        assert "kit_file" in fake.deleted
        assert os.path.isfile(str(base))  # the input atlas is never touched

    # F2 (#775 fix wave): a second apply to the same material resolves its
    # own previous composite as the new base (the first apply's rewire made
    # that the colour slot's current file) and is about to write over that
    # same path - warn rather than silently compound.
    def test_reapply_to_same_material_warns_and_still_succeeds(self, fake,
                                                                tmp_path):
        _masks(tmp_path)
        first = surfdetail.apply_surface_detail(_params(tmp_path))
        assert not any("colour base" in w for w in first["warnings"])

        second = surfdetail.apply_surface_detail(_params(tmp_path))
        assert second["color_file"] == first["color_file"]
        assert any("colour base" in w for w in second["warnings"])
        assert any("limb_mat_color_detail.png" in w
                   for w in second["warnings"])
        assert os.path.isfile(second["color_file"])

    def test_grain_happy_path_wires_bump_network(self, fake, tmp_path):
        _masks(tmp_path)
        out = surfdetail.apply_surface_detail(
            _params(tmp_path, effects=[{"kind": "grain", "strength": 0.7}]))
        assert out["height_basename"] == "limb_height.png"
        assert os.path.isfile(out["height_file"])
        assert out["color_file"] is None

        bump_nodes = [n for n in fake.created if fake.types.get(n) == "bump2d"]
        assert len(bump_nodes) == 1
        bump = bump_nodes[0]
        assert fake.attr_values[bump + ".bumpInterp"] == 0
        assert fake.attr_values[bump + ".bumpDepth"] == 0.7

        file_nodes = [n for n in fake.created if fake.types.get(n) == "file"]
        assert len(file_nodes) == 1
        fnode = file_nodes[0]
        assert (fnode + ".outAlpha", bump + ".bumpValue") in fake.connected
        # Without alphaIsLuminance the whole network is INERT: pngwrite
        # emits RGB with no alpha, so the file node's outAlpha - the plug
        # driving bumpValue on the line above - is a CONSTANT 1.0 and no
        # bumpDepth can make it shade (#775 task 6, measured live).
        assert fake.attr_values[fnode + ".alphaIsLuminance"] is True
        assert (bump + ".outNormal", "limb_mat.normalCamera") in fake.connected

    def test_changed_fraction_below_floor_warns(self, fake, tmp_path,
                                                monkeypatch):
        _masks(tmp_path)
        monkeypatch.setattr(
            surfdetail.surfdetail_math, "composite_detail",
            lambda base, effects, res: {
                "pixels": [(0, 0, 0)] * (res * res),
                "changed": {"wear": 0.001}})
        out = surfdetail.apply_surface_detail(_params(tmp_path))
        assert out["effects"][0]["changed_fraction"] == 0.001
        assert any("almost nothing" in w for w in out["warnings"])

    def test_grain_changed_fraction_below_floor_warns(self, fake, tmp_path,
                                                       monkeypatch):
        _masks(tmp_path)
        monkeypatch.setattr(
            surfdetail, "_grain_pixels",
            lambda grain, res: ([(0, 0, 0)] * (res * res), 0.001))
        out = surfdetail.apply_surface_detail(
            _params(tmp_path, effects=[{"kind": "grain"}]))
        assert out["effects"][0]["changed_fraction"] == 0.001
        assert any("almost nothing" in w for w in out["warnings"])

    def test_postcondition_reads_file_backed_at_the_new_path(self, fake,
                                                              tmp_path):
        _masks(tmp_path)
        out = surfdetail.apply_surface_detail(_params(tmp_path))
        claims = surfdetail.texclaim.material_claims(fake, ["|limbShape"])
        claim = next(c for c in claims if c["material"] == "limb_mat"
                    and c["attr"] == "baseColor")
        assert claim["classification"] == "file"
        assert claim["terminals"][0]["file_path"] == out["color_file"].replace(
            "\\", "/")

    def test_result_shape_exact_keys(self, fake, tmp_path):
        _masks(tmp_path)
        out = surfdetail.apply_surface_detail(_params(tmp_path, effects=[
            {"kind": "wear"}, {"kind": "grain"}]))
        assert set(out) == {"mesh", "effects", "color_file", "color_basename",
                            "height_file", "height_basename", "file_nodes",
                            "checkpoint_id", "warnings"}
        for eff in out["effects"]:
            assert set(eff) == {"kind", "strength", "scale", "changed_fraction"}

    def test_apply_failure_sweeps_created_nodes(self, fake, tmp_path,
                                                monkeypatch):
        _masks(tmp_path)

        # Fail on the bump2d creation, after the file+place2d already exist.
        real_shading_node = fake.shadingNode

        def _flaky(node_type, name=None, **kw):
            if node_type == "bump2d":
                raise RuntimeError("kaboom")
            return real_shading_node(node_type, name=name, **kw)
        monkeypatch.setattr(fake, "shadingNode", _flaky)
        with pytest.raises(HandlerError, match="checkpoint") as exc:
            surfdetail.apply_surface_detail(
                _params(tmp_path, effects=[{"kind": "grain"}]))
        assert "cp" in str(exc.value)
        # the file + place2d created before the failure are gone again
        remaining = [n for n in fake.created if n not in fake.deleted]
        assert not any(fake.types.get(n) in ("file", "place2dTexture")
                       for n in remaining)
        assert all(n in fake.deleted for n in fake.created)


class TestTheFakeRefusesWhatMayaRefuses:
    """#799 round 2: the regression barrier for THIS file's FakeCmds.

    Round 1's hardening was measured to be INERT with respect to the
    suite - neutering every new refusal left the five look-group files at
    184 passed / 2 xfailed / 0 failed, so the ticket's own premise ("a
    green suite proves nothing") was reproduced one level up. Only the
    contract points this fake actually models are asserted below; there
    is deliberately no polyEvaluate case, because this fake has none.
    """

    # contract 1 - a name the scene does not hold ---------------------
    def test_a_query_about_a_deleted_node_raises(self, fake):
        fake.shadingNode("bump2d", name="mcpDetail_bump")
        fake.delete("mcpDetail_bump")
        for call in (lambda: fake.nodeType("mcpDetail_bump"),
                     lambda: fake.getAttr("mcpDetail_bump.bumpValue"),
                     lambda: fake.setAttr("mcpDetail_bump.bumpDepth", 1.0),
                     lambda: fake.listConnections("mcpDetail_bump.outNormal",
                                                  source=True),
                     lambda: fake.attributeQuery("bumpValue",
                                                 node="mcpDetail_bump",
                                                 exists=True),
                     lambda: fake.listRelatives("mcpDetail_bump", shapes=True),
                     lambda: fake.listSets(object="mcpDetail_bump")):
            with pytest.raises(RuntimeError, match="No object matches name"):
                call()

    def test_a_query_about_a_node_that_never_existed_raises(self, fake):
        with pytest.raises(RuntimeError, match="No object matches name"):
            fake.nodeType("never_made")
        with pytest.raises(RuntimeError, match="No object matches name"):
            fake.getAttr("never_made.outColor")

    def test_objExists_answers_for_a_vanished_node_instead_of_raising(
            self, fake):
        fake.shadingNode("bump2d", name="mcpDetail_bump")
        assert fake.objExists("mcpDetail_bump") is True
        fake.delete("mcpDetail_bump")
        assert fake.objExists("mcpDetail_bump") is False
        assert fake.objExists("never_made") is False

    def test_a_deleted_name_re_created_exists_again(self, fake):
        """The round-2 BLOCKING defect: `self.deleted` was a permanent
        tombstone nothing could clear, so a name this module's rollback
        deleted and its next attempt re-created was present in `types` and
        absent to `_require` at the same time - a scene Maya cannot
        have."""
        fake.shadingNode("bump2d", name="mcpDetail_bump")
        fake.delete("mcpDetail_bump")
        fake.shadingNode("bump2d", name="mcpDetail_bump")
        assert fake.objExists("mcpDetail_bump") is True
        assert fake.nodeType("mcpDetail_bump") == "bump2d"
        fake.setAttr("mcpDetail_bump.bumpDepth", 1.0)   # must not raise
        assert fake.deleted == ["mcpDetail_bump"]       # still a RECORD

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
        fake.types["mcpDetail_file"] = "file"
        with pytest.raises(RuntimeError, match="already connected"):
            fake.connectAttr("mcpDetail_file.outColor",
                             "limbSG.surfaceShader")
        fake.connectAttr("mcpDetail_file.outColor", "limbSG.surfaceShader",
                         force=True)
        assert fake.conns["limbSG.surfaceShader"] == [
            "mcpDetail_file.outColor"]

    def test_connectAttr_refuses_a_node_that_is_not_in_the_scene(self, fake):
        with pytest.raises(RuntimeError, match="No object matches name"):
            fake.connectAttr("ghost.outColor", "limb_mat.emissionColor")
        with pytest.raises(RuntimeError, match="No object matches name"):
            fake.connectAttr("limb_mat.outColor", "ghost.baseColor")

    # contract 3 - answers that used to be constants -------------------
    def test_ls_with_uuid_answers_identities_not_paths(self, fake):
        """`uuid=True` asks which NODE, not which path. The old fake
        answered with DAG paths, so `texbake._node_ids` compared paths
        while reading as if it compared identities. Pinning it here is
        what round 1 lacked: reverting `ls` to the old form left all 184
        tests green."""
        assert fake.ls("|limbShape", long=True) == ["|limbShape"]
        ids = fake.ls("|limbShape", uuid=True)
        assert ids == ["uuid:|limbShape"]
        assert not set(ids) & {"|limbShape", "|limb"}   # never a path

    def test_listRelatives_answers_the_shape_to_transform_direction(
            self, fake):
        """Answering None to `parent=True` unconditionally sent every call
        down meshmaps._transform_short_name's "a shape that cannot answer
        stands for itself" degrade arm."""
        assert fake.listRelatives("|limbShape", parent=True) == ["|limb"]
        assert fake.listRelatives("|limb", shapes=True) == ["|limbShape"]
