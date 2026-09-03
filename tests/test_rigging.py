"""Rigging handlers (#602 phase 1) - orchestration under a FakeCmds.

Real joints, real skinClusters and real deformation are mayapy's job
(tests/test_handlers_mayapy.py); this file pins the call SEQUENCE: one
checkpoint, unique naming, parent selection order, measured-not-echoed
reporting, and every refusal path.
"""

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import rigging, session


class FakeCmds:
    def __init__(self, angle_unit="deg"):
        self.objects = []
        self.calls = []
        self.attrs = {}
        self.parents = {}       # child long -> parent long
        self._angle_unit = angle_unit
        self.selection = []
        self.node_types = {}   # explicit overrides; unset defaults to "joint"
        self.skin_history = []  # set by tests: skinClusters in the mesh's history
        self.skin_clusters = []  # set by tests: all skinClusters in the scene,
                                  # what cmds.ls(type="skinCluster") returns
        self.skin_influences = {}  # sc name -> [joint long names]
        self.skin_geometry = {}    # sc name -> [shape long names]
        self.bind_poses = []    # set by tests: dagPose(query=True, bindPose=True)
        self.positions = {}    # node long name -> [x, y, z] for xform queries
        self.matrices = {}     # node long name -> 16 floats for matrix queries
        self.vertex_tables = {}  # mesh long -> flat [x,y,z,...] world points
        self.shapes = {}       # transform long -> shape long (tests wire more)
        self.deleted = []      # #799: what cmds.delete took away
        self.driven_plugs = {}  # plug -> source plug (constraint, blend, SDK)
        self.locked_plugs = set()          # plugs a rigger locked
        self.string_attrs = {}             # node -> {attr: value}

    # --- existence (#799) ------------------------------------------------
    def _live(self):
        """Every name some fixture actually put in this scene, in order.

        #799 contract points 1 and 3. `ls` used to answer `[n]` for a name
        nothing had ever created and `nodeType` defaulted to "joint", so a
        typo, a stale long name, or a node this fake had DELETED resolved
        and typed as a perfectly good joint. That is the shape of blindness
        that let #796 ship a nodeType-after-delete crash: real Maya answers
        "No object matches name" to every one of these.
        """
        out, seen = [], set()

        def add(name):
            if name and name not in seen:
                seen.add(name)
                out.append(name)

        for n in self.objects:
            add(n)
        for child, parent in self.parents.items():
            add(child)
            add(parent)
        for shape in self.shapes.values():
            add(shape)
        for sc in list(self.skin_clusters) + list(self.skin_history):
            add(sc)
        for sc, influences in self.skin_influences.items():
            add(sc)
            for j in influences:
                add(j)
        for sc, geometry in self.skin_geometry.items():
            add(sc)
            for g in geometry:
                add(g)
        for n in self.node_types:
            add(n)
        # An attribute cannot be set on a node that does not exist: a
        # fixture writing attrs["|r|L_a.rotate"] has declared that joint.
        for plug in self.attrs:
            add(plug.split(".", 1)[0])
        for node in self.string_attrs:
            add(node)
        # A curve exists only as a consequence of `curve_plugs`; a
        # constraint/blend node only of `driven_plugs`. Both get asked for
        # their nodeType by clip.partition_driven_keys and the blend walk.
        for plug in getattr(self, "curve_plugs", ()):
            add(self._curve_for(plug))
        for src in self.driven_plugs.values():
            add(src.split(".")[0])
        return [n for n in out if n not in self.deleted]

    def _resolve(self, name):
        """Every LIVE long name `name` addresses. Maya's own resolution: a
        unique short name is as good as a long one (cmds.joint returns the
        SHORT name and the handler writes through it), and a component or
        plug resolves iff its node does."""
        node = name.split(".", 1)[0]
        return [o for o in self._live()
                if o == node or o.split("|")[-1] == node]

    def _require(self, name):
        if not self._resolve(name):
            raise RuntimeError("No object matches name: %s" % name)

    def _with_descendants(self, roots):
        """Deleting a DAG node takes its children and its shape with it."""
        out, frontier = [], list(roots)
        while frontier:
            n = frontier.pop()
            if n in out:
                continue
            out.append(n)
            frontier.extend(c for c, p in self.parents.items() if p == n)
            shape = self.shapes.get(n)
            if shape:
                frontier.append(shape)
        return out

    def _revive(self, *names):
        """A name is gone only until something CREATES it again. ROUND 2
        (#799): a permanent tombstone is a fake wrong in the STRICT
        direction - a node re-made under a deleted name would stay
        invisible forever, and Maya has no such memory."""
        for n in names:
            while n in self.deleted:
                self.deleted.remove(n)

    @staticmethod
    def _curve_for(plug):
        return plug.replace("|", "_").replace(".", "_") + "_crv"

    # --- names
    def objExists(self, name):
        return any(o.split("|")[-1] == name or o == name
                   for o in self._live())

    def ls(self, pattern=None, long=False, type=None, **kw):
        if type == "skinCluster":
            if pattern is None:
                # cmds.ls(type="skinCluster"): every skinCluster in the scene,
                # for _bound_meshes to scan.
                return list(self.skin_clusters)
            # mirrors cmds.ls(history_nodes, type="skinCluster"): the fake's
            # listHistory already returns only skinClusters, so the input
            # list IS the filtered result - present only when a bind exists.
            nodes = pattern if isinstance(pattern, list) else ([pattern] if pattern else [])
            return list(nodes) if self.skin_history else []
        live = self._live()
        if pattern is None:
            return live
        names = pattern if isinstance(pattern, list) else [pattern]
        out = []
        for n in names:
            # #799: NOT `matches or [n]`. Maya's `ls` returns nothing for a
            # name that is not in the scene - inventing the name back made
            # naming.require_object incapable of refusing anything.
            if "." in n:
                # A component or plug ("|hum.vtx[0]"): it resolves exactly
                # when its node does, which is what the faces->vertices
                # conversion asks about.
                node = n.split(".", 1)[0]
                if any(o == node or o.split("|")[-1] == node for o in live):
                    out.append(n)
                continue
            out.extend(o for o in live
                       if o == n or o.split("|")[-1] == n)
        return out

    def nodeType(self, node):
        self._require(node)
        if node in self.node_types:
            return self.node_types[node]
        if node.endswith("_crv"):
            # What `curve_plugs` conjures is a ROTATION curve; answering
            # "joint" for it left clip.partition_driven_keys bucketing it
            # right by luck rather than by type (#799).
            return "animCurveTA"
        # a shape node (by naming convention, "...Shape") is a mesh unless a
        # test says otherwise; anything else defaults to "joint" - the fake
        # never has to know about "transform" until a test asks for one.
        return "mesh" if "Shape" in node.split("|")[-1] else "joint"

    # --- creation
    def select(self, *args, **kw):
        if kw.get("clear"):
            self.selection = []
        elif args:
            self.selection = list(args)
        self.calls.append(("select", tuple(args), kw.get("clear", False)))

    def joint(self, *args, **kw):
        if kw.get("edit"):
            self.calls.append(("joint_edit", args, kw))
            return None
        name = kw["name"]
        parent = self.selection[0] if self.selection else None
        long = (parent + "|" + name) if parent else ("|" + name)
        self._revive(long)
        self.objects.append(long)
        self.parents[long] = parent
        self.attrs[long + ".jointOrient"] = [(0.0, 0.0, 0.0)]
        # ROUND 2 (#799): a created joint HAS a world position - `cmds.joint
        # -position` places it - so record it instead of leaving the xform
        # query to the invented [1,2,3] this fake used to answer.
        self.positions.setdefault(long, [float(v) for v in kw["position"]])
        self.calls.append(("joint", name, tuple(kw["position"]), parent))
        return name

    def listRelatives(self, node, children=False, parent=False,
                      allDescendents=False, shapes=False, type=None,
                      fullPath=False, **kw):
        self._require(node)
        if parent:
            p = self.parents.get(node)
            return [p] if p else None
        if shapes:
            # #799: `shapes=True` used to fall through to the CHILDREN
            # branch, so any joint with a child answered a shape query -
            # which made rigging._bound_meshes call a bare joint chain a
            # set of bound meshes and measure vertex positions on it.
            shape = self.shapes.get(node)
            if shape is None or type not in (None, "mesh"):
                return None
            return [shape]
        out = [o for o, p in self.parents.items() if p == node]
        if allDescendents:
            walked = []
            frontier = list(out)
            while frontier:
                k = frontier.pop()
                walked.append(k)
                frontier.extend(o for o, p in self.parents.items() if p == k)
            out = walked
        if type is not None:
            # #799: `type` was accepted and ignored. Maya matches DERIVED
            # types, so a joint answers type="transform" - but a mesh SHAPE
            # never does.
            out = [k for k in out
                   if (self.nodeType(k) == type
                       or (type == "transform"
                           and self.nodeType(k) != "mesh"))]
        return out or None

    # #799 contract point 2. MEASURED in #771 and #796: a plug a connection
    # feeds - a constraint, a pairBlend, an anim layer, a driven key, a
    # poseInterpolator - refuses a static write, and so does a LOCKED one;
    # Maya raises "locked or connected and cannot be modified". A compound
    # write refuses when any CHILD is fed, and a child write refuses when
    # the connection landed on the compound. This fake wrote to anything,
    # which is exactly why #796's compound-setAttr crash was invisible
    # headlessly.
    _COMPOUNDS = ("rotate", "translate", "scale", "jointOrient",
                  "preferredAngle")

    def _static_write_blocker(self, plug):
        """What makes a static write to `plug` raise, or None."""
        node, _, attr = plug.rpartition(".")
        fed = set(getattr(self, "curve_plugs", ())) | set(self.driven_plugs)
        candidates = [plug]
        if attr in self._COMPOUNDS:
            candidates += ["%s.%s%s" % (node, attr, ax) for ax in "XYZ"]
        elif attr[:-1] in self._COMPOUNDS and attr[-1] in "XYZ":
            candidates.append("%s.%s" % (node, attr[:-1]))
        for candidate in candidates:
            if candidate in self.locked_plugs:
                return candidate + " (locked)"
            if candidate in fed:
                return self.driven_plugs.get(candidate,
                                             self._curve_for(candidate))
        return None

    def xform(self, node, query=False, worldSpace=False, translation=False,
              matrix=False, **kw):
        self._require(node)
        if query and matrix:
            self.calls.append(("xform_matrix", node))
            if node not in self.matrices:
                # ROUND 2 (#799): an invented IDENTITY is a measurement no
                # fixture made. Maya reads a real world matrix here; a fake
                # that answers "unrotated, unmoved" for any node lets a
                # handler's arithmetic look right against nothing.
                raise AssertionError(
                    "FakeCmds.xform: no matrix declared for %s - wire "
                    "`fake.matrices` rather than inherit an identity (#799)"
                    % node)
            return list(self.matrices[node])
        if not query and not isinstance(translation, bool):
            # An `xform -translation` is a static write to node.translate,
            # and refuses on the same connections setAttr does (#799).
            blocker = self._static_write_blocker(node + ".translate")
            if blocker:
                raise RuntimeError(
                    "xform: The attribute '%s.translate' is locked or "
                    "connected and cannot be modified (%s)"
                    % (node, blocker))
            self.calls.append(("xform_set", node, tuple(translation)))
            return None
        self.calls.append(("xform_query", node))
        if node in self.positions:
            return list(self.positions[node])
        if node.endswith(".vtx[*]"):
            # sculpt.vertex_positions asks a whole mesh for its points.
            # ROUND 2 (#799): the [1,2,3] below answered this too, so every
            # mesh in this file measured as ONE vertex that never moves -
            # the fiction that made ten TestPoseIk displacement assertions
            # green against nothing. `vertex_tables` is how a test declares
            # a mesh's real points; an undeclared mesh has none to give.
            return list(self.vertex_tables.get(node[:-len(".vtx[*]")], []))
        if "." in node:
            raise AssertionError(
                "FakeCmds.xform: no position declared for the component %s "
                "- it used to answer an invented [1,2,3] for any plug or "
                "component of any live node (#799)" % node)
        # A transform nothing has moved sits at the origin, which is what
        # Maya answers - not the [1,2,3] this used to invent.
        return [0.0, 0.0, 0.0]

    def setAttr(self, plug, *values, **kw):
        self._require(plug.rpartition(".")[0])
        blocker = self._static_write_blocker(plug)
        if blocker:
            raise RuntimeError(
                "setAttr: The attribute '%s' is locked or connected and "
                "cannot be modified (%s)" % (plug, blocker))
        self.attrs[plug] = [tuple(values)] if len(values) == 3 else list(values)
        self.calls.append(("setAttr", plug, values))

    def getAttr(self, plug, type=False, lock=False, **kw):
        node, _, attr = plug.rpartition(".")
        self._require(node)
        if lock:
            # ROUND 2 (#799): `lock=True` used to fall into **kw and drop
            # through to the compound default, which answers [(0,0,0)] -
            # TRUTHY - so a guard shaped like
            # correctives._joint_rotation_writable would call EVERY joint
            # locked. A fake that is wrong in the strict direction produces
            # spurious failures the next person "fixes" by weakening it.
            return plug in self.locked_plugs
        if type:
            return "doubleAngle"
        if plug in self.attrs:
            return self.attrs[plug]
        if attr in self.string_attrs.get(node, {}):
            return self.string_attrs[node][attr]
        if attr in self._COMPOUNDS:
            # Maya's own zero default for an unwritten transform compound.
            return [(0.0, 0.0, 0.0)]
        # #799: `self.attrs.get(plug, [(0.0, 0.0, 0.0)])` answered a rotate
        # triple for EVERY attribute, scalars included - so a handler
        # reading an attribute no fixture ever set read as "zero" instead
        # of raising the way Maya does.
        raise RuntimeError("No object matches name: %s" % plug)

    def currentUnit(self, query=False, angle=False, linear=False, **kw):
        return self._angle_unit if angle else "cm"

    # --- binding
    def listHistory(self, node, pruneDagObjects=False, **kw):
        self._require(node)
        self.calls.append(("listHistory", node))
        # ROUND 2 (#799): `return list(self.skin_history)` answered ONE
        # global history for EVERY node in the scene, so a bare JOINT read
        # as bound to whatever mesh a fixture had bound, and
        # _skin_cluster_for's "is not bound" refusal could only ever fire
        # by emptying skin_history globally - never for the one unbound
        # mesh in a scene that also holds a bound one. A deformer stack
        # belongs to the GEOMETRY it deforms; nothing else has one.
        if self.nodeType(node) != "mesh":
            return []
        return list(self.skin_history)

    def skinCluster(self, *args, **kw):
        self.calls.append(("skinCluster", args, kw))
        if kw.get("query"):
            sc = args[0] if args else None
            if kw.get("influence"):
                return list(self.skin_influences.get(sc, []))
            if kw.get("geometry"):
                return list(self.skin_geometry.get(sc, []))
            return None
        return ["fakeSkin1"]

    def ikHandle(self, startJoint=None, endEffector=None, solver=None,
                 name=None, **kw):
        handle, effector = "|" + name, "|" + name + "_eff"
        self._revive(handle, effector)
        self.objects.extend([handle, effector])
        self.calls.append(("ikHandle", startJoint, endEffector, solver, name))
        return [handle, effector]

    def spaceLocator(self, name=None, **kw):
        self._revive("|" + name)
        self.objects.append("|" + name)
        self.calls.append(("spaceLocator", name))
        return ["|" + name]

    def poleVectorConstraint(self, locator, handle, **kw):
        self.calls.append(("poleVectorConstraint", locator, handle))
        return [handle + "_pvc"]

    def delete(self, *names, **kw):
        self.calls.append(("delete", names))
        for n in names:
            self._require(n)
            # #799: RECORD the deletion. Dropping the name from `objects`
            # alone was not enough - a name a fixture had also mentioned in
            # `parents` (every joint) stayed answerable forever.
            # ROUND 2: record the LONG names, and the descendants Maya
            # takes with them. `self.deleted.append(n)` stored whatever
            # string the caller used while `_live()` filters by exact name,
            # so a delete addressed by SHORT name tombstoned nothing and
            # nodeType/objExists/ls kept answering for the dead node.
            for long in self._with_descendants(self._resolve(n)):
                if long not in self.deleted:
                    self.deleted.append(long)
                if long in self.objects:
                    self.objects.remove(long)

    # --- posing
    def dagPose(self, *args, query=False, bindPose=False, restore=False, **kw):
        self.calls.append(("dagPose", args,
                          dict(kw, query=query, bindPose=bindPose, restore=restore)))
        if query and bindPose:
            return list(self.bind_poses)
        return None

    def attributeQuery(self, attr, node=None, exists=False):
        # #799: this answered False unconditionally, so clip.clip_meta could
        # never find an mcp_clip record and guard_static_pose's "(clip
        # 'walk')" naming branch was dead code under this fake. It is a
        # modelled lookup now; `string_attrs` is how a test declares one.
        self._require(node)
        if exists:
            return attr in self.string_attrs.get(node, {})
        raise AssertionError(
            "FakeCmds.attributeQuery models exists= only (#799)")

    def listConnections(self, plug, source=False, destination=True,
                        type=None, plugs=False, **kw):
        # `plugs` was ABSENT from this signature, so every
        # clip.driven_weight_source call raised TypeError and was swallowed
        # by the blend walk's broad except - the entire indirect-curve arm
        # of guard_static_pose could not run here at all (#799).
        self._require(plug.split(".")[0])
        if not source:
            raise AssertionError(
                "FakeCmds.listConnections models source queries only (#799)")
        srcs = []
        if plug in getattr(self, "curve_plugs", ()):
            srcs.append(self._curve_for(plug) + ".output")
        if plug in self.driven_plugs:
            srcs.append(self.driven_plugs[plug])
        if type is not None:
            # Maya's type filter matches DERIVED types, so an animCurveTA
            # answers type="animCurve" (the #796 defect-1 trap).
            srcs = [x for x in srcs
                    if self.nodeType(x.split(".")[0]) == type
                    or (type == "animCurve"
                        and self.nodeType(x.split(".")[0]).startswith(
                            "animCurve"))]
        if not srcs:
            return None
        return srcs if plugs else [x.split(".")[0] for x in srcs]


@pytest.fixture
def fake(monkeypatch):
    fake = FakeCmds()
    monkeypatch.setattr(rigging, "_cmds", lambda: fake)
    monkeypatch.setattr(session, "auto_checkpoint",
                        lambda reason: {"checkpoint_id": "001_" + reason,
                                        "path": "x.ma"})
    return fake


class TestCreateSkeleton:
    def test_chain_parents_each_joint_under_the_previous(self, fake):
        out = rigging.create_skeleton({
            "chain": [[0, 0, 0], [0, 1, 0], [0, 2, 0]], "chain_prefix": "s"})
        made = [c for c in fake.calls if c[0] == "joint"]
        assert [m[1] for m in made] == ["s_01", "s_02", "s_03"]
        assert made[0][3] is None
        assert made[1][3] == "|s_01"
        assert out["root"] == "|s_01"
        assert [j["parent"] for j in out["joints"]] == [None, "|s_01", "|s_01|s_02"]

    def test_positions_are_measured_back_not_echoed(self, fake):
        # ROUND 2 (#799): this used to read back the fake's invented
        # [1,2,3] - an answer no fixture ever declared. The scene now
        # DISAGREES with the request on purpose (Maya's own orient pass
        # moves a joint the caller asked for at the origin), and the report
        # has to carry what the scene says, not what was asked for.
        real_joint = fake.joint

        def displaced(*a, **kw):
            if kw.get("edit"):
                return real_joint(*a, **kw)
            name = real_joint(*a, **kw)
            long = [o for o in fake.objects if o.split("|")[-1] == name][0]
            fake.positions[long] = [1.0, 2.0, 3.0]
            return name

        fake.joint = displaced
        out = rigging.create_skeleton({"chain": [[0, 0, 0], [0, 9, 0]]})
        assert out["joints"][0]["position"] == [1.0, 2.0, 3.0]

    def test_one_checkpoint_before_any_joint(self, fake, monkeypatch):
        events = []
        monkeypatch.setattr(session, "auto_checkpoint",
                            lambda reason: events.append("checkpoint") or
                            {"checkpoint_id": "001", "path": "x.ma"})
        real_joint = fake.joint
        def logged_joint(*a, **kw):
            events.append("joint")
            return real_joint(*a, **kw)
        fake.joint = logged_joint
        rigging.create_skeleton({"chain": [[0, 0, 0], [0, 1, 0]]})
        assert events[0] == "checkpoint"
        assert events.count("checkpoint") == 1

    def test_a_name_collision_warns_and_renames(self, fake):
        fake.objects.append("|s_01")
        fake.parents["|s_01"] = None
        out = rigging.create_skeleton({"chain": [[0, 0, 0], [0, 1, 0]],
                                       "chain_prefix": "s"})
        assert any("s_01" in w for w in out["warnings"])
        made = [c[1] for c in fake.calls if c[0] == "joint"]
        assert "s_01_001" in made

    def test_validation_failure_costs_nothing(self, fake, monkeypatch):
        monkeypatch.setattr(session, "auto_checkpoint",
                            lambda reason: pytest.fail("checkpointed a bad call"))
        with pytest.raises(HandlerError):
            rigging.create_skeleton({"chain": [[0, 0, 0]]})
        assert fake.objects == []


class TestBindSkinValidation:
    def _mesh(self, fake):
        fake.objects.append("|serpent")
        fake.shapes = {"|serpent": "|serpent|serpentShape"}
        def listRelatives(node, shapes=False, **kw):
            if shapes:
                return [fake.shapes.get(node)]
            return FakeCmds.listRelatives(fake, node, **kw)
        fake.listRelatives = listRelatives

    def test_root_must_be_a_joint(self, fake):
        self._mesh(fake)
        fake.objects.append("|not_a_joint")
        fake.node_types = {"|not_a_joint": "transform"}
        with pytest.raises(HandlerError, match="not a joint"):
            rigging.bind_skin({"mesh": "serpent", "root": "not_a_joint"})

    def test_unknown_method_lists_the_valid_ones(self, fake):
        self._mesh(fake)
        fake.objects.append("|root_j")
        with pytest.raises(HandlerError, match="closestDistance"):
            rigging.bind_skin({"mesh": "serpent", "root": "root_j",
                               "method": "psychic"})

    def test_max_influences_bounds(self, fake):
        self._mesh(fake)
        fake.objects.append("|root_j")
        with pytest.raises(HandlerError, match="max_influences"):
            rigging.bind_skin({"mesh": "serpent", "root": "root_j",
                               "max_influences": 0})

    def test_rebind_is_refused_with_the_unbind_hint(self, fake):
        self._mesh(fake)
        fake.objects.append("|root_j")
        fake.skin_history = ["oldSkin"]
        with pytest.raises(HandlerError, match="already bound") as err:
            rigging.bind_skin({"mesh": "serpent", "root": "root_j"})
        assert "unbind" in err.value.hint


class TestPoseValidation:
    def _skeleton(self, fake):
        fake.objects += ["|r", "|r|a"]
        fake.parents = {"|r|a": "|r"}

    def test_space_other_than_local_is_refused(self, fake):
        self._skeleton(fake)
        with pytest.raises(HandlerError, match="space"):
            rigging.pose_skeleton({"root": "r", "space": "world",
                                   "rotations": {"a": [0, 0, 10]}})

    def test_empty_rotations_refused(self, fake):
        self._skeleton(fake)
        with pytest.raises(HandlerError, match="rotations"):
            rigging.pose_skeleton({"root": "r", "rotations": {}})

    def test_a_joint_outside_the_root_is_refused_by_name(self, fake):
        self._skeleton(fake)
        with pytest.raises(HandlerError, match="stranger"):
            rigging.pose_skeleton({"root": "r",
                                   "rotations": {"stranger": [0, 0, 10]}})

    def test_rotations_reach_maya_in_scene_units(self, fake):
        import math
        fake._angle_unit = "rad"
        self._skeleton(fake)
        rigging.pose_skeleton({"root": "r", "rotations": {"a": [0, 0, 90]}})
        wrote = [c for c in fake.calls
                 if c[0] == "setAttr" and c[1] == "|r|a.rotate"]
        assert wrote[0][2][2] == pytest.approx(math.pi / 2)

    def test_no_bound_mesh_is_a_warning_not_silence(self, fake):
        self._skeleton(fake)
        out = rigging.pose_skeleton({"root": "r", "rotations": {"a": [0, 0, 10]}})
        assert any("moves no mesh" in w for w in out["warnings"])
        assert out["max_displacement"] == 0.0

    def test_a_unique_short_name_resolves_to_its_joint(self, fake):
        fake.objects += ["|r", "|r|arm"]
        fake.parents["|r|arm"] = "|r"
        out = rigging.pose_skeleton({"root": "r", "rotations": {"arm": [0, 0, 10]}})
        wrote = [c for c in fake.calls
                 if c[0] == "setAttr" and c[1] == "|r|arm.rotate"]
        assert wrote
        assert out["applied"] == 1

    def test_two_spellings_of_the_same_joint_are_refused(self, fake):
        fake.objects += ["|r", "|r|arm"]
        fake.parents["|r|arm"] = "|r"
        with pytest.raises(HandlerError, match="twice") as err:
            rigging.pose_skeleton({
                "root": "r",
                "rotations": {"arm": [0, 0, 10], "|r|arm": [0, 0, 20]}})
        assert "|r|arm" in str(err.value)

    def test_an_ambiguous_short_name_is_refused_with_the_long_name_fix(self, fake):
        fake.objects += ["|r", "|r|a", "|r|b", "|r|a|tip", "|r|b|tip"]
        fake.parents.update({
            "|r|a": "|r",
            "|r|b": "|r",
            "|r|a|tip": "|r|a",
            "|r|b|tip": "|r|b",
        })
        with pytest.raises(HandlerError, match="ambiguous") as err:
            rigging.pose_skeleton({"root": "r", "rotations": {"tip": [0, 0, 10]}})
        assert "|r|a|tip" in err.value.hint


class TestResetPose:
    def test_unbound_skeleton_zeroes_rotations_with_a_warning(self, fake):
        fake.objects += ["|r", "|r|a"]
        fake.parents = {"|r|a": "|r"}
        out = rigging.reset_pose({"root": "r"})
        assert out["reset"] is True
        assert any("no bind pose" in w for w in out["warnings"])
        zeroed = [c for c in fake.calls
                  if c[0] == "setAttr" and c[1].endswith(".rotate")]
        assert len(zeroed) == 2


class TestPosePerMesh:
    def test_reset_with_two_bind_poses_warns_and_restores_the_first(self, fake):
        fake.objects += ["|r", "|r|a"]
        fake.parents = {"|r|a": "|r"}
        fake.bind_poses = ["bindPose1", "bindPose2"]
        out = rigging.reset_pose({"root": "r"})
        assert any("2 bind poses" in w for w in out["warnings"])
        restored = [c for c in fake.calls
                    if c[0] == "dagPose" and c[2].get("restore")]
        assert restored and restored[0][1][0] == "bindPose1"

    def test_pose_reports_per_mesh_and_names_the_inert_one(self, fake, monkeypatch):
        fake.objects += ["|r", "|r|a"]
        fake.parents = {"|r|a": "|r"}
        fake.skin_clusters = ["scA", "scB"]
        fake.skin_influences = {"scA": ["|r|a"], "scB": ["|r|a"]}
        fake.skin_geometry = {"scA": ["|meshA|meshAShape"],
                              "scB": ["|meshB|meshBShape"]}
        fake.objects += ["|meshA", "|meshB"]
        fake.parents.update({"|meshA|meshAShape": "|meshA",
                             "|meshB|meshBShape": "|meshB"})
        # _bound_meshes asks a shape for its parent transform; the base fake
        # only answers children queries.
        def listRelatives(node, parent=False, fullPath=False, **kw):
            if parent:
                p = fake.parents.get(node)
                return [p] if p else None
            return FakeCmds.listRelatives(fake, node, **kw)
        fake.listRelatives = listRelatives
        from maya_plugin.handlers import sculpt
        state = {"posed": False}
        def positions(cmds, mesh):
            # meshA moves 1.0 when posed; meshB never moves.
            if mesh == "|meshA" and state["posed"]:
                return [0.0, 1.0, 0.0,  0.0, 3.0, 0.0]
            if mesh == "|meshA":
                return [0.0, 0.0, 0.0,  0.0, 2.0, 0.0]
            return [5.0, 0.0, 0.0,  5.0, 2.0, 0.0]
        monkeypatch.setattr(sculpt, "vertex_positions", positions)
        real_set = fake.setAttr
        def set_attr(plug, *values, **kw):
            state["posed"] = True
            return real_set(plug, *values, **kw)
        fake.setAttr = set_attr
        out = rigging.pose_skeleton({"root": "r",
                                     "rotations": {"a": [0, 0, 30]}})
        assert len(out["per_mesh"]) == 2
        by_mesh = {m["mesh"]: m for m in out["per_mesh"]}
        assert by_mesh["|meshA"]["max_displacement"] == pytest.approx(1.0)
        assert by_mesh["|meshB"]["max_displacement"] == 0.0
        assert out["max_displacement"] == pytest.approx(1.0)
        assert any("meshB" in w and "near-zero" in w for w in out["warnings"])


class TestWeightReport:
    def _bound_mesh(self, fake, monkeypatch):
        fake.objects.append("|serpent")
        fake.shapes = {"|serpent": "|serpent|serpentShape"}
        def listRelatives(node, shapes=False, **kw):
            if shapes:
                return [fake.shapes.get(node)]
            return FakeCmds.listRelatives(fake, node, **kw)
        fake.listRelatives = listRelatives
        fake.skin_history = ["skin1"]
        fake.attrs["skin1.maxInfluences"] = 4
        # 3 verts x 2 joints: v2 unweighted
        monkeypatch.setattr(
            rigging, "_skin_weights",
            lambda sc, shape: (["|r|a", "|r|b"],
                               [1.0, 0.0, 0.6, 0.4, 0.0, 0.0], 3))

    def test_report_is_measured_and_never_checkpoints(self, fake, monkeypatch):
        self._bound_mesh(fake, monkeypatch)
        monkeypatch.setattr(session, "auto_checkpoint",
                            lambda reason: pytest.fail("a measurement checkpointed"))
        out = rigging.weight_report({"mesh": "serpent"})
        assert out["skin_cluster"] == "skin1"
        assert out["vertices"] == 3
        assert out["max_influences"] == 4
        assert out["unweighted_vertices"] == 1
        assert out["unweighted_sample"] == [2]
        assert any("belong to NO joint" in w for w in out["warnings"])

    def test_unbound_mesh_is_refused_with_the_bind_hint(self, fake, monkeypatch):
        self._bound_mesh(fake, monkeypatch)
        fake.skin_history = []
        with pytest.raises(HandlerError, match="not bound") as err:
            rigging.weight_report({"mesh": "serpent"})
        assert "bind_skin" in err.value.hint


class TestMirrorWeights:
    def _bound(self, fake, monkeypatch,
               positions=(1.0, 0.5, 0.0,  -1.0, 0.5, 0.0),
               weights=(0.0, 1.0, 0.0,     1.0, 0.0, 0.0),
               joints=("|r", "|r|L_a", "|r|R_a"),
               joint_pos=((0.0, 1, 0), (0.5, 1, 0), (-0.5, 1, 0))):
        fake.objects.append("|hum")
        fake.shapes = {"|hum": "|hum|humShape"}
        def listRelatives(node, shapes=False, **kw):
            if shapes:
                return [fake.shapes.get(node)]
            return FakeCmds.listRelatives(fake, node, **kw)
        fake.listRelatives = listRelatives
        fake.skin_history = ["skin1"]
        fake.attrs["skin1.maxInfluences"] = 4
        for j, p in zip(joints, joint_pos):
            fake.attrs[j + ".rotate"] = [(0.0, 0.0, 0.0)]
        state = {"weights": list(weights)}
        monkeypatch.setattr(
            rigging, "_skin_weights",
            lambda sc, shape: (list(joints), list(state["weights"]),
                               len(positions) // 3))
        written = {}
        def set_weights(sc, shape, ncols, table):
            written["table"] = list(table)
            state["weights"] = list(table)
        monkeypatch.setattr(rigging, "_set_skin_weights", set_weights)
        from maya_plugin.handlers import sculpt
        monkeypatch.setattr(sculpt, "vertex_positions",
                            lambda cmds, mesh: list(positions))
        jp = {j: list(p) for j, p in zip(joints, joint_pos)}
        def xform(node, query=False, worldSpace=False, translation=False, **kw):
            return jp.get(node, [0.0, 0.0, 0.0])
        fake.xform = xform
        return written

    def test_mirror_writes_swapped_columns_and_measures_back(self, fake, monkeypatch):
        written = self._bound(fake, monkeypatch)
        out = rigging.mirror_weights({"mesh": "hum"})
        assert written["table"][3:6] == [0.0, 0.0, 1.0]   # L column -> R column
        assert out["mirrored_vertices"] == 1
        assert out["changed_vertices"] == 1
        assert out["unweighted_vertices"] == 0

    def test_unknown_axis_and_direction_are_refused(self, fake, monkeypatch):
        self._bound(fake, monkeypatch)
        with pytest.raises(HandlerError, match="axis"):
            rigging.mirror_weights({"mesh": "hum", "axis": "w"})
        with pytest.raises(HandlerError, match="direction"):
            rigging.mirror_weights({"mesh": "hum", "direction": "sideways"})

    def test_an_asymmetric_skeleton_is_refused_by_name(self, fake, monkeypatch):
        self._bound(fake, monkeypatch,
                    joints=("|r", "|r|L_a"),
                    joint_pos=((0.0, 1, 0), (0.5, 1, 0)),
                    weights=(0.0, 1.0, 1.0, 0.0))
        with pytest.raises(HandlerError, match="no mirror partner") as err:
            rigging.mirror_weights({"mesh": "hum"})
        assert "L_a" in str(err.value)

    def test_unpaired_vertices_warn_but_do_not_refuse(self, fake, monkeypatch):
        self._bound(fake, monkeypatch,
                    positions=(1.0, 0.5, 0.0,  -1.0, 0.5, 0.0,  2.0, 9.0, 0.0),
                    weights=(0.0, 1.0, 0.0,  1.0, 0.0, 0.0,  0.0, 1.0, 0.0))
        out = rigging.mirror_weights({"mesh": "hum"})
        assert out["unpaired_vertices"] == 1
        assert any("unpaired" in w for w in out["warnings"])

    def test_a_posed_skeleton_warns_before_mirroring(self, fake, monkeypatch):
        self._bound(fake, monkeypatch)
        fake.attrs["|r|L_a.rotate"] = [(0.0, 0.0, 30.0)]
        out = rigging.mirror_weights({"mesh": "hum"})
        assert any("posed" in w for w in out["warnings"])

    def test_mirror_checkpoints_once_after_validation(self, fake, monkeypatch):
        self._bound(fake, monkeypatch)
        events = []
        monkeypatch.setattr(session, "auto_checkpoint",
                            lambda reason: events.append(reason) or
                            {"checkpoint_id": "001", "path": "x.ma"})
        rigging.mirror_weights({"mesh": "hum"})
        assert events == ["mirror_weights"]


class TestSmoothWeights:
    def _bound(self, fake, monkeypatch, weights, joints=("|r|a", "|r|b"),
               adjacency=((1,), (0, 2), (1,))):
        fake.objects.append("|hum")
        fake.shapes = {"|hum": "|hum|humShape"}
        def listRelatives(node, shapes=False, **kw):
            if shapes:
                return [fake.shapes.get(node)]
            return FakeCmds.listRelatives(fake, node, **kw)
        fake.listRelatives = listRelatives
        fake.skin_history = ["skin1"]
        fake.attrs["skin1.maxInfluences"] = 4
        for j in joints:
            fake.attrs[j + ".rotate"] = [(0.0, 0.0, 0.0)]
        state = {"weights": list(weights)}
        monkeypatch.setattr(
            rigging, "_skin_weights",
            lambda sc, shape: (list(joints), list(state["weights"]),
                               len(weights) // len(joints)))
        def set_weights(sc, shape, ncols, table):
            state["weights"] = list(table)
        monkeypatch.setattr(rigging, "_set_skin_weights", set_weights)
        monkeypatch.setattr(rigging, "_vertex_adjacency",
                            lambda shape: [list(a) for a in adjacency])
        return state

    def test_smooth_measures_what_changed(self, fake, monkeypatch):
        state = self._bound(fake, monkeypatch,
                            [1.0, 0.0, 1.0, 0.0, 0.0, 1.0])
        out = rigging.smooth_weights({"mesh": "hum"})
        assert out["iterations"] == 1
        assert out["smoothed_vertices"] == 3
        assert out["changed_vertices"] >= 1
        assert out["unweighted_vertices"] == 0
        assert state["weights"][2:4] == pytest.approx([0.75, 0.25])

    def test_joints_filter_selects_rows_by_held_weight(self, fake, monkeypatch):
        self._bound(fake, monkeypatch, [1.0, 0.0, 1.0, 0.0, 0.0, 1.0])
        out = rigging.smooth_weights({"mesh": "hum", "joints": ["b"]})
        # only v2 holds b -> only v2 is a smoothing target
        assert out["smoothed_vertices"] == 1

    def test_unknown_joint_is_refused_with_candidates(self, fake, monkeypatch):
        self._bound(fake, monkeypatch, [1.0, 0.0, 1.0, 0.0, 0.0, 1.0])
        with pytest.raises(HandlerError, match="not an influence") as err:
            rigging.smooth_weights({"mesh": "hum", "joints": ["nope"]})
        assert "a" in err.value.hint

    def test_iterations_bounds(self, fake, monkeypatch):
        self._bound(fake, monkeypatch, [1.0, 0.0, 1.0, 0.0, 0.0, 1.0])
        with pytest.raises(HandlerError, match="iterations"):
            rigging.smooth_weights({"mesh": "hum", "iterations": 0})
        with pytest.raises(HandlerError, match="iterations"):
            rigging.smooth_weights({"mesh": "hum", "iterations": 999})


class TestSetRegionWeights:
    def _bound(self, fake, monkeypatch,
               positions=(0.0, 0.0, 0.0,  1.0, 0.0, 0.0),
               weights=(0.5, 0.5, 0.5, 0.5),
               joints=("|r|a", "|r|b")):
        fake.objects.append("|hum")
        fake.shapes = {"|hum": "|hum|humShape"}
        def listRelatives(node, shapes=False, **kw):
            if shapes:
                return [fake.shapes.get(node)]
            return FakeCmds.listRelatives(fake, node, **kw)
        fake.listRelatives = listRelatives
        fake.skin_history = ["skin1"]
        fake.attrs["skin1.maxInfluences"] = 4
        for j in joints:
            fake.attrs[j + ".rotate"] = [(0.0, 0.0, 0.0)]
        state = {"weights": list(weights)}
        monkeypatch.setattr(
            rigging, "_skin_weights",
            lambda sc, shape: (list(joints), list(state["weights"]),
                               len(positions) // 3))
        def set_weights(sc, shape, ncols, table):
            state["weights"] = list(table)
        monkeypatch.setattr(rigging, "_set_skin_weights", set_weights)
        from maya_plugin.handlers import sculpt
        monkeypatch.setattr(sculpt, "vertex_positions",
                            lambda cmds, mesh: list(positions))
        fake.face_count = 4
        def polyEvaluate(mesh, face=False, vertex=False, **kw):
            return fake.face_count if face else len(positions) // 3
        fake.polyEvaluate = polyEvaluate
        def plcc(*comps, fromFace=False, toVertex=False, **kw):
            return ["|hum.vtx[0]"]
        fake.polyListComponentConversion = plcc
        return state

    def test_radius_mode_blends_and_reports(self, fake, monkeypatch):
        state = self._bound(fake, monkeypatch)
        out = rigging.set_region_weights({
            "mesh": "hum", "joint": "a", "within_radius_of": [0, 0, 0],
            "radius": 0.5, "weight": 1.0})
        assert out["vertices_in_region"] == 1
        assert out["changed_vertices"] == 1
        assert state["weights"][:2] == pytest.approx([1.0, 0.0])
        assert state["weights"][2:] == pytest.approx([0.5, 0.5])

    def test_faces_mode_converts_and_assigns_hard(self, fake, monkeypatch):
        state = self._bound(fake, monkeypatch)
        out = rigging.set_region_weights({
            "mesh": "hum", "joint": "b", "faces": [0], "weight": 1.0})
        assert out["vertices_in_region"] == 1
        assert state["weights"][:2] == pytest.approx([0.0, 1.0])

    def test_exactly_one_region_form(self, fake, monkeypatch):
        self._bound(fake, monkeypatch)
        with pytest.raises(HandlerError, match="exactly one"):
            rigging.set_region_weights({"mesh": "hum", "joint": "a",
                                        "weight": 1.0})
        with pytest.raises(HandlerError, match="exactly one"):
            rigging.set_region_weights({
                "mesh": "hum", "joint": "a", "faces": [0],
                "within_radius_of": [0, 0, 0], "radius": 1, "weight": 1.0})

    def test_weight_bounds_and_radius_requirements(self, fake, monkeypatch):
        self._bound(fake, monkeypatch)
        with pytest.raises(HandlerError, match="weight"):
            rigging.set_region_weights({"mesh": "hum", "joint": "a",
                                        "faces": [0], "weight": 1.5})
        with pytest.raises(HandlerError, match="radius"):
            rigging.set_region_weights({
                "mesh": "hum", "joint": "a", "within_radius_of": [0, 0, 0],
                "weight": 1.0})

    def test_falloff_is_a_radius_mode_concept(self, fake, monkeypatch):
        self._bound(fake, monkeypatch)
        with pytest.raises(HandlerError, match="falloff"):
            rigging.set_region_weights({
                "mesh": "hum", "joint": "a", "faces": [0], "weight": 1.0,
                "falloff": "linear"})

    def test_an_empty_region_is_refused_not_a_noop(self, fake, monkeypatch):
        self._bound(fake, monkeypatch)
        with pytest.raises(HandlerError, match="no vertices"):
            rigging.set_region_weights({
                "mesh": "hum", "joint": "a", "within_radius_of": [99, 99, 99],
                "radius": 0.1, "weight": 1.0})

    def test_out_of_range_face_is_refused(self, fake, monkeypatch):
        self._bound(fake, monkeypatch)
        with pytest.raises(HandlerError, match="face"):
            rigging.set_region_weights({"mesh": "hum", "joint": "a",
                                        "faces": [99], "weight": 1.0})

    def test_sole_owner_vertices_is_measured_from_the_reread(
            self, fake, monkeypatch):
        # Vertex 0 is solely owned by 'a' ([1.0, 0.0]) and is the only vertex
        # within_radius_of picks up; vertex 1 is untouched (outside radius).
        state = self._bound(fake, monkeypatch, weights=(1.0, 0.0, 0.5, 0.5))
        out = rigging.set_region_weights({
            "mesh": "hum", "joint": "a", "within_radius_of": [0, 0, 0],
            "radius": 0.5, "weight": 0.6})
        # It has nobody to shed weight to, so it stays fully owned - the
        # RE-READ table (state["weights"]) proves it, not the request.
        assert state["weights"][:2] == pytest.approx([1.0, 0.0])
        assert out["sole_owner_vertices"] == 1
        assert any("solely owned by a" in w for w in out["warnings"])

        # weight == 1.0 never asks anything to shed - 0 by definition, not by
        # measurement.
        state["weights"] = [1.0, 0.0, 0.5, 0.5]
        out2 = rigging.set_region_weights({
            "mesh": "hum", "joint": "a", "within_radius_of": [0, 0, 0],
            "radius": 0.5, "weight": 1.0})
        assert out2["sole_owner_vertices"] == 0
        assert not any("solely owned" in w for w in out2["warnings"])

    def test_max_influences_exceeded_is_reported_after_blend(
            self, fake, monkeypatch):
        # Vertex 0 already holds 4 other joints at maxInfluences=4; blending
        # in a 5th adds an influence rather than dropping one - nothing
        # prunes a region blend the way smooth_weights prunes. That must be
        # surfaced, not silently left for the exporter to discover.
        joints = ("|r|a", "|r|b", "|r|c", "|r|d", "|r|e")
        self._bound(fake, monkeypatch, positions=(0.0, 0.0, 0.0),
                    weights=(0.25, 0.25, 0.25, 0.25, 0.0), joints=joints)
        out = rigging.set_region_weights({
            "mesh": "hum", "joint": "e", "faces": [0], "weight": 0.5})
        assert out["max_influences_exceeded"] == 1
        assert any("max_influences" in w for w in out["warnings"])


class TestPoseIk:
    def _rig(self, fake, bent=True):
        fake.objects = ["|pelvis", "|pelvis|hip", "|pelvis|hip|knee",
                        "|pelvis|hip|knee|ankle"]
        fake.parents = {"|pelvis|hip": "|pelvis",
                        "|pelvis|hip|knee": "|pelvis|hip",
                        "|pelvis|hip|knee|ankle": "|pelvis|hip|knee"}
        knee_z = 0.05 if bent else 0.0   # bent skips the prebend path
        fake.positions = {"|pelvis": [0.0, 1.0, 0.0],
                          "|pelvis|hip": [0.1, 0.95, 0.0],
                          "|pelvis|hip|knee": [0.1, 0.5, knee_z],
                          "|pelvis|hip|knee|ankle": [0.1, 0.08, 0.0]}
        # ROUND 2 (#799): the fake no longer invents an identity world
        # matrix for any node asked. solve_ik_and_bake reads one per
        # INTERIOR joint to turn a world-space prebend into that joint's
        # local frame, so the fixture declares the frame it means: local
        # axes parallel to world, sitting at the joint.
        fake.matrices = {
            joint: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0] + list(pos) + [1]
            for joint, pos in fake.positions.items()}

    def test_default_start_is_two_joints_up(self, fake):
        self._rig(fake)
        out = rigging.pose_ik({"root": "pelvis", "joint": "ankle",
                               "target": [0.1, 0.6, 0.2]})
        assert out["chain"] == ["|pelvis|hip", "|pelvis|hip|knee",
                                "|pelvis|hip|knee|ankle"]
        made = [c for c in fake.calls if c[0] == "ikHandle"]
        assert made == [("ikHandle", "|pelvis|hip", "|pelvis|hip|knee|ankle",
                         rigging.IK_SOLVER, "ankle_ikh")]

    def test_solve_bake_delete_order(self, fake):
        self._rig(fake)
        out = rigging.pose_ik({"root": "pelvis", "joint": "ankle",
                               "target": [0.1, 0.6, 0.2]})
        names = [c[0] for c in fake.calls]
        # the handle is moved to the target, rotations are read, the IK
        # nodes die, and ONLY THEN the rotations are re-applied as plain FK
        target_set = names.index("xform_set")
        deleted = names.index("delete")
        assert target_set < deleted
        rebakes = [i for i, c in enumerate(fake.calls)
                   if c[0] == "setAttr" and c[1].endswith(".rotate")
                   and i > deleted]
        assert len(rebakes) == 3          # one per chain joint
        # nothing IK-shaped survives
        assert not any("ikh" in o for o in fake.objects)
        assert out["kept"] is True
        assert set(out["rotations"]) == set(out["chain"])

    def test_default_pole_rides_the_bent_knee(self, fake):
        self._rig(fake, bent=True)
        out = rigging.pose_ik({"root": "pelvis", "joint": "ankle",
                               "target": [0.1, 0.6, 0.2]})
        assert out["pole_used"] is not None
        assert out["pole_used"][2] > 0            # knee bends +Z
        assert any(c[0] == "poleVectorConstraint" for c in fake.calls)

    def test_straight_chain_without_pole_warns_and_uses_no_constraint(self, fake):
        self._rig(fake, bent=False)
        out = rigging.pose_ik({"root": "pelvis", "joint": "ankle",
                               "target": [0.1, 0.6, 0.2]})
        assert out["pole_used"] is None
        assert not any(c[0] == "poleVectorConstraint" for c in fake.calls)
        straight = [w for w in out["warnings"] if "STRAIGHT" in w]
        assert straight
        # #814: MEASURED on Maya 2027 - with no pole the knee of a straight
        # chain goes to world +Z every time (the ikHandle's default pole
        # vector), so the warning names that instead of calling it a guess.
        assert "+Z" in straight[0] and "default pole vector" in straight[0]

    def test_straight_chain_with_pole_prebends_the_knee(self, fake):
        self._rig(fake, bent=False)
        rigging.pose_ik({"root": "pelvis", "joint": "ankle",
                         "target": [0.1, 0.6, 0.2], "pole": [0.1, 0.5, 0.5]})
        handle_at = [i for i, c in enumerate(fake.calls)
                     if c[0] == "ikHandle"][0]
        prebends = [i for i, c in enumerate(fake.calls)
                    if c[0] == "setAttr" and c[1] == "|pelvis|hip|knee.rotate"
                    and i < handle_at]
        assert prebends, "the interior joint must be nudged BEFORE the handle exists"
        # regression: preferredAngle seed and restore - no persistent IK state
        pa_calls = [c for c in fake.calls
                    if c[0] == "setAttr" and c[1] == "|pelvis|hip|knee.preferredAngle"]
        assert len(pa_calls) >= 2, (
            "preferredAngle must be set at least twice (seed and restore)")
        assert fake.attrs["|pelvis|hip|knee.preferredAngle"] == [(0.0, 0.0, 0.0)], (
            "the final preferredAngle must restore to the prior value")

    def test_error_inside_the_solve_window_still_cleans_up(self, fake, monkeypatch):
        # regression (#671 final review): a RuntimeError anywhere between
        # ikHandle creation and the doomed-node delete must not leave the
        # handle, effector, pole locator, or a seeded .preferredAngle behind
        # - "no persistent IK state ever exists" has to hold on the error
        # path too, not just the success path.
        self._rig(fake, bent=False)   # prebend path also seeds preferredAngle
        def boom(*a, **kw):
            raise RuntimeError("maya blew up mid-solve")
        monkeypatch.setattr(fake, "poleVectorConstraint", boom)
        with pytest.raises(RuntimeError, match="maya blew up mid-solve"):
            rigging.pose_ik({"root": "pelvis", "joint": "ankle",
                             "target": [0.1, 0.6, 0.2], "pole": [0.1, 0.5, 0.5]})
        assert not any("ikh" in o or "pole" in o for o in fake.objects), (
            "the handle, effector, or pole locator survived the exception")
        assert fake.attrs["|pelvis|hip|knee.preferredAngle"] == [(0.0, 0.0, 0.0)], (
            "the preferredAngle seed must be restored even when the solve "
            "never finished")

    def test_out_of_reach_target_warns_with_the_reach(self, fake):
        self._rig(fake)
        out = rigging.pose_ik({"root": "pelvis", "joint": "ankle",
                               "target": [5.0, 5.0, 5.0]})
        assert any("reaches only" in w for w in out["warnings"])

    def test_keep_false_restores_and_says_so(self, fake):
        self._rig(fake)
        fake.attrs["|pelvis|hip|knee.rotate"] = [(0.0, 7.0, 0.0)]
        out = rigging.pose_ik({"root": "pelvis", "joint": "ankle",
                               "target": [0.1, 0.6, 0.2], "keep": False})
        assert out["kept"] is False
        assert fake.attrs["|pelvis|hip|knee.rotate"] == [(0.0, 7.0, 0.0)]
        assert any("keep=false" in w for w in out["warnings"])

    def test_one_checkpoint_after_validation(self, fake, monkeypatch):
        self._rig(fake)
        events = []
        monkeypatch.setattr(session, "auto_checkpoint",
                            lambda reason: events.append(reason) or
                            {"checkpoint_id": "001_" + reason, "path": "x.ma"})
        with pytest.raises(HandlerError):
            rigging.pose_ik({"root": "pelvis", "joint": "ankle",
                             "target": "not-a-vec"})
        assert events == []
        rigging.pose_ik({"root": "pelvis", "joint": "ankle",
                         "target": [0.1, 0.6, 0.2]})
        assert events == ["pose_ik"]

    def test_refusals(self, fake):
        self._rig(fake)
        with pytest.raises(HandlerError, match="BELOW the root"):
            rigging.pose_ik({"root": "pelvis", "joint": "pelvis",
                             "target": [0, 0, 0]})
        with pytest.raises(HandlerError, match="missing required param 'target'"):
            rigging.pose_ik({"root": "pelvis", "joint": "ankle"})
        with pytest.raises(HandlerError, match="keep must be"):
            rigging.pose_ik({"root": "pelvis", "joint": "ankle",
                             "target": [0, 0, 0], "keep": "yes"})
        with pytest.raises(HandlerError, match="single bone"):
            rigging.pose_ik({"root": "pelvis", "joint": "ankle",
                             "target": [0, 0, 0], "start": "knee"})
        with pytest.raises(HandlerError, match="not an ancestor"):
            rigging.pose_ik({"root": "pelvis", "joint": "knee",
                             "target": [0, 0, 0], "start": "ankle"})
        with pytest.raises(HandlerError, match="no default chain"):
            rigging.pose_ik({"root": "pelvis", "joint": "hip",
                             "target": [0, 0, 0]})
        with pytest.raises(HandlerError, match="not a joint under this root"):
            rigging.pose_ik({"root": "pelvis", "joint": "elbow",
                             "target": [0, 0, 0]})


class TestAPoleOnTheStartTargetLineIsRefused:
    """#797 row 22 (the branch contract's scene row for pose_ik).

    A pole ON the start->target line is a pole with no bend plane, and
    every part of the solve quietly drops it: `plane_normal` is None so
    `prebend_rotations` returns {} and the pre-bend never happens, Maya
    still builds the poleVectorConstraint (a degenerate one), and the
    straight-chain warning - which only fires when NO pole was given -
    stays silent because a pole WAS given. The caller therefore asked for
    a bend direction, got Maya's guess, and was told nothing.
    """

    _rig = TestPoseIk._rig
    # midway along hip[0.1, 0.95, 0] -> target[0.1, 0.6, 0.2]
    ON_LINE = [0.1, 0.775, 0.1]

    def test_a_collinear_pole_refuses_naming_the_branch(self, fake):
        self._rig(fake, bent=False)
        with pytest.raises(HandlerError) as exc:
            rigging.pose_ik({"root": "pelvis", "joint": "ankle",
                             "target": [0.1, 0.6, 0.2], "pole": self.ON_LINE})
        message = str(exc.value)
        assert "pose_ik does not use 'pole'" in message
        assert "start-target line" in message
        assert "bend plane" in message
        assert "knee/elbow" in exc.value.hint

    def test_a_collinear_pole_on_a_BENT_chain_refuses_too(self, fake):
        # The pole's own geometry decides this, not the chain's: a bent
        # chain takes the same degenerate constraint.
        self._rig(fake, bent=True)
        with pytest.raises(HandlerError, match="does not use 'pole'"):
            rigging.pose_ik({"root": "pelvis", "joint": "ankle",
                             "target": [0.1, 0.6, 0.2], "pole": self.ON_LINE})

    def test_the_refusal_precedes_the_checkpoint_and_every_write(
            self, fake, monkeypatch):
        self._rig(fake, bent=False)
        events = []
        monkeypatch.setattr(session, "auto_checkpoint",
                            lambda reason: events.append(reason) or
                            {"checkpoint_id": "001_" + reason, "path": "x.ma"})
        with pytest.raises(HandlerError, match="does not use 'pole'"):
            rigging.pose_ik({"root": "pelvis", "joint": "ankle",
                             "target": [0.1, 0.6, 0.2], "pole": self.ON_LINE})
        assert events == []
        assert not any(c[0] in ("setAttr", "ikHandle", "spaceLocator",
                                "poleVectorConstraint") for c in fake.calls)

    def test_a_pole_off_the_line_is_untouched(self, fake):
        # The negative: the pre-bend path this refusal sits in front of
        # still runs for a pole that HAS a bend plane.
        self._rig(fake, bent=False)
        out = rigging.pose_ik({"root": "pelvis", "joint": "ankle",
                               "target": [0.1, 0.6, 0.2],
                               "pole": [0.1, 0.5, 0.5]})
        assert out["pole_used"] == [0.1, 0.5, 0.5]
        assert any(c[0] == "poleVectorConstraint" for c in fake.calls)

    def test_a_chain_with_no_pole_is_untouched(self, fake):
        # The default pole (or none at all, on a straight chain) is never
        # a param the caller passed - there is nothing to refuse.
        self._rig(fake, bent=False)
        out = rigging.pose_ik({"root": "pelvis", "joint": "ankle",
                               "target": [0.1, 0.6, 0.2]})
        assert out["pole_used"] is None
        assert any("STRAIGHT" in w for w in out["warnings"])

    def test_a_pole_just_off_the_line_scales_with_the_chain(self, fake):
        # The threshold is a FRACTION of reach (COLLINEAR_RATIO), so this
        # ~0.87-long leg accepts a pole 1cm off the line and refuses one
        # a tenth of that.
        self._rig(fake, bent=False)
        accepted = [self.ON_LINE[0] + 0.01, self.ON_LINE[1], self.ON_LINE[2]]
        rigging.pose_ik({"root": "pelvis", "joint": "ankle",
                         "target": [0.1, 0.6, 0.2], "pole": accepted})
        refused = [self.ON_LINE[0] + 0.001, self.ON_LINE[1], self.ON_LINE[2]]
        with pytest.raises(HandlerError, match="does not use 'pole'"):
            rigging.pose_ik({"root": "pelvis", "joint": "ankle",
                             "target": [0.1, 0.6, 0.2], "pole": refused})


class TestClipGuard:
    """#695: while animation curves drive the skeleton, static pose writes
    refuse - a value a curve overrides on the next frame change is the
    quietest way to lie about a pose."""

    def test_pose_skeleton_refuses_on_a_driven_skeleton(self, fake):
        fake.objects += ["|<root>", "|<root>|<child>"]
        fake.parents = {"|<root>|<child>": "|<root>"}
        fake.curve_plugs = {"|<root>|<child>.rotateZ"}
        with pytest.raises(HandlerError, match="animation curves"):
            rigging.pose_skeleton({"root": "<root>",
                                   "rotations": {"<child>": [0, 0, 10]}})

    def test_reset_pose_refuses_on_a_driven_skeleton(self, fake):
        fake.objects += ["|<root>", "|<root>|<child>"]
        fake.parents = {"|<root>|<child>": "|<root>"}
        fake.curve_plugs = {"|<root>.rotateX"}
        with pytest.raises(HandlerError, match="animation curves"):
            rigging.reset_pose({"root": "<root>"})

    def test_pose_ik_refuses_on_a_driven_skeleton(self, fake):
        fake.objects += ["|<root>", "|<root>|<mid>", "|<root>|<mid>|<tip>"]
        fake.parents = {"|<root>|<mid>": "|<root>",
                       "|<root>|<mid>|<tip>": "|<root>|<mid>"}
        fake.curve_plugs = {"|<root>|<mid>.rotateY"}
        with pytest.raises(HandlerError, match="animation curves"):
            rigging.pose_ik({"root": "<root>", "joint": "<tip>",
                             "target": [1.0, 0.0, 0.0], "start": "<root>"})

    def test_an_undriven_skeleton_poses_exactly_as_before(self, fake):
        fake.objects += ["|<root>", "|<root>|<child>"]
        fake.parents = {"|<root>|<child>": "|<root>"}
        # no curve_plugs: the ordinary happy-path pose test body, unchanged
        out = rigging.pose_skeleton({"root": "<root>",
                                     "rotations": {"<child>": [0, 0, 10]}})
        assert out["applied"] == 1


class TestConnectionGuard:
    """#802 FIXED: `guard_static_pose` refuses CURVES, and nothing else.

    Its own docstring counts "FOUR kinds of CURVE" - so a rotate channel a
    CONSTRAINT owns (an orientConstraint, an HIK retarget, an expression, a
    poseInterpolator) and a channel a rigger simply LOCKED both walked past
    it into `cmds.setAttr(joint + ".rotate", ...)`. All three commands ask
    `plugwrite.guard` now, which is the guard
    `correctives._joint_rotation_writable` was and now calls.

    #799 pinned these expecting Maya to refuse every one of those writes.
    The live probe it asked for (evals/static_write_probe_802b.py) found
    that only the LOCK does: a constraint-driven setAttr returns cleanly,
    reads back the value written, and reverts at the next evaluation. So
    the constrained cases were never a traceback - they were a pose the
    tool reported as applied and Maya quietly undid, which is why the fix
    had to be a pre-check and could never have been an except clause.
    """

    @staticmethod
    def _constrained(fake):
        """|r|a's rotation owned by an orientConstraint - which lands per
        CHILD plug, the wiring #796's live gate measured for pairBlend."""
        fake.objects += ["|r", "|r|a"]
        fake.parents = {"|r|a": "|r"}
        fake.node_types = {"|oc1": "orientConstraint"}
        fake.driven_plugs = {"|r|a.rotate%s" % ax: "|oc1.constraintRotate%s" % ax
                             for ax in "XYZ"}

    def test_pose_skeleton_refuses_a_constrained_joint(self, fake):
        """#802 FIXED. guard_static_pose answers for CURVES; this is not one.

        #799 pinned it expecting a raw RuntimeError after the checkpoint.
        Measured (#802, O4/O5/O6): Maya takes that setAttr without a murmur
        and the constraint reasserts on the next evaluation - so the pose
        was reported as applied and then quietly undone. Worse than the
        traceback, and invisible to any except clause.
        """
        self._constrained(fake)
        with pytest.raises(HandlerError, match="connect|constraint|driven"):
            rigging.pose_skeleton({"root": "r",
                                   "rotations": {"a": [0, 0, 10]}})

    @staticmethod
    def _locked(fake):
        """|r|a's rotateX locked by a rigger. ONE axis is enough: the
        handler writes the COMPOUND, and Maya refuses a compound write when
        any child is locked."""
        fake.objects += ["|r", "|r|a"]
        fake.parents = {"|r|a": "|r"}
        fake.locked_plugs = {"|r|a.rotateX"}

    def test_reset_pose_refuses_a_locked_rotate_channel(self, fake):
        """#802 FIXED. A HandlerError where a raw RuntimeError used to be.

        The lock arm IS the one #799 described accurately: Maya refuses a
        compound write when any child of it is locked, with "A child
        attribute of 'x.rotate' is locked or connected" (measured A04).
        """
        self._locked(fake)
        with pytest.raises(HandlerError, match="lock"):
            rigging.reset_pose({"root": "r"})

    def test_reset_pose_refuses_before_it_writes_any_joint(self, fake):
        """#802 FIXED. The refusal lands before the first write.

        reset_pose zeroed |r, Maya then refused |r|a, and nothing rolled |r
        back - the call half-poses the rig and reports nothing. The guard
        now runs before the checkpoint, so the damage it prevents is
        asserted below as an ABSENCE.
        """
        self._locked(fake)
        with pytest.raises((HandlerError, RuntimeError)):
            rigging.reset_pose({"root": "r"})
        # ROUND 2 (#799): the damage a pre-mutation guard prevents, asserted
        # as its ABSENCE. Round 1 asserted the refusal AND the half-write in
        # one body - a pair no fix can satisfy at once, so that strict
        # marker could never XPASS and the fix would have landed unannounced.
        assert not [c for c in fake.calls if c[0] == "setAttr"]

    # ---- pose_ik: the third command, unpinned by #799 rather than given a
    # near-duplicate marker, and fixed here with the other two.

    @staticmethod
    def _chain(fake):
        fake.objects += ["|r", "|r|m", "|r|m|t"]
        fake.parents = {"|r|m": "|r", "|r|m|t": "|r|m"}

    def test_pose_ik_refuses_a_constrained_chain_joint(self, fake):
        self._chain(fake)
        fake.node_types = {"|oc1": "orientConstraint"}
        fake.driven_plugs = {"|r|m.rotateY": "|oc1.constraintRotateY"}
        with pytest.raises(HandlerError, match="connect|constraint|driven"):
            rigging.pose_ik({"root": "r", "joint": "t",
                             "target": [1.0, 0.0, 0.0], "start": "r"})
        assert not [c for c in fake.calls if c[0] == "setAttr"]

    def test_pose_ik_refuses_a_locked_chain_joint(self, fake):
        self._chain(fake)
        fake.locked_plugs = {"|r|m.rotateX"}
        with pytest.raises(HandlerError, match="lock"):
            rigging.pose_ik({"root": "r", "joint": "t",
                             "target": [1.0, 0.0, 0.0], "start": "r"})
        assert not [c for c in fake.calls if c[0] == "setAttr"]

    # preferredAngle: the solve seeds it on the INTERIOR joints, and only
    # when the chain is straight and a pole exists (#671) - so that is the
    # exact set the guard asks about. Review of the first cut measured it
    # guarding every chain joint: on an already-bent limb, the ordinary
    # case, that refused a command for a channel the solve never touches.

    @staticmethod
    def _limb(fake, bent):
        TestPoseIk._rig(None, fake, bent=bent)

    def test_pose_ik_refuses_a_driven_preferred_angle_it_will_seed(self, fake):
        self._limb(fake, bent=False)           # straight: the prebend path
        fake.node_types = {"|sdk1": "animCurveUA"}
        fake.driven_plugs = {"|pelvis|hip|knee.preferredAngleY": "|sdk1.output"}
        with pytest.raises(HandlerError, match="knee.preferredAngle"):
            rigging.pose_ik({"root": "pelvis", "joint": "ankle",
                             "target": [0.1, 0.6, 0.2], "pole": [0.1, 0.5, 1.0]})
        assert not [c for c in fake.calls if c[0] == "setAttr"]

    def test_a_bent_chain_seeds_nothing_so_nothing_is_refused(self, fake):
        self._limb(fake, bent=True)            # bent: no prebend at all
        fake.node_types = {"|sdk1": "animCurveUA"}
        fake.driven_plugs = {"|pelvis|hip|knee.preferredAngleY": "|sdk1.output"}
        out = rigging.pose_ik({"root": "pelvis", "joint": "ankle",
                               "target": [0.1, 0.6, 0.2]})
        assert out["chain"][1] == "|pelvis|hip|knee"

    def test_an_end_joints_preferred_angle_is_never_asked_about(self, fake):
        """chain[0] and chain[-1] never take a preferredAngle write on any
        input; a lock there is a rigger's cleanup, not an obstacle."""
        self._limb(fake, bent=False)
        fake.locked_plugs = {"|pelvis|hip.preferredAngleX",
                             "|pelvis|hip|knee|ankle.preferredAngleZ"}
        out = rigging.pose_ik({"root": "pelvis", "joint": "ankle",
                               "target": [0.1, 0.6, 0.2], "pole": [0.1, 0.5, 1.0]})
        assert out["kept"] is True

    # ---- the ordering plugwrite calls "the point": refuse BEFORE the
    # checkpoint. The class fixture stubs auto_checkpoint with a lambda, so
    # nothing above could see it move below the guard (review catch).

    @staticmethod
    def _no_checkpoint(monkeypatch):
        monkeypatch.setattr(
            session, "auto_checkpoint",
            lambda reason: pytest.fail("checkpointed before refusing (%s)"
                                       % reason))

    def test_pose_skeleton_refuses_before_it_checkpoints(self, fake, monkeypatch):
        self._constrained(fake)
        self._no_checkpoint(monkeypatch)
        with pytest.raises(HandlerError):
            rigging.pose_skeleton({"root": "r", "rotations": {"a": [0, 0, 1]}})

    def test_reset_pose_refuses_before_it_checkpoints(self, fake, monkeypatch):
        self._locked(fake)
        self._no_checkpoint(monkeypatch)
        with pytest.raises(HandlerError):
            rigging.reset_pose({"root": "r"})

    def test_pose_ik_refuses_before_it_checkpoints(self, fake, monkeypatch):
        self._chain(fake)
        fake.locked_plugs = {"|r|m.rotateX"}
        self._no_checkpoint(monkeypatch)
        with pytest.raises(HandlerError):
            rigging.pose_ik({"root": "r", "joint": "t",
                             "target": [1.0, 0.0, 0.0], "start": "r"})

    # ---- reset_pose has two branches with two write sets, and the one that
    # runs on every BOUND rig is dagPose -restore, which returns a whole
    # transform (review catch: the first cut guarded .rotate for both).

    def test_a_bound_rig_with_a_locked_translate_is_refused(self, fake):
        self._locked(fake)
        fake.locked_plugs = {"|r|a.translateY"}
        fake.bind_poses = ["bindPose1"]
        with pytest.raises(HandlerError, match="translateY"):
            rigging.reset_pose({"root": "r"})
        assert not [c for c in fake.calls if c[0] == "dagPose"
                    and c[2].get("restore")]

    def test_a_bound_rig_with_a_locked_scale_still_resets(self, fake):
        """Riggers lock joint scale as a matter of course, and the bind pose
        holds the scale the joint already has - refusing there would cost
        every production rig the command for nothing."""
        self._locked(fake)
        fake.locked_plugs = {"|r|a.scaleX"}
        fake.bind_poses = ["bindPose1"]
        out = rigging.reset_pose({"root": "r"})
        assert out["reset"] is True

    def test_an_unbound_rig_with_a_locked_translate_still_zeroes(self, fake):
        """No bind pose: the zeroing loop writes .rotate and nothing else,
        so a locked translate is not an obstacle to it."""
        self._locked(fake)
        fake.locked_plugs = {"|r|a.translateY"}
        out = rigging.reset_pose({"root": "r"})
        assert out["reset"] is True
        assert [c for c in fake.calls if c[0] == "setAttr"]

    def test_a_joint_outside_the_write_set_is_not_refused(self, fake):
        """pose_skeleton guards the joints it will WRITE, not the whole
        hierarchy: refusing because some unrelated joint elsewhere on an
        ordinary control rig is constrained would make the command unusable
        on exactly the rigs it is for. A guard that over-refuses gets
        weakened back by the next reader (#799's lesson, both directions).
        """
        fake.objects += ["|r", "|r|a", "|r|b"]
        fake.parents = {"|r|a": "|r", "|r|b": "|r"}
        fake.node_types = {"|oc1": "orientConstraint"}
        fake.driven_plugs = {"|r|b.rotateX": "|oc1.constraintRotateX"}
        out = rigging.pose_skeleton({"root": "r",
                                     "rotations": {"a": [0, 0, 10]}})
        assert out["applied"] == 1


class TestPositionsSurviveExplicitOrient:
    """#719: `orient` used to cost the caller their positions. Maya lays a
    child's translate in the PARENT's frame, so overwriting a parent's
    jointOrient swings its children through world space - asked for
    (0, 2.05, 0), the #713 golem measured (0.33, 1.72, 0). The requested
    world positions are the contract, so they are re-asserted after
    orienting. Real placement is mayapy's job
    (TestCreateSkeletonPositionsInMaya); this pins the call SEQUENCE.
    """

    @staticmethod
    def _sets(fake):
        return [c for c in fake.calls if c[0] == "xform_set"]

    def test_every_joint_is_re_asserted_parents_first(self, fake):
        rigging.create_skeleton({"joints": [
            {"name": "jnt_root", "position": [0, 0, 0]},
            {"name": "jnt_torso", "position": [0, 2.05, 0],
             "parent": "jnt_root", "orient": [0, 0, 0]},
            {"name": "jnt_head", "position": [0, 3.4, 0],
             "parent": "jnt_torso", "orient": [0, 0, 0]},
        ]})
        assert self._sets(fake) == [
            ("xform_set", "|jnt_root", (0, 0, 0)),
            ("xform_set", "|jnt_root|jnt_torso", (0, 2.05, 0)),
            ("xform_set", "|jnt_root|jnt_torso|jnt_head", (0, 3.4, 0)),
        ]

    def test_the_re_assertion_follows_the_orient_writes(self, fake):
        """Before them it would be undone by the very edit that moves them."""
        rigging.create_skeleton({"joints": [
            {"name": "a", "position": [0, 0, 0]},
            {"name": "b", "position": [0, 2, 0], "parent": "a",
             "orient": [0, 0, 0]},
        ]})
        kinds = [c[0] for c in fake.calls]
        assert kinds.index("xform_set") > max(
            i for i, c in enumerate(fake.calls)
            if c[0] == "setAttr" and "jointOrient" in c[1])

    def test_an_auto_oriented_chain_is_re_asserted_too(self, fake):
        """No orient given: the positions are the same contract, and the
        re-assertion must be a no-op rather than a special case."""
        rigging.create_skeleton({"chain": [[0, 0, 0], [0, 2, 0]],
                                 "chain_prefix": "c"})
        assert [c[2] for c in self._sets(fake)] == [(0, 0, 0), (0, 2, 0)]


class TestBoundMeshes:
    """#720: two rig shapes are legal. A skinned mesh is found through its
    skinCluster; a rigid-parent rig (#713 - chunks parented under joints, no
    deformer at all) is found structurally. Reporting zero displacement for
    the second shape is an echo, not a measurement (#636).
    """

    @staticmethod
    def _hierarchy(fake, parents, shapes):
        """Wire the fake for shape queries and type-filtered descendants.

        The base fake answers children queries only and ignores `type`; real
        Maya excludes shapes from type="transform" and returns mesh shapes
        for shapes=True.
        """
        fake.parents = dict(parents)
        fake.shapes = dict(shapes)
        shape_nodes = set(shapes.values())

        def listRelatives(node, shapes=False, type=None, **kw):
            if shapes:
                shape = fake.shapes.get(node)
                if shape is None or type not in (None, "mesh"):
                    return None
                return [shape]
            out = FakeCmds.listRelatives(fake, node, **kw) or []
            if type == "transform":
                out = [n for n in out if n not in shape_nodes]
            return out or None
        fake.listRelatives = listRelatives

    def test_finds_rigidly_parented_children(self, fake):
        """A chunk parented under a joint moves with it, skinCluster or not."""
        self._hierarchy(
            fake,
            parents={"|root|jnt_torso": "|root",
                     "|root|jnt_torso|torso_plates": "|root|jnt_torso",
                     "|root|jnt_torso|torso_plates|torso_platesShape":
                         "|root|jnt_torso|torso_plates"},
            shapes={"|root|jnt_torso|torso_plates":
                    "|root|jnt_torso|torso_plates|torso_platesShape"})
        found = rigging._bound_meshes(fake, {"|root|jnt_torso"})
        assert found == ["|root|jnt_torso|torso_plates"]

    def test_a_chunk_under_a_descendant_joint_counts_too(self, fake):
        """The skeleton MOVES it - depth through the joint chain is not a
        reason to call the displacement zero."""
        self._hierarchy(
            fake,
            parents={"|root|jnt_a": "|root",
                     "|root|jnt_a|jnt_b": "|root|jnt_a",
                     "|root|jnt_a|jnt_b|shin": "|root|jnt_a|jnt_b",
                     "|root|jnt_a|jnt_b|shin|shinShape":
                         "|root|jnt_a|jnt_b|shin"},
            shapes={"|root|jnt_a|jnt_b|shin": "|root|jnt_a|jnt_b|shin|shinShape"})
        assert rigging._bound_meshes(fake, {"|root|jnt_a", "|root|jnt_a|jnt_b"}) \
            == ["|root|jnt_a|jnt_b|shin"]

    def test_a_shapeless_group_under_a_joint_is_not_a_mesh(self, fake):
        """Locators, empty groups and child joints are not geometry."""
        self._hierarchy(
            fake,
            parents={"|root|jnt_a": "|root",
                     "|root|jnt_a|grp_empty": "|root|jnt_a"},
            shapes={})
        assert rigging._bound_meshes(fake, {"|root|jnt_a"}) == []

    def test_a_skinned_mesh_that_is_also_a_descendant_appears_once(self, fake):
        self._hierarchy(
            fake,
            parents={"|root|jnt_a": "|root",
                     "|root|jnt_a|body": "|root|jnt_a",
                     "|root|jnt_a|body|bodyShape": "|root|jnt_a|body"},
            shapes={"|root|jnt_a|body": "|root|jnt_a|body|bodyShape"})
        fake.skin_clusters = ["skinCluster1"]
        fake.skin_influences = {"skinCluster1": ["|root|jnt_a"]}
        fake.skin_geometry = {"skinCluster1": ["|root|jnt_a|body|bodyShape"]}
        assert rigging._bound_meshes(fake, {"|root|jnt_a"}) == ["|root|jnt_a|body"]

    def test_an_unrelated_skinned_mesh_is_unaffected(self, fake):
        """The skinned path is untouched: a mesh bound to these joints but
        living outside their hierarchy still comes back."""
        self._hierarchy(
            fake,
            parents={"|root|jnt_a": "|root",
                     "|meshA|meshAShape": "|meshA"},
            shapes={"|meshA": "|meshA|meshAShape"})
        fake.skin_clusters = ["scA"]
        fake.skin_influences = {"scA": ["|root|jnt_a"]}
        fake.skin_geometry = {"scA": ["|meshA|meshAShape"]}
        assert rigging._bound_meshes(fake, {"|root|jnt_a"}) == ["|meshA"]


class TestTheFakeRefusesWhatMayaRefuses:
    """#799 round 2: the regression barrier for THIS file's FakeCmds.

    Round 1 hardened the fake and nothing asserted the hardening - a
    reviewer measured that reverting every behavioural change left the
    suite fully green, which is this ticket's own "a green suite proves
    nothing" moved up one level. Every assertion below fails the day
    someone loosens the fake back toward answering anything.

    Only what this fake models is pinned here: it has no setKeyframe (no
    rigging handler calls one), so the driven-key/pairBlend return codes
    belong to the files whose fakes do.
    """

    _GONE = "No object matches name"

    def test_a_node_no_fixture_created_raises_from_every_query(self, fake):
        fake.objects = ["|r"]
        calls = [
            lambda: fake.nodeType("|ghost"),
            lambda: fake.listRelatives("|ghost", children=True),
            lambda: fake.listRelatives("|ghost", shapes=True),
            lambda: fake.listHistory("|ghost"),
            lambda: fake.getAttr("|ghost.rotate"),
            lambda: fake.setAttr("|ghost.rotate", 0.0, 0.0, 0.0),
            lambda: fake.xform("|ghost", query=True, worldSpace=True,
                               translation=True),
            lambda: fake.delete("|ghost"),
            lambda: fake.attributeQuery("mcp_clip", node="|ghost",
                                        exists=True),
            lambda: fake.listConnections("|ghost.rotate", source=True),
        ]
        for call in calls:
            with pytest.raises(RuntimeError, match=self._GONE):
                call()
        # `ls` answers nothing rather than inventing the name back, which is
        # what makes naming.require_object able to refuse at all.
        assert fake.ls("|ghost") == []
        assert fake.ls(["|ghost"]) == []
        assert fake.objExists("|ghost") is False

    def test_a_deleted_node_stops_answering(self, fake):
        fake.objects = ["|r", "|r|a"]
        fake.parents = {"|r|a": "|r"}
        assert fake.nodeType("|r|a") == "joint"
        fake.delete("|r|a")
        with pytest.raises(RuntimeError, match=self._GONE):
            fake.nodeType("|r|a")
        assert fake.ls("|r|a") == []
        assert fake.objExists("|r|a") is False

    def test_a_delete_by_short_name_kills_the_long_name(self, fake):
        # Round-1 minor: `deleted.append(n)` stored the literal string the
        # caller used while the liveness filter matched exact names, so a
        # short-name delete tombstoned nothing and the node kept answering.
        fake.objects = ["|r", "|r|a"]
        fake.parents = {"|r|a": "|r"}
        fake.delete("a")
        with pytest.raises(RuntimeError, match=self._GONE):
            fake.nodeType("|r|a")
        assert fake.objExists("a") is False
        assert fake.ls("a") == []

    def test_deleting_a_parent_takes_its_children_and_shape(self, fake):
        fake.objects = ["|r", "|r|a"]
        fake.parents = {"|r|a": "|r"}
        fake.shapes = {"|r|a": "|r|a|aShape"}
        fake.delete("|r")
        for gone in ("|r", "|r|a", "|r|a|aShape"):
            with pytest.raises(RuntimeError, match=self._GONE):
                fake.nodeType(gone)

    def test_a_name_created_again_answers_again(self, fake):
        # The other direction: a PERMANENT tombstone is a fake wrong in the
        # strict direction, and Maya keeps no memory of a deleted name.
        fake.spaceLocator(name="pole1")
        fake.delete("|pole1")
        with pytest.raises(RuntimeError, match=self._GONE):
            fake.nodeType("|pole1")
        fake.spaceLocator(name="pole1")
        assert fake.objExists("|pole1") is True

    def test_a_write_to_a_fed_plug_refuses_in_both_compound_directions(
            self, fake):
        fake.objects = ["|r|a"]
        fake.node_types = {"|oc1": "orientConstraint", "|pb1": "pairBlend"}
        # the connection landed on the CHILD; the handler writes the compound
        fake.driven_plugs = {"|r|a.rotateX": "|oc1.constraintRotateX"}
        with pytest.raises(RuntimeError, match="locked or connected"):
            fake.setAttr("|r|a.rotate", 0.0, 0.0, 0.0)
        # the connection landed on the COMPOUND; the handler writes a child
        fake.driven_plugs = {"|r|a.translate": "|pb1.outTranslate"}
        with pytest.raises(RuntimeError, match="locked or connected"):
            fake.setAttr("|r|a.translateY", 1.0)
        # and it does NOT over-refuse: a free channel still writes. A fake
        # wrong in the strict direction is as bad as a permissive one.
        fake.setAttr("|r|a.scaleY", 2.0)
        assert ("setAttr", "|r|a.scaleY", (2.0,)) in fake.calls

    def test_an_animation_curve_refuses_the_same_write(self, fake):
        fake.objects = ["|r|a"]
        fake.curve_plugs = ["|r|a.rotateY"]
        with pytest.raises(RuntimeError, match="locked or connected"):
            fake.setAttr("|r|a.rotate", 0.0, 0.0, 0.0)

    def test_a_locked_channel_refuses_and_getAttr_lock_reports_it(self, fake):
        fake.objects = ["|r|a"]
        fake.locked_plugs = {"|r|a.rotateX"}
        with pytest.raises(RuntimeError, match="locked"):
            fake.setAttr("|r|a.rotate", 0.0, 0.0, 0.0)
        # ROUND 2: `lock=True` is MODELLED. It used to fall into **kw and
        # drop through to the compound default [(0,0,0)] - truthy - so a
        # guard shaped like correctives._joint_rotation_writable would have
        # called every joint in the scene locked, and the two reset_pose
        # xfails above could never have XPASSed.
        assert fake.getAttr("|r|a.rotateX", lock=True) is True
        assert fake.getAttr("|r|a.rotateY", lock=True) is False
        assert fake.getAttr("|r|a.rotate", lock=True) is False

    def test_an_xform_translate_refuses_a_fed_translate(self, fake):
        fake.objects = ["|loc"]
        fake.node_types = {"|pb1": "pairBlend"}
        fake.driven_plugs = {"|loc.translateY": "|pb1.outTranslateY"}
        with pytest.raises(RuntimeError, match="locked or connected"):
            fake.xform("|loc", worldSpace=True, translation=[0.0, 1.0, 0.0])

    def test_xform_invents_neither_a_matrix_nor_a_component_position(
            self, fake):
        # Round-1 minor: an invented [1,2,3] for any plug or component of
        # any live node, and an invented identity matrix for any node - the
        # fallback the report blames for ten fictional TestPoseIk asserts.
        fake.objects = ["|hum"]
        with pytest.raises(AssertionError, match="no matrix declared"):
            fake.xform("|hum", query=True, worldSpace=True, matrix=True)
        with pytest.raises(AssertionError, match="no position declared"):
            fake.xform("|hum.vtx[999]", query=True, worldSpace=True,
                       translation=True)
        # An undeclared mesh has NO points to give - not one vertex at
        # (1,2,3) that never moves however the rig is posed.
        assert fake.xform("|hum.vtx[*]", query=True, worldSpace=True,
                          translation=True) == []
        fake.vertex_tables = {"|hum": [0.0, 1.0, 0.0]}
        assert fake.xform("|hum.vtx[*]", query=True, worldSpace=True,
                          translation=True) == [0.0, 1.0, 0.0]

    def test_only_geometry_answers_a_deformer_history(self, fake):
        # Round-1 minor: ONE global history answered for every node, so a
        # bare joint read as bound to whatever mesh a fixture had bound and
        # "is not bound" could only fire by emptying skin_history globally.
        fake.objects = ["|hum", "|hum|humShape", "|r", "|r|a"]
        fake.parents = {"|r|a": "|r"}
        fake.skin_history = ["skin1"]
        assert fake.listHistory("|hum|humShape") == ["skin1"]
        assert fake.listHistory("|r|a") == []

    def test_a_shapes_query_never_answers_children(self, fake):
        fake.objects = ["|r", "|r|a"]
        fake.parents = {"|r|a": "|r"}
        assert fake.listRelatives("|r", shapes=True) is None
        assert fake.listRelatives("|r", children=True) == ["|r|a"]
        fake.shapes = {"|r": "|r|rShape"}
        assert fake.listRelatives("|r", shapes=True) == ["|r|rShape"]

    def test_listConnections_models_sources_and_derived_types(self, fake):
        fake.objects = ["|r|a"]
        fake.node_types = {"|crv1": "animCurveTA"}
        fake.driven_plugs = {"|r|a.rotateX": "|crv1.output"}
        assert fake.listConnections("|r|a.rotateX", source=True,
                                    plugs=True) == ["|crv1.output"]
        # Maya's type filter matches DERIVED types (the #796 defect-1 trap)
        assert fake.listConnections("|r|a.rotateX", source=True,
                                    type="animCurve") == ["|crv1"]
        assert fake.listConnections("|r|a.rotateX", source=True,
                                    type="pairBlend") is None
        with pytest.raises(AssertionError, match="source queries only"):
            fake.listConnections("|r|a.rotateX", destination=True)

    def test_attributeQuery_and_getAttr_answer_only_what_was_declared(
            self, fake):
        fake.objects = ["|r"]
        fake.string_attrs = {"|r": {"mcp_clip": "walk"}}
        assert fake.attributeQuery("mcp_clip", node="|r", exists=True) is True
        assert fake.attributeQuery("nope", node="|r", exists=True) is False
        assert fake.getAttr("|r.mcp_clip") == "walk"
        # An attribute nothing declared is not a zero - it is a refusal.
        with pytest.raises(RuntimeError, match=self._GONE):
            fake.getAttr("|r.maxInfluences")
