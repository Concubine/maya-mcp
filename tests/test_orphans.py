"""orphans: the network a look handler replaces, found before the edge goes
and deleted only where nothing real uses it (#804)."""
from __future__ import annotations

import pytest

from maya_plugin.handlers import orphans


class FakeCmds:
    """A DG-only scene: node -> type, and (src plug, dst plug) pairs, with
    Maya's two bookkeeping singletons and the colour-management node wired
    the way the #804 probe measured them (every file node gets four inputs
    from defaultColorMgtGlobals and one output to defaultTextureList1;
    every utility one output to defaultRenderUtilityList1)."""

    def __init__(self):
        self.types = {"kit": "standardSurface", "defaultColorMgtGlobals": "colorManagementGlobals",
                      "defaultTextureList1": "textureList",
                      "defaultRenderUtilityList1": "renderUtilityList"}
        self.pairs = []
        self.deleted = []

    def add(self, name, node_type):
        self.types[name] = node_type
        if node_type in ("file", "ramp", "noise", "layeredTexture"):
            self.pairs.append((name + ".message", "defaultTextureList1.textures[0]"))
        if node_type in ("place2dTexture", "reverse", "bump2d"):
            self.pairs.append((name + ".message", "defaultRenderUtilityList1.utilities[0]"))
        if node_type == "file":
            for _ in range(4):
                self.pairs.append(("defaultColorMgtGlobals.cmEnabled", name + ".colorManagementEnabled"))
        return name

    def connect(self, src, dst):
        self.pairs = [(s, d) for s, d in self.pairs if d != dst]
        self.pairs.append((src, dst))

    def _require(self, node):
        if node not in self.types:
            raise RuntimeError("No object matches name: %s" % node)

    def objExists(self, node):
        return node in self.types

    def nodeType(self, node):
        self._require(node)
        return self.types[node]

    def listConnections(self, node, source=False, destination=True, plugs=False, **kw):
        self._require(node.split(".")[0])
        bare = "." not in node
        if source and not destination:
            hits = [s for s, d in self.pairs
                    if (d.split(".")[0] == node if bare else d == node)]
        else:
            hits = [d for s, d in self.pairs
                    if (s.split(".")[0] == node if bare else s == node)]
        if plugs:
            return hits or None
        return list(dict.fromkeys(h.split(".")[0] for h in hits)) or None

    def delete(self, node):
        self._require(node)
        self.deleted.append(node)
        del self.types[node]
        self.pairs = [(s, d) for s, d in self.pairs
                      if s.split(".")[0] != node and d.split(".")[0] != node]


@pytest.fixture
def scene():
    """kit.baseColor <- inv (reverse) <- tex (file) <- p2d; kit.specularRoughness
    <- tex.outColorR too (one image, two slots)."""
    fake = FakeCmds()
    fake.add("tex", "file"); fake.add("p2d", "place2dTexture"); fake.add("inv", "reverse")
    fake.connect("p2d.outUV", "tex.uvCoord")
    fake.connect("p2d.outUvFilterSize", "tex.uvFilterSize")
    fake.connect("tex.outColor", "inv.input")
    fake.connect("inv.output", "kit.baseColor")
    fake.connect("tex.outColorR", "kit.specularRoughness")
    return fake


class TestRealOutputs:
    def test_bookkeeping_singletons_do_not_count(self, scene):
        scene.pairs = [(s, d) for s, d in scene.pairs if d != "kit.baseColor"]
        assert orphans.real_outputs(scene, "inv") == []

    def test_a_real_consumer_counts(self, scene):
        assert orphans.real_outputs(scene, "inv") == ["kit"]


class TestUpstreamNetwork:
    def test_follows_sweepable_types_only_and_never_the_colour_globals(self, scene):
        assert orphans.upstream_network(scene, "kit.baseColor") == ["inv", "tex", "p2d"]

    def test_stops_at_a_node_it_did_not_build(self, scene):
        scene.add("layer", "lambert")            # not a sweepable type
        scene.connect("layer.outColor", "inv.input")
        assert orphans.upstream_network(scene, "kit.baseColor") == ["inv"]

    def test_a_cycle_back_to_the_start_is_not_a_candidate(self, scene):
        scene.connect("kit.outColor", "tex.uvCoord")   # a loop, however absurd
        assert "kit" not in orphans.upstream_network(scene, "kit.baseColor")

    def test_an_unfed_plug_has_no_network(self, scene):
        assert orphans.upstream_network(scene, "kit.metalness") == []


class TestSweep:
    def test_deletes_to_a_fixpoint_once_the_edge_is_gone(self, scene):
        scene.pairs = [(s, d) for s, d in scene.pairs if d != "kit.baseColor"]
        scene.pairs = [(s, d) for s, d in scene.pairs if d != "kit.specularRoughness"]
        deleted, survivors = orphans.sweep(scene, ["inv", "tex", "p2d"])
        assert deleted == ["inv", "tex", "p2d"]
        assert survivors == []
        assert "tex" not in scene.types and "p2d" not in scene.types

    def test_a_node_another_slot_still_uses_is_kept_and_named(self, scene):
        scene.pairs = [(s, d) for s, d in scene.pairs if d != "kit.baseColor"]
        deleted, survivors = orphans.sweep(scene, ["inv", "tex", "p2d"])
        assert deleted == ["inv"]
        assert survivors == [("tex", ["kit"]), ("p2d", ["tex"])]
        assert orphans.survivor_warnings(survivors, "re-texturing kit") == [
            "tex was not deleted after re-texturing kit - still used by kit",
            "p2d was not deleted after re-texturing kit - still used by tex"]

    def test_never_sweep_is_never_deleted(self, scene):
        deleted, _ = orphans.sweep(scene, ["defaultColorMgtGlobals"])
        assert deleted == [] and "defaultColorMgtGlobals" in scene.types

    def test_a_vanished_candidate_is_skipped(self, scene):
        scene.delete("inv")
        deleted, survivors = orphans.sweep(scene, ["inv"])
        assert deleted == [] and survivors == []


class TestTheFakeRefusesWhatMayaRefuses:
    def test_a_missing_node_raises_on_every_query(self, scene):
        with pytest.raises(RuntimeError):
            scene.listConnections("ghost.outColor", source=True, destination=False)
        with pytest.raises(RuntimeError):
            scene.nodeType("ghost")

    def test_nothing_connected_answers_none_not_an_empty_list(self, scene):
        assert scene.listConnections("kit.metalness", source=True, destination=False) is None
