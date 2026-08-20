"""create_blendshape / set_blendshape_weights (#691) under a FakeCmds.

Real deformation is mayapy's job (tests/test_handlers_mayapy.py); this file
pins validation, the alias contract, target consumption, the additive-create
rule, sequential measurement and every refusal path. The vertex seam
blendshape._points is monkeypatched - FakeCmds cannot deform, and that is
exactly why the seam is module-level (the rigging._set_skin_weights
precedent).
"""

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import blendshape


class FakeCmds:
    """Transforms in `objects` (long names), shapes in `shapes`, per-shape
    history in `history`. blendShape nodes live in `blend_nodes` with their
    aliases in `aliases[node]` (index order); weights in `weights[(node,
    alias)]`. setAttr/getAttr accept both the `node.w[i]` plug form the
    handler uses during create and the `node.alias` form set_weights uses."""

    def __init__(self):
        self.objects = []
        self.shapes = {}          # transform long -> shape long
        self.history = {}         # shape long -> [node names]
        self.vertex_counts = {}   # transform long -> int
        self.blend_nodes = set()
        self.aliases = {}         # node -> [alias, ...]
        self.weights = {}         # (node, alias) -> float
        self.deleted = []
        self.created = []         # blendShape() create-call records
        self.edited = []          # blendShape(edit=True) records
        self.checkpoints = []

    # --- resolution ----------------------------------------------------
    def ls(self, pattern=None, long=False, type=None, **kw):
        if isinstance(pattern, list):
            if type == "blendShape":
                return [n for n in pattern if n in self.blend_nodes]
            return list(pattern)
        if pattern is None:
            return list(self.objects)
        return [o for o in self.objects
                if o == pattern or o.split("|")[-1] == pattern]

    def objExists(self, name):
        return bool(self.ls(name)) or name in self.blend_nodes

    def listRelatives(self, node, shapes=False, fullPath=False,
                      noIntermediate=False, **kw):
        if shapes:
            s = self.shapes.get(node)
            return [s] if s else None
        return None

    def nodeType(self, node):
        if node in self.blend_nodes:
            return "blendShape"
        return "mesh" if node.endswith("Shape") else "transform"

    def listHistory(self, node, pruneDagObjects=False, **kw):
        return list(self.history.get(node, []))

    def polyEvaluate(self, node, vertex=False, **kw):
        return self.vertex_counts[node]

    # --- the blendShape surface the handler drives ----------------------
    def blendShape(self, *args, **kw):
        if kw.get("edit"):
            node = args[0]
            base, index, target, _w = kw["target"]
            self.edited.append({"node": node, "index": index,
                                "target": target})
            self.aliases[node].append("w[%d]" % index)  # unaliased until aliasAttr
            return [node]
        *targets, base = args
        node = kw["name"]
        assert kw.get("frontOfChain") is True
        self.blend_nodes.add(node)
        self.aliases[node] = ["w[%d]" % i for i in range(len(targets))]
        self.created.append({"node": node, "base": base,
                             "targets": list(targets)})
        self.history.setdefault(self.shapes[base], []).append(node)
        return [node]

    def aliasAttr(self, alias, plug):
        node, index = plug.split(".w[")
        index = int(index[:-1])
        self.aliases[node][index] = alias
        self.weights.setdefault((node, alias), 0.0)

    def listAttr(self, plug, multi=False):
        node = plug.split(".")[0]
        return list(self.aliases.get(node, [])) or None

    def _resolve_weight_key(self, key):
        node, attr = key.split(".", 1)
        if attr.startswith("w[") and attr.endswith("]"):
            attr = self.aliases[node][int(attr[2:-1])]
        return node, attr

    def setAttr(self, key, value):
        node, alias = self._resolve_weight_key(key)
        self.weights[(node, alias)] = float(value)

    def getAttr(self, key):
        node, alias = self._resolve_weight_key(key)
        return self.weights[(node, alias)]

    def delete(self, *names):
        for n in names:
            self.deleted.append(n)
            self.objects.remove(n)


@pytest.fixture
def fake(monkeypatch):
    fake = FakeCmds()
    fake.deltas = {}   # alias -> per-unit-weight displacement of vertex 0
    monkeypatch.setattr(blendshape, "_cmds", lambda: fake)
    monkeypatch.setattr(blendshape.session, "auto_checkpoint",
                        lambda label: fake.checkpoints.append(label) or
                        {"checkpoint_id": "cp"})

    def points(mesh):
        # A 2-vertex mesh 1.0 wide (so bbox_extent is 1.0); vertex 0 rises
        # by sum(weight * delta) over every alias on every node - the
        # minimal linear model of what a blendShape does.
        lift = sum(fake.weights.get((node, alias), 0.0)
                   * fake.deltas.get(alias, 0.0)
                   for node in fake.aliases
                   for alias in fake.aliases[node])
        return [0.0, lift, 0.0, 1.0, 0.0, 0.0]

    monkeypatch.setattr(blendshape, "_points", points)
    return fake


def _scene(fake):
    fake.objects = ["|humanoid", "|brow", "|bulge"]
    fake.shapes = {"|humanoid": "|humanoid|humanoidShape",
                   "|brow": "|brow|browShape",
                   "|bulge": "|bulge|bulgeShape"}
    fake.vertex_counts = {"|humanoid": 2, "|brow": 2, "|bulge": 2}


def _create(fake, targets):
    return blendshape.create_blendshape(
        {"mesh": "humanoid", "targets": targets})


class TestCreateValidation:
    def test_refusals(self, fake):
        _scene(fake)
        with pytest.raises(HandlerError, match="targets must be"):
            blendshape.create_blendshape({"mesh": "humanoid"})
        with pytest.raises(HandlerError, match="targets must be"):
            blendshape.create_blendshape({"mesh": "humanoid", "targets": []})
        with pytest.raises(HandlerError, match="plain identifier"):
            _create(fake, [{"name": "2bad", "target_mesh": "brow"}])
        with pytest.raises(HandlerError, match="plain identifier"):
            _create(fake, [{"name": "has space", "target_mesh": "brow"}])
        with pytest.raises(HandlerError, match="plain identifier"):
            _create(fake, [{"name": "brow_é", "target_mesh": "brow"}])
        with pytest.raises(HandlerError, match="appears twice"):
            _create(fake, [{"name": "a", "target_mesh": "brow"},
                           {"name": "a", "target_mesh": "bulge"}])
        with pytest.raises(HandlerError, match="reuses"):
            _create(fake, [{"name": "a", "target_mesh": "brow"},
                           {"name": "b", "target_mesh": "brow"}])
        with pytest.raises(HandlerError, match="its own target"):
            _create(fake, [{"name": "a", "target_mesh": "humanoid"}])
        with pytest.raises(HandlerError, match="not found"):
            _create(fake, [{"name": "a", "target_mesh": "nope"}])
        # nothing above reached the checkpoint - a bad call costs nothing
        assert fake.checkpoints == []

    def test_topology_mismatch_refused_with_both_counts(self, fake):
        _scene(fake)
        fake.vertex_counts["|brow"] = 3
        with pytest.raises(HandlerError,
                           match="topology does not match") as exc:
            _create(fake, [{"name": "a", "target_mesh": "brow"}])
        assert "2" in str(exc.value) and "3" in str(exc.value)


class TestCreate:
    def test_wires_aliases_measures_and_consumes(self, fake):
        _scene(fake)
        fake.deltas = {"brow_raise": 0.25, "bulge_up": 0.1}
        out = _create(fake, [
            {"name": "brow_raise", "target_mesh": "brow"},
            {"name": "bulge_up", "target_mesh": "bulge"}])
        assert out["mesh"] == "|humanoid"
        node = out["blend_shape"]
        assert fake.aliases[node] == ["brow_raise", "bulge_up"]
        by = {t["name"]: t for t in out["targets"]}
        assert by["brow_raise"]["max_delta"] == pytest.approx(0.25)
        assert by["bulge_up"]["max_delta"] == pytest.approx(0.1)
        assert by["brow_raise"]["vertex_count"] == 2
        # measured, then restored: every weight back at 0
        assert all(w == 0.0 for w in fake.weights.values())
        # consumed
        assert "|brow" in fake.deleted and "|bulge" in fake.deleted
        assert fake.checkpoints == ["create_blendshape"]

    def test_zero_delta_target_warns_but_wires(self, fake):
        _scene(fake)
        fake.deltas = {"noop": 0.0}
        out = _create(fake, [{"name": "noop", "target_mesh": "brow"}])
        assert any("identical to the base" in w for w in out["warnings"])
        assert out["targets"][0]["max_delta"] == 0.0
        assert "|brow" in fake.deleted

    def test_second_create_adds_to_the_same_node(self, fake):
        _scene(fake)
        fake.deltas = {"a": 0.2, "b": 0.3}
        first = _create(fake, [{"name": "a", "target_mesh": "brow"}])
        out = _create(fake, [{"name": "b", "target_mesh": "bulge"}])
        assert out["blend_shape"] == first["blend_shape"]
        assert fake.aliases[out["blend_shape"]] == ["a", "b"]
        assert fake.edited and fake.edited[0]["index"] == 1

    def test_alias_collision_with_existing_target_refused(self, fake):
        _scene(fake)
        fake.deltas = {"a": 0.2}
        _create(fake, [{"name": "a", "target_mesh": "brow"}])
        with pytest.raises(HandlerError, match="already exists"):
            _create(fake, [{"name": "a", "target_mesh": "bulge"}])


class TestSetWeights:
    def _wired(self, fake):
        _scene(fake)
        fake.deltas = {"brow_raise": 0.25, "bulge_up": 0.1}
        return _create(fake, [
            {"name": "brow_raise", "target_mesh": "brow"},
            {"name": "bulge_up", "target_mesh": "bulge"}])["blend_shape"]

    def test_refusals(self, fake):
        _scene(fake)
        with pytest.raises(HandlerError, match="no blendShape"):
            blendshape.set_blendshape_weights(
                {"mesh": "humanoid", "weights": {"a": 1.0}})
        node = self._wired(fake)
        for bad in ({}, None, []):
            with pytest.raises(HandlerError, match="non-empty map"):
                blendshape.set_blendshape_weights(
                    {"mesh": "humanoid", "weights": bad})
        with pytest.raises(HandlerError, match="not a target"):
            blendshape.set_blendshape_weights(
                {"mesh": "humanoid", "weights": {"nope": 0.5}})
        for value in (-0.1, 1.5, True, "x"):
            with pytest.raises(HandlerError, match="0..1"):
                blendshape.set_blendshape_weights(
                    {"mesh": "humanoid", "weights": {"brow_raise": value}})
        assert node in fake.blend_nodes  # nothing was harmed

    def test_sequential_measurement_and_reread(self, fake):
        self._wired(fake)
        out = blendshape.set_blendshape_weights(
            {"mesh": "humanoid",
             "weights": {"brow_raise": 1.0, "bulge_up": 0.5}})
        steps = {p["name"]: p for p in out["per_target"]}
        assert steps["brow_raise"]["max_displacement"] == pytest.approx(0.25)
        assert steps["bulge_up"]["max_displacement"] == pytest.approx(0.05)
        assert steps["brow_raise"]["weight"] == 1.0
        assert out["weights"] == {"brow_raise": 1.0, "bulge_up": 0.5}
        assert out["max_displacement"] == pytest.approx(0.30)
        assert out["warnings"] == []

    def test_all_zero_is_the_reset(self, fake):
        self._wired(fake)
        blendshape.set_blendshape_weights(
            {"mesh": "humanoid",
             "weights": {"brow_raise": 1.0, "bulge_up": 1.0}})
        out = blendshape.set_blendshape_weights(
            {"mesh": "humanoid",
             "weights": {"brow_raise": 0.0, "bulge_up": 0.0}})
        assert out["weights"] == {"brow_raise": 0.0, "bulge_up": 0.0}
        assert out["max_displacement"] == pytest.approx(0.35)

    def test_unnamed_aliases_still_reported(self, fake):
        self._wired(fake)
        out = blendshape.set_blendshape_weights(
            {"mesh": "humanoid", "weights": {"brow_raise": 0.5}})
        assert set(out["weights"]) == {"brow_raise", "bulge_up"}
        assert out["weights"]["bulge_up"] == 0.0

    def test_noop_call_warns(self, fake):
        self._wired(fake)
        out = blendshape.set_blendshape_weights(
            {"mesh": "humanoid", "weights": {"brow_raise": 0.0}})
        assert any("nothing moved" in w for w in out["warnings"])
