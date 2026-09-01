import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import naming


class FakeCmds:
    """A scene of transforms, each optionally carrying one shape.

    #799. `require_object` reads what `ls` hands back as a COUNT of nodes, so
    what this fake resolves - and how many entries it returns per node - is the
    resolution shape every other fake in this suite copies. Three rules:

      1. every query about a node this scene does not hold RAISES the way Maya
         does ("No object matches name"); `objExists` is the one exception, it
         is the question you ask precisely BECAUSE you do not know.
      2. does not apply: naming.py makes no static write - no setAttr, no
         xform, nothing that a connection or a lock could refuse.
      3. nothing answers unconditionally. `nodeType` used to raise
         AssertionError for anything that was not a registered shape, which
         made a legitimate question about a transform look like a test bug;
         it now answers "transform" for a node the scene really holds and
         raises Maya's own error for one it does not.

    `ls` resolves SHAPES as well as transforms, because Maya's does: a caller
    that hands `ls` a shape long name and reads the answer as "this shape
    exists" is right in Maya and was wrong here.
    """

    def __init__(self, objects=None, shapes=None):
        self.objects = set(objects or [])
        self.shapes = shapes or {}  # long transform -> (shape_long, node_type)
        self.deleted = []           # every name delete() has taken away

    # -- resolution -------------------------------------------------------
    def _live(self):
        """Every node name the scene currently holds, shapes included."""
        names = set(self.objects) | {s for s, _ in self.shapes.values()}
        return names - set(self.deleted)

    def _matches(self, name):
        """`ls`'s answer: one entry per node whose long OR short name matches.

        Sorted, so an ambiguous resolution reports the same first candidate
        in its hint every run.
        """
        return sorted(n for n in self._live()
                      if n == name or n.split("|")[-1] == name)

    def _require(self, name):
        if not self._matches(name):
            raise RuntimeError("No object matches name: %s" % name)

    def objExists(self, name):
        return bool(self._matches(name))

    def ls(self, name, long=False):
        assert long
        return self._matches(name)

    def listRelatives(self, node, shapes=False, fullPath=False, noIntermediate=False):
        assert shapes and fullPath and noIntermediate
        self._require(node)
        entry = self.shapes.get(node)
        if not entry or entry[0] in self.deleted:
            return None
        return [entry[0]]

    def nodeType(self, node):
        self._require(node)
        for shape, ntype in self.shapes.values():
            if shape == node:
                return ntype
        return "transform"

    def delete(self, *names):
        """Maya's delete takes the whole SUBTREE, so a transform's shape dies
        with it (#799 round 2). Marking only the name that was passed left
        `ls`/`nodeType` answering happily about a shape whose parent had gone,
        which is the answers-anything shape this fake exists to refuse - and
        this is the resolution layer test_material.py and test_pbr.py copy.
        """
        for name in names:
            self._require(name)
            resolved = self._matches(name)[0]
            self.deleted.append(resolved)
            entry = self.shapes.get(resolved)
            if entry:
                self.deleted.append(entry[0])


def test_unique_name_passthrough_when_free():
    assert naming.unique_name(FakeCmds(), "golem_arm") == "golem_arm"


def test_unique_name_deterministic_suffix():
    fake = FakeCmds(objects={"golem_arm", "golem_arm_001"})
    assert naming.unique_name(fake, "golem_arm") == "golem_arm_002"


def test_require_object_missing_has_hint():
    with pytest.raises(HandlerError) as exc:
        naming.require_object(FakeCmds(), "|nope")
    assert "maya_get_scene_graph" in exc.value.hint


def test_require_object_ambiguous_short_name():
    fake = FakeCmds(objects={"|a|torso", "|b|torso"})
    with pytest.raises(HandlerError) as exc:
        naming.require_object(fake, "torso")
    assert "ambiguous" in str(exc.value)


def test_require_mesh_rejects_non_mesh():
    fake = FakeCmds(
        objects={"|keyLight"},
        shapes={"|keyLight": ("|keyLight|keyLightShape", "pointLight")},
    )
    with pytest.raises(HandlerError) as exc:
        naming.require_mesh(fake, "|keyLight")
    assert "not a polygon mesh" in str(exc.value)


def test_require_mesh_returns_long_names():
    fake = FakeCmds(
        objects={"|golem|torso"},
        shapes={"|golem|torso": ("|golem|torso|torsoShape", "mesh")},
    )
    assert naming.require_mesh(fake, "|golem|torso") == (
        "|golem|torso",
        "|golem|torso|torsoShape",
    )


def test_a_mesh_whose_shape_was_deleted_is_refused_not_asked_about():
    # #799 contract point 1, on the shape of the defect #796 shipped: the
    # transform survives its shape's deletion, so require_mesh gets a live
    # node with nothing under it. It must refuse on the empty shape list and
    # never ask nodeType about the vanished shape - in Maya that question
    # raises "No object matches name" instead of answering.
    fake = FakeCmds(
        objects={"|golem|torso"},
        shapes={"|golem|torso": ("|golem|torso|torsoShape", "mesh")},
    )
    fake.delete("|golem|torso|torsoShape")
    with pytest.raises(HandlerError) as exc:
        naming.require_mesh(fake, "|golem|torso")
    assert "not a polygon mesh" in str(exc.value)


class TestTheFakeRefusesWhatMayaRefuses:
    """#799 round 2: the hardening above has to be ASSERTED somewhere.

    Reverting any of these behaviours in FakeCmds used to leave the whole
    suite green - the exact "a green suite proves nothing" failure this
    ticket exists to remove, moved up one level into the harness. These
    tests are the regression barrier: loosen the fake and they go red.
    Only what THIS fake models is asserted here; naming.py makes no static
    write, so there is no setAttr/xform contract to pin in this file.
    """

    def _scene(self):
        return FakeCmds(
            objects={"|golem|torso"},
            shapes={"|golem|torso": ("|golem|torso|torsoShape", "mesh")},
        )

    def test_a_question_about_a_node_that_never_existed_raises(self):
        fake = self._scene()
        for call in (lambda: fake.nodeType("|ghost"),
                     lambda: fake.listRelatives("|ghost", shapes=True,
                                                fullPath=True,
                                                noIntermediate=True),
                     lambda: fake.delete("|ghost")):
            with pytest.raises(RuntimeError, match="No object matches name"):
                call()

    def test_objExists_is_the_one_question_that_answers_instead(self):
        # It is the question you ask BECAUSE you do not know.
        assert self._scene().objExists("|ghost") is False

    def test_a_question_about_a_deleted_node_raises(self):
        fake = self._scene()
        fake.delete("|golem|torso")
        assert fake.objExists("|golem|torso") is False
        with pytest.raises(RuntimeError, match="No object matches name"):
            fake.nodeType("|golem|torso")

    def test_deleting_a_transform_takes_its_shape_with_it(self):
        fake = self._scene()
        fake.delete("|golem|torso")
        assert fake.objExists("|golem|torso|torsoShape") is False
        assert fake.ls("|golem|torso|torsoShape", long=True) == []
        with pytest.raises(RuntimeError, match="No object matches name"):
            fake.nodeType("|golem|torso|torsoShape")

    def test_ls_resolves_a_shape_the_way_maya_does(self):
        # The fallback that was removed: `ls` used to answer from transforms
        # only, so a shape long name looked like a node that did not exist.
        fake = self._scene()
        assert fake.ls("|golem|torso|torsoShape", long=True) == [
            "|golem|torso|torsoShape"]
        assert fake.nodeType("|golem|torso|torsoShape") == "mesh"

    def test_nodeType_answers_transform_only_for_a_node_that_is_there(self):
        # The other removed fallback: this used to raise AssertionError for
        # every non-shape, which made a legitimate question look like a bug.
        fake = self._scene()
        assert fake.nodeType("|golem|torso") == "transform"
