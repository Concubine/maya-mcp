"""maya_array handler: does it drive Maya correctly?

The NUMBERS are Task 1's job (tests/test_arraymath.py). What is tested here is
the driving: that the right command ran on the right node in the right order.
The fake below reproduces Maya's behaviour where it MATTERS - notably that
cmds.ls returns short names unless long=True is passed, which is the exact lie
that hid a live-only bug through a green suite in #584.
"""

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import array


class FakeCmds:
    def __init__(self, objects=("|tooth",)):
        self.objects = list(objects)
        self.calls = []           # (command, primary_target) in order
        self.attrs = {}           # "node.attr" -> value
        self.xforms = {}          # long name -> dict of relative deltas applied
        self.parents = {}         # child -> parent
        self._dup_n = 0

    # --- name resolution ---------------------------------------------------
    def ls(self, pattern=None, long=False, **kwargs):
        if pattern is None:
            return list(self.objects) if long else [n.split("|")[-1] for n in self.objects]
        hits = [n for n in self.objects if n == pattern or n.split("|")[-1] == pattern]
        return hits if long else [h.split("|")[-1] for h in hits]

    def objExists(self, name):
        return bool(self.ls(name))

    # --- creation ----------------------------------------------------------
    def duplicate(self, source, name=None, returnRootsOnly=False, **kwargs):
        self._dup_n += 1
        new = "|" + (name or ("%s_dup%d" % (source.split("|")[-1], self._dup_n)))
        self.objects.append(new)
        self.calls.append(("duplicate", source))
        return [new]

    def group(self, *members, **kwargs):
        name = kwargs.get("name") or "group1"
        grp = "|" + name
        self.objects.append(grp)
        for m in members:
            self.parents[m] = grp
        self.calls.append(("group", grp))
        return grp

    def parent(self, child, target=None, world=False, **kwargs):
        self.parents.pop(child, None)
        self.calls.append(("parent", child))
        return [child]

    def delete(self, name, **kwargs):
        self.calls.append(("delete", name))
        if name in self.objects and not kwargs:
            self.objects.remove(name)

    # --- transforms --------------------------------------------------------
    def xform(self, name, query=False, **kwargs):
        if query:
            if kwargs.get("translation"):
                return [0.0, 0.0, 0.0]
            if kwargs.get("rotation"):
                return [0.0, 0.0, 0.0]
            if kwargs.get("scale"):
                return [1.0, 1.0, 1.0]
            if kwargs.get("boundingBox"):
                return [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
            return [0.0, 0.0, 0.0]
        self.calls.append(("xform", name))
        record = self.xforms.setdefault(name, [])
        record.append({k: v for k, v in kwargs.items() if k != "query"})
        return None

    def rotate(self, rx, ry, rz, name, **kwargs):
        self.calls.append(("rotate", name))
        self.xforms.setdefault(name, []).append(
            {"rotate": [rx, ry, rz], "pivot": kwargs.get("pivot")}
        )

    def setAttr(self, plug, *values, **kwargs):
        self.calls.append(("setAttr", plug))
        self.attrs[plug] = values[0] if len(values) == 1 else list(values)

    def getAttr(self, plug, **kwargs):
        return self.attrs.get(plug, 0.0)

    def makeIdentity(self, name, **kwargs):
        self.calls.append(("makeIdentity", name))

    def polyNormal(self, name, **kwargs):
        self.calls.append(("polyNormal", name))

    def listRelatives(self, name, **kwargs):
        return None

    def nodeType(self, name):
        return "mesh"


@pytest.fixture
def fake(monkeypatch):
    f = FakeCmds()
    monkeypatch.setattr(array, "_cmds", lambda: f)
    return f


class TestValidation:
    def test_rejects_unknown_mode(self, fake):
        with pytest.raises(HandlerError):
            array.array({"name": "|tooth", "mode": "spiral", "count": 4})

    def test_rejects_missing_source(self, fake):
        with pytest.raises(HandlerError):
            array.array({"name": "|nope", "mode": "radial", "count": 4})

    def test_radial_rejects_count_below_two(self, fake):
        with pytest.raises(HandlerError):
            array.array({"name": "|tooth", "mode": "radial", "count": 1})


class TestRadial:
    def test_makes_count_minus_one_copies(self, fake):
        result = array.array(
            {"name": "|tooth", "mode": "radial", "count": 12, "axis": "y"}
        )
        assert len(result["names"]) == 11

    def test_every_copy_is_rotated_about_the_given_center(self, fake):
        array.array(
            {"name": "|tooth", "mode": "radial", "count": 4, "axis": "y",
             "center": [0.0, 3.0, 0.0]}
        )
        rotations = [c for c in fake.calls if c[0] == "rotate"]
        assert len(rotations) == 3
        for name, *_ in [(c[1],) for c in rotations]:
            applied = fake.xforms[name][-1]
            assert applied["pivot"] == (0.0, 3.0, 0.0)

    def test_rotation_angles_follow_the_full_circle_rule(self, fake):
        array.array({"name": "|tooth", "mode": "radial", "count": 4, "axis": "y"})
        applied = [
            fake.xforms[c[1]][-1]["rotate"][1]
            for c in fake.calls
            if c[0] == "rotate"
        ]
        assert applied == pytest.approx([90.0, 180.0, 270.0])

    def test_rotates_about_the_named_axis_only(self, fake):
        array.array({"name": "|tooth", "mode": "radial", "count": 3, "axis": "z"})
        first = fake.xforms[[c[1] for c in fake.calls if c[0] == "rotate"][0]][-1]
        assert first["rotate"][0] == 0.0 and first["rotate"][1] == 0.0
        assert first["rotate"][2] != 0.0

    def test_signed_volume_is_not_reported_for_radial(self, fake):
        result = array.array({"name": "|tooth", "mode": "radial", "count": 3})
        assert result["signed_volume"] is None


class TestLinear:
    def test_makes_count_minus_one_copies(self, fake):
        result = array.array(
            {"name": "|tooth", "mode": "linear", "count": 9, "offset": [0.0, 1.5, 0.0]}
        )
        assert len(result["names"]) == 8

    def test_offsets_accumulate_down_the_run(self, fake):
        array.array(
            {"name": "|tooth", "mode": "linear", "count": 4, "offset": [0.0, 2.0, 0.0]}
        )
        moved = [
            entry["translation"][1]
            for name in fake.xforms
            for entry in fake.xforms[name]
            if "translation" in entry
        ]
        assert sorted(moved) == pytest.approx([2.0, 4.0, 6.0])

    def test_scale_compounds(self, fake):
        array.array(
            {"name": "|tooth", "mode": "linear", "count": 4,
             "offset": [1.0, 0.0, 0.0], "step_scale": [0.5, 0.5, 0.5]}
        )
        scales = [
            entry["scale"][0]
            for name in fake.xforms
            for entry in fake.xforms[name]
            if "scale" in entry
        ]
        assert sorted(scales, reverse=True) == pytest.approx([0.5, 0.25, 0.125])

    def test_linear_requires_an_offset(self, fake):
        with pytest.raises(HandlerError):
            array.array({"name": "|tooth", "mode": "linear", "count": 4})


class TestNamingAndGrouping:
    def test_copies_take_the_source_name_as_prefix_by_default(self, fake):
        result = array.array({"name": "|tooth", "mode": "radial", "count": 3})
        assert all("tooth" in n for n in result["names"])

    def test_name_prefix_overrides(self, fake):
        result = array.array(
            {"name": "|tooth", "mode": "radial", "count": 3, "name_prefix": "cog"}
        )
        assert all("cog" in n for n in result["names"])

    def test_no_group_by_default(self, fake):
        result = array.array({"name": "|tooth", "mode": "radial", "count": 3})
        assert result["group"] is None

    def test_group_name_parents_the_copies(self, fake):
        result = array.array(
            {"name": "|tooth", "mode": "radial", "count": 3, "group_name": "gear"}
        )
        assert result["group"] is not None
        assert ("group", result["group"]) in fake.calls

    def test_source_is_never_reparented(self, fake):
        array.array(
            {"name": "|tooth", "mode": "radial", "count": 3, "group_name": "gear"}
        )
        # Grouping the user's own object under our new group would silently
        # move it in the hierarchy; only the copies belong to us.
        assert "|tooth" not in fake.parents
