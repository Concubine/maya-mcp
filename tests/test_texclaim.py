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

    def listSets(self, object=None, type=None):
        return list(self.sets.get(object, []))

    def listConnections(self, plug, source=False, destination=True,
                        plugs=False, **kw):
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
        return self.types.get(node, "transform")

    def attributeQuery(self, attr, node=None, exists=False):
        return ("%s.%s" % (node, attr)) in self.existing_attrs

    def getAttr(self, plug):
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
        fake = FakeCmds()
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
