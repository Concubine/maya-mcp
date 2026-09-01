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
    aliases in `aliases[node]` ({weight index -> alias}, NOT necessarily
    dense - a test can pop an entry to simulate a target removed outside
    this tool, leaving a hole); weights in `weights[(node, alias)]`.
    setAttr/getAttr accept both the `node.w[i]` plug form the handler uses
    during create and the `node.alias` form set_weights uses."""

    def __init__(self):
        self.objects = []
        self.shapes = {}          # transform long -> shape long
        self.history = {}         # shape long -> [node names]
        self.vertex_counts = {}   # transform long -> int
        self.blend_nodes = set()
        self.aliases = {}         # node -> {index: alias}
        self.weights = {}         # (node, alias) -> float
        self.deleted = []
        self.created = []         # blendShape() create-call records
        self.edited = []          # blendShape(edit=True) records
        self.checkpoints = []

    # --- existence (#799) ----------------------------------------------
    def _live(self):
        """Every name a query may legally be asked about.

        #799 contract point 1: this fake DELETES (create_blendshape
        consumes its targets), and before this ticket a query about a
        consumed mesh still answered - nodeType by naming convention,
        listRelatives/polyEvaluate off dicts `delete` never pruned. Real
        Maya raises "No object matches name" for all of them, which is the
        exact blindness that let #796 ship a classify-after-delete crash.
        """
        live = (list(self.objects) + list(self.shapes.values())
                + sorted(self.blend_nodes)
                + list(getattr(self, "node_types", {})))
        # Curve nodes exist only as a consequence of `curve_plugs`, and the
        # corrective/driven-key sources only of `driven_plugs`; both get
        # asked for their nodeType by clip.partition_driven_keys.
        for plug in getattr(self, "curve_plugs", ()):
            live.append(self._curve_for(plug))
        for src in getattr(self, "driven_plugs", {}).values():
            live.append(src.split(".")[0])
        return live

    def _require(self, node):
        if node not in self._live():
            raise RuntimeError("No object matches name: %s" % node)

    @staticmethod
    def _curve_for(plug):
        return plug.replace("|", "_").replace(".", "_") + "_crv"

    # --- resolution ----------------------------------------------------
    def ls(self, pattern=None, long=False, type=None, **kw):
        if isinstance(pattern, list):
            # ROUND 2 (#799): NOT `list(pattern)`, and NOT nodeType() on a
            # raw name either. Maya's `ls` DROPS a name that is not in the
            # scene (it never raises for one), so the list form has to be
            # filtered to what is live first: inventing the name back is
            # the same answers-anything fallback round 1 deleted from
            # tests/test_rigging.py, and it left this fake's deletion purge
            # unreachable through the list form.
            live = [n for n in pattern if n in self._live()]
            if type == "blendShape":
                return [n for n in live if n in self.blend_nodes]
            if type is not None:
                return [n for n in live if self.nodeType(n) == type]
            return live
        if pattern is None:
            return list(self.objects)
        return [o for o in self.objects
                if o == pattern or o.split("|")[-1] == pattern]

    def objExists(self, name):
        return bool(self.ls(name)) or name in self.blend_nodes

    def listRelatives(self, node, shapes=False, fullPath=False,
                      noIntermediate=False, **kw):
        self._require(node)
        if shapes:
            s = self.shapes.get(node)
            return [s] if s else None
        return None

    def nodeType(self, node):
        # #799 contract point 3: the naming convention below answers for a
        # name the fixture built. For one it never built - or one `delete`
        # consumed - Maya raises, and answering "transform" instead is how
        # a query-after-delete stays invisible.
        self._require(node)
        if node in self.blend_nodes:
            return "blendShape"
        override = getattr(self, "node_types", {}).get(node)
        if override:
            return override
        if node.endswith("_crv"):
            return "animCurveTU"
        return "mesh" if node.endswith("Shape") else "transform"

    def listHistory(self, node, pruneDagObjects=False, **kw):
        self._require(node)
        # MEASURED (#805): a history-less shape answers None, never [] -
        # every production call site carries `or []` for exactly this.
        return list(self.history.get(node, [])) or None

    def polyEvaluate(self, node, vertex=False, **kw):
        self._require(node)
        return self.vertex_counts[node]

    # --- the blendShape surface the handler drives ----------------------
    def blendShape(self, *args, **kw):
        if kw.get("edit"):
            node = args[0]
            base, index, target, _w = kw["target"]
            self.edited.append({"node": node, "index": index,
                                "target": target})
            self.aliases[node][index] = "w[%d]" % index  # unaliased until aliasAttr
            return [node]
        *targets, base = args
        node = kw["name"]
        assert kw.get("frontOfChain") is True
        self.blend_nodes.add(node)
        self.aliases[node] = {i: "w[%d]" % i for i in range(len(targets))}
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
        self._require(node)
        aliases = self.aliases.get(node)
        if not aliases:
            return None
        return [aliases[i] for i in sorted(aliases)]

    def _resolve_weight_key(self, key):
        node, attr = key.split(".", 1)
        if attr.startswith("w[") and attr.endswith("]"):
            attr = self.aliases[node][int(attr[2:-1])]
        return node, attr

    def _write_blocker(self, key):
        """The connection that makes a static write to `key` raise, or None.

        #799 contract point 2, MEASURED in #771 (evals/correctives_probe/):
        setAttr on a driven weight raises "locked or connected". This fake
        wrote happily to any plug, so every guard that exists to keep this
        handler off a connected weight was pinned only by its own refusal
        message - never by the crash the refusal is there to prevent.
        """
        node, alias = self._resolve_weight_key(key)
        plug = "%s.%s" % (node, alias)
        if plug in getattr(self, "curve_plugs", ()):
            return self._curve_for(plug)
        return getattr(self, "driven_plugs", {}).get(plug)

    def setAttr(self, key, value):
        # ROUND 2 (#799): EXISTENCE first. `_resolve_weight_key` reads
        # `self.aliases[node]`, so a write to `<gone>.w[0]` raised KeyError
        # where Maya answers "No object matches name".
        self._require(key.split(".", 1)[0])
        node, alias = self._resolve_weight_key(key)
        blocker = self._write_blocker(key)
        if blocker:
            raise RuntimeError(
                "setAttr: The attribute '%s.%s' is locked or connected and "
                "cannot be modified (%s feeds it)" % (node, alias, blocker))
        self.weights[(node, alias)] = float(value)

    def getAttr(self, key, multiIndices=False):
        self._require(key.split(".", 1)[0])
        if multiIndices:
            node, attr = key.split(".", 1)
            assert attr == "w"
            return sorted(self.aliases.get(node, {}))
        node, alias = self._resolve_weight_key(key)
        return self.weights[(node, alias)]

    def delete(self, *names):
        for n in names:
            self._require(n)
            self.deleted.append(n)
            self.objects.remove(n)
            # #799: the node is GONE. Leaving its shape and vertex count in
            # place let listRelatives/polyEvaluate keep answering for a
            # target mesh create_blendshape had already consumed.
            shape = self.shapes.pop(n, None)
            self.history.pop(shape, None)
            self.vertex_counts.pop(n, None)
            # ROUND 2 (#799): a `node_types` entry outlived its node and
            # `_live` reads that dict, so a deleted target a test had typed
            # explicitly stayed answerable.
            getattr(self, "node_types", {}).pop(n, None)

    def listConnections(self, plug, source=False, destination=True,
                        type=None, plugs=False):
        self._require(plug.split(".")[0])
        if not source:
            # #799: no handler here walks downstream from a weight plug, so
            # an unconditional None would let an unmodelled destination
            # query read as "nothing connected".
            raise AssertionError(
                "FakeCmds.listConnections models source queries only (#799)")
        srcs = []
        if plug in getattr(self, "curve_plugs", ()):
            srcs.append(self._curve_for(plug) + ".output")
        # #771: a corrective-driven plug - a non-animCurve source.
        driven = getattr(self, "driven_plugs", {})
        if plug in driven:
            srcs.append(driven[plug])
        if type is not None:
            # #799: `type` was honoured for driven_plugs and ignored for
            # curve_plugs. Maya filters BOTH - and matches DERIVED types, so
            # an animCurveTU answers type="animCurve" (the #796 defect-1
            # trap).
            srcs = [s for s in srcs
                    if self.nodeType(s.split(".")[0]) == type
                    or (type == "animCurve"
                        and self.nodeType(s.split(".")[0]).startswith(
                            "animCurve"))]
        if not srcs:
            return None
        return srcs if plugs else [s.split(".")[0] for s in srcs]


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
                   for alias in fake.aliases[node].values())
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
        with pytest.raises(HandlerError, match="plain identifier"):
            # re.match's $ matches before a trailing newline - a name like
            # this must be refused, not silently accepted then blow up in
            # aliasAttr after the checkpoint already ran.
            _create(fake, [{"name": "brow\n", "target_mesh": "brow"}])
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
        assert fake.listAttr(node + ".w") == ["brow_raise", "bulge_up"]
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
        assert fake.listAttr(out["blend_shape"] + ".w") == ["a", "b"]
        assert fake.edited and fake.edited[0]["index"] == 1

    def test_additive_create_skips_a_hole_left_by_external_removal(self, fake):
        """A node whose targets were touched outside this tool (Shape
        Editor, `blendShape -e -rm`) can have sparse weight indices. The
        next additive index must come from the actual multi
        (getAttr(node+".w", multiIndices=True)), not from len(existing) -
        landing on an OCCUPIED index makes aliasAttr silently rename the
        survivor instead of naming a fresh one."""
        _scene(fake)
        fake.objects.append("|chin")
        fake.shapes["|chin"] = "|chin|chinShape"
        fake.vertex_counts["|chin"] = 2
        fake.deltas = {"a": 0.2, "b": 0.3, "c": 0.4}
        first = _create(fake, [{"name": "a", "target_mesh": "brow"},
                               {"name": "b", "target_mesh": "bulge"}])
        node = first["blend_shape"]
        # Simulate an external removal of index 0's target: index 0 is
        # gone, "b" survives at index 1 - a HOLE at the front, not a
        # shrink from the end. len(existing) would (wrongly) say 1.
        del fake.aliases[node][0]
        out = _create(fake, [{"name": "c", "target_mesh": "chin"}])
        assert out["blend_shape"] == node
        # "b" must be untouched - not clobbered by "c" landing on its index.
        assert fake.listAttr(node + ".w") == ["b", "c"]
        assert fake.edited[-1]["index"] == 2

    def test_alias_collision_with_existing_target_refused(self, fake):
        _scene(fake)
        fake.deltas = {"a": 0.2}
        _create(fake, [{"name": "a", "target_mesh": "brow"}])
        with pytest.raises(HandlerError, match="already exists"):
            _create(fake, [{"name": "a", "target_mesh": "bulge"}])


class TestBlendNodeWarning:
    """_blend_node_for silently returned nodes[0] when a mesh carried more
    than one blendShape node (hand-stacked outside this tool) - a silent
    pick violates 'silence is never an answer'. It must still pick the
    first (unchanged, load-bearing precedent), but now it must SAY so."""

    def test_multiple_blend_nodes_warns_naming_the_ignored_one(self, fake):
        _scene(fake)
        fake.deltas = {"a": 0.2}
        first = _create(fake, [{"name": "a", "target_mesh": "brow"}])
        real_node = first["blend_shape"]
        shape = fake.shapes["|humanoid"]
        # A second blendShape node stacked on the mesh outside this tool,
        # sitting AHEAD of the tool's node in history.
        stacked = "stackedBlendShape"
        fake.blend_nodes.add(stacked)
        fake.aliases[stacked] = {}
        fake.history[shape].insert(0, stacked)

        fake.deltas["b"] = 0.3
        out = _create(fake, [{"name": "b", "target_mesh": "bulge"}])

        assert out["blend_shape"] == stacked  # still picks the first
        assert any(stacked in w and real_node in w and "blendShape nodes" in w
                  for w in out["warnings"])

    def test_a_single_blend_node_warns_nothing(self, fake):
        _scene(fake)
        fake.deltas = {"a": 0.2}
        out = _create(fake, [{"name": "a", "target_mesh": "brow"}])
        assert out["warnings"] == []


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


class TestClipGuard:
    def test_set_weights_refuses_on_a_keyed_channel(self, fake):
        _scene(fake)
        fake.deltas = {"blink": 0.2}
        node = _create(fake, [{"name": "blink",
                               "target_mesh": "brow"}])["blend_shape"]
        fake.curve_plugs = {"%s.blink" % node}
        with pytest.raises(HandlerError, match="animation curves"):
            blendshape.set_blendshape_weights(
                {"mesh": "humanoid", "weights": {"blink": 0.5}})

    def test_unkeyed_channels_still_write(self, fake):
        _scene(fake)
        fake.deltas = {"blink": 0.2}
        _create(fake, [{"name": "blink", "target_mesh": "brow"}])
        out = blendshape.set_blendshape_weights(
            {"mesh": "humanoid", "weights": {"blink": 0.5}})
        assert out["weights"]["blink"] == 0.5


class TestMushOrderGuard:
    """#771, MEASURED (evals/correctives_probe/probe_bs_hang.py): a NEW
    frontOfChain blendShape under a deltaMush hangs Maya 20+ minutes;
    adding a target to an existing node under the same mush is instant."""

    def test_new_node_under_a_mush_refuses(self, fake):
        _scene(fake)
        fake.node_types = {"deltaMush1": "deltaMush"}
        fake.history["|humanoid|humanoidShape"] = ["deltaMush1"]
        with pytest.raises(HandlerError, match="deltaMush"):
            _create(fake, [{"name": "blink", "target_mesh": "brow"}])

    def test_adding_to_an_existing_node_under_a_mush_is_allowed(self, fake):
        _scene(fake)
        fake.deltas = {"blink": 0.2, "wink": 0.1}
        _create(fake, [{"name": "blink", "target_mesh": "brow"}])
        fake.node_types = {"deltaMush1": "deltaMush"}
        fake.history["|humanoid|humanoidShape"].insert(0, "deltaMush1")
        out = _create(fake, [{"name": "wink", "target_mesh": "bulge"}])
        assert [t["name"] for t in out["targets"]] == ["wink"]


class TestCorrectiveGuard:
    """#771: a poseInterpolator-driven weight refuses hand-setting -
    MEASURED (evals/correctives_probe/): setAttr on a connected plug raises
    a raw locked-or-connected error, which is not a contract."""

    def test_set_weights_refuses_on_a_driven_channel(self, fake):
        _scene(fake)
        fake.deltas = {"elbow_fix": 0.2}
        node = _create(fake, [{"name": "elbow_fix",
                               "target_mesh": "brow"}])["blend_shape"]
        fake.driven_plugs = {
            "%s.elbow_fix" % node: "elbow_poseInterpShape.output[3]"}
        fake.node_types = {"elbow_poseInterpShape": "poseInterpolator"}
        with pytest.raises(HandlerError, match="corrective"):
            blendshape.set_blendshape_weights(
                {"mesh": "humanoid", "weights": {"elbow_fix": 0.5}})

    def test_a_corrective_elsewhere_does_not_lock_other_targets(self, fake):
        _scene(fake)
        fake.deltas = {"elbow_fix": 0.2, "brow_raise": 0.1}
        node = _create(fake, [
            {"name": "elbow_fix", "target_mesh": "brow"},
            {"name": "brow_raise", "target_mesh": "bulge"}])["blend_shape"]
        fake.driven_plugs = {
            "%s.elbow_fix" % node: "elbow_poseInterpShape.output[3]"}
        fake.node_types = {"elbow_poseInterpShape": "poseInterpolator"}
        out = blendshape.set_blendshape_weights(
            {"mesh": "humanoid", "weights": {"brow_raise": 0.7}})
        assert out["weights"]["brow_raise"] == 0.7


class TestTheFakeRefusesWhatMayaRefuses:
    """#799 round 2: the regression barrier for THIS file's FakeCmds.

    Round 1 hardened the fake and nothing asserted the hardening - a
    reviewer measured that reverting every behavioural change left the
    suite fully green, which is this ticket's own "a green suite proves
    nothing" moved up one level. These assertions go red the day someone
    loosens the fake back toward answering anything.

    The compound direction of contract point 2 has no meaning on a weight
    (a blendShape weight is a scalar); its analogue is the two ways the
    same plug is addressed - `node.alias` and `node.w[i]` - and both are
    pinned. This fake has no setKeyframe: no blendshape handler calls one.
    """

    _GONE = "No object matches name"

    @staticmethod
    def _wired(fake):
        """The scene plus one blendShape carrying two weights."""
        _scene(fake)
        fake.blend_nodes.add("bs1")
        fake.aliases["bs1"] = {0: "elbow_fix", 1: "bulge"}
        fake.weights[("bs1", "elbow_fix")] = 0.0
        fake.weights[("bs1", "bulge")] = 0.0
        fake.history["|humanoid|humanoidShape"] = ["bs1"]

    def test_a_node_no_fixture_created_raises_from_every_query(self, fake):
        _scene(fake)
        calls = [
            lambda: fake.nodeType("|ghost"),
            lambda: fake.listRelatives("|ghost", shapes=True),
            lambda: fake.listHistory("|ghost"),
            lambda: fake.polyEvaluate("|ghost", vertex=True),
            lambda: fake.listAttr("|ghost.w"),
            lambda: fake.getAttr("|ghost.w", multiIndices=True),
            lambda: fake.setAttr("|ghost.w[0]", 1.0),
            lambda: fake.delete("|ghost"),
            lambda: fake.listConnections("|ghost.w[0]", source=True),
        ]
        for call in calls:
            with pytest.raises(RuntimeError, match=self._GONE):
                call()
        assert fake.ls("|ghost") == []
        # ROUND 2: the list form used to answer `list(pattern)` - inventing
        # the name back for anything asked, which is the fallback round 1
        # deleted from tests/test_rigging.py and left standing here.
        assert fake.ls(["|ghost"]) == []
        assert fake.objExists("|ghost") is False

    def test_a_consumed_target_stops_answering(self, fake):
        _scene(fake)
        assert fake.polyEvaluate("|brow", vertex=True) == 2
        fake.delete("|brow")
        for call in (lambda: fake.nodeType("|brow"),
                     lambda: fake.polyEvaluate("|brow", vertex=True),
                     lambda: fake.listRelatives("|brow", shapes=True),
                     lambda: fake.nodeType("|brow|browShape")):
            with pytest.raises(RuntimeError, match=self._GONE):
                call()
        assert fake.ls("|brow") == []
        assert fake.ls(["|brow"]) == []

    def test_an_explicitly_typed_target_dies_with_the_node(self, fake):
        # ROUND 2: `_live` reads `node_types`, so an entry a test wrote by
        # hand outlived the node `delete` consumed.
        _scene(fake)
        fake.node_types = {"|brow": "transform"}
        fake.delete("|brow")
        with pytest.raises(RuntimeError, match=self._GONE):
            fake.nodeType("|brow")

    def test_a_driven_weight_refuses_the_write_both_ways_it_is_addressed(
            self, fake):
        self._wired(fake)
        fake.node_types = {"poseInterp1": "poseInterpolator"}
        fake.driven_plugs = {"bs1.elbow_fix": "poseInterp1.output[0]"}
        with pytest.raises(RuntimeError, match="locked or connected"):
            fake.setAttr("bs1.elbow_fix", 1.0)
        with pytest.raises(RuntimeError, match="locked or connected"):
            fake.setAttr("bs1.w[0]", 1.0)
        # and it does NOT over-refuse: the free weight on the same node
        # still writes. A fake wrong in the strict direction is as bad as a
        # permissive one.
        fake.setAttr("bs1.w[1]", 0.5)
        assert fake.weights[("bs1", "bulge")] == 0.5

    def test_an_animation_curve_on_a_weight_refuses_the_write(self, fake):
        self._wired(fake)
        fake.curve_plugs = ["bs1.elbow_fix"]
        with pytest.raises(RuntimeError, match="locked or connected"):
            fake.setAttr("bs1.elbow_fix", 1.0)

    def test_listConnections_models_sources_and_derived_types(self, fake):
        self._wired(fake)
        fake.curve_plugs = ["bs1.elbow_fix"]
        crv = fake._curve_for("bs1.elbow_fix")
        fake.node_types = {crv: "animCurveTU"}
        assert fake.listConnections("bs1.elbow_fix", source=True,
                                    plugs=True) == [crv + ".output"]
        # ROUND 1 fixed the half of this that ignored `type` for curves;
        # Maya's filter also matches DERIVED types (the #796 defect-1 trap).
        assert fake.listConnections("bs1.elbow_fix", source=True,
                                    type="animCurve") == [crv]
        assert fake.listConnections("bs1.elbow_fix", source=True,
                                    type="poseInterpolator") is None
        with pytest.raises(AssertionError, match="source queries only"):
            fake.listConnections("bs1.elbow_fix", destination=True)

    def test_listAttr_answers_none_for_a_node_with_no_targets(self, fake):
        self._wired(fake)
        assert fake.listAttr("bs1.w") == ["elbow_fix", "bulge"]
        fake.aliases["bs1"] = {}
        assert fake.listAttr("bs1.w") is None
