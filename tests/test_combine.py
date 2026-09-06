"""maya_combine: does it merge meshes the way a kit needs, and refuse the rest?

The fake reproduces the two Maya behaviours that have burned this project
before:

  * cmds.polyUnite RENAMES its result on a name collision, so the handler must
    re-resolve by short name rather than trusting the name it asked for
    (modeling.py documents the same trap for grouping).
  * combining meshes that carry different shaders leaves PER-FACE shading
    group membership, which #577 found silently no-ops later per-face work and
    corrupts SGs. The handler collapses to one object-level SG and says so.
"""

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import combine


class FakeCmds:
    def __init__(self, objects=("|a", "|b"), shapes=None, unite_name=None):
        self.objects = list(objects)
        self.shapes = (
            dict(shapes)
            if shapes is not None
            else {o: (o + "Shape", "mesh") for o in self.objects}
        )
        self.calls = []
        # #799: what stopped existing - deleted, or consumed by polyUnite.
        # Every modelled query consults it through _require below.
        self.deleted = []
        # LIVE pivot state, which a freeze clears (see makeIdentity), kept
        # apart from the log of pivot WRITES below - conflating the two is
        # how a pivot that Maya has already thrown away goes on looking
        # placed (#799).
        self.pivots = {}
        self.pivot_writes = []
        self.frozen = []
        # node -> world bounding box. Modelled rather than one constant for
        # every node (#799 contract 3): a box centred on the origin makes the
        # "center" pivot mode indistinguishable from the "origin" one, and
        # from a pivot that was never placed at all.
        self.bboxes = {}
        # what polyUnite will actually name the result, when Maya disagrees
        self._unite_name = unite_name
        self.sg_members = {}
        # shading group -> members, as cmds.sets(sg, query=True) reports them.
        self.set_members = {}
        # DG nodes with no DAG path of their own - a shadingEngine is one.
        # cmds.ls(<transform pattern>) does not list them, but cmds.sets and
        # cmds.listConnections address them by name, so _live has to know
        # they exist (#799 round 2: refusing a shading group as if it were a
        # missing DAG node made ensure_object_shading's HEALTHY branch, the
        # one branch this fake exists to reach, impossible to test).
        self.dg_nodes = set()
        # #799 contract 2: plug -> the node feeding it. A fed plug refuses a
        # static write; so does a compound whose child is fed. Empty by
        # default - a polyUnite result is a brand-new transform with nothing
        # driving it, so combine's own writes are never blocked.
        self.connected_plugs = {}
        # node -> connections, for the typed listConnections queries.
        self.connections = {}
        # node -> its parent's long path (#867). A node absent here is at
        # the root, as listRelatives(parent=True) answers None for one.
        self.parents = {}
        # result -> the inputs a polyUnite WITH history left behind as empty
        # transforms, reaped by delete(constructionHistory=True) (#867).
        self.history = {}

    # --- existence ---------------------------------------------------------
    # #799 contract 1: real Maya raises "No object matches name" for a node it
    # no longer has, and polyUnite CONSUMES every input it is handed - so this
    # fake, of all of them, must stop answering about them. Answering a
    # default is the shape that hid #796's first blocking defect.
    def _live(self, name):
        node = name.split(".")[0]
        known = (list(self.objects) + [s for s, _k in self.shapes.values()]
                 + list(self.dg_nodes))
        if node in known:
            return True
        # An ABSOLUTE path names one node and nothing else; a short name
        # matches the way cmds.ls matches it.
        if node.startswith("|"):
            return False
        return any(n.split("|")[-1] == node for n in known)

    def _require(self, name):
        if not self._live(name):
            raise RuntimeError("No object matches name: %s" % name.split(".")[0])

    def add_shading_group(self, sg, members=()):
        """Declare a shadingEngine and who is in it, the way a scene has one.

        Registers it as a DG node too: `cmds.sets(sg, query=True)` is a real
        call Maya answers, and a fake that refuses it is wrong in the STRICT
        direction - which costs the next person a spurious failure they will
        "fix" by loosening the fake back (#799 round 2).
        """
        self.dg_nodes.add(sg)
        self.set_members[sg] = list(members)
        for member in members:
            self.sg_members.setdefault(member.split(".")[0], [])
            if sg not in self.sg_members[member.split(".")[0]]:
                self.sg_members[member.split(".")[0]].append(sg)

    def _write_blocker(self, plug):
        if plug in self.connected_plugs:
            return plug
        node, _, attr = plug.rpartition(".")
        if attr in ("translate", "rotate", "scale", "rotatePivot"):
            for child in ("%s.%s%s" % (node, attr, ax) for ax in "XYZ"):
                if child in self.connected_plugs:
                    return child
        elif attr[:-1] in ("translate", "rotate", "scale", "rotatePivot") \
                and attr[-1] in "XYZ":
            parent = "%s.%s" % (node, attr[:-1])
            if parent in self.connected_plugs:
                return parent
        return None

    def _refuse_static_write(self, command, plug):
        blocker = self._write_blocker(plug)
        if blocker:
            raise RuntimeError(
                "%s: The attribute '%s' is locked or connected and cannot be "
                "modified (%s feeds it)"
                % (command, plug, self.connected_plugs[blocker])
            )

    # --- names -------------------------------------------------------------
    def ls(self, pattern=None, long=False, **kwargs):
        if pattern is None:
            hits = list(self.objects)
        else:
            hits = [
                n for n in self.objects
                if n == pattern or n.split("|")[-1] == pattern
            ]
        return hits if long else [h.split("|")[-1] for h in hits]

    def objExists(self, name):
        return bool(self.ls(name))

    def listRelatives(self, node, shapes=False, children=False, fullPath=False,
                      noIntermediate=False, parent=False, **kwargs):
        self._require(node)
        if shapes:
            entry = self.shapes.get(node)
            return [entry[0]] if entry else None
        if parent:
            found = self.parents.get(node)
            return [found] if found else None
        return None

    def parent(self, child, target):
        """cmds.parent: the child moves under target and answers its NEW
        path. Modelled with the rename below in mind: every per-node table
        is re-keyed, so a later question about the old path raises the way
        Maya's does (#799), and one about the new path answers."""
        self._require(child)
        self._require(target)
        moved = target + "|" + child.split("|")[-1]
        self.objects.remove(child)
        self.objects.append(moved)
        self.shapes[moved] = self.shapes.pop(child, (moved + "Shape", "mesh"))
        for table in (self.pivots, self.bboxes, self.sg_members, self.history):
            if child in table:
                table[moved] = table.pop(child)
        self.parents.pop(child, None)
        self.parents[moved] = target
        self.calls.append(("parent", child, target))
        return [moved]

    def nodeType(self, node):
        self._require(node)
        for _transform, (shape, kind) in self.shapes.items():
            if shape == node:
                return kind
        return "transform"

    # --- the operation -----------------------------------------------------
    def polyUnite(self, *args, **kwargs):
        members = list(args[0]) if args and isinstance(args[0], (list, tuple)) else list(args)
        for m in members:
            self._require(m)
        self.calls.append(("polyUnite", tuple(members), kwargs.get("ch")))
        asked = kwargs.get("name") or "polySurface1"
        # MEASURED (#803, evals/combine_pivot_probe_803.py): the result is
        # named while the inputs STILL EXIST, so asking for an input's own
        # name (or any held name) gets body1 - and the input's name is free
        # once the unite has consumed it. A fake that handed the asked name
        # straight back could not fail for the uniquify-first order.
        taken = {o.split("|")[-1] for o in self.objects}
        actual = self._unite_name or (asked + "1" if asked in taken else asked)
        node = "|" + actual
        if kwargs.get("ch"):
            # History ON (#867): the inputs stay as EMPTY transforms - their
            # shapes feed the unite - until delete(constructionHistory=True)
            # reaps them, and with them any parent left childless.
            for m in members:
                self.shapes.pop(m, None)
            self.history[node] = list(members)
        else:
            for m in members:
                # Consumed, not merely hidden: the transform and its shape
                # both stop existing, and a later question about either
                # must raise. MEASURED (live gate 2026-09-06): a parent
                # holding nothing else goes with them.
                self._reap(m)
        self.objects.append(node)
        self.shapes[node] = (node + "Shape", "mesh")
        return [node, node + "_unite"]

    def _reap(self, node):
        if node in self.objects:
            self.objects.remove(node)
            self.deleted.append(node)
        self.shapes.pop(node, None)
        parent = self.parents.pop(node, None)
        if parent and parent in self.objects and not any(
                self.parents.get(o) == parent for o in self.objects):
            self._reap(parent)

    def polyEvaluate(self, node, **kwargs):
        self._require(node)
        if kwargs.get("shell"):
            return 2
        if kwargs.get("triangle"):
            return 24
        if kwargs.get("vertex"):
            return 16
        if kwargs.get("face"):
            return 12
        # #799 round 2: no answers-anything tail. A flag this fixture never
        # modelled used to come back as a plausible-looking 0 that landed in
        # the response as a count - the same fallback already removed from
        # test_assemble.py and test_uvatlas.py.
        raise AssertionError("unmodelled polyEvaluate flags: %r" % (kwargs,))

    def xform(self, node, **kwargs):
        self._require(node)
        if kwargs.get("query"):
            # Logged like a write, so a test can assert WHEN the handler
            # asked (the #803 query-after-freeze rule is an ordering).
            self.calls.append(("xform", node, dict(kwargs)))
            if kwargs.get("boundingBox"):
                return [-1.5, -1.5, -1.5, 1.5, 1.5, 1.5]
            return list(self.pivots.get(node, (0.0, 0.0, 0.0))) \
                if kwargs.get("rotatePivot") else [0.0, 0.0, 0.0]
        # #799 contract 2: a pivot write is a static write to rotatePivot /
        # scalePivot, and Maya refuses it on a connected or locked plug the
        # same way it refuses setAttr.
        if "pivots" in kwargs:
            self._refuse_static_write("xform", node + ".rotatePivot")
            self.pivots[node] = tuple(kwargs["pivots"])
            self.pivot_writes.append((node, tuple(kwargs["pivots"])))
        for key, channel in (("translation", "translate"),
                             ("rotation", "rotate"), ("scale", "scale")):
            if key in kwargs:
                self._refuse_static_write("xform", "%s.%s" % (node, channel))
        self.calls.append(("xform", node, dict(kwargs)))
        return None

    def exactWorldBoundingBox(self, node):
        self._require(node)
        return list(self.bboxes.get(node, [-1.5, -1.5, -1.5, 1.5, 1.5, 1.5]))

    def makeIdentity(self, node, **kwargs):
        self._require(node)
        self.frozen.append(node)
        self.calls.append(("makeIdentity", node, None))
        # A freeze LEAVES THE PIVOT WHERE IT IS. MEASURED (#803,
        # evals/combine_pivot_probe_803.py, Maya 2027): after makeIdentity
        # on a rotated, scaled, off-origin mesh the world rotate and scale
        # pivots answer exactly what was written. #799 had this fake throw
        # the pivot away on a "measured" citation that was a plan-doc
        # sentence (2026-08-15-golem-articulated.md) - a fake wrong in the
        # strict direction, which pinned a defect the handler never had.
        # test_modeling.py's and test_assemble.py's doubles agree.

    def delete(self, node, **kwargs):
        self._require(node)
        self.calls.append(("delete", node, bool(kwargs.get("constructionHistory"))))
        if kwargs.get("constructionHistory"):
            # Reaps the unite's emptied inputs (and a parent left with no
            # child - MEASURED); the result itself stays.
            for member in self.history.pop(node, []):
                self._reap(member)
            return
        if node in self.objects:
            self.objects.remove(node)
            self.shapes.pop(node, None)
            self.deleted.append(node)

    def rename(self, node, new):
        self._require(node)
        # Maya never refuses a rename collision; it suffixes. Modelled so a
        # handler that renames onto a held name is caught by the name it
        # gets back, the way it would be live.
        if any(o.split("|")[-1] == new and o != node for o in self.objects):
            new = new + "1"
        self.objects.remove(node)
        # The path is kept: a rename does not move a node (#867).
        renamed = node.rsplit("|", 1)[0] + "|" + new
        self.objects.append(renamed)
        self.shapes[renamed] = self.shapes.pop(node, (renamed + "Shape", "mesh"))
        for table in (self.pivots, self.bboxes, self.sg_members, self.parents,
                      self.history):
            if node in table:
                table[renamed] = table.pop(node)
        self.calls.append(("rename", node, new))
        return renamed

    # --- shading -----------------------------------------------------------
    def listSets(self, object=None, type=None, **kwargs):
        self._require(object)
        return list(self.sg_members.get(object, []))

    def sets(self, *args, **kwargs):
        target = args[0] if args else None
        self._require(target)
        self.calls.append(("sets", target, None))
        if kwargs.get("query"):
            return list(self.set_members.get(target, []))
        # An edit is a forceElement assignment: record it both ways, so a
        # later listSets/sets query reports what this call actually did
        # rather than the constant [] the fake used to answer (#799).
        sg = kwargs.get("forceElement")
        # The SG a forceElement names exists from here on, so a later
        # cmds.sets(sg, query=True) is answerable rather than refused.
        self.dg_nodes.add(sg)
        members = self.set_members.setdefault(sg, [])
        if target not in members:
            members.append(target)
        self.sg_members[target] = [sg]
        return sg

    def listConnections(self, plug, **kwargs):
        self._require(plug)
        return list(self.connections.get(plug, []))


@pytest.fixture(autouse=True)
def _no_checkpoint(monkeypatch):
    from maya_plugin.handlers import session

    monkeypatch.setattr(session, "auto_checkpoint", lambda reason: {"path": "x.ma"})


def _run(fake, **params):
    combine._cmds = lambda: fake  # noqa: SLF001 - the module's only Maya seam
    return combine.combine(params)


class TestCombine:
    def test_merges_two_meshes_into_one(self):
        fake = FakeCmds()
        out = _run(fake, names=["|a", "|b"], name="kit_piece")
        assert out["name"] == "|kit_piece"
        assert ("polyUnite", ("|a", "|b"), True) in [  # history on, deleted after the reparent (#867)
            (c[0], c[1], c[2]) for c in fake.calls if c[0] == "polyUnite"
        ]

    def test_reports_measured_geometry_not_claims(self):
        out = _run(FakeCmds(), names=["|a", "|b"])
        assert out["tris"] == 24
        assert out["shells"] == 2
        assert out["inputs"] == 2

    def test_the_result_may_take_a_consumed_input_s_own_name(self):
        # #803 (the #640 defect): polyUnite CONSUMES its inputs, so an
        # input's name is free by the time the result needs it. combine used
        # to uniquify BEFORE the unite, while Maya still held body, and hand
        # back body_001. Now it asks for body, gets Maya's body1 (measured),
        # and claims body once the inputs are gone.
        fake = FakeCmds(objects=("|body", "|arm"))
        out = _run(fake, names=["|body", "|arm"], name="body")
        assert out["name"] == "|body"
        assert ("rename", "|body1", "body") in fake.calls
        assert out["warnings"] == []
        assert fake.ls("body", long=True) == ["|body"]

    def test_a_name_held_by_an_unrelated_object_gets_the_suffix_and_a_warning(self):
        # The other half of the claim: a name some OTHER object holds is not
        # taken from it. The result gets the deterministic suffix and the
        # caller is told - the same contract boolean_op states for new_name.
        fake = FakeCmds(objects=("|a", "|b", "|body"))
        out = _run(fake, names=["|a", "|b"], name="body")
        assert out["name"] == "|body_001"
        assert fake.ls("body", long=True) == ["|body"]      # untouched
        assert any("body" in w and "body_001" in w for w in out["warnings"])

    def test_re_resolves_when_maya_renames_the_result(self):
        # Maya hands back polySurface7 despite being asked for kit_piece
        fake = FakeCmds(unite_name="polySurface7")
        out = _run(fake, names=["|a", "|b"], name="kit_piece")
        assert out["name"] == "|kit_piece"
        assert ("rename", "|polySurface7", "kit_piece") in fake.calls

    def test_pivot_defaults_to_the_bounding_box_centre(self):
        # Asserted on the WRITE. The box is deliberately off-origin, or
        # "center" would be indistinguishable from "origin" and from no
        # write at all.
        fake = FakeCmds()
        fake.bboxes["|p"] = [1.0, 2.0, 3.0, 3.0, 4.0, 5.0]
        _run(fake, names=["|a", "|b"], name="p")
        assert fake.pivot_writes == [("|p", (2.0, 3.0, 4.0))]

    def test_pivot_origin_places_it_at_the_world_origin(self):
        fake = FakeCmds()
        fake.bboxes["|p"] = [1.0, 2.0, 3.0, 3.0, 4.0, 5.0]
        _run(fake, names=["|a", "|b"], name="p", pivot="origin")
        assert fake.pivot_writes == [("|p", (0.0, 0.0, 0.0))]

    def test_pivot_keep_warns_that_it_kept_the_origin(self):
        """#797 / live probe 2026-09-03 (pid 33088): a FRESH polyUnite result
        has rotatePivot, scalePivot and translate all at (0, 0, 0) regardless
        of `ch`, so there is no prior pivot to keep - `keep` on a combine
        result is `origin` under another name. Not refused: the value is
        legal, and assemble's single-part branch does keep a real pivot."""
        fake = FakeCmds()
        fake.bboxes["|p"] = [1.0, 2.0, 3.0, 3.0, 4.0, 5.0]
        out = _run(fake, names=["|a", "|b"], name="p", pivot="keep")
        assert out["pivot_mode"] == "keep"
        # `keep` writes nothing - it reads the pivot polyUnite gave the node.
        assert fake.pivot_writes == []
        note = [w for w in out["warnings"] if "keep" in w]
        assert note, out["warnings"]
        assert "origin" in note[0]

    def test_the_other_pivot_modes_do_not_carry_the_keep_warning(self):
        for mode in ("center", "origin"):
            fake = FakeCmds()
            fake.bboxes["|p"] = [1.0, 2.0, 3.0, 3.0, 4.0, 5.0]
            out = _run(fake, names=["|a", "|b"], name="p", pivot=mode)
            assert not [w for w in out["warnings"] if "polyUnite gives" in w], mode

    def test_the_reported_pivot_is_where_maya_actually_has_it(self):
        # #803: the report is the QUERY after the freeze, never the value
        # written. Measured, the two coincide (a freeze leaves the pivot in
        # place), which is why the fake's makeIdentity keeps it; the query
        # is what keeps the report honest if that ever changes.
        fake = FakeCmds()
        fake.bboxes["|p"] = [1.0, 2.0, 3.0, 3.0, 4.0, 5.0]
        out = _run(fake, names=["|a", "|b"], name="p")
        assert out["frozen"] is True
        assert out["pivot"] == [2.0, 3.0, 4.0]
        assert out["pivot"] == list(
            fake.xform("|p", query=True, worldSpace=True, rotatePivot=True)
        )
        queries = [i for i, c in enumerate(fake.calls)
                   if c[0] == "xform" and c[2].get("query") and c[2].get("rotatePivot")]
        freezes = [i for i, c in enumerate(fake.calls) if c[0] == "makeIdentity"]
        assert queries and freezes
        assert queries[-1] > freezes[-1], "queried BEFORE the freeze"

    def test_the_reported_pivot_is_honest_when_nothing_freezes_it(self):
        # The same assertion with freeze off: the query-back is not gated on
        # the freeze.
        fake = FakeCmds()
        fake.bboxes["|p"] = [1.0, 2.0, 3.0, 3.0, 4.0, 5.0]
        out = _run(fake, names=["|a", "|b"], name="p", freeze=False)
        assert out["pivot"] == [2.0, 3.0, 4.0]
        assert out["pivot"] == list(
            fake.xform("|p", query=True, worldSpace=True, rotatePivot=True)
        )

    def test_freeze_is_on_by_default(self):
        fake = FakeCmds()
        _run(fake, names=["|a", "|b"], name="p")
        assert fake.frozen

    def test_freeze_can_be_declined(self):
        fake = FakeCmds()
        _run(fake, names=["|a", "|b"], name="p", freeze=False)
        assert not fake.frozen

    def test_collapses_shading_to_one_object_level_group(self):
        fake = FakeCmds()
        out = _run(fake, names=["|a", "|b"], name="p")
        assert "shading" in out

    def test_rejects_fewer_than_two_inputs(self):
        with pytest.raises(HandlerError):
            _run(FakeCmds(), names=["|a"])

    def test_rejects_a_missing_object(self):
        with pytest.raises(HandlerError):
            _run(FakeCmds(), names=["|a", "|nope"])

    def test_rejects_a_non_mesh_input(self):
        fake = FakeCmds(objects=("|a", "|curve1"),
                        shapes={"|a": ("|aShape", "mesh"),
                                "|curve1": ("|curve1Shape", "nurbsCurve")})
        with pytest.raises(HandlerError) as excinfo:
            _run(fake, names=["|a", "|curve1"])
        assert "mesh" in str(excinfo.value).lower()

    def test_rejects_duplicate_names_in_the_input_list(self):
        with pytest.raises(HandlerError):
            _run(FakeCmds(), names=["|a", "|a"])


class TestTheFakeRefusesWhatMayaRefuses:
    """The regression barrier for #799's hardening of THIS fake.

    Round 1 taught the fake to refuse what Maya refuses; a round-2 review
    then measured that reverting every one of those refusals left the suite
    fully green, because no assertion read them. That is the ticket's own
    failure - "a green suite proves nothing" - one level up. Each test below
    pins one contract point, so loosening the fake goes RED here.
    """

    def test_a_query_about_a_node_polyunite_consumed_raises(self):
        fake = FakeCmds(objects=("|a", "|b"))
        fake.polyUnite(["|a", "|b"], ch=False, name="p")
        # polyUnite CONSUMES its inputs: the transform and its shape both
        # stop existing, so neither can go on answering.
        with pytest.raises(RuntimeError):
            fake.nodeType("|a")
        with pytest.raises(RuntimeError):
            fake.nodeType("|aShape")
        with pytest.raises(RuntimeError):
            fake.listRelatives("|b", shapes=True)
        assert fake.nodeType("|p") == "transform"

    def test_a_query_about_a_deleted_node_raises(self):
        fake = FakeCmds(objects=("|a", "|b"))
        fake.delete("|a")
        with pytest.raises(RuntimeError):
            fake.xform("|a", query=True, worldSpace=True, rotatePivot=True)
        with pytest.raises(RuntimeError):
            fake.polyEvaluate("|aShape", triangle=True)

    def test_a_query_about_a_node_that_never_existed_raises(self):
        fake = FakeCmds()
        with pytest.raises(RuntimeError):
            fake.nodeType("|ghost")
        with pytest.raises(RuntimeError):
            fake.exactWorldBoundingBox("|ghost")
        with pytest.raises(RuntimeError):
            fake.listSets(object="|ghost", type=1)

    def test_a_name_freed_by_a_delete_is_live_again_once_recreated(self):
        # The STRICT direction is a defect too: a permanent tombstone would
        # make a node re-created under a previously-deleted name invisible
        # forever, which Maya never does.
        fake = FakeCmds(objects=("|a", "|b"))
        fake.delete("|a")
        fake.objects.append("|a")
        fake.shapes["|a"] = ("|aShape", "mesh")
        assert fake.nodeType("|aShape") == "mesh"

    def test_a_write_to_a_connection_fed_plug_raises_both_ways(self):
        # A compound write when a CHILD is fed...
        fake = FakeCmds()
        fake.connected_plugs["|a.translateX"] = "|a_parentConstraint1"
        with pytest.raises(RuntimeError):
            fake.xform("|a", worldSpace=True, translation=(1.0, 0.0, 0.0))
        # ...and a CHILD write when the compound is fed.
        other = FakeCmds()
        other.connected_plugs["|a.rotate"] = "|a_orientConstraint1"
        with pytest.raises(RuntimeError):
            other.xform("|a", worldSpace=True, rotation=(0.0, 90.0, 0.0))
        assert other._write_blocker("|a.rotateY") == "|a.rotate"

    def test_a_pivot_write_to_a_fed_rotatepivot_raises_both_ways(self):
        fake = FakeCmds()
        fake.connected_plugs["|a.rotatePivotX"] = "pc1"
        with pytest.raises(RuntimeError):
            fake.xform("|a", worldSpace=True, pivots=(1.0, 2.0, 3.0))
        assert fake.pivot_writes == []
        child_fed = FakeCmds()
        child_fed.connected_plugs["|a.rotatePivot"] = "pc1"
        assert child_fed._write_blocker("|a.rotatePivotZ") == "|a.rotatePivot"

    def test_an_unmodelled_polyevaluate_flag_refuses_rather_than_answering_0(self):
        fake = FakeCmds()
        with pytest.raises(AssertionError):
            fake.polyEvaluate("|a", uvcoord=True)

    def test_a_freeze_keeps_the_live_pivot_as_measured(self):
        # #803 MEASURED: makeIdentity leaves the pivot in place. The #799
        # fake threw it away, which pinned a defect combine never had.
        fake = FakeCmds()
        fake.xform("|a", worldSpace=True, pivots=(1.0, 2.0, 3.0))
        fake.makeIdentity("|a", apply=True)
        assert fake.xform("|a", query=True, worldSpace=True,
                          rotatePivot=True) == [1.0, 2.0, 3.0]

    def test_polyunite_names_the_result_while_the_inputs_still_exist(self):
        # #803 MEASURED: polyUnite(name=<an input's name>) -> body1, and the
        # input's name is free afterwards; a free name is honoured directly.
        fake = FakeCmds(objects=("|body", "|arm"))
        assert fake.polyUnite(["|body", "|arm"], ch=False, name="body")[0] == "|body1"
        assert fake.ls("body") == []
        fake = FakeCmds(objects=("|body", "|arm"))
        assert fake.polyUnite(["|body", "|arm"], ch=False, name="fresh")[0] == "|fresh"

    def test_rename_onto_a_held_name_suffixes_as_maya_does(self):
        fake = FakeCmds(objects=("|a", "|b"))
        assert fake.rename("|a", "b") == "|b1"

    def test_a_shading_group_is_a_node_the_fake_answers_about(self):
        # The other direction of the same rule: a shadingEngine is a DG node
        # with no DAG path, and cmds.sets(sg, query=True) is a call Maya
        # ANSWERS. Refusing it would make ensure_object_shading's healthy
        # branch untestable - and force the next person to lie about the
        # scene by putting the SG in cmds.ls output.
        fake = FakeCmds()
        fake.add_shading_group("blinn1SG", ["|aShape"])
        assert fake.sets("blinn1SG", query=True) == ["|aShape"]
        assert fake.listSets(object="|aShape", type=1) == ["blinn1SG"]
        assert "blinn1SG" not in fake.ls()

    def test_the_healthy_single_shader_branch_is_left_alone(self):
        # What the SG modelling buys: unite REPAIRS shading unless it is
        # already exactly one object-level SG. With the fake refusing the
        # query, this branch could not be reached at all.
        fake = FakeCmds()
        fake.add_shading_group("blinn1SG", ["|aShape", "|bShape", "|pShape"])
        out = _run(fake, names=["|a", "|b"], name="p")
        assert out["shading"] == {"sg": "blinn1SG", "repaired": False}
        assert out["warnings"] == []

    def test_two_shading_groups_in_collapse_to_one_and_warn(self):
        fake = FakeCmds()
        fake.add_shading_group("blinn1SG", ["|aShape"])
        fake.add_shading_group("blinn2SG", ["|bShape"])
        out = _run(fake, names=["|a", "|b"], name="p")
        assert out["shading"]["repaired"] is True
        assert any("shading groups" in w for w in out["warnings"])


class TestCombineCarriesTheParent:
    """#867: polyUnite lands its result at the world root, and combine said
    nothing - twelve armour plates under |kethran came back as |armor at the
    root, outside the group that moves the animal, with a plain success.
    boolean_op carries a's parent (modeling._carry_parent); combine now
    carries names[0]'s the same way, BEFORE the freeze so the freeze bakes
    the compensating transform cmds.parent introduces, and says so when the
    inputs sat under several parents."""

    @staticmethod
    def _fake(objects, parents):
        fake = FakeCmds(objects=objects)
        fake.parents.update(parents)
        return fake

    def test_inputs_under_one_group_keep_it(self):
        fake = self._fake(("|grp", "|grp|a", "|grp|b"),
                          {"|grp|a": "|grp", "|grp|b": "|grp"})
        fake.shapes.pop("|grp")  # a group has no shape
        out = _run(fake, names=["|grp|a", "|grp|b"], name="ab")
        assert out["name"] == "|grp|ab"
        assert out["parent"] == "|grp"
        assert ("parent", "|ab", "|grp") in fake.calls
        assert not [w for w in out["warnings"] if "parent" in w]

    def test_the_reparent_comes_before_the_freeze_so_the_freeze_bakes_it(self):
        fake = self._fake(("|grp", "|grp|a", "|grp|b"),
                          {"|grp|a": "|grp", "|grp|b": "|grp"})
        fake.shapes.pop("|grp")
        _run(fake, names=["|grp|a", "|grp|b"], name="ab")
        kinds = [c[0] for c in fake.calls]
        assert kinds.index("parent") < kinds.index("makeIdentity"), kinds
        assert fake.frozen == ["|grp|ab"]

    def test_mixed_parents_carry_the_first_and_say_which(self):
        fake = self._fake(("|grp", "|other", "|grp|a", "|other|b", "|c"),
                          {"|grp|a": "|grp", "|other|b": "|other"})
        fake.shapes.pop("|grp")
        fake.shapes.pop("|other")
        out = _run(fake, names=["|grp|a", "|other|b", "|c"], name="abc")
        assert out["name"] == "|grp|abc"
        assert out["parent"] == "|grp"
        note = [w for w in out["warnings"] if "parent" in w]
        assert len(note) == 1, out["warnings"]
        assert "|grp" in note[0] and "|other" in note[0] and "root" in note[0]

    def test_root_level_inputs_stay_at_the_root_without_a_word(self):
        fake = self._fake(("|a", "|b"), {})
        out = _run(fake, names=["|a", "|b"], name="ab")
        assert out["name"] == "|ab"
        assert out["parent"] is None
        assert not [c for c in fake.calls if c[0] == "parent"]
        assert not [w for w in out["warnings"] if "parent" in w]

    def test_a_first_input_at_the_root_with_grouped_siblings_says_so(self):
        fake = self._fake(("|grp", "|a", "|grp|b"), {"|grp|b": "|grp"})
        fake.shapes.pop("|grp")
        out = _run(fake, names=["|a", "|grp|b"], name="ab")
        assert out["name"] == "|ab" and out["parent"] is None
        note = [w for w in out["warnings"] if "parent" in w]
        assert len(note) == 1 and "|grp" in note[0], out["warnings"]

    def test_a_parent_that_no_longer_exists_is_named_and_the_result_stays_at_the_root(self):
        fake = self._fake(("|a", "|b"), {"|a": "|gone"})
        out = _run(fake, names=["|a", "|b"], name="ab")
        assert out["name"] == "|ab" and out["parent"] is None
        note = [w for w in out["warnings"] if "|gone" in w]
        assert note and "root" in note[0], out["warnings"]

    def test_the_reported_parent_is_read_back_not_assumed(self):
        # cmds.parent answers the new path; the result reports what Maya
        # has, the way the pivot is reported after the freeze (#803).
        fake = self._fake(("|grp", "|grp|a", "|grp|b"),
                          {"|grp|a": "|grp", "|grp|b": "|grp"})
        fake.shapes.pop("|grp")
        out = _run(fake, names=["|grp|a", "|grp|b"], name="ab")
        assert fake.parents["|grp|ab"] == "|grp"
        assert out["parent"] == fake.listRelatives("|grp|ab", parent=True, fullPath=True)[0]

    def test_the_fake_moves_a_node_the_way_maya_does(self):
        fake = self._fake(("|grp", "|a"), {})
        fake.shapes.pop("|grp")
        assert fake.parent("|a", "|grp") == ["|grp|a"]
        assert "|grp|a" in fake.objects and "|a" not in fake.objects
        assert fake.listRelatives("|grp|a", parent=True, fullPath=True) == ["|grp"]
        assert fake.listRelatives("|grp", parent=True, fullPath=True) is None
        with pytest.raises(RuntimeError):
            fake.parent("|a", "|grp")  # already moved: Maya has no |a any more

    def test_a_group_holding_only_the_inputs_survives_to_hold_the_result(self):
        # MEASURED (live gate 2026-09-06): polyUnite without history reaps a
        # parent left with no child along with the inputs, so the group was
        # gone before the result could be put under it. History stays on
        # until the result is under the group; the delete then reaps the
        # emptied inputs and the group survives because it holds the result.
        fake = self._fake(("|grp", "|grp|a", "|grp|b"),
                          {"|grp|a": "|grp", "|grp|b": "|grp"})
        fake.shapes.pop("|grp")
        out = _run(fake, names=["|grp|a", "|grp|b"], name="ab")
        assert "|grp" in fake.objects
        assert out["name"] == "|grp|ab" and out["parent"] == "|grp"
        assert "|grp|a" not in fake.objects and "|grp|b" not in fake.objects
        kinds = [(c[0], c[2]) for c in fake.calls if c[0] in ("polyUnite", "parent", "delete", "rename")]
        assert kinds[0] == ("polyUnite", True)
        assert kinds.index(("parent", "|grp")) < kinds.index(("delete", True))

    def test_the_fake_reaps_a_childless_parent_with_the_history_delete(self):
        fake = self._fake(("|grp", "|grp|a", "|grp|b"),
                          {"|grp|a": "|grp", "|grp|b": "|grp"})
        fake.shapes.pop("|grp")
        node = fake.polyUnite(["|grp|a", "|grp|b"], ch=True, name="ab")[0]
        assert "|grp|a" in fake.objects  # still there, empty, until the delete
        fake.delete(node, constructionHistory=True)
        assert "|grp" not in fake.objects and "|grp|a" not in fake.objects
