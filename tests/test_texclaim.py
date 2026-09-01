"""#714: the scene-side texture claim. Pure classification first; the
walker's cmds surface is faked below the way test_texture_recipes.py does."""

import pytest

from maya_plugin.handlers import texclaim


class TestAuthoredAttrs:
    def test_derived_from_the_slot_tables_not_copied(self):
        # #714: a new slot in pbr.SLOTS or material.SHADER_SLOTS must widen
        # the walk automatically - a copied constant is how a slot silently
        # falls out of the claim.
        from maya_plugin.handlers import material, pbr

        expected = {attr for attr, _kind in pbr.SLOTS.values()}
        for slots in material.SHADER_SLOTS.values():
            expected |= set(slots.values())
        assert set(texclaim.AUTHORED_ATTRS) == expected
        assert "baseColor" in texclaim.AUTHORED_ATTRS
        assert "normalCamera" in texclaim.AUTHORED_ATTRS
        assert "eccentricity" in texclaim.AUTHORED_ATTRS

    def test_slot_for_attr_maps_back(self):
        assert texclaim.SLOT_FOR_ATTR["baseColor"] == "color"
        assert texclaim.SLOT_FOR_ATTR["normalCamera"] == "normal"
        assert texclaim.SLOT_FOR_ATTR.get("nosuchattr") is None


class TestClassify:
    def test_all_file_terminals_are_a_file_claim(self):
        assert texclaim.classify([{"node": "t", "type": "file"}]) == "file"

    def test_any_non_file_terminal_makes_it_procedural(self):
        # The MIX is what the exporter loses: a layeredTexture blending two
        # real files still cannot travel.
        assert texclaim.classify([
            {"node": "a", "type": "file"},
            {"node": "b", "type": "layeredTexture"}]) == "procedural"

    def test_no_terminals_is_a_value(self):
        assert texclaim.classify([]) == "value"


class FakeCmds:
    """A shading graph, faked at the four calls the walker makes.

    Scene: |body has SG bodySG -> shader 'skin_mat' (standardSurface).
    Graphs are declared per test by writing `conns` and `types`.
    """

    def __init__(self):
        self.sets = {"|bodyShape": ["bodySG"]}
        # plug -> [source plugs]
        self.conns = {"bodySG.surfaceShader": ["skin_mat.outColor"]}
        self.types = {"skin_mat": "standardSurface"}
        self.attrs = {}          # "node.attr" -> value
        self.existing_attrs = set()   # "node.attr" the shader really has

    # existence -------------------------------------------------------
    def _exists(self, node):
        """Every name this scene holds: the shapes `sets` is keyed by, the
        shading groups it names, and every DG node in `types`."""
        return (node in self.types or node in self.sets
                or any(node in sgs for sgs in self.sets.values()))

    def _require(self, node):
        """Raise the way real Maya does for a node that was never created
        - #799 contract 1.

        `material_claims` is a pure READ: it has no cmds.delete, setAttr,
        connectAttr or disconnectAttr anywhere in it, so this fake models
        neither deletion nor writing. Round 1 added a `delete()` and a
        `self.deleted` here on the belief that texbake, meshmaps and
        surfdetail re-run THIS fake as a postcondition; they do not - they
        re-run the texclaim HANDLER against their OWN fakes, which is
        where deletion is modelled. Round 2 removed the dead pair.

        What remains is the half that matters here: a name the scene does
        not hold raises rather than answering a plausible default
        (nodeType said "transform", getAttr said ""), so the walk cannot
        classify a network hanging off a node nobody created.

        NOTE for whoever adds the first WRITE to this fake: the other four
        look-group fakes carry a `_static_write_blocker` that refuses a
        setAttr to a fed or locked plug. There is deliberately none here,
        because there is no setAttr here. Add both together or neither.
        """
        if not self._exists(node):
            raise RuntimeError("No object matches name: %s" % node)

    def listSets(self, object=None, type=None):
        self._require(object)
        return list(self.sets.get(object, []))

    def listConnections(self, plug, source=False, destination=True,
                        plugs=False, **kw):
        self._require(plug.split(".")[0])
        if "." in plug:
            srcs = self.conns.get(plug) or []
        else:
            # Real Maya: a bare node name returns every source connection
            # into ANY attribute of that node - the walker relies on this
            # for the hop past a pass-through node (bump2d.bumpValue,
            # reverse.input*), so the fake has to aggregate across attrs too.
            srcs = []
            for key, vals in self.conns.items():
                if key.split(".", 1)[0] == plug:
                    srcs.extend(vals)
        if not srcs:
            return None
        return list(srcs) if plugs else [s.split(".")[0] for s in srcs]

    def nodeType(self, node):
        # No fallback: `return self.types.get(node, "transform")` is the
        # exact shape #799 exists to delete - a node the fixture never set
        # up came back as a plausible "transform" terminal, and the walk
        # happily classified the network around it (#799 contract 3).
        self._require(node)
        if node in self.types:
            return self.types[node]
        if node in self.sets:
            return "mesh"
        return "shadingEngine"   # _require leaves only an SG name here

    def attributeQuery(self, attr, node=None, exists=False):
        self._require(node)
        return ("%s.%s" % (node, attr)) in self.existing_attrs

    def getAttr(self, plug):
        """The plug's value. "" is the modelled answer for an attribute
        this fake has no value for - Maya answers the attribute's default
        the same way - but it is reached only AFTER the node is known to
        exist, which is the half that used to be missing (#799). It is
        also what `_file_terminal` turns into `on_disk: False`."""
        self._require(plug.split(".")[0])
        return self.attrs.get(plug, "")


def _shader_with(fake, attr, source_plug):
    fake.existing_attrs.add("skin_mat." + attr)
    fake.conns["skin_mat." + attr] = [source_plug]


class TestMaterialClaims:
    def test_a_file_texture_is_a_file_claim(self, tmp_path):
        image = tmp_path / "grain.png"
        image.write_bytes(b"x")
        fake = FakeCmds()
        fake.types["mcpTex_file"] = "file"
        fake.attrs["mcpTex_file.fileTextureName"] = str(image)
        fake.attrs["mcpTex_file.colorSpace"] = "sRGB"
        _shader_with(fake, "baseColor", "mcpTex_file.outColor")

        claims = texclaim.material_claims(fake, ["|bodyShape"])

        assert len(claims) == 1
        claim = claims[0]
        assert claim["classification"] == "file"
        assert claim["slot"] == "color"
        assert claim["attr"] == "baseColor"
        assert claim["material"] == "skin_mat"
        assert claim["terminals"][0]["basename"] == "grain.png"
        assert claim["terminals"][0]["on_disk"] is True
        assert claim["semantics_lost"] == []

    def test_a_missing_image_is_claimed_but_not_on_disk(self, tmp_path):
        fake = FakeCmds()
        fake.types["mcpTex_file"] = "file"
        fake.attrs["mcpTex_file.fileTextureName"] = str(tmp_path / "gone.png")
        _shader_with(fake, "baseColor", "mcpTex_file.outColor")

        claim = texclaim.material_claims(fake, ["|bodyShape"])[0]

        assert claim["classification"] == "file"
        assert claim["terminals"][0]["on_disk"] is False

    def test_noise_through_bump2d_is_procedural_and_records_the_via(self):
        fake = FakeCmds()
        fake.types["mcpTex_noise"] = "noise"
        fake.types["mcpTex_bump"] = "bump2d"
        fake.conns["mcpTex_bump.bumpValue"] = ["mcpTex_noise.outColorR"]
        _shader_with(fake, "normalCamera", "mcpTex_bump.outNormal")

        claim = texclaim.material_claims(fake, ["|bodyShape"])[0]

        assert claim["classification"] == "procedural"
        assert claim["slot"] == "normal"
        assert claim["via"] == ["bump2d"]
        assert claim["terminals"][0]["node"] == "mcpTex_noise"
        assert claim["terminals"][0]["type"] == "noise"

    def test_a_file_through_reverse_on_a_scalar_reports_semantics_lost(
            self, tmp_path):
        image = tmp_path / "rough.png"
        image.write_bytes(b"x")
        fake = FakeCmds()
        fake.types["rough_tex"] = "file"
        fake.types["rough_inv"] = "reverse"
        fake.attrs["rough_tex.fileTextureName"] = str(image)
        fake.attrs["rough_tex.colorSpace"] = "Raw"
        fake.conns["rough_inv.inputX"] = ["rough_tex.outColorR"]
        # A second channel of the SAME file into reverse's other component -
        # both swizzles must be reported, and the file still resolves once.
        fake.conns["rough_inv.inputY"] = ["rough_tex.outAlpha"]
        _shader_with(fake, "specularRoughness", "rough_inv.outputX")

        claim = texclaim.material_claims(fake, ["|bodyShape"])[0]

        assert claim["classification"] == "file"
        assert claim["via"] == ["reverse"]
        assert len(claim["terminals"]) == 1
        lost = " ".join(claim["semantics_lost"])
        assert "outColorR" in lost and "outAlpha" in lost
        assert "reverse" in lost and "Raw" in lost

    def test_a_layered_texture_mixing_a_file_is_procedural(self, tmp_path):
        image = tmp_path / "base.png"
        image.write_bytes(b"x")
        fake = FakeCmds()
        fake.types["mcpTex_layered"] = "layeredTexture"
        fake.types["inner_file"] = "file"
        fake.attrs["inner_file.fileTextureName"] = str(image)
        # the walk does NOT descend into layeredTexture: it is a terminal.
        fake.conns["mcpTex_layered.inputs[0].color"] = ["inner_file.outColor"]
        _shader_with(fake, "baseColor", "mcpTex_layered.outColor")

        claim = texclaim.material_claims(fake, ["|bodyShape"])[0]

        assert claim["classification"] == "procedural"
        assert [t["type"] for t in claim["terminals"]] == ["layeredTexture"]

    def test_an_unconnected_slot_is_not_claimed_at_all(self):
        fake = FakeCmds()
        fake.existing_attrs.add("skin_mat.baseColor")
        assert texclaim.material_claims(fake, ["|bodyShape"]) == []

    def test_a_cycle_terminates_and_reports_unresolved(self):
        fake = FakeCmds()
        fake.types["a"] = "bump2d"
        fake.types["b"] = "reverse"
        fake.conns["a.bumpValue"] = ["b.outputX"]
        fake.conns["b.inputX"] = ["a.outNormal"]
        _shader_with(fake, "normalCamera", "a.outNormal")

        claim = texclaim.material_claims(fake, ["|bodyShape"])[0]

        assert claim["classification"] == "procedural"
        assert any(t["type"] == "unresolved(depth)"
                   for t in claim["terminals"])

    def test_a_shape_with_no_shading_group_is_skipped_silently(self):
        # #799: the shape has to EXIST and be in no set. Naming a shape
        # the scene never held used to read as "no shading group" here
        # because the fake answered [] for any name; real Maya raises "No
        # object matches name" from listSets, so the old fixture was
        # asserting this walk's behaviour on a scene Maya cannot have -
        # and the branch it meant to cover (a real, unassigned mesh) was
        # never the branch it reached.
        fake = FakeCmds()
        fake.sets["|otherShape"] = []
        assert texclaim.material_claims(fake, ["|otherShape"]) == []

    def test_a_file_reaching_one_pass_through_twice_is_still_a_file_claim(
            self):
        # #714 fix round 1: one file feeding TWO attrs of the same bump2d
        # (two channels of one mask) is an ACYCLIC reconvergence, not a
        # loss - conflating "seen before" with "cycle" turned this into a
        # false procedural drop.
        fake = FakeCmds()
        fake.types["grain"] = "file"
        fake.types["mcpTex_bump"] = "bump2d"
        fake.conns["mcpTex_bump.bumpValue"] = ["grain.outColorR"]
        fake.conns["mcpTex_bump.bumpFilter"] = ["grain.outColorG"]
        _shader_with(fake, "normalCamera", "mcpTex_bump.outNormal")

        claim = texclaim.material_claims(fake, ["|bodyShape"])[0]

        assert claim["classification"] == "file"
        assert len(claim["terminals"]) == 1
        lost = " ".join(claim["semantics_lost"])
        assert "outColorR" in lost and "outColorG" in lost

    def test_a_file_reaching_the_shader_by_two_branches_is_one_terminal(
            self):
        # The same file reached DIRECTLY (bump2d.bumpValue) and again
        # through a second pass-through (bump2d.bumpFilter -> reverse ->
        # the same file): a real diamond, not a cycle - still one terminal.
        fake = FakeCmds()
        fake.types["grain"] = "file"
        fake.types["mcpTex_bump"] = "bump2d"
        fake.types["mcpTex_inv"] = "reverse"
        fake.conns["mcpTex_bump.bumpValue"] = ["grain.outColorR"]
        fake.conns["mcpTex_bump.bumpFilter"] = ["mcpTex_inv.outputX"]
        fake.conns["mcpTex_inv.inputX"] = ["grain.outColorG"]
        _shader_with(fake, "normalCamera", "mcpTex_bump.outNormal")

        claim = texclaim.material_claims(fake, ["|bodyShape"])[0]

        assert claim["classification"] == "file"
        assert len(claim["terminals"]) == 1

    def test_a_chain_longer_than_max_depth_reports_unresolved(self):
        # The depth cap alone, no cycle: MAX_DEPTH + 1 DISTINCT
        # pass-through nodes chained in a straight line must still be
        # capped - the cycle test above does not exercise this branch.
        fake = FakeCmds()
        nodes = ["p%d" % i for i in range(texclaim.MAX_DEPTH + 1)]
        for name in nodes:
            fake.types[name] = "bump2d"
        for i in range(len(nodes) - 1):
            fake.conns["%s.bumpValue" % nodes[i]] = [
                "%s.outNormal" % nodes[i + 1]]
        _shader_with(fake, "normalCamera", "%s.outNormal" % nodes[0])

        claim = texclaim.material_claims(fake, ["|bodyShape"])[0]

        assert claim["classification"] == "procedural"
        assert any(t["type"] == "unresolved(depth)"
                   for t in claim["terminals"])


class TestTheFakeRefusesWhatMayaRefuses:
    """#799 round 2: the regression barrier for THIS file's FakeCmds.

    Round 1's hardening was measured to be INERT with respect to the
    suite - neutering every new refusal left the five look-group files at
    184 passed / 2 xfailed / 0 failed, so the ticket's own premise ("a
    green suite proves nothing") was reproduced one level up.

    `material_claims` is a pure READ - no delete, no setAttr, no
    connectAttr anywhere in it - so this fake models neither deletion nor
    writing, and there is nothing here about either. Round 1 added a
    `delete()` and a `self.deleted` on the belief that the other look
    modules re-run THIS fake as a postcondition; they re-run the texclaim
    HANDLER against their OWN fakes, so the pair was dead code and round 2
    removed it. What is left to pin is the refusal that matters for a
    read-only walk: a name the scene does not hold.
    """

    def _scene(self):
        cmds = FakeCmds()
        cmds.types["mcpTex_file"] = "file"
        cmds.conns["skin_mat.baseColor"] = ["mcpTex_file.outColor"]
        cmds.attrs["mcpTex_file.fileTextureName"] = "C:/tex/skin.png"
        cmds.existing_attrs.add("skin_mat.baseColor")
        return cmds

    def test_every_query_about_a_node_that_never_existed_raises(self):
        cmds = self._scene()
        for call in (lambda: cmds.nodeType("never_made"),
                     lambda: cmds.getAttr("never_made.fileTextureName"),
                     lambda: cmds.listConnections("never_made.outColor",
                                                  source=True),
                     lambda: cmds.attributeQuery("baseColor",
                                                 node="never_made",
                                                 exists=True),
                     lambda: cmds.listSets(object="|ghostShape")):
            with pytest.raises(RuntimeError, match="No object matches name"):
                call()

    def test_nodeType_has_no_answers_anything_fallback(self):
        """`return self.types.get(node, "transform")` answered for every
        string ever handed to it, so a node the fixture never set up came
        back as a plausible terminal and the walk classified the network
        around it."""
        cmds = self._scene()
        assert cmds.nodeType("mcpTex_file") == "file"
        assert cmds.nodeType("skin_mat") == "standardSurface"
        assert cmds.nodeType("|bodyShape") == "mesh"
        assert cmds.nodeType("bodySG") == "shadingEngine"
        with pytest.raises(RuntimeError, match="No object matches name"):
            cmds.nodeType("mcpTex_file_001")

    def test_getAttr_is_a_stored_value_reached_only_after_existence(self):
        cmds = self._scene()
        assert cmds.getAttr("mcpTex_file.fileTextureName") == "C:/tex/skin.png"
        # the modelled default - and what _file_terminal turns into
        # on_disk: False - but only for a node that IS in the scene
        assert cmds.getAttr("skin_mat.baseColor") == ""
        with pytest.raises(RuntimeError, match="No object matches name"):
            cmds.getAttr("ghost.fileTextureName")

    def test_attributeQuery_answers_from_the_shader_not_from_hope(self):
        cmds = self._scene()
        assert cmds.attributeQuery("baseColor", node="skin_mat",
                                   exists=True) is True
        assert cmds.attributeQuery("emissionColor", node="skin_mat",
                                   exists=True) is False
        with pytest.raises(RuntimeError, match="No object matches name"):
            cmds.attributeQuery("baseColor", node="ghost_mat", exists=True)

    def test_the_walk_still_reads_a_scene_this_fake_accepts(self):
        """The refusals above must not have made the fake so strict that
        the handler cannot run against it - the round-2 brief's second
        rule. A real, fully-declared network still classifies."""
        cmds = self._scene()
        claims = texclaim.material_claims(cmds, ["|bodyShape"])
        assert [c["material"] for c in claims] == ["skin_mat"]
        assert claims[0]["classification"] == "file"
        assert claims[0]["attr"] == "baseColor"

    def test_the_fake_models_no_writes_and_therefore_owns_no_write_guard(
            self):
        """Contract 2 ("a setAttr to a fed or locked plug raises") is
        carried by the four look-group fakes whose handlers write. Round
        1's report claimed all five; this fake has no setAttr and no
        connectAttr because `material_claims` makes neither call. Pinned
        so that adding the first write here has to come with the guard -
        this assertion is what goes red the moment one appears."""
        assert not hasattr(FakeCmds, "setAttr")
        assert not hasattr(FakeCmds, "connectAttr")
        assert not hasattr(FakeCmds, "delete")
