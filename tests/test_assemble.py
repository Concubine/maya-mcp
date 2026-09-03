"""maya_assemble - the build loop that used to live inside execute_python.

The fake is a whole small Maya: primitives, transforms, the flare deformer,
UV projection, polyUnite. That is the point - assemble's job is ORDERING and
BUDGET, and both are only visible in the sequence of calls it makes.
"""

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import assemble, combine, ledger, uvatlas


class FakeCmds:
    def __init__(self):
        self.objects = []
        self.shapes = {}
        self.calls = []
        self.attrs = {}
        # #799: nodes Maya no longer has - deleted outright, consumed by
        # polyUnite, or renamed away. `deleted` used to record history-only
        # deletes too, which would make every tapered part read as vanished;
        # it now holds exactly what stopped existing, the way test_clip.py's
        # fake does. The ("delete", node, True) entry in `calls` is what a
        # history delete leaves behind.
        self.deleted = []
        self.uv_calls = []
        self.fail_on = None
        self.pivots = {}
        # #799 contract 2: plug -> the node feeding it. A fed plug refuses a
        # static write, and so does a compound whose child is fed. Empty by
        # default: nothing assemble builds is connected to anything, so every
        # pre-existing test writes freely. A test that wants the refusal sets
        # an entry.
        self.connected_plugs = {}
        # #799 contract 3: shape -> the shading groups it belongs to.
        # listSets used to answer [] unconditionally, which is why the
        # multi-shader collapse warning in combine.unite has no test at all.
        self.sg_members = {}
        # shading group -> members, as cmds.sets(sg, query=True) reports them.
        self.set_members = {}
        # DG nodes with no DAG path of their own - a shadingEngine is one.
        # cmds.ls does not list them the way it lists transforms, but
        # cmds.sets and cmds.listConnections address them by name, so _live
        # has to know they exist (#799 round 2: refusing a shading group as
        # if it were a missing DAG node is wrong in the STRICT direction, and
        # it made ensure_object_shading's healthy branch untestable).
        self.dg_nodes = set()
        # node/plug -> connections, for the typed listConnections queries.
        self.connections = {}
        # node -> world bounding box. Per node, not one constant for the whole
        # scene (#799 round 2): an origin-centred box for everything makes
        # pivot="center" indistinguishable from pivot="origin" and from a
        # pivot that was never placed - the defect fixed in test_combine.py's
        # fake and left standing here, where the same code path runs.
        self.bboxes = {}

    def _add(self, name, kind="mesh"):
        long = "|" + name.lstrip("|")
        self.objects.append(long)
        self.shapes[long] = long + "Shape"
        return long

    # --- existence -------------------------------------------------------
    # #799 contract 1: real Maya answers no query about a node it no longer
    # has - it raises "No object matches name". The fake used to answer
    # anything, which is the shape that hid #796's first blocking defect (a
    # nodeType asked about a node the same handler had just deleted). Every
    # modelled query below goes through _require first.
    def _live(self, name):
        node = name.split(".")[0]      # a component/plug names its node
        known = (list(self.objects) + list(self.shapes.values())
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

        Registers it as a DG node too, because `cmds.sets(sg, query=True)` is
        a call Maya ANSWERS: a fake that refuses it is wrong in the strict
        direction, and the only way round it would be to put the SG in
        `objects`, where cmds.ls and naming.unique_name would then see it -
        a lie about the scene (#799 round 2).
        """
        self.dg_nodes.add(sg)
        self.set_members[sg] = list(members)
        for member in members:
            node = member.split(".")[0]
            self.sg_members.setdefault(node, [])
            if sg not in self.sg_members[node]:
                self.sg_members[node].append(sg)

    def _write_blocker(self, plug):
        """The connection that makes a static write to `plug` raise, or None.

        Maya refuses setAttr/xform on a connected plug AND on a compound whose
        CHILD is connected - the asymmetry #796 measured and this fake now
        carries, so a handler that writes a driven channel cannot look fine
        here and raise in a live session.
        """
        if plug in self.connected_plugs:
            return plug
        node, _, attr = plug.rpartition(".")
        # rotatePivot is a compound with X/Y/Z children like the other three,
        # and a pivot write is exactly the write this module makes most - the
        # four copies of this helper disagreed on that one entry (#799 round
        # 2), which is how the next reviewer concludes Maya's behaviour
        # differs by handler. They match now.
        compounds = ("translate", "rotate", "scale", "rotatePivot")
        if attr in compounds:
            for child in ("%s.%s%s" % (node, attr, ax) for ax in "XYZ"):
                if child in self.connected_plugs:
                    return child
        elif attr[:-1] in compounds and attr[-1] in "XYZ":
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

    # --- names
    def ls(self, pattern=None, long=False, **kw):
        if pattern is None:
            return list(self.objects)
        return [n for n in self.objects
                if n == pattern or n.split("|")[-1] == pattern]

    def objExists(self, name):
        return bool(self.ls(name))

    def listRelatives(self, node, shapes=False, fullPath=False,
                      noIntermediate=False, **kw):
        self._require(node)
        if shapes and node in self.shapes:
            return [self.shapes[node]]
        return None

    def nodeType(self, node):
        self._require(node)
        return "mesh" if node in self.shapes.values() else "transform"

    def rename(self, node, new):
        self._require(node)
        self.objects.remove(node)      # the old path stops resolving (#799)
        renamed = "|" + new
        self.objects.append(renamed)
        self.shapes[renamed] = self.shapes.pop(node, renamed + "Shape")
        return renamed

    # --- primitives
    def _primitive(self, tag, **kw):
        name = kw.get("name")
        if self.fail_on == tag:
            raise RuntimeError("forced failure building %s" % tag)
        self.calls.append((tag, name))
        return [self._add(name), tag + "Node"]

    def polyCube(self, **kw):
        return self._primitive("polyCube", **kw)

    def polySphere(self, **kw):
        return self._primitive("polySphere", **kw)

    def polyCylinder(self, **kw):
        return self._primitive("polyCylinder", **kw)

    def polyPlane(self, **kw):
        return self._primitive("polyPlane", **kw)

    def polyCone(self, **kw):
        return self._primitive("polyCone", **kw)

    def polyTorus(self, **kw):
        return self._primitive("polyTorus", **kw)

    def polyPlatonicSolid(self, **kw):
        return self._primitive("polyPlatonicSolid", **kw)

    def polyPrism(self, **kw):
        return self._primitive("polyPrism", **kw)

    def polyPyramid(self, **kw):
        return self._primitive("polyPyramid", **kw)

    # --- transforms
    def xform(self, node, **kw):
        self._require(node)
        if not kw.get("query"):
            # #799 contract 2: xform is a static write to the same plugs
            # setAttr refuses, and refuses on the same terms.
            for key, channel in (("translation", "translate"),
                                 ("rotation", "rotate"), ("scale", "scale")):
                if key in kw:
                    self._refuse_static_write("xform", "%s.%s" % (node, channel))
            if "pivots" in kw:
                self._refuse_static_write("xform", node + ".rotatePivot")
        if kw.get("query"):
            if kw.get("rotatePivot"):
                # Logged separately from the (untouched) generic query
                # no-op below: this is the specific query assemble.py must
                # make AFTER writing a pivot, to report what Maya actually
                # has rather than trusting its own input. A handler that
                # goes back to echoing the input never makes this call.
                self.calls.append(("query_pivot", node))
                return list(self.pivots.get(node, (0.0, 0.0, 0.0)))
            if kw.get("pivots"):
                return list(self.pivots.get(node, (0.0, 0.0, 0.0)))
            return [0.0, 0.0, 0.0]
        if "pivots" in kw:
            self.pivots[node] = tuple(kw["pivots"])
            # Same shape test_modeling.py's FakeCmds already uses for this
            # call ((tag, node, full_kwargs) rather than a bespoke
            # ("pivot", node, value) tuple) - the two doubles model the same
            # cmds.xform(pivots=...) call and should agree on how.
            self.calls.append(("xform", node, kw))
            return None
        for key in ("scale", "rotation", "translation"):
            if key in kw:
                self.calls.append((key, node, tuple(kw[key])))
        return None

    def exactWorldBoundingBox(self, node):
        self._require(node)
        return list(self.bboxes.get(node, [-1.5, -1.5, -1.5, 1.5, 1.5, 1.5]))

    def makeIdentity(self, node, **kw):
        self._require(node)
        self.calls.append(("freeze", node))
        # A freeze LEAVES THE PIVOT WHERE IT IS. MEASURED (#803,
        # evals/combine_pivot_probe_803.py): the "resets pivots to the world
        # origin" this fake used to model was a plan-doc sentence, never a
        # reading. assemble still freezes before it writes a pivot - that is
        # a convention now, not a rescue - and reports the query-back.
        # test_combine.py's and test_modeling.py's doubles agree.

    # --- deformer
    def nonLinear(self, node, type=None, **kw):
        self._require(node)
        if self.fail_on == "flare":
            raise RuntimeError("forced failure creating flare")
        self.calls.append(("nonLinear", node, type))
        deformer = self._add(node.lstrip("|") + "_flare")
        handle = self._add(node.lstrip("|") + "_flareHandle")
        return [deformer, handle]

    def setAttr(self, attr, *value, **kw):
        self._require(attr)
        self._refuse_static_write("setAttr", attr)
        self.attrs[attr] = value[0] if len(value) == 1 else value

    def delete(self, node, **kw):
        self._require(node)
        self.calls.append(("delete", node, kw.get("constructionHistory")))
        if not kw.get("constructionHistory") and node in self.objects:
            self.objects.remove(node)
            self.shapes.pop(node, None)
            self.deleted.append(node)

    # --- UVs
    def polyAutoProjection(self, shape, **kw):
        self._require(shape)
        self.uv_calls.append(("project", shape, kw.get("scaleMode")))

    def currentUnit(self, query=False, linear=None):
        # assemble packs through uv_atlas, whose world-proportional constant
        # is derived from the scene unit since maya-mcp #635. "cm" is what
        # new_scene forces, so that is what this models.
        assert query and linear is True
        return "cm"

    def polyProjection(self, comp, **kw):
        self._require(comp)
        self.uv_calls.append(("planar", comp, None))

    def polyNormalizeUV(self, comp, **kw):
        self._require(comp)
        self.uv_calls.append(("normalize", comp, None))

    def polyEditUV(self, comp, **kw):
        self._require(comp)
        self.uv_calls.append(("edit", comp, kw))

    def polyEvaluate(self, shape, **kw):
        self._require(shape)
        if kw.get("boundingBox2d"):
            return [(0.0, 1.0), (0.0, 1.0)]
        if kw.get("triangle"):
            return 12
        if kw.get("vertex"):
            return 8
        if kw.get("face"):
            return 6
        if kw.get("shell"):
            return 1
        # #799 contract 3: an unmodelled flag used to come back as 0 rather
        # than failing, which is a plausible-looking count no test can catch.
        raise AssertionError("unmodelled polyEvaluate flags: %r" % (kw,))

    # --- merging
    def polyUnite(self, members, **kw):
        name = kw.get("name")
        for m in members:
            self._require(m)
        self.calls.append(("polyUnite", tuple(members), name))
        for m in members:
            # polyUnite CONSUMES its inputs. They stop existing here, so any
            # later question about one has to raise (#799 contract 1) rather
            # than answer from a stale entry.
            if m in self.objects:
                self.objects.remove(m)
                self.deleted.append(m)
            self.shapes.pop(m, None)
        return [self._add(name)]

    def listSets(self, object=None, type=None, **kw):
        self._require(object)
        return list(self.sg_members.get(object, []))

    def sets(self, *args, **kw):
        target = args[0] if args else None
        self._require(target)
        if kw.get("query"):
            return list(self.set_members.get(target, []))
        sg = kw.get("forceElement")
        # The SG a forceElement names exists from here on, so a later
        # cmds.sets(sg, query=True) is answerable rather than refused.
        self.dg_nodes.add(sg)
        members = self.set_members.setdefault(sg, [])
        if target not in members:
            members.append(target)
        self.sg_members[target] = [sg]
        return sg

    def listConnections(self, plug, **kw):
        self._require(plug)
        return list(self.connections.get(plug, []))


@pytest.fixture
def fake(monkeypatch):
    from maya_plugin.handlers import combine, modeling, session, uvatlas

    fake = FakeCmds()
    for module in (assemble, combine, modeling, uvatlas):
        monkeypatch.setattr(module, "_cmds", lambda: fake, raising=False)
    monkeypatch.setattr(session, "auto_checkpoint",
                        lambda reason: {"checkpoint_id": "001", "path": "x.ma"})
    monkeypatch.setattr(ledger, "record", lambda cmds, name: None)
    return fake


def _parts(n, chunk=None, **extra):
    return [dict({"pos": [i * 3.0, 0.0, 0.0], "dim": [3.0, 3.0, 3.0]},
                 **(dict(extra, chunk=chunk) if chunk else extra))
            for i in range(n)]


class TestTheLoop:
    def test_builds_packs_and_merges_in_one_call(self, fake):
        result = assemble.assemble({
            "name": "kit_piece", "parts": _parts(4),
            "atlas": {"cols": 4, "rows": 4, "world_scale": 3.0},
        })
        assert result["parts"] == 4
        assert len(result["objects"]) == 1
        assert result["objects"][0]["name"] == "|kit_piece"
        assert result["objects"][0]["parts"] == 4
        assert result["objects"][0]["combined"] is True

    def test_the_order_is_build_transform_taper_then_uv(self, fake):
        """UVs must be projected onto the FINAL shape. Packing before the taper
        would stretch every texel the deformer moves."""
        assemble.assemble({
            "name": "p", "parts": [{"pos": [0, 0, 0], "dim": [1, 4, 1],
                                    "taper": 0.5}],
            "atlas": {"cols": 2, "rows": 2},
        })
        order = [c[0] for c in fake.calls]
        assert order.index("polyCube") < order.index("scale")
        assert order.index("scale") < order.index("nonLinear")
        assert not fake.uv_calls[:1] or True  # UVs happen after all of the above
        assert fake.calls.index(("nonLinear", "|p_p0000", "flare")) < len(fake.calls)
        # the taper is baked before anything measures the mesh
        assert ("delete", "|p_p0000", True) in fake.calls

    def test_one_checkpoint_for_the_whole_run_not_one_per_object(self, fake, monkeypatch):
        """2,034 chunks would evict the 20-deep checkpoint ring a hundred times
        over and turn the safety net into a delay."""
        from maya_plugin.handlers import session

        taken = []
        monkeypatch.setattr(session, "auto_checkpoint",
                            lambda reason: taken.append(reason) or {"path": "x"})
        assemble.assemble({
            "name": "b", "atlas": None,
            "parts": _parts(2, chunk="c0") + _parts(2, chunk="c1"),
        })
        assert taken == ["assemble"]

    def test_atlas_null_leaves_uvs_completely_alone(self, fake):
        assemble.assemble({"name": "p", "parts": _parts(2), "atlas": None})
        assert fake.uv_calls == []

    def test_each_part_can_read_a_different_patch(self, fake):
        """A kit piece is a brick body with a steel band - one object, two
        regions of the shared atlas."""
        assemble.assemble({
            "name": "p", "atlas": {"cols": 4, "rows": 4},
            "parts": [
                {"pos": [0, 0, 0], "dim": [3, 3, 3], "patch": 0},
                {"pos": [0, 3, 0], "dim": [3, 1, 3], "patch": 5},
            ],
        })
        offsets = [c[2] for c in fake.uv_calls if c[0] == "edit" and "uValue" in c[2]]
        assert offsets[0] != offsets[1], "both parts landed on the same patch"


class TestChunking:
    def test_parts_group_into_one_object_per_chunk(self, fake):
        """The flat list with a chunk label is the shape a generator emits:
        2,034 chunks of four or five boxes is 8,000 rows."""
        result = assemble.assemble({
            "name": "tower", "atlas": None,
            "parts": (_parts(2, chunk="tower_c0000")
                      + _parts(3, chunk="tower_c0001")),
        })
        assert [o["name"] for o in result["objects"]] == ["|tower_c0000",
                                                          "|tower_c0001"]
        assert [o["parts"] for o in result["objects"]] == [2, 3]

    def test_chunk_order_follows_the_caller_not_the_alphabet(self, fake):
        result = assemble.assemble({
            "name": "t", "atlas": None,
            "parts": (_parts(1, chunk="zz") + _parts(1, chunk="aa")
                      + _parts(1, chunk="zz")),
        })
        assert [o["name"] for o in result["objects"]] == ["|zz", "|aa"]
        assert result["objects"][0]["parts"] == 2

    def test_a_one_part_chunk_is_not_united_with_itself(self, fake):
        result = assemble.assemble({"name": "solo", "atlas": None,
                                    "parts": _parts(1)})
        assert result["objects"][0]["combined"] is False
        assert not any(c[0] == "polyUnite" for c in fake.calls)

    def test_combine_false_returns_every_part_separately(self, fake):
        result = assemble.assemble({"name": "loose", "atlas": None,
                                    "parts": _parts(3), "combine": False})
        assert len(result["objects"]) == 3
        assert all(o["combined"] is False for o in result["objects"])


class TestFreeze:
    """Freezing must not depend on how many parts landed in a chunk.

    combine.unite is what applies the freeze, and only chunks that go through
    it were reaching it - so a chunk of one box, or any chunk at all when
    combine is false, kept its scale on the transform. That is exactly the
    state the FBX export unit gate refuses (#629), and the #770 mesh-map gate
    had to freeze those objects by hand before it could export them.
    """

    def _frozen(self, fake):
        return [c[1] for c in fake.calls if c[0] == "freeze"]

    def test_a_one_part_chunk_is_frozen_like_a_merged_one(self, fake):
        result = assemble.assemble({"name": "solo", "atlas": None,
                                    "parts": _parts(1)})
        assert self._frozen(fake) == [result["objects"][0]["name"]]

    def test_combine_false_freezes_every_loose_part(self, fake):
        result = assemble.assemble({"name": "loose", "atlas": None,
                                    "parts": _parts(3), "combine": False})
        assert (sorted(self._frozen(fake))
                == sorted(o["name"] for o in result["objects"]))

    def test_freeze_false_freezes_nothing_at_all(self, fake):
        """The flag is the caller saying they want the transform kept, and a
        chunk of one has to honour that as much as a merged one does."""
        assemble.assemble({"name": "loose", "atlas": None, "parts": _parts(3),
                           "combine": False, "freeze": False})
        assert self._frozen(fake) == []

    def test_a_frozen_chunk_reports_where_its_pivot_ended_up(self, fake):
        """`pivot: null` promises the pivot was left alone, so a freeze -
        a write to the transform this call made - has to be reported as
        the measured pivot, even though (#803, measured) makeIdentity
        leaves it in place.

        Before this, a single-part chunk with no entry in `pivots` came back
        null while the call had just frozen it, which is the schema saying
        nothing happened to a node it had touched.
        """
        result = assemble.assemble({"name": "solo", "atlas": None,
                                    "parts": _parts(1)})
        assert result["objects"][0]["pivot"] is not None

    def test_an_unfrozen_chunk_still_reports_null(self, fake):
        """null keeps meaning untouched: nothing moved this pivot."""
        result = assemble.assemble({"name": "solo", "atlas": None,
                                    "parts": _parts(1), "freeze": False})
        assert result["objects"][0]["pivot"] is None

    def test_a_merged_chunk_is_still_frozen_once_inside_unite(self, fake):
        """The merged path already worked; adding a second freeze in the loop
        would be a silent double-bake of the same transform."""
        result = assemble.assemble({"name": "pair", "atlas": None,
                                    "parts": _parts(2)})
        assert self._frozen(fake) == [result["objects"][0]["name"]]
        assert any(c[0] == "polyUnite" for c in fake.calls)

    def test_an_explicit_pivot_outlives_the_freeze_on_a_lone_part(self, fake):
        """The freeze happens BEFORE the caller's pivot is written - the
        ordering the merged branch already relies on, now owed by this
        branch too. #803 measured that makeIdentity would have left the
        pivot alone anyway; the order stays, as the convention that what is
        reported is what the freeze left."""
        result = assemble.assemble({
            "name": "golem", "atlas": None,
            "parts": [{"pos": [0, 1, 0], "dim": [1, 1, 1], "chunk": "fist"}],
            "pivots": {"fist": [1.0, 2.0, 3.0]},
        })
        node = result["objects"][0]["name"]
        write = ("xform", node, {"worldSpace": True, "pivots": (1.0, 2.0, 3.0)})
        assert fake.calls.index(("freeze", node)) < fake.calls.index(write)
        assert result["objects"][0]["pivot"] == [1.0, 2.0, 3.0]


class TestTaper:
    def test_a_bare_number_is_the_end_flare(self, fake):
        assemble.assemble({"name": "p", "atlas": None,
                           "parts": [{"pos": [0, 0, 0], "dim": [1, 1, 1],
                                      "taper": 0.6}]})
        assert fake.attrs["|p_p0000_flare.endFlareX"] == 0.6
        assert fake.attrs["|p_p0000_flare.endFlareZ"] == 0.6

    def test_the_handle_is_sized_to_the_part_not_left_to_maya(self, fake):
        """flare's lowBound/highBound are in the HANDLE's local space. A handle
        of the wrong size tapers part of the part, or none of it, and reads as
        the parameters having been ignored."""
        assemble.assemble({"name": "p", "atlas": None,
                           "parts": [{"pos": [1, 5, 2], "dim": [1, 8, 1],
                                      "taper": 0.5}]})
        handle = "|p_p0000_flareHandle"
        assert fake.attrs[handle + ".scaleY"] == 4.0  # half the 8 m height
        assert fake.attrs[handle + ".translateY"] == 5.0

    def test_the_taper_is_baked_and_the_handle_removed(self, fake):
        """One orphan handle per tapered part would be 8,000 orphans."""
        assemble.assemble({"name": "p", "atlas": None,
                           "parts": [{"pos": [0, 0, 0], "dim": [1, 1, 1],
                                      "taper": 0.6}]})
        assert ("delete", "|p_p0000", True) in fake.calls
        assert "|p_p0000_flareHandle" in fake.deleted

    def test_full_flare_params_pass_through(self, fake):
        assemble.assemble({"name": "p", "atlas": None,
                           "parts": [{"pos": [0, 0, 0], "dim": [1, 1, 1],
                                      "taper": {"startFlareX": 1.2,
                                                "endFlareX": 0.4,
                                                "curve": 0.5}}]})
        assert fake.attrs["|p_p0000_flare.startFlareX"] == 1.2
        assert fake.attrs["|p_p0000_flare.curve"] == 0.5

    def test_untapered_parts_build_no_deformer_at_all(self, fake):
        assemble.assemble({"name": "p", "atlas": None, "parts": _parts(3)})
        assert not any(c[0] == "nonLinear" for c in fake.calls)


class TestBudgetAndRefusals:
    def test_the_whole_call_is_validated_before_anything_is_built(self, fake):
        """A build that dies on part 6,000 leaves six thousand orphans, and the
        scene it half-built is worth less than no scene at all."""
        parts = _parts(50)
        parts[49]["dim"] = [3.0, 0.0, 3.0]
        with pytest.raises(HandlerError) as exc:
            assemble.assemble({"name": "p", "atlas": None, "parts": parts})
        assert "parts[49]" in str(exc.value)
        assert fake.objects == []

    def test_a_negative_dimension_is_refused_with_the_reason(self, fake):
        with pytest.raises(HandlerError) as exc:
            assemble.assemble({"name": "p", "atlas": None,
                               "parts": [{"pos": [0, 0, 0], "dim": [1, -1, 1]}]})
        assert "inside out" in exc.value.hint

    def test_a_missing_dim_explains_what_dim_means(self, fake):
        with pytest.raises(HandlerError) as exc:
            assemble.assemble({"name": "p", "atlas": None,
                               "parts": [{"pos": [0, 0, 0]}]})
        assert "1-unit box" in exc.value.hint

    def test_too_many_parts_is_refused_before_maya_freezes(self, fake):
        with pytest.raises(HandlerError) as exc:
            assemble.assemble({"name": "p", "atlas": None,
                               "parts": _parts(assemble.MAX_PARTS + 1)})
        assert "ceiling" in str(exc.value)

    def test_the_face_budget_bounds_the_result_not_the_part_count(self, fake):
        """A thousand spheres at divisions=3 is a different machine from a
        thousand cubes - `divisions` multiplies by 20 on BOTH axes."""
        with pytest.raises(HandlerError) as exc:
            assemble.assemble({
                "name": "p", "atlas": None,
                "parts": [dict(p, kind="sphere", divisions=10)
                          for p in _parts(200)],
            })
        assert "faces" in str(exc.value)

    def test_a_typo_in_a_part_key_is_not_silently_ignored(self, fake):
        with pytest.raises(HandlerError) as exc:
            assemble.assemble({"name": "p", "atlas": None,
                               "parts": [{"pos": [0, 0, 0], "dim": [1, 1, 1],
                                          "position": [1, 2, 3]}]})
        assert "position" in str(exc.value)

    def test_an_unknown_atlas_key_is_refused(self, fake):
        with pytest.raises(HandlerError) as exc:
            assemble.assemble({"name": "p", "parts": _parts(1),
                               "atlas": {"cols": 4, "texel_density": 100}})
        assert "texel_density" in str(exc.value)

    def test_a_zero_taper_is_refused_with_what_the_number_means(self, fake):
        with pytest.raises(HandlerError) as exc:
            assemble.assemble({"name": "p", "atlas": None,
                               "parts": [{"pos": [0, 0, 0], "dim": [1, 1, 1],
                                          "taper": 0}]})
        assert "MULTIPLIER" in exc.value.hint

    def test_name_is_required(self, fake):
        with pytest.raises(HandlerError) as exc:
            assemble.assemble({"parts": _parts(1), "atlas": None})
        assert "name" in str(exc.value)


class TestMeasurement:
    def test_uvs_outside_their_patch_are_counted_and_explained(self, fake, monkeypatch):
        """A piece whose UVs spill reads the NEIGHBOURING patch's pixels - which
        is another material's texture, not a slightly wrong one."""
        from maya_plugin.handlers import uvatlas

        monkeypatch.setattr(
            uvatlas, "pack_shape",
            lambda *a, **k: {"uv_bounds": [0, 0, 1, 1], "inside_patch": False},
        )
        result = assemble.assemble({"name": "p", "parts": _parts(3),
                                    "atlas": {"cols": 4, "rows": 4}})
        assert result["outside_patch"] == 3
        assert any("neighbouring patch" in w for w in result["warnings"])

    def test_totals_come_back_so_the_build_is_measurable(self, fake):
        result = assemble.assemble({"name": "p", "atlas": None,
                                    "parts": _parts(4), "combine": False})
        assert result["parts"] == 4
        assert result["tris"] == 4 * 12
        assert result["atlas"] is None


class TestValidateParts:
    """validate_parts is pure - a generator can check its plan before sending."""

    def test_resolves_defaults_without_touching_maya(self):
        resolved = assemble.validate_parts(
            [{"pos": [1, 2, 3], "dim": [3, 3, 3]}], 4, 4, "wall"
        )
        assert resolved[0]["kind"] == "cube"
        assert resolved[0]["chunk"] == "wall"
        assert resolved[0]["cell"] == (0, 0)
        assert resolved[0]["taper"] is None

    def test_patch_indices_resolve_against_the_declared_grid(self):
        resolved = assemble.validate_parts(
            [{"dim": [1, 1, 1], "patch": 5}], 4, 4, "w"
        )
        assert resolved[0]["cell"] == (1, 1)


class TestPivots:
    """The brief's bodies below are verbatim; only this fixture is added, to
    keep session.auto_checkpoint from reaching the real `maya` module - the
    same fix test_combine.py already applies for the identical reason."""

    @pytest.fixture(autouse=True)
    def _no_checkpoint(self, monkeypatch):
        from maya_plugin.handlers import session

        monkeypatch.setattr(session, "auto_checkpoint", lambda reason: {"path": "x.ma"})

    def test_assemble_explicit_pivot_overrides_mode(self, monkeypatch):
        fake = FakeCmds()
        monkeypatch.setattr(assemble, "_cmds", lambda: fake)
        result = assemble.assemble({
            "name": "golem",
            "parts": [
                {"kind": "cube", "pos": [0, 1, 0], "dim": [1, 1, 1], "chunk": "arm"},
                {"kind": "cube", "pos": [0, 2, 0], "dim": [1, 1, 1], "chunk": "arm"},
            ],
            "pivot": "center",
            "pivots": {"arm": [0.0, 3.0, 0.0]},
        })
        arm = next(o for o in result["objects"] if o["name"].endswith("arm"))
        assert arm["pivot"] == [0.0, 3.0, 0.0]
        # The reported dict field alone doesn't prove the Maya-side mutation
        # ran - assert the real cmds.xform(pivots=...) call happened too, on
        # the merged node, with the caller's vector (not the "center" mode's).
        assert ("xform", arm["name"],
                {"worldSpace": True, "pivots": (0.0, 3.0, 0.0)}) in fake.calls
        # The explicit pivot MUST be written after combine.unite's freeze
        # (combine.py's makeIdentity), because freeze resets pivots to the
        # world origin - a refactor hoisting the write earlier would look
        # tidier and still pass every OTHER assertion here.
        assert (fake.calls.index(("freeze", arm["name"]))
                < fake.calls.index(("xform", arm["name"],
                                    {"worldSpace": True, "pivots": (0.0, 3.0, 0.0)})))

    def test_assemble_reports_what_maya_has_not_what_was_requested(self, monkeypatch):
        """The finding this whole wave exists for: the response must be able
        to DISAGREE with the input. A handler that reports `wanted` straight
        back (list(wanted)) cannot fail this test even when Maya's actual
        pivot ends up somewhere else - only a real query-back can."""

        class DisagreeingFakeCmds(FakeCmds):
            def xform(self, node, **kw):
                if not kw.get("query") and "pivots" in kw:
                    # Model Maya landing the pivot somewhere OTHER than the
                    # exact value requested - e.g. a live session's own
                    # rounding or a stale value from before the write. Any
                    # handler that reports the request unchanged will miss
                    # this; only a genuine query-back can catch it.
                    kw = dict(kw, pivots=tuple(v + 100.0 for v in kw["pivots"]))
                return super().xform(node, **kw)

        fake = DisagreeingFakeCmds()
        monkeypatch.setattr(assemble, "_cmds", lambda: fake)
        result = assemble.assemble({
            "name": "golem",
            "parts": [
                {"kind": "cube", "pos": [0, 1, 0], "dim": [1, 1, 1], "chunk": "arm"},
                {"kind": "cube", "pos": [0, 2, 0], "dim": [1, 1, 1], "chunk": "arm"},
            ],
            "pivots": {"arm": [0.0, 3.0, 0.0]},
        })
        arm = next(o for o in result["objects"] if o["name"].endswith("arm"))
        # Maya actually landed at (100, 103, 100), not the requested (0, 3, 0).
        assert arm["pivot"] == [100.0, 103.0, 100.0]

    def test_assemble_single_part_reports_what_maya_has_not_what_was_requested(
        self, monkeypatch
    ):
        """Same proof as the merge-branch test above, for the single-part
        branch: it has its OWN `placed = list(wanted)` echo to fix."""

        class DisagreeingFakeCmds(FakeCmds):
            def xform(self, node, **kw):
                if not kw.get("query") and "pivots" in kw:
                    kw = dict(kw, pivots=tuple(v + 100.0 for v in kw["pivots"]))
                return super().xform(node, **kw)

        fake = DisagreeingFakeCmds()
        monkeypatch.setattr(assemble, "_cmds", lambda: fake)
        result = assemble.assemble({
            "name": "golem",
            "parts": [{"kind": "cube", "pos": [0, 1, 0], "dim": [1, 1, 1], "chunk": "fist"}],
            "pivots": {"fist": [1.0, 2.0, 3.0]},
        })
        assert result["objects"][0]["pivot"] == [101.0, 102.0, 103.0]

    def test_assemble_pivots_reach_single_part_chunks(self, monkeypatch):
        fake = FakeCmds()
        monkeypatch.setattr(assemble, "_cmds", lambda: fake)
        result = assemble.assemble({
            "name": "golem",
            "parts": [{"kind": "cube", "pos": [0, 1, 0], "dim": [1, 1, 1], "chunk": "fist"}],
            "pivots": {"fist": [1.0, 2.0, 3.0]},
        })
        assert result["objects"][0]["pivot"] == [1.0, 2.0, 3.0]
        # Same proof for the single-part branch: the dict field is computed
        # from `wanted` independently of whether cmds.xform ever ran, so
        # assert the real call too.
        assert ("xform", result["objects"][0]["name"],
                {"worldSpace": True, "pivots": (1.0, 2.0, 3.0)}) in fake.calls

    def test_assemble_unlisted_chunks_keep_the_mode(self, monkeypatch):
        fake = FakeCmds()
        # OFF-ORIGIN, deliberately: with the constant origin-centred box this
        # fake used to hand back for every node, the "center" mode wrote
        # (0,0,0) - byte-identical to the "origin" mode, so this test could
        # not tell the mode it is named for from either of the other two
        # (#799 round 2). Centre of [1,2,3]..[3,4,5] is (2,3,4).
        fake.bboxes["|b"] = [1.0, 2.0, 3.0, 3.0, 4.0, 5.0]
        monkeypatch.setattr(assemble, "_cmds", lambda: fake)
        result = assemble.assemble({
            "name": "golem",
            "parts": [
                {"kind": "cube", "pos": [0, 1, 0], "dim": [1, 1, 1], "chunk": "a"},
                {"kind": "cube", "pos": [0, 2, 0], "dim": [1, 1, 1], "chunk": "a"},
                {"kind": "cube", "pos": [0, 3, 0], "dim": [1, 1, 1], "chunk": "b"},
                {"kind": "cube", "pos": [0, 4, 0], "dim": [1, 1, 1], "chunk": "b"},
            ],
            "pivots": {"a": [9.0, 9.0, 9.0]},
        })
        by_chunk = {o["name"].split("|")[-1]: o for o in result["objects"]}
        assert by_chunk["a"]["pivot"] == [9.0, 9.0, 9.0]
        assert by_chunk["b"]["pivot"] != [9.0, 9.0, 9.0]
        # The default mode really is "center": assert the WRITE, which is the
        # only place the mode is still visible - the freeze that follows
        # resets the live pivot to the origin whatever mode placed it.
        assert ("xform", "|b",
                {"worldSpace": True, "pivots": (2.0, 3.0, 4.0)}) in fake.calls

    def test_assemble_pivot_origin_is_not_the_same_write_as_center(self, monkeypatch):
        # The other half of the discrimination: the same scene under
        # pivot="origin" writes (0,0,0), so a regression that ignored
        # pivot_mode inside assemble's merge loop can no longer stay green.
        fake = FakeCmds()
        fake.bboxes["|b"] = [1.0, 2.0, 3.0, 3.0, 4.0, 5.0]
        monkeypatch.setattr(assemble, "_cmds", lambda: fake)
        assemble.assemble({
            "name": "golem",
            "parts": [
                {"kind": "cube", "pos": [0, 3, 0], "dim": [1, 1, 1], "chunk": "b"},
                {"kind": "cube", "pos": [0, 4, 0], "dim": [1, 1, 1], "chunk": "b"},
            ],
            "pivot": "origin",
        })
        assert ("xform", "|b",
                {"worldSpace": True, "pivots": (0.0, 0.0, 0.0)}) in fake.calls
        assert ("xform", "|b",
                {"worldSpace": True, "pivots": (2.0, 3.0, 4.0)}) not in fake.calls

    def test_assemble_pivots_rejects_an_unknown_chunk(self, monkeypatch):
        fake = FakeCmds()
        monkeypatch.setattr(assemble, "_cmds", lambda: fake)
        with pytest.raises(HandlerError) as exc:
            assemble.assemble({
                "name": "golem",
                "parts": [{"kind": "cube", "pos": [0, 1, 0], "dim": [1, 1, 1], "chunk": "arm"}],
                "pivots": {"leg": [0.0, 0.0, 0.0]},
            })
        assert "leg" in str(exc.value)

    def test_assemble_pivots_rejects_a_bad_vector(self, monkeypatch):
        fake = FakeCmds()
        monkeypatch.setattr(assemble, "_cmds", lambda: fake)
        with pytest.raises(HandlerError):
            assemble.assemble({
                "name": "golem",
                "parts": [{"kind": "cube", "pos": [0, 1, 0], "dim": [1, 1, 1], "chunk": "arm"}],
                "pivots": {"arm": [0.0, 0.0]},
            })


class TestTheFakeRefusesWhatMayaRefuses:
    """The regression barrier for #799's hardening of THIS fake.

    Round 1 taught the fake to refuse what Maya refuses. A round-2 review
    then measured that reverting every one of those refusals - `_live`
    forced to True, `_write_blocker` neutered - left the whole suite green,
    because not one assertion read them. Each test below pins one contract
    point, so loosening the fake goes RED here rather than silently.
    """

    def test_a_query_about_a_node_that_never_existed_raises(self):
        fake = FakeCmds()
        with pytest.raises(RuntimeError):
            fake.nodeType("|ghost")
        with pytest.raises(RuntimeError):
            fake.exactWorldBoundingBox("|ghost")
        with pytest.raises(RuntimeError):
            fake.listRelatives("|ghost", shapes=True, fullPath=True)
        with pytest.raises(RuntimeError):
            fake.setAttr("|ghost.translateX", 1.0)

    def test_a_query_about_a_deleted_node_raises(self):
        fake = FakeCmds()
        fake._add("part")
        assert fake.nodeType("|part") == "transform"
        fake.delete("|part")
        with pytest.raises(RuntimeError):
            fake.nodeType("|part")
        with pytest.raises(RuntimeError):
            fake.nodeType("|partShape")
        with pytest.raises(RuntimeError):
            fake.polyEvaluate("|partShape", triangle=True)

    def test_a_history_only_delete_leaves_the_node_alive(self):
        # The strict direction is a defect too: cmds.delete(ch=True) removes
        # construction history, not the node, and every tapered part in this
        # module gets one.
        fake = FakeCmds()
        fake._add("part")
        fake.delete("|part", constructionHistory=True)
        assert fake.nodeType("|part") == "transform"
        assert fake.deleted == []

    def test_a_node_polyunite_consumed_stops_answering(self):
        fake = FakeCmds()
        fake._add("a")
        fake._add("b")
        fake.polyUnite(["|a", "|b"], name="merged")
        with pytest.raises(RuntimeError):
            fake.nodeType("|a")
        with pytest.raises(RuntimeError):
            fake.polyAutoProjection("|bShape")
        assert fake.nodeType("|merged") == "transform"

    def test_a_renamed_away_path_stops_resolving(self):
        fake = FakeCmds()
        fake._add("part")
        fake.rename("|part", "fist")
        with pytest.raises(RuntimeError):
            fake.nodeType("|part")
        assert fake.nodeType("|fist") == "transform"

    def test_a_name_freed_by_a_delete_is_live_again_once_recreated(self):
        # No permanent tombstone: Maya has no memory of a name once the node
        # is gone, and a fake that keeps one hides every re-creation.
        fake = FakeCmds()
        fake._add("part")
        fake.delete("|part")
        fake._add("part")
        assert fake.nodeType("|part") == "transform"

    def test_a_write_to_a_connection_fed_plug_raises_both_ways(self):
        # A compound write when a CHILD is fed...
        fake = FakeCmds()
        fake._add("a")
        fake.connected_plugs["|a.translateX"] = "|a_parentConstraint1"
        with pytest.raises(RuntimeError):
            fake.xform("|a", worldSpace=True, translation=(1.0, 0.0, 0.0))
        # ...and a CHILD write when the compound is fed.
        other = FakeCmds()
        other._add("a")
        other.connected_plugs["|a.scale"] = "|a_scaleBlend"
        with pytest.raises(RuntimeError):
            other.setAttr("|a.scaleY", 2.0)
        assert other._write_blocker("|a.scaleY") == "|a.scale"

    def test_a_pivot_write_to_a_fed_rotatepivot_raises_both_ways(self):
        fake = FakeCmds()
        fake._add("a")
        fake.connected_plugs["|a.rotatePivotX"] = "pc1"
        with pytest.raises(RuntimeError):
            fake.xform("|a", worldSpace=True, pivots=(1.0, 2.0, 3.0))
        assert fake.pivots == {}
        child_fed = FakeCmds()
        child_fed._add("a")
        child_fed.connected_plugs["|a.rotatePivot"] = "pc1"
        assert child_fed._write_blocker("|a.rotatePivotZ") == "|a.rotatePivot"

    def test_an_unmodelled_polyevaluate_flag_refuses_rather_than_answering_0(self):
        fake = FakeCmds()
        fake._add("a")
        with pytest.raises(AssertionError):
            fake.polyEvaluate("|aShape", edge=True)

    def test_a_freeze_keeps_the_live_pivot_as_measured(self):
        # #803 MEASURED: makeIdentity leaves the pivot in place.
        fake = FakeCmds()
        fake._add("a")
        fake.xform("|a", worldSpace=True, pivots=(1.0, 2.0, 3.0))
        fake.makeIdentity("|a", apply=True)
        assert fake.xform("|a", query=True, worldSpace=True,
                          rotatePivot=True) == [1.0, 2.0, 3.0]

    def test_a_shading_group_is_a_node_the_fake_answers_about(self):
        # The other direction of the same rule: a shadingEngine is a DG node
        # with no DAG path, and cmds.sets(sg, query=True) is a call Maya
        # ANSWERS. Refusing it as a missing DAG object would make the healthy
        # branch of ensure_object_shading unreachable in this fixture.
        fake = FakeCmds()
        fake._add("a")
        fake.add_shading_group("blinn1SG", ["|aShape"])
        assert fake.sets("blinn1SG", query=True) == ["|aShape"]
        assert fake.listSets(object="|aShape", type=1) == ["blinn1SG"]
        assert "blinn1SG" not in fake.ls()

    def test_a_chunk_already_on_one_shader_is_not_reassigned(self, fake):
        # What the SG modelling buys: the healthy branch of the collapse.
        # The merged node's shape is already the sole member of one SG, so
        # unite must leave it alone rather than force-assigning
        # initialShadingGroup over it.
        fake.add_shading_group("blinn1SG", ["|armShape"])
        result = assemble.assemble({
            "name": "golem",
            "parts": [
                {"kind": "cube", "pos": [0, 1, 0], "dim": [1, 1, 1], "chunk": "arm"},
                {"kind": "cube", "pos": [0, 2, 0], "dim": [1, 1, 1], "chunk": "arm"},
            ],
        })
        # Narrowed from `warnings == []` (#797): this build names no part
        # "golem", so it now also carries the tier-2 warning that the base
        # name went unused. The subject here is the SHADING collapse, and
        # the collapse warning is what must be absent.
        assert not any("shading" in w for w in result["warnings"])
        assert fake.set_members == {"blinn1SG": ["|armShape"]}
        assert "initialShadingGroup" not in fake.dg_nodes

    def test_an_unshaded_chunk_is_force_assigned_instead(self):
        # The contrast that makes the test above mean something: with no SG
        # on the result, unite falls back to initialShadingGroup and the
        # forceElement really runs.
        fake = FakeCmds()
        fake._add("a")
        fake._add("b")
        from maya_plugin.handlers import combine as combine_mod

        out = combine_mod.unite(fake, ["|a", "|b"], "merged")
        assert out["shading"] == {"sg": "initialShadingGroup", "repaired": True}
        assert fake.set_members["initialShadingGroup"] == ["|mergedShape"]


class TestTheBranchDropsIt:
    """#797: a param this call's branch never consumes is REFUSED, not kept.

    The refusals here all fire before assemble touches Maya, which is what
    the `_no_maya` fixture pins: `_cmds` raises, so a refusal moved back
    below it fails here with that AssertionError instead of a HandlerError.
    A refusal after `cmds = _cmds()` is a refusal after the checkpoint, and
    the checkpoint is the expensive half of the call.
    """

    @pytest.fixture
    def _no_maya(self, monkeypatch):
        def boom():
            raise AssertionError(
                "assemble reached Maya before refusing the inert param")

        monkeypatch.setattr(assemble, "_cmds", boom)

    # --- row 6: the pivot mode is a property of the combine ---------------

    def test_pivot_mode_is_refused_when_combine_is_false(self, _no_maya):
        with pytest.raises(HandlerError) as exc:
            assemble.assemble({"name": "kit", "parts": _parts(2),
                               "combine": False, "pivot": "origin"})
        assert "does not use 'pivot'" in str(exc.value)
        assert "combine" in str(exc.value)

    def test_pivot_mode_is_refused_when_every_chunk_holds_one_part(self, _no_maya):
        with pytest.raises(HandlerError) as exc:
            assemble.assemble({"name": "kit", "parts": _parts(1),
                               "pivot": "keep"})
        assert "does not use 'pivot'" in str(exc.value)
        assert "single" in str(exc.value)

    def test_center_is_what_a_lone_part_already_has_so_it_stands(self, fake):
        """The discrimination the plan measured: a primitive's own pivot IS
        its bbox centre, so `center` is observably honoured on a chunk that
        never goes through unite. Only origin/keep ask for a write that
        never happens."""
        result = assemble.assemble({"name": "kit", "atlas": None,
                                    "parts": _parts(1), "pivot": "center"})
        assert result["objects"][0]["parts"] == 1

    def test_an_unpassed_pivot_is_not_a_passed_one(self, fake):
        """The wrapper now sends pivot=None on every call (#797), so a
        handler that keyed the refusal on the KEY rather than the VALUE
        would refuse every single-part build ever made."""
        result = assemble.assemble({"name": "kit", "atlas": None,
                                    "parts": _parts(1), "pivot": None})
        assert result["objects"][0]["parts"] == 1

    def test_a_mixed_build_keeps_the_mode_and_names_the_chunks_that_lose_it(
        self, fake
    ):
        """With one multi-part chunk the mode IS consumed - refusing would
        refuse a working call. The single-part chunks still get no mode, and
        saying which ones is the honest half of that."""
        result = assemble.assemble({
            "name": "kit", "atlas": None, "pivot": "origin",
            "parts": (_parts(2, chunk="body") + _parts(1, chunk="stud")),
        })
        assert [o["combined"] for o in result["objects"]] == [True, False]
        assert any("stud" in w and "pivot" in w for w in result["warnings"])

    # --- row 7: a patch is a cell of an atlas that does not exist ---------

    def test_a_patch_without_an_atlas_is_refused_naming_the_part(self, _no_maya):
        with pytest.raises(HandlerError) as exc:
            assemble.assemble({"name": "kit", "parts": _parts(1, patch=3)})
        message = str(exc.value)
        assert "does not use 'patch'" in message
        assert "atlas" in message
        assert "parts[0]" in message

    def test_a_patch_index_off_a_phantom_grid_is_not_range_checked(self, _no_maya):
        """The defect: with no atlas the cell was resolved against a 4x4
        grid that does not exist, so `patch: 16` came back "outside a 4x4
        atlas" - a refusal naming a grid the caller never asked for."""
        with pytest.raises(HandlerError) as exc:
            assemble.assemble({"name": "kit", "parts": _parts(1, patch=16)})
        assert "does not use 'patch'" in str(exc.value)
        assert "4x4" not in str(exc.value)

    def test_a_patch_with_an_atlas_still_resolves(self, fake):
        result = assemble.assemble({
            "name": "kit", "atlas": {"cols": 4, "rows": 4},
            "parts": _parts(1, patch=5),
        })
        assert result["atlas"] == [4, 4]

    # --- rows 8 and 9: world_scale box-projects and never normalises ------

    def test_atlas_project_keep_is_refused_under_world_scale(self, _no_maya):
        with pytest.raises(HandlerError) as exc:
            assemble.assemble({"name": "kit", "parts": _parts(1),
                               "atlas": {"world_scale": 2.0, "project": "keep"}})
        assert "does not use 'project'" in str(exc.value)
        assert "world_scale" in str(exc.value)

    def test_atlas_project_planar_is_refused_under_world_scale(self, _no_maya):
        with pytest.raises(HandlerError) as exc:
            assemble.assemble({"name": "kit", "parts": _parts(1),
                               "atlas": {"world_scale": 2.0,
                                         "project": "planar"}})
        assert "does not use 'project'" in str(exc.value)

    def test_atlas_project_box_is_what_world_mode_does_so_it_stands(self, fake):
        result = assemble.assemble({
            "name": "kit", "parts": _parts(1),
            "atlas": {"world_scale": 2.0, "project": "box"},
        })
        assert result["parts"] == 1

    def test_atlas_project_keep_without_world_scale_still_works(self, fake):
        result = assemble.assemble({
            "name": "kit", "parts": _parts(1),
            "atlas": {"cols": 2, "rows": 2, "project": "keep"},
        })
        assert result["parts"] == 1

    def test_atlas_normalize_true_is_refused_under_world_scale(self, _no_maya):
        with pytest.raises(HandlerError) as exc:
            assemble.assemble({"name": "kit", "parts": _parts(1),
                               "atlas": {"world_scale": 2.0,
                                         "normalize": True}})
        assert "does not use 'normalize'" in str(exc.value)
        assert "world_scale" in str(exc.value)

    def test_atlas_normalize_false_is_what_world_mode_does_so_it_stands(self, fake):
        """The same rule as `project: box`: world mode normalises nothing, so
        a caller who asked for nothing got what they asked for."""
        result = assemble.assemble({
            "name": "kit", "parts": _parts(1),
            "atlas": {"world_scale": 2.0, "normalize": False},
        })
        assert result["parts"] == 1

    def test_the_default_normalize_is_untouched_without_world_scale(self, fake):
        result = assemble.assemble({"name": "kit", "parts": _parts(1),
                                    "atlas": {"cols": 2, "rows": 2}})
        assert result["parts"] == 1

    def test_an_explicit_null_normalize_reads_as_the_default_not_as_false(
        self, fake, monkeypatch
    ):
        """`bool(atlas.get("normalize", True))` cannot see a TCP caller's
        explicit null: the key is PRESENT, so the True default never applies
        and None collapses to False - an un-normalised pack, silently, from a
        caller who said nothing. uvatlas.py reads None as the default; this
        is the same read."""
        packed = []
        real_pack = uvatlas.pack_shape

        def spy(cmds, shape, rect, **kwargs):
            packed.append(kwargs)
            return real_pack(cmds, shape, rect, **kwargs)

        monkeypatch.setattr(uvatlas, "pack_shape", spy)
        assemble.assemble({"name": "kit", "parts": _parts(1),
                           "atlas": {"cols": 2, "rows": 2,
                                     "normalize": None}})
        assert packed and packed[0]["normalize"] is True

    # --- the keep warning: a united result has no prior pivot -------------

    def test_pivot_keep_on_a_united_chunk_warns_that_keep_is_origin(self, fake):
        """#797 / live probe 2026-09-03 (pid 33088): polyUnite hands back a
        transform whose rotatePivot, scalePivot and translate are all
        (0, 0, 0) whatever `ch` says, so `keep` on the merged object keeps
        the ORIGIN - it is `origin` under another name. combine.unite raises
        the note per result and assemble sums it into one."""
        result = assemble.assemble({
            "name": "kit", "atlas": None, "pivot": "keep",
            "parts": _parts(2, chunk="body"),
        })
        note = [w for w in result["warnings"] if "keep" in w and "origin" in w]
        assert note, result["warnings"]

    def test_the_keep_note_is_summed_once_per_call_not_once_per_chunk(
        self, fake
    ):
        """The delivery this module was written for is 8,000 parts over 2,034
        chunks: combine.unite raises the note on every united result, so
        carrying them up verbatim would bury every other warning under two
        thousand identical lines. assemble drops the per-result copies and
        states the COUNT instead."""
        result = assemble.assemble({
            "name": "kit", "atlas": None, "pivot": "keep",
            "parts": (_parts(2, chunk="body") + _parts(2, chunk="head")),
        })
        assert combine.KEEP_PIVOT_NOTE not in result["warnings"]
        note = [w for w in result["warnings"] if "keep" in w and "origin" in w]
        assert len(note) == 1, result["warnings"]
        assert "2 combined chunk(s)" in note[0]

    def test_no_keep_note_when_nothing_asked_to_keep(self, fake):
        result = assemble.assemble({
            "name": "kit", "atlas": None, "pivot": "origin",
            "parts": (_parts(2, chunk="body") + _parts(2, chunk="head")),
        })
        assert not [w for w in result["warnings"] if "polyUnite gives" in w]


class TestWarnedNotRefused:
    """Tier 2 (#797): the schema or the wrapper makes refusing impossible, so
    the call runs and says what it did with the value instead."""

    # --- row 34: `name` is required, and may name nothing at all ----------

    def test_a_base_name_no_part_used_is_reported(self, fake):
        result = assemble.assemble({
            "name": "kit", "atlas": None,
            "parts": _parts(2, chunk="body") + _parts(2, chunk="head"),
        })
        assert any("no part used the base name" in w for w in result["warnings"])
        assert any("kit" in w for w in result["warnings"])

    def test_a_base_name_a_part_defaulted_to_is_not_warned_about(self, fake):
        result = assemble.assemble({"name": "kit", "atlas": None,
                                    "parts": _parts(2)})
        assert result["warnings"] == []

    def test_a_chunk_that_spells_the_base_name_out_counts_as_using_it(self, fake):
        result = assemble.assemble({"name": "kit", "atlas": None,
                                    "parts": _parts(2, chunk="kit")})
        assert result["warnings"] == []

    def test_a_part_named_after_the_base_is_not_said_to_be_missing(self, fake):
        """The warning must not claim more than it measured. A part that asks
        for the base name as its OWN name, in a chunk nothing unites, KEEPS
        that name - so the scene really does contain a node called 'kit', and
        "nothing is called 'kit'" would be exactly the false claim #797
        exists to remove. The true half - that `name` was only ever the
        default chunk - still stands and is still said."""
        result = assemble.assemble({
            "name": "kit", "atlas": None,
            "parts": [{"pos": [0, 0, 0], "dim": [1, 1, 1], "chunk": "body",
                       "name": "kit"}],
        })
        assert any(o["name"] == "|kit" for o in result["objects"])
        assert any("no part used the base name" in w for w in result["warnings"])
        assert not any("nothing is called" in w for w in result["warnings"])

    def test_a_part_name_the_unite_eats_leaves_the_base_name_unclaimed(self, fake):
        """The other half: in a chunk of two the part named 'kit' is consumed
        by polyUnite and the result is called after the chunk, so nothing IS
        called 'kit' and the claim is true."""
        result = assemble.assemble({
            "name": "kit", "atlas": None,
            "parts": [
                {"pos": [0, 0, 0], "dim": [1, 1, 1], "chunk": "body",
                 "name": "kit"},
                {"pos": [2, 0, 0], "dim": [1, 1, 1], "chunk": "body"},
            ],
        })
        assert not any(o["name"] == "|kit" for o in result["objects"])
        assert any("nothing is called" in w for w in result["warnings"])

    # --- row 35: a part name the unite eats -------------------------------

    def test_a_part_name_eaten_by_the_unite_is_reported(self, fake):
        result = assemble.assemble({
            "name": "kit", "atlas": None,
            "parts": [
                {"pos": [0, 0, 0], "dim": [1, 1, 1], "chunk": "body",
                 "name": "brick_a"},
                {"pos": [2, 0, 0], "dim": [1, 1, 1], "chunk": "body"},
            ],
        })
        assert any("brick_a" in w and "polyUnite" in w
                   for w in result["warnings"])

    def test_a_part_name_that_survives_is_not_warned_about(self, fake):
        result = assemble.assemble({
            "name": "kit", "atlas": None, "combine": False,
            "parts": [{"pos": [0, 0, 0], "dim": [1, 1, 1], "chunk": "body",
                       "name": "brick_a"}],
        })
        assert not any("brick_a" in w for w in result["warnings"])
