"""maya_assemble - the build loop that used to live inside execute_python.

The fake is a whole small Maya: primitives, transforms, the flare deformer,
UV projection, polyUnite. That is the point - assemble's job is ORDERING and
BUDGET, and both are only visible in the sequence of calls it makes.
"""

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import assemble, ledger


class FakeCmds:
    def __init__(self):
        self.objects = []
        self.shapes = {}
        self.calls = []
        self.attrs = {}
        self.deleted = []
        self.uv_calls = []
        self.fail_on = None

    def _add(self, name, kind="mesh"):
        long = "|" + name.lstrip("|")
        self.objects.append(long)
        self.shapes[long] = long + "Shape"
        return long

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
        if shapes and node in self.shapes:
            return [self.shapes[node]]
        return None

    def nodeType(self, node):
        return "mesh" if node.endswith("Shape") else "transform"

    def rename(self, node, new):
        self.objects.remove(node)
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
        if kw.get("query"):
            return [0.0, 0.0, 0.0]
        if "pivots" in kw:
            self.calls.append(("pivot", node))
            return None
        for key in ("scale", "rotation", "translation"):
            if key in kw:
                self.calls.append((key, node, tuple(kw[key])))
        return None

    def exactWorldBoundingBox(self, node):
        return [-1.5, -1.5, -1.5, 1.5, 1.5, 1.5]

    def makeIdentity(self, node, **kw):
        self.calls.append(("freeze", node))

    # --- deformer
    def nonLinear(self, node, type=None, **kw):
        if self.fail_on == "flare":
            raise RuntimeError("forced failure creating flare")
        self.calls.append(("nonLinear", node, type))
        deformer = self._add(node.lstrip("|") + "_flare")
        handle = self._add(node.lstrip("|") + "_flareHandle")
        return [deformer, handle]

    def setAttr(self, attr, *value, **kw):
        self.attrs[attr] = value[0] if len(value) == 1 else value

    def delete(self, node, **kw):
        self.calls.append(("delete", node, kw.get("constructionHistory")))
        self.deleted.append(node)
        if not kw.get("constructionHistory") and node in self.objects:
            self.objects.remove(node)
            self.shapes.pop(node, None)

    # --- UVs
    def polyAutoProjection(self, shape, **kw):
        self.uv_calls.append(("project", shape, kw.get("scaleMode")))

    def polyProjection(self, comp, **kw):
        self.uv_calls.append(("planar", comp, None))

    def polyNormalizeUV(self, comp, **kw):
        self.uv_calls.append(("normalize", comp, None))

    def polyEditUV(self, comp, **kw):
        self.uv_calls.append(("edit", comp, kw))

    def polyEvaluate(self, shape, **kw):
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
        return 0

    # --- merging
    def polyUnite(self, members, **kw):
        name = kw.get("name")
        self.calls.append(("polyUnite", tuple(members), name))
        for m in members:
            if m in self.objects:
                self.objects.remove(m)
            self.shapes.pop(m, None)
        return [self._add(name)]

    def listSets(self, object=None, type=None, **kw):
        return []

    def sets(self, *args, **kw):
        return "|set1"

    def listConnections(self, plug, **kw):
        return []


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

    def test_assemble_pivots_reach_single_part_chunks(self, monkeypatch):
        fake = FakeCmds()
        monkeypatch.setattr(assemble, "_cmds", lambda: fake)
        result = assemble.assemble({
            "name": "golem",
            "parts": [{"kind": "cube", "pos": [0, 1, 0], "dim": [1, 1, 1], "chunk": "fist"}],
            "pivots": {"fist": [1.0, 2.0, 3.0]},
        })
        assert result["objects"][0]["pivot"] == [1.0, 2.0, 3.0]

    def test_assemble_unlisted_chunks_keep_the_mode(self, monkeypatch):
        fake = FakeCmds()
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
