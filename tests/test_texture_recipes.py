"""Named texture recipes - no Maya required."""

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import material, texture_recipes


class FakeCmds:
    """|torso (shape |torso|torsoShape) wears clay_matSG -> clay_mat.

    #799 rebuilt the answers below. Every one of them used to be an
    unconditional constant - nodeType guessed "mesh" or "standardSurface"
    from the NAME, listSets always said ["clay_matSG"], listConnections
    always said ["clay_mat"], attributeQuery(exists=True) always said True
    - so no fixture could put this fake in a state any of them failed on,
    and _shader_of's two refusals could not be reached at all. The graph
    is modelled now, and a query about a name the scene does not hold
    raises the way Maya's does.
    """

    def __init__(self):
        self.objects = {"|torso", "clay_mat"}
        self.shapes = {"|torso": ("|torso|torsoShape", "mesh")}
        # node -> type, for everything that is not a DAG shape. `delete`
        # pops from it, so nodeType stops answering for a swept node.
        self.types = {"clay_mat": "standardSurface"}
        # shape -> the shading groups it wears (empty list = unassigned).
        self.shape_sgs = {"|torso|torsoShape": ["clay_matSG"]}
        # plug -> [source plugs], the same shape every other shading fake
        # in this suite uses.
        self.conns = {"clay_matSG.surfaceShader": ["clay_mat.outColor"]}
        self.created = []
        self.connections = []
        self.deleted = []
        self.fail_on = None
        self.uv_count = 4  # default: the mesh has UVs
        self.raise_on_poly_evaluate = False
        self.attrs = {}          # "node.attr" -> value setAttr wrote

    # existence -------------------------------------------------------
    def _shape_names(self):
        return {entry[0] for entry in self.shapes.values()}

    def _sg_names(self):
        return {sg for sgs in self.shape_sgs.values() for sg in sgs}

    def _exists(self, node):
        return (node in self.objects or node in self._shape_names()
                or node in self._sg_names())

    def _require(self, node):
        """Raise the way real Maya does for a node that was deleted or
        never created - #799 contract 1. The zero-orphan sweep below
        DELETES every node a failed recipe built, and this fake used to
        answer for them afterwards as happily as for a live node.

        Deletion is modelled by `delete` REMOVING the node from the
        registries `_exists` reads, NOT by a name tombstone: #799 round 2
        found that consulting `self.deleted` made a name that was deleted
        and then re-created present and absent at the same time - a scene
        Maya cannot have, and one a retried recipe reaches. `self.deleted`
        is a RECORD for assertions, never an existence oracle.
        """
        if not self._exists(node):
            raise RuntimeError("No object matches name: %s" % node)

    def _compound_parent(self, plug):
        """`clay_mat.baseColorR` -> `clay_mat.baseColor`, or None."""
        node, _, attr = plug.rpartition(".")
        if len(attr) > 1 and attr[-1] in "RGBXYZ":
            return "%s.%s" % (node, attr[:-1])
        return None

    def _static_write_blocker(self, plug):
        """The connection that makes `setAttr(plug, ...)` raise, or None -
        #799 contract 2. Maya refuses a static write to a plug something
        feeds, to a COMPOUND whose CHILD is fed, AND to a CHILD whose
        parent compound is fed - round 1 modelled only the middle one."""
        parent = self._compound_parent(plug)
        for candidate in (plug, parent):
            if candidate is not None and candidate in self.conns:
                return self.conns[candidate][0]
        node, _, attr = plug.rpartition(".")
        for dst, srcs in self.conns.items():
            dnode, _, dattr = dst.rpartition(".")
            if dnode == node and dattr[:-1] == attr and dattr[-1:] in tuple(
                    "RGBXYZ"):
                return srcs[0]
        return None

    def ls(self, name=None, long=False, **kw):
        return [o for o in self.objects if o == name or o.split("|")[-1] == name]

    def objExists(self, name):
        # The one query #799 exempts: objExists ANSWERS for a vanished
        # node rather than raising - it is how naming.unique_name and the
        # recipe's own sweep ask the question.
        return self._exists(name)

    def listRelatives(self, node, shapes=False, fullPath=False, noIntermediate=False):
        self._require(node)
        entry = self.shapes.get(node)
        return [entry[0]] if entry else None

    def nodeType(self, node):
        # No guessing from the NAME: `"mesh" if node.endswith("Shape") else
        # "standardSurface"` answered for every string ever handed to it,
        # so resolve_slot's unknown-shader refusal could not be reached and
        # a swept node still read as a live shader (#799 contract 3).
        self._require(node)
        for shape, kind in self.shapes.values():
            if shape == node:
                return kind
        if node in self.types:
            return self.types[node]
        if node in self._sg_names():
            return "shadingEngine"
        return "transform"   # a DAG transform, e.g. |torso

    def listConnections(self, plug, type=None, source=True,
                        destination=True, plugs=False, **kw):
        # Maya's defaults are source=True AND destination=True, and the
        # direction flags select which end of each edge is answered. Until
        # #812 this fake answered SOURCES whatever the flags said, so
        # orphans.real_outputs (source=False, destination=True) read a
        # bump2d's noise as "something still using it" and the sweep it
        # gates could never be modelled here.
        self._require(plug.split(".")[0])
        node = plug.split(".")[0]
        has_attr = "." in plug
        hits = []
        if source:
            if has_attr:
                hits += list(self.conns.get(plug) or [])
            else:
                hits += [s for dst, lst in self.conns.items()
                         if dst.split(".")[0] == node for s in lst]
        if destination:
            for dst, lst in self.conns.items():
                for s in lst:
                    if (s == plug) if has_attr else (s.split(".")[0] == node):
                        hits.append(dst)
        if not hits:
            return None
        return hits if plugs else list(dict.fromkeys(h.split(".")[0] for h in hits))

    def rename(self, node, new):
        # Maya suffixes on collision rather than refusing (the pbr fake's
        # model) - the #812 name reclaim is caught by the name it gets back.
        self._require(node)
        if new in self.objects and new != node:
            new = new + "1"
        self.objects.discard(node)
        self.objects.add(new)
        self.types[new] = self.types.pop(node, "transform")
        self.created = [new if c == node else c for c in self.created]

        def fix(plug):
            return new + plug[len(node):] if plug.split(".")[0] == node else plug
        self.conns = {fix(dst): [fix(s) for s in srcs]
                      for dst, srcs in self.conns.items()}
        for key in [k for k in self.attrs if k.split(".")[0] == node]:
            self.attrs[new + key[len(node):]] = self.attrs.pop(key)
        return new

    def listSets(self, object=None, type=None):
        self._require(object)
        return list(self.shape_sgs.get(object, []))

    def shadingNode(self, node_type, name=None, **kw):
        if self.fail_on == node_type:
            raise RuntimeError("forced failure creating %s" % node_type)
        self.created.append(name)
        self.objects.add(name)
        self.types[name] = node_type
        return name

    def connectAttr(self, src, dst, force=False):
        self._require(src.split(".")[0])
        self._require(dst.split(".")[0])
        if dst in self.conns and not force:
            raise RuntimeError(
                "connectAttr: The destination attribute '%s' cannot be "
                "connected because it is already connected." % dst)
        self.connections.append((src, dst))
        self.conns[dst] = [src]

    def setAttr(self, plug, *value, **kw):
        self._require(plug.split(".")[0])
        blocker = self._static_write_blocker(plug)
        if blocker:
            raise RuntimeError(
                "setAttr: The attribute '%s' is locked or connected and "
                "cannot be modified (%s feeds it)" % (plug, blocker))
        self.attrs[plug] = value[0] if len(value) == 1 else list(value)

    def delete(self, *names, **kw):
        for n in names:
            self.deleted.append(n)
            self.objects.discard(n)
            self.types.pop(n, None)
            for dst in list(self.conns):
                if dst.split(".")[0] == n:
                    del self.conns[dst]
                    continue
                kept = [s for s in self.conns[dst] if s.split(".")[0] != n]
                if kept:
                    self.conns[dst] = kept
                else:
                    del self.conns[dst]

    def polyEvaluate(self, node, uvcoord=False, **kw):
        self._require(node)
        if self.raise_on_poly_evaluate:
            raise RuntimeError("forced polyEvaluate failure")
        return self.uv_count if uvcoord else 0

    # Real Maya's numberOfChildren answers a list ([3]) for a compound
    # (float3) attribute and None for a scalar one - texture_recipes'
    # _wire_color_output (#714 Task 6) uses exactly that shape to pick
    # outColor vs outColorR. baseColor/normalCamera are this fixture's only
    # compound attrs; specularRoughness (the roughness slot) is the scalar
    # case every file_texture/ramp_gradient-on-roughness test exercises.
    _COMPOUND_ATTRS = {"baseColor", "normalCamera", "color", "emissionColor"}

    # Which attributes a shader really carries. DERIVED from the same slot
    # table resolve_slot reads, so the fake cannot claim an attribute the
    # tool would never ask for - and, more to the point, cannot answer
    # `exists=True` for an attribute no shader has (#799 contract 3).
    def _node_attrs(self, node):
        slots = material.SHADER_SLOTS.get(self.nodeType(node))
        return set(slots.values()) if slots else set()

    def attributeQuery(self, attr, node=None, exists=False,
                       numberOfChildren=False):
        self._require(node)
        known = self._node_attrs(node)
        if exists:
            return attr in known
        if attr not in known:
            # Maya answers "No such attribute" rather than a shape for an
            # attribute the node does not have.
            raise RuntimeError("attributeQuery: No such attribute '%s.%s'"
                               % (node, attr))
        if numberOfChildren:
            return [3] if attr in self._COMPOUND_ATTRS else None
        return None


def test_noise_bump_builds_and_connects_to_the_normal_slot(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(texture_recipes, "_cmds", lambda: fake)
    result = texture_recipes.apply_texture_recipe(
        {"mesh": "|torso", "recipe": "noise_bump", "params": {"scale": 2.0}}
    )
    assert result["recipe"] == "noise_bump"
    assert result["slot"] == "normal"
    assert len(result["nodes"]) == 2          # noise + bump2d
    assert any(dst.endswith(".normalCamera") for _, dst in fake.connections)


def test_noise_bump_bad_scale_type_raises_hinted_handler_error(monkeypatch):
    # I2: scale/depth used to go straight to float(), so a bad type raised a
    # raw ValueError with no hint - and did so AFTER the noise node was
    # already created. Must now be a HandlerError, and must leave no orphan.
    fake = FakeCmds()
    monkeypatch.setattr(texture_recipes, "_cmds", lambda: fake)
    before = set(fake.objects)
    with pytest.raises(HandlerError) as exc:
        texture_recipes.apply_texture_recipe(
            {"mesh": "|torso", "recipe": "noise_bump",
             "params": {"scale": "big"}}
        )
    assert "scale" in str(exc.value)
    assert fake.objects == before


def test_noise_bump_bad_depth_type_raises_hinted_handler_error(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(texture_recipes, "_cmds", lambda: fake)
    before = set(fake.objects)
    with pytest.raises(HandlerError) as exc:
        texture_recipes.apply_texture_recipe(
            {"mesh": "|torso", "recipe": "noise_bump",
             "params": {"depth": [1, 2]}}
        )
    assert "depth" in str(exc.value)
    assert fake.objects == before


def test_unknown_recipe_lists_the_valid_ones(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(texture_recipes, "_cmds", lambda: fake)
    with pytest.raises(HandlerError) as exc:
        texture_recipes.apply_texture_recipe({"mesh": "|torso", "recipe": "marble"})
    assert "noise_bump" in exc.value.hint


def test_failure_midway_sweeps_every_node_it_created(monkeypatch):
    # The zero-orphan rule, asserted on the path that actually breaks it.
    fake = FakeCmds()
    fake.fail_on = "bump2d"        # noise is created first, then this raises
    monkeypatch.setattr(texture_recipes, "_cmds", lambda: fake)
    with pytest.raises(Exception):
        texture_recipes.apply_texture_recipe(
            {"mesh": "|torso", "recipe": "noise_bump"}
        )
    assert fake.deleted == fake.created, (
        "recipe left orphans: created %s, deleted %s" % (fake.created, fake.deleted)
    )


def test_file_texture_requires_a_path(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(texture_recipes, "_cmds", lambda: fake)
    with pytest.raises(HandlerError) as exc:
        texture_recipes.apply_texture_recipe(
            {"mesh": "|torso", "recipe": "file_texture"}
        )
    assert "file_path" in str(exc.value) or "file_path" in exc.value.hint


def test_procedural_recipes_warn_that_the_map_will_not_export(monkeypatch):
    # #714: Maya's FBX exporter silently drops procedural networks - the
    # recipe that builds one must say so up front, not leave it to be
    # discovered later in maya_export_fbx's dropped_maps. Phase 2: now that
    # maya_bake_textures exists, the warning names it as the remedy.
    fake = FakeCmds()
    monkeypatch.setattr(texture_recipes, "_cmds", lambda: fake)
    result = texture_recipes.apply_texture_recipe(
        {"mesh": "|torso", "recipe": "noise_bump"}
    )
    assert any("silently drops" in w and "maya_bake_textures" in w
               for w in result["warnings"])


def test_procedural_recipe_on_a_uv_less_mesh_warns_bake_will_refuse_it(monkeypatch):
    # #714 phase 2: maya_bake_textures refuses a UV-less mesh outright - the
    # recipe gives that signal up front rather than leaving it to be
    # discovered at bake time.
    fake = FakeCmds()
    fake.uv_count = 0
    monkeypatch.setattr(texture_recipes, "_cmds", lambda: fake)
    result = texture_recipes.apply_texture_recipe(
        {"mesh": "|torso", "recipe": "noise_bump"}
    )
    assert any("no UVs" in w and "maya_uv_atlas" in w for w in result["warnings"])


def test_uv_probe_raising_does_not_crash_an_already_succeeded_recipe(monkeypatch):
    # Fix round 1: the no-UV check sits AFTER the recipe's own nodes already
    # exist - a polyEvaluate that raises (a corrupt mesh, a stale reference)
    # is a different problem from "no UVs" and must not crash a call whose
    # texture was in fact applied. Skip the warning, not the result.
    fake = FakeCmds()
    fake.raise_on_poly_evaluate = True
    monkeypatch.setattr(texture_recipes, "_cmds", lambda: fake)
    result = texture_recipes.apply_texture_recipe(
        {"mesh": "|torso", "recipe": "noise_bump"}
    )
    assert result["recipe"] == "noise_bump"
    assert any("silently drops" in w for w in result["warnings"])
    assert not any("no UVs" in w for w in result["warnings"])


def test_the_file_texture_recipe_does_not_warn(monkeypatch, tmp_path):
    # The path is a REAL file now (#797 row 13): an absolute path to
    # nothing is refused up front, the way assign_pbr refuses it, because
    # Maya renders a missing file as flat colour and says nothing.
    image = tmp_path / "t.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    fake = FakeCmds()
    monkeypatch.setattr(texture_recipes, "_cmds", lambda: fake)
    result = texture_recipes.apply_texture_recipe(
        {"mesh": "|torso", "recipe": "file_texture",
         "params": {"file_path": str(image)}}
    )
    assert result["warnings"] == []


class TestTheParamsARecipeActuallyReads:
    """#797 rows 12-13: a recipe's `params` are per-recipe, and two recipes
    read none at all.

    `_ramp_gradient` and `_layered_mask` take the `params` argument and
    never look at it - a caller who passes {"scale": 2} to ramp_gradient
    gets Maya's default ramp and is told nothing. `_noise_bump` reads
    {scale, depth} and `_file_texture` reads {file_path}; every other
    nested key is the #767 defect one level down, where the key is
    accepted because the TOP-level `params` key is known.
    """

    def _fake(self, monkeypatch):
        fake = FakeCmds()
        monkeypatch.setattr(texture_recipes, "_cmds", lambda: fake)
        return fake

    def test_ramp_gradient_reads_no_params_at_all(self, monkeypatch):
        fake = self._fake(monkeypatch)
        with pytest.raises(HandlerError) as exc:
            texture_recipes.apply_texture_recipe(
                {"mesh": "|torso", "recipe": "ramp_gradient",
                 "params": {"scale": 2}})
        assert "does not use 'params'" in str(exc.value)
        assert "ramp_gradient" in str(exc.value)
        assert fake.created == []

    def test_layered_mask_reads_no_params_at_all(self, monkeypatch):
        fake = self._fake(monkeypatch)
        with pytest.raises(HandlerError) as exc:
            texture_recipes.apply_texture_recipe(
                {"mesh": "|torso", "recipe": "layered_mask",
                 "params": {"depth": 1}})
        assert "does not use 'params'" in str(exc.value)
        assert "layered_mask" in str(exc.value)
        assert fake.created == []

    def test_an_empty_params_dict_is_not_a_passed_value(self, monkeypatch):
        """The wrapper used to send params={} on every call - refusing that
        would refuse the command itself."""
        self._fake(monkeypatch)
        result = texture_recipes.apply_texture_recipe(
            {"mesh": "|torso", "recipe": "ramp_gradient", "params": {}})
        assert result["recipe"] == "ramp_gradient"

    def test_params_none_is_not_a_passed_value(self, monkeypatch):
        self._fake(monkeypatch)
        result = texture_recipes.apply_texture_recipe(
            {"mesh": "|torso", "recipe": "layered_mask", "params": None})
        assert result["recipe"] == "layered_mask"

    def test_a_key_noise_bump_never_reads_is_refused(self, monkeypatch):
        fake = self._fake(monkeypatch)
        with pytest.raises(HandlerError) as exc:
            texture_recipes.apply_texture_recipe(
                {"mesh": "|torso", "recipe": "noise_bump",
                 "params": {"scale": 2, "octaves": 3}})
        assert "does not take" in str(exc.value)
        assert "octaves" in str(exc.value)
        assert "noise_bump" in str(exc.value)
        assert fake.created == []

    def test_a_key_file_texture_never_reads_is_refused(self, monkeypatch):
        fake = self._fake(monkeypatch)
        with pytest.raises(HandlerError) as exc:
            texture_recipes.apply_texture_recipe(
                {"mesh": "|torso", "recipe": "file_texture",
                 "params": {"file_path": "x.png", "scale": 2}})
        assert "does not take" in str(exc.value)
        assert "scale" in str(exc.value)
        assert "file_texture" in str(exc.value)
        assert fake.created == []

    def test_the_keys_a_recipe_does_read_still_work(self, monkeypatch):
        self._fake(monkeypatch)
        result = texture_recipes.apply_texture_recipe(
            {"mesh": "|torso", "recipe": "noise_bump",
             "params": {"scale": 2.0, "depth": 0.2}})
        assert len(result["nodes"]) == 2

    def test_params_must_be_an_object(self, monkeypatch):
        self._fake(monkeypatch)
        with pytest.raises(HandlerError) as exc:
            texture_recipes.apply_texture_recipe(
                {"mesh": "|torso", "recipe": "noise_bump", "params": [2]})
        assert "params" in str(exc.value)

    def test_an_absolute_file_path_to_nothing_is_refused(self, monkeypatch,
                                                        tmp_path):
        """pbr.missing_files's rule, reused: a missing map is not an error
        in Maya - the file node renders flat and the material merely looks
        wrong."""
        fake = self._fake(monkeypatch)
        absent = tmp_path / "never_baked.png"
        with pytest.raises(HandlerError) as exc:
            texture_recipes.apply_texture_recipe(
                {"mesh": "|torso", "recipe": "file_texture",
                 "params": {"file_path": str(absent)}})
        assert "never_baked.png" in str(exc.value)
        assert fake.created == []

    def test_a_relative_or_udim_path_is_not_second_guessed(self, monkeypatch):
        self._fake(monkeypatch)
        for path in ("sourceimages/kit.png", "D:/kit/atlas.<UDIM>.png"):
            result = texture_recipes.apply_texture_recipe(
                {"mesh": "|torso", "recipe": "file_texture",
                 "params": {"file_path": path}})
            assert result["recipe"] == "file_texture"

    def test_every_recipe_appears_in_every_table(self):
        """A recipe added to RECIPES but not to RECIPE_PARAM_KEYS would
        KeyError inside the validator instead of refusing - and one added
        to the key table but not to _BUILDERS would validate params for a
        recipe that cannot be built. The four tables are one table."""
        recipes = set(texture_recipes.RECIPES)
        assert recipes == set(texture_recipes.RECIPE_PARAM_KEYS)
        assert recipes == set(texture_recipes._BUILDERS)
        assert recipes == set(texture_recipes.RECIPE_SLOT)
        # And the "why" a param-less recipe refuses exists for exactly the
        # recipes that are param-less - refuse_inert would KeyError, after
        # deciding to refuse, on any other split.
        assert set(texture_recipes._PARAMLESS_WHY) == {
            name for name, keys in texture_recipes.RECIPE_PARAM_KEYS.items()
            if not keys}

    def test_the_refusal_fires_before_maya_is_imported(self):
        """#767's proof: no fake is installed here, so anything reaching
        `_cmds()` raises ModuleNotFoundError instead."""
        with pytest.raises(HandlerError) as exc:
            texture_recipes.apply_texture_recipe(
                {"mesh": "|torso", "recipe": "ramp_gradient",
                 "params": {"scale": 2}})
        assert "does not use 'params'" in str(exc.value)


class TestTheFakeRefusesWhatMayaRefuses:
    """#799 round 2: the regression barrier for THIS file's FakeCmds.

    Round 1 rebuilt five unconditional constants here (nodeType guessed
    from the name, listSets always said ["clay_matSG"], listConnections
    always said ["clay_mat"], attributeQuery(exists) always said True,
    setAttr always passed) and added ZERO tests, so an adversarial
    reviewer could neuter every one of them and still see 184 passed / 2
    xfailed / 0 failed. These are the tests that make that impossible.

    The first two drive the REAL handler down refusals that were
    unreachable while the constants stood.
    """

    # contract 3, via the handler --------------------------------------
    def test_a_mesh_whose_shape_wears_no_shading_group_is_refused(
            self, monkeypatch):
        """`listSets` answered ["clay_matSG"] for every object, so
        _shader_of's "has no shading group" arm could not be reached from
        any fixture."""
        fake = FakeCmds()
        fake.shape_sgs["|torso|torsoShape"] = []
        monkeypatch.setattr(texture_recipes, "_cmds", lambda: fake)
        with pytest.raises(HandlerError, match="no shading group"):
            texture_recipes.apply_texture_recipe(
                {"mesh": "|torso", "recipe": "noise_bump"})
        assert fake.created == []          # refused before anything is built

    def test_a_shading_group_with_no_shader_is_refused(self, monkeypatch):
        """`listConnections` answered ["clay_mat"] for every plug, so
        _shader_of's "has no shader" arm could not be reached either."""
        fake = FakeCmds()
        del fake.conns["clay_matSG.surfaceShader"]
        monkeypatch.setattr(texture_recipes, "_cmds", lambda: fake)
        with pytest.raises(HandlerError, match="no shader"):
            texture_recipes.apply_texture_recipe(
                {"mesh": "|torso", "recipe": "noise_bump"})
        assert fake.created == []

    def test_a_shader_type_the_slot_table_does_not_know_is_refused(
            self, monkeypatch):
        """`nodeType` guessed "standardSurface" for anything not ending in
        "Shape", so resolve_slot's unknown-shader refusal was unreachable
        from this fake."""
        fake = FakeCmds()
        fake.types["clay_mat"] = "aiStandardSurface"
        monkeypatch.setattr(texture_recipes, "_cmds", lambda: fake)
        with pytest.raises(HandlerError, match="unknown shader type"):
            texture_recipes.apply_texture_recipe(
                {"mesh": "|torso", "recipe": "noise_bump"})
        assert fake.created == []

    # contract 1 - a name the scene does not hold ---------------------
    def test_a_query_about_a_deleted_node_raises(self):
        fake = FakeCmds()
        fake.shadingNode("noise", name="mcpTex_noise")
        fake.delete("mcpTex_noise")
        for call in (lambda: fake.nodeType("mcpTex_noise"),
                     lambda: fake.setAttr("mcpTex_noise.scale", 2.0),
                     lambda: fake.listConnections("mcpTex_noise.outColor",
                                                  source=True),
                     lambda: fake.attributeQuery("baseColor",
                                                 node="mcpTex_noise",
                                                 exists=True),
                     lambda: fake.polyEvaluate("mcpTex_noise", uvcoord=True),
                     lambda: fake.listSets(object="mcpTex_noise"),
                     lambda: fake.listRelatives("mcpTex_noise", shapes=True)):
            with pytest.raises(RuntimeError, match="No object matches name"):
                call()

    def test_a_query_about_a_node_that_never_existed_raises(self):
        fake = FakeCmds()
        with pytest.raises(RuntimeError, match="No object matches name"):
            fake.nodeType("never_made")
        with pytest.raises(RuntimeError, match="No object matches name"):
            fake.polyEvaluate("never_made", uvcoord=True)

    def test_objExists_answers_for_a_vanished_node_instead_of_raising(self):
        fake = FakeCmds()
        fake.shadingNode("noise", name="mcpTex_noise")
        assert fake.objExists("mcpTex_noise") is True
        fake.delete("mcpTex_noise")
        assert fake.objExists("mcpTex_noise") is False
        assert fake.objExists("never_made") is False

    def test_a_deleted_name_re_created_exists_again(self):
        """The round-2 BLOCKING defect: `self.deleted` was a permanent
        tombstone, so a name the orphan sweep deleted and a retry
        re-created was present in `types` and absent to `_require` at the
        same time - a scene Maya cannot have."""
        fake = FakeCmds()
        fake.shadingNode("noise", name="mcpTex_noise")
        fake.delete("mcpTex_noise")
        fake.shadingNode("noise", name="mcpTex_noise")
        assert fake.objExists("mcpTex_noise") is True
        assert fake.nodeType("mcpTex_noise") == "noise"
        fake.setAttr("mcpTex_noise.scale", 2.0)      # must not raise
        assert fake.deleted == ["mcpTex_noise"]      # still a RECORD

    def test_a_recipe_runs_again_after_a_failed_one_swept_its_nodes(
            self, monkeypatch):
        """The same defect at handler level: the sweep deletes every node
        the failed attempt built, and the retry rebuilds them under the
        SAME names. A tombstoned fake refused the retry."""
        fake = FakeCmds()
        fake.fail_on = "bump2d"
        monkeypatch.setattr(texture_recipes, "_cmds", lambda: fake)
        with pytest.raises(Exception):
            texture_recipes.apply_texture_recipe(
                {"mesh": "|torso", "recipe": "noise_bump"})
        assert fake.deleted == fake.created

        fake.fail_on = None
        result = texture_recipes.apply_texture_recipe(
            {"mesh": "|torso", "recipe": "noise_bump"})
        assert result["slot"] == "normal"
        assert any(dst.endswith(".normalCamera")
                   for _src, dst in fake.connections)

    # contract 2 - locked or connected --------------------------------
    def test_setAttr_refuses_a_plug_a_connection_feeds(self):
        fake = FakeCmds()
        with pytest.raises(RuntimeError, match="locked or connected"):
            fake.setAttr("clay_matSG.surfaceShader", "x")

    def test_setAttr_refuses_both_compound_directions(self):
        """A child write when the COMPOUND is fed, and a compound write
        when a CHILD is fed. Round 1 modelled only the second."""
        fake = FakeCmds()
        fake.shadingNode("noise", name="mcpTex_noise")
        fake.conns["clay_mat.baseColor"] = ["mcpTex_noise.outColor"]
        with pytest.raises(RuntimeError, match="locked or connected"):
            fake.setAttr("clay_mat.baseColorR", 1.0)
        fake.conns["clay_mat.emissionColorG"] = ["mcpTex_noise.outAlpha"]
        with pytest.raises(RuntimeError, match="locked or connected"):
            fake.setAttr("clay_mat.emissionColor", 0.0, 0.0, 0.0)

    def test_setAttr_to_a_free_plug_records_the_value(self):
        """`setAttr` used to be `pass` - a method that can never fail a
        test."""
        fake = FakeCmds()
        fake.setAttr("clay_mat.specularRoughness", 0.25)
        assert fake.attrs["clay_mat.specularRoughness"] == 0.25

    def test_connectAttr_refuses_an_occupied_destination_unless_forced(self):
        fake = FakeCmds()
        fake.shadingNode("noise", name="mcpTex_noise")
        with pytest.raises(RuntimeError, match="already connected"):
            fake.connectAttr("mcpTex_noise.outColor",
                             "clay_matSG.surfaceShader")
        fake.connectAttr("mcpTex_noise.outColor", "clay_matSG.surfaceShader",
                         force=True)
        assert fake.conns["clay_matSG.surfaceShader"] == [
            "mcpTex_noise.outColor"]

    def test_connectAttr_refuses_a_node_that_is_not_in_the_scene(self):
        fake = FakeCmds()
        with pytest.raises(RuntimeError, match="No object matches name"):
            fake.connectAttr("ghost.outColor", "clay_mat.baseColor")
        with pytest.raises(RuntimeError, match="No object matches name"):
            fake.connectAttr("clay_mat.outColor", "ghost.baseColor")

    # contract 3 - attributeQuery is derived, not always-yes ----------
    def test_attributeQuery_answers_from_the_slot_table(self):
        fake = FakeCmds()
        assert fake.attributeQuery("baseColor", node="clay_mat",
                                   exists=True) is True
        assert fake.attributeQuery("emissionColor", node="clay_mat",
                                   exists=True) is False
        assert fake.attributeQuery("baseColor", node="clay_mat",
                                   numberOfChildren=True) == [3]
        assert fake.attributeQuery("specularRoughness", node="clay_mat",
                                   numberOfChildren=True) is None
        with pytest.raises(RuntimeError, match="No such attribute"):
            fake.attributeQuery("emissionColor", node="clay_mat",
                                numberOfChildren=True)


class TestReApplyingARecipeSweepsWhatItReplaces:
    """#812. A recipe force-connects onto its slot, and Maya never reaps the
    network that connection displaced (MEASURED, evals/recipe_orphans_probe.py
    on Maya 2027): the old ramp / noise+bump2d / layered+mask / pbr file+p2d
    stay in the scene wired only to defaultTextureList1 or
    defaultRenderUtilityList1, and the new node is named `mcpTex_ramp_001`.
    assign_pbr over a recipe slot already sweeps (#804); this is the other
    direction.
    """

    @pytest.fixture
    def fake(self, monkeypatch):
        fake = FakeCmds()
        monkeypatch.setattr(texture_recipes, "_cmds", lambda: fake)
        return fake

    def apply(self, recipe, **extra):
        return texture_recipes.apply_texture_recipe(
            {"mesh": "|torso", "recipe": recipe, **extra})

    def test_a_first_recipe_on_a_free_slot_replaces_nothing(self, fake):
        result = self.apply("ramp_gradient")
        assert result["replaced"] == []
        assert result["nodes"] == ["mcpTex_ramp"]

    def test_a_second_ramp_deletes_the_first_and_takes_back_its_name(self, fake):
        self.apply("ramp_gradient")
        result = self.apply("ramp_gradient")
        assert "mcpTex_ramp" in fake.deleted
        assert result["replaced"] == ["mcpTex_ramp"]
        # the survivor is the NEW ramp, under the base name, feeding the slot
        assert result["nodes"] == ["mcpTex_ramp"]
        assert not fake.objExists("mcpTex_ramp_001")
        assert fake.conns["clay_mat.baseColor"] == ["mcpTex_ramp.outColor"]
        assert fake.types["mcpTex_ramp"] == "ramp"

    def test_noise_bump_twice_sweeps_the_old_bump_and_then_its_noise(self, fake):
        # the noise is two hops up and loses its consumer only once the bump
        # is gone - the fixpoint, not a single pass
        self.apply("noise_bump")
        result = self.apply("noise_bump", params={"scale": 2.0})
        assert sorted(result["replaced"]) == ["mcpTex_bump", "mcpTex_noise"]
        assert result["nodes"] == ["mcpTex_noise", "mcpTex_bump"]
        assert fake.conns["clay_mat.normalCamera"] == ["mcpTex_bump.outNormal"]
        assert fake.conns["mcpTex_bump.bumpValue"] == ["mcpTex_noise.outColorR"]
        assert fake.attrs["mcpTex_noise.frequency"] == 16.0, "the NEW noise carries the new scale"

    def test_layered_mask_twice_sweeps_the_layered_and_its_mask(self, fake):
        self.apply("layered_mask")
        result = self.apply("layered_mask")
        assert sorted(result["replaced"]) == ["mcpTex_layered", "mcpTex_mask"]
        assert result["nodes"] == ["mcpTex_layered", "mcpTex_mask"]

    def test_a_recipe_over_a_pbr_slot_takes_the_file_node_and_its_place2d(self, fake):
        # what assign_pbr leaves on the slot: file <- place2dTexture, and the
        # colour-management singleton feeding the file (measured, #804) that
        # the walk must never follow
        for name, kind in (("clay_color_tex", "file"), ("clay_color_p2d", "place2dTexture"),
                           ("defaultColorMgtGlobals", "colorManagementGlobals")):
            fake.objects.add(name)
            fake.types[name] = kind
        fake.conns["clay_mat.baseColor"] = ["clay_color_tex.outColor"]
        fake.conns["clay_color_tex.uvCoord"] = ["clay_color_p2d.outUV"]
        fake.conns["clay_color_tex.colorManagementConfigFileEnabled"] = [
            "defaultColorMgtGlobals.cmConfigFileEnabled"]
        result = self.apply("ramp_gradient")
        assert result["replaced"] == ["clay_color_tex", "clay_color_p2d"]
        assert fake.objExists("defaultColorMgtGlobals")
        assert fake.conns["clay_mat.baseColor"] == ["mcpTex_ramp.outColor"]

    def test_an_old_node_something_else_still_uses_survives_and_is_named(self, fake):
        self.apply("ramp_gradient")
        fake.objects.add("other")
        fake.types["other"] = "lambert"
        fake.conns["other.color"] = ["mcpTex_ramp.outColor"]
        result = self.apply("ramp_gradient")
        assert result["replaced"] == []
        assert fake.objExists("mcpTex_ramp")
        assert fake.conns["other.color"] == ["mcpTex_ramp.outColor"]
        assert any("mcpTex_ramp" in w and "still used by other" in w
                   for w in result["warnings"]), result["warnings"]
        # the base name was not free, so the new ramp keeps its suffix
        assert result["nodes"] == ["mcpTex_ramp_001"]
        assert fake.conns["clay_mat.baseColor"] == ["mcpTex_ramp_001.outColor"]

    def test_a_different_slot_replaces_nothing(self, fake):
        self.apply("ramp_gradient")
        result = self.apply("noise_bump")
        assert result["replaced"] == []
        assert fake.objExists("mcpTex_ramp")

    def test_a_failure_after_the_capture_leaves_the_old_network_wired(self, fake):
        self.apply("noise_bump")
        fake.fail_on = "bump2d"
        with pytest.raises(RuntimeError):
            self.apply("noise_bump")
        assert fake.objExists("mcpTex_noise") and fake.objExists("mcpTex_bump")
        assert fake.conns["clay_mat.normalCamera"] == ["mcpTex_bump.outNormal"]
        assert "mcpTex_noise_001" in fake.deleted, "the failure sweep takes only what this call built"
        assert "mcpTex_noise" not in fake.deleted
