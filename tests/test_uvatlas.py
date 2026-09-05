"""maya_uv_atlas: do the UVs actually LAND in the patch?

The fake carries real UV coordinates and applies polyEditUV to them, so these
tests measure the resulting bounds instead of asserting that a command ran.
That distinction is the #587 lesson: the flare was "verified" by the mesh still
having vertices, which proved nothing about the feature.
"""

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import units, uvatlas, uvmath

_CM_PER_UNIT = units._CM_PER_UNIT


class FakeCmds:
    """A mesh whose UVs start somewhere unhelpful, so normalisation matters."""

    def __init__(self, objects=("|box",), shapes=None, uvs=None, world_m=3.0,
                 linear="m", bbox=(-1.0, 0.0, -1.0, 1.0, 0.0, 1.0)):
        # #822: world bbox the planar branch reads to pick its axis. The
        # default is a flat sheet lying in XZ (thin on Y).
        self.bbox = list(bbox)
        # Default "m" keeps every pre-existing test measuring what it always
        # measured; the maya-mcp #635 tests below set it explicitly.
        self.linear = linear
        self.world_m = world_m
        self.objects = list(objects)
        self.shapes = (
            dict(shapes)
            if shapes is not None
            else {o: (o + "Shape", "mesh") for o in self.objects}
        )
        # deliberately NOT 0..1: a raw polyCube's UVs span a bigger range
        self.uvs = list(uvs if uvs is not None else [(-2.0, 3.0), (4.0, 7.0)])
        self.calls = []
        self.normalize_types = []
        # #799 contract 1: what stopped existing. uv_atlas deletes nothing
        # itself, but it is handed shapes by callers that do (assemble packs
        # each part between a taper bake and a polyUnite), so a query about a
        # node Maya no longer has must raise here as it does everywhere else.
        self.deleted = []

    # --- existence ---------------------------------------------------------
    def _live(self, name):
        node = name.split(".")[0]      # ".map[*]" / ".f[*]" name their shape
        known = list(self.objects) + [s for s, _k in self.shapes.values()]
        if node in known:
            return True
        if node.startswith("|"):
            return False
        return any(n.split("|")[-1] == node for n in known)

    def _require(self, name):
        if not self._live(name):
            raise RuntimeError("No object matches name: %s" % name.split(".")[0])

    def ls(self, pattern=None, long=False, **kwargs):
        if pattern is None:
            hits = list(self.objects)
        else:
            hits = [n for n in self.objects
                    if n == pattern or n.split("|")[-1] == pattern]
        return hits if long else [h.split("|")[-1] for h in hits]

    def objExists(self, name):
        return bool(self.ls(name))

    def listRelatives(self, node, shapes=False, fullPath=False,
                      noIntermediate=False, **kwargs):
        self._require(node)
        if shapes:
            entry = self.shapes.get(node)
            return [entry[0]] if entry else None
        return None

    def nodeType(self, node):
        # #799 contract 1+3: a node that is gone raises rather than answering
        # "transform", which _require_mesh would have reported as the far
        # milder "not a polygon mesh".
        self._require(node)
        for _t, (shape, kind) in self.shapes.items():
            if shape == node:
                return kind
        return "transform"

    def currentUnit(self, query=False, linear=None):
        assert query and linear is True, "uv_atlas must only QUERY the unit"
        return self.linear

    # --- uv operations -----------------------------------------------------
    def polyAutoProjection(self, target, **kwargs):
        self._require(target)
        self.calls.append("polyAutoProjection:sm=%s" % kwargs.get("scaleMode"))
        if kwargs.get("scaleMode") == 0:
            # World-proportional. Measured on Maya 2027: polyAutoProjection
            # sizes UVs from Maya's INTERNAL centimetres, so the constant
            # tracks the scene's linear unit - 100 UV units per metre with the
            # scene in "m", and 1.0 with it in "cm" (maya-mcp #635, measured by
            # evals/combine_uv_live.py in both). The fake reproduces that
            # dependency rather than a fixed factor, so a handler that ignores
            # the scene unit cannot pass.
            extent = self.world_m * _CM_PER_UNIT[self.linear]
            self.uvs = [(0.0, 0.0), (extent, extent)]
        else:
            self.uvs = [(0.0, 0.0), (1.0, 1.0)]

    def exactWorldBoundingBox(self, name):
        self._require(name)
        return list(self.bbox)

    def polyProjection(self, target, **kwargs):
        self._require(target)
        self.calls.append("polyProjection:%s:%s" % (kwargs.get("type"), kwargs.get("md")))
        self.uvs = [(0.0, 0.0), (1.0, 1.0)]

    def polyNormalizeUV(self, target, **kwargs):
        self._require(target)
        self.calls.append("polyNormalizeUV")
        # #845: the MODE is the whole defect. Maya's normalizeType=0 scales
        # every face to the full square on its own; 1 is the collective one.
        # The fake normalises collectively whichever mode it is handed, which
        # is exactly why no test could see the wrong mode - so it records it.
        self.normalize_types.append(kwargs.get("normalizeType"))
        us = [u for u, _ in self.uvs]
        vs = [v for _, v in self.uvs]
        du = (max(us) - min(us)) or 1.0
        dv = (max(vs) - min(vs)) or 1.0
        self.uvs = [((u - min(us)) / du, (v - min(vs)) / dv) for u, v in self.uvs]

    def polyEditUV(self, target=None, **kwargs):
        self._require(target)
        self.calls.append("polyEditUV")
        su = kwargs.get("scaleU", 1.0)
        sv = kwargs.get("scaleV", 1.0)
        pu = kwargs.get("pivotU", 0.0)
        pv = kwargs.get("pivotV", 0.0)
        du = kwargs.get("uValue", 0.0)
        dv = kwargs.get("vValue", 0.0)
        self.uvs = [
            ((u - pu) * su + pu + du, (v - pv) * sv + pv + dv) for u, v in self.uvs
        ]

    def polyEvaluate(self, node, **kwargs):
        self._require(node)
        if kwargs.get("boundingBox2d"):
            us = [u for u, _ in self.uvs]
            vs = [v for _, v in self.uvs]
            return [[min(us), max(us)], [min(vs), max(vs)]]
        if kwargs.get("boundingBoxComponent2d"):
            # Real Maya (2027, measured): the COMPONENT form returns zeros when
            # handed a shape rather than a component selection. The fake used
            # to answer it as if it worked, which let the handler ship with the
            # wrong flag through a green suite - so it now lies exactly the way
            # Maya lies.
            return [[0.0, 0.0], [0.0, 0.0]]
        if kwargs.get("uvcoord") or kwargs.get("uv"):
            return len(self.uvs)
        # #799 contract 3: no answers-anything fallback. A flag the fixture
        # never modelled used to come back as 0 - a plausible-looking count
        # that no test could fail on.
        raise AssertionError("unmodelled polyEvaluate flags: %r" % (kwargs,))


def _run(fake, **params):
    uvatlas._cmds = lambda: fake  # noqa: SLF001 - the module's only Maya seam
    return uvatlas.uv_atlas(params)


class TestLanding:
    def test_uvs_end_up_inside_the_requested_patch(self):
        fake = FakeCmds()
        out = _run(fake, names=["|box"], cols=4, rows=4, patch=6, margin=0.0)
        rect = uvmath.patch_rect(4, 4, 2, 1)
        assert out["meshes"][0]["uv_bounds"] == pytest.approx(list(rect))

    def test_margin_defaults_to_a_small_non_zero_inset(self):
        # Deliberate: an atlas patch that runs to its own edge bleeds into its
        # neighbour under bilinear filtering. Callers who want an exact fit ask
        # for margin=0.
        out = _run(FakeCmds(), names=["|box"], cols=4, rows=4, patch=0)
        assert out["margin"] > 0.0
        assert out["meshes"][0]["uv_bounds"][0] > 0.0

    def test_measured_bounds_are_reported_per_mesh(self):
        out = _run(FakeCmds(), names=["|box"], cols=2, rows=2, patch=[1, 1])
        assert out["meshes"][0]["inside_patch"] is True
        assert out["patch"] == [1, 1]

    def test_margin_pulls_the_uvs_off_the_patch_edge(self):
        fake = FakeCmds()
        out = _run(fake, names=["|box"], cols=4, rows=4, patch=0, margin=0.1)
        rect = uvmath.patch_rect(4, 4, 0, 0, margin=0.1)
        assert out["meshes"][0]["uv_bounds"] == pytest.approx(list(rect))
        # and strictly inside the un-inset patch
        bare = uvmath.patch_rect(4, 4, 0, 0)
        assert out["meshes"][0]["uv_bounds"][0] > bare[0]
        assert out["meshes"][0]["uv_bounds"][3] < bare[3]

    def test_a_single_patch_atlas_fills_the_whole_square(self):
        out = _run(FakeCmds(), names=["|box"], cols=1, rows=1, patch=0, margin=0.0)
        assert out["meshes"][0]["uv_bounds"] == pytest.approx([0.0, 0.0, 1.0, 1.0])

    def test_several_meshes_land_in_the_same_patch(self):
        fake = FakeCmds(objects=("|a", "|b"))
        out = _run(fake, names=["|a", "|b"], cols=8, rows=8, patch=17)
        assert len(out["meshes"]) == 2
        assert out["meshes"][0]["uv_bounds"] == pytest.approx(
            out["meshes"][1]["uv_bounds"]
        )


class TestOrderAndModes:
    def test_normalises_before_fitting(self):
        # Without normalisation first, an arbitrary incoming UV range lands
        # scaled by the wrong factor - the whole point of the step.
        fake = FakeCmds()
        _run(fake, names=["|box"], cols=4, rows=4, patch=0)
        assert fake.calls.index("polyNormalizeUV") < fake.calls.index("polyEditUV")

    def test_box_projection_is_the_default(self):
        fake = FakeCmds()
        _run(fake, names=["|box"], cols=2, rows=2, patch=0)
        assert any(c.startswith("polyAutoProjection") for c in fake.calls)

    def test_keep_does_not_reproject(self):
        fake = FakeCmds(uvs=[(0.0, 0.0), (1.0, 1.0)])
        _run(fake, names=["|box"], cols=2, rows=2, patch=0, project="keep")
        assert not any(c.startswith("poly" + "AutoProjection") for c in fake.calls)
        assert not any(c.startswith("polyProjection") for c in fake.calls)

    def test_planar_projection_runs_along_the_sheet_s_thin_axis(self, monkeypatch):
        # #822 measured: md="z" is WORLD -z whatever the mesh faces - a sheet
        # facing X collapsed 16/16 faces to zero UV area, silently. The axis
        # now follows the mesh's thinnest world extent.
        monkeypatch.setattr(uvatlas, "_face_uv_loops", lambda cmds, shape: [])
        fake = FakeCmds()                                   # lying flat: thin on Y
        _run(fake, names=["|box"], cols=2, rows=2, patch=0, project="planar")
        assert "polyProjection:Planar:y" in fake.calls
        fake = FakeCmds(bbox=(0, -1, -1, 0, 1, 1))          # standing: thin on X
        _run(fake, names=["|box"], cols=2, rows=2, patch=0, project="planar")
        assert "polyProjection:Planar:x" in fake.calls
        fake = FakeCmds(bbox=(-1, -1, -1, 1, 1, 1))         # a solid: z, the old default
        _run(fake, names=["|box"], cols=2, rows=2, patch=0, project="planar")
        assert "polyProjection:Planar:z" in fake.calls

    def test_normalisation_can_be_declined(self):
        fake = FakeCmds(uvs=[(0.0, 0.0), (1.0, 1.0)])
        _run(fake, names=["|box"], cols=2, rows=2, patch=0,
             project="keep", normalize=False)
        assert "polyNormalizeUV" not in fake.calls


class TestPlanarHonesty:
    """#822: planar cannot be made to suit a solid, so it has to SAY what it
    did - the faces edge-on to the projection collapse to zero UV area (a
    cube: 4 of 6) and the far side of a sphere lands mirrored on the near
    side (200 of 400)."""

    SQUARE = [(0, 0), (1, 0), (1, 1), (0, 1)]
    MIRRORED = [(0, 0), (0, 1), (1, 1), (1, 0)]
    LINE = [(0, 0), (1, 0), (1, 0), (0, 0)]

    def test_collapsed_faces_are_named_in_warnings(self, monkeypatch):
        fake = FakeCmds()
        monkeypatch.setattr(uvatlas, "_face_uv_loops",
                            lambda cmds, shape: [self.SQUARE, self.SQUARE] + [self.LINE] * 4)
        out = _run(fake, names=["|box"], cols=2, rows=2, patch=0, project="planar")
        assert len(out["warnings"]) == 1
        assert "4 of 6" in out["warnings"][0] and "|box" in out["warnings"][0]

    def test_mirrored_faces_are_named_in_warnings(self, monkeypatch):
        fake = FakeCmds()
        monkeypatch.setattr(uvatlas, "_face_uv_loops",
                            lambda cmds, shape: [self.SQUARE] * 3 + [self.MIRRORED] * 2)
        out = _run(fake, names=["|box"], cols=2, rows=2, patch=0, project="planar")
        assert len(out["warnings"]) == 1
        assert "2 of 5" in out["warnings"][0] and "mirrored" in out["warnings"][0]

    def test_a_flat_sheet_warns_about_nothing(self, monkeypatch):
        fake = FakeCmds()
        monkeypatch.setattr(uvatlas, "_face_uv_loops", lambda cmds, shape: [self.SQUARE] * 16)
        out = _run(fake, names=["|box"], cols=2, rows=2, patch=0, project="planar")
        assert out["warnings"] == []

    def test_box_projection_never_reads_the_faces(self, monkeypatch):
        fake = FakeCmds()
        monkeypatch.setattr(uvatlas, "_face_uv_loops",
                            lambda cmds, shape: pytest.fail("box projection measured faces"))
        out = _run(fake, names=["|box"], cols=2, rows=2, patch=0)
        assert out["warnings"] == []


class TestRejections:
    def test_rejects_an_empty_name_list(self):
        with pytest.raises(HandlerError):
            _run(FakeCmds(), names=[], cols=2, rows=2, patch=0)

    def test_rejects_a_missing_object(self):
        with pytest.raises(HandlerError):
            _run(FakeCmds(), names=["|nope"], cols=2, rows=2, patch=0)

    def test_rejects_a_non_mesh(self):
        fake = FakeCmds(objects=("|c",), shapes={"|c": ("|cShape", "nurbsCurve")})
        with pytest.raises(HandlerError) as excinfo:
            _run(fake, names=["|c"], cols=2, rows=2, patch=0)
        assert "mesh" in str(excinfo.value).lower()

    def test_rejects_an_unknown_projection_mode(self):
        with pytest.raises(HandlerError):
            _run(FakeCmds(), names=["|box"], cols=2, rows=2, patch=0,
                 project="spherical-ish")

    def test_rejects_a_patch_outside_the_grid(self):
        with pytest.raises(HandlerError):
            _run(FakeCmds(), names=["|box"], cols=2, rows=2, patch=99)


class TestWorldScale:
    """Texel density decided by real-world size, not by filling the patch.

    This is the mode that makes a STATED density possible: a 3 m slab and a
    0.5 m band must carry the same pixels per metre, or a wall reads as a model
    of a wall.
    """

    def test_a_full_cell_piece_fills_the_patch(self):
        fake = FakeCmds(world_m=3.0)
        out = _run(fake, names=["|box"], cols=4, rows=4, patch=0,
                   margin=0.0, world_scale=3.0)
        rect = uvmath.patch_rect(4, 4, 0, 0, margin=0.0)
        assert out["meshes"][0]["uv_bounds"] == pytest.approx(list(rect))

    def test_a_sixth_size_piece_uses_a_sixth_of_the_patch(self):
        fake = FakeCmds(world_m=0.5)
        out = _run(fake, names=["|box"], cols=4, rows=4, patch=0,
                   margin=0.0, world_scale=3.0)
        bounds = out["meshes"][0]["uv_bounds"]
        rect = uvmath.patch_rect(4, 4, 0, 0, margin=0.0)
        # 0.5 m of a 3 m patch: one sixth of the width, and it must stay inside.
        # abs tolerance because the handler reports uv_bounds rounded to 6 dp.
        assert (bounds[2] - bounds[0]) == pytest.approx(
            (rect[2] - rect[0]) / 6.0, abs=2e-6
        )
        assert out["meshes"][0]["inside_patch"] is True

    def test_a_full_cell_piece_fills_the_patch_in_a_CENTIMETRE_scene(self):
        # maya-mcp #635: identical call, identical authored size, only the
        # scene unit differs - and cm is what new_scene now forces (#634).
        # With the default hard-coded to the metre-scene constant this lands at
        # 1/100th of the patch and every texture reads 100x too fine.
        fake = FakeCmds(world_m=3.0, linear="cm")
        out = _run(fake, names=["|box"], cols=4, rows=4, patch=0,
                   margin=0.0, world_scale=3.0)
        rect = uvmath.patch_rect(4, 4, 0, 0, margin=0.0)
        assert out["meshes"][0]["uv_bounds"] == pytest.approx(list(rect))

    def test_the_default_uv_per_metre_follows_the_scene_unit(self):
        for unit, expected in (("cm", 1.0), ("m", 100.0), ("mm", 0.1)):
            out = _run(FakeCmds(linear=unit), names=["|box"], cols=4, rows=4,
                       patch=0, margin=0.0, world_scale=3.0)
            assert out["uv_per_metre"] == expected, unit

    def test_an_explicit_uv_per_metre_still_overrides_the_scene(self):
        # The generators pass 1.0 explicitly (evals/maya_export.py). Deriving
        # the DEFAULT must not take that override away from them.
        out = _run(FakeCmds(linear="m"), names=["|box"], cols=4, rows=4,
                   patch=0, margin=0.0, world_scale=3.0, uv_per_metre=1.0)
        assert out["uv_per_metre"] == 1.0

    def test_density_is_identical_across_sizes(self):
        # The property the whole mode exists for, stated as a ratio.
        big = _run(FakeCmds(world_m=3.0), names=["|box"], cols=4, rows=4,
                   patch=0, margin=0.0, world_scale=3.0)["meshes"][0]["uv_bounds"]
        small = _run(FakeCmds(world_m=0.5), names=["|box"], cols=4, rows=4,
                     patch=0, margin=0.0, world_scale=3.0)["meshes"][0]["uv_bounds"]
        big_per_m = (big[2] - big[0]) / 3.0
        small_per_m = (small[2] - small[0]) / 0.5
        assert big_per_m == pytest.approx(small_per_m, abs=1e-5)

    def test_the_piece_is_centred_in_its_patch(self):
        fake = FakeCmds(world_m=1.0)
        out = _run(fake, names=["|box"], cols=4, rows=4, patch=5,
                   margin=0.0, world_scale=3.0)
        rect = uvmath.patch_rect(4, 4, 1, 1, margin=0.0)
        bounds = out["meshes"][0]["uv_bounds"]
        assert (bounds[0] + bounds[2]) / 2 == pytest.approx((rect[0] + rect[2]) / 2)
        assert (bounds[1] + bounds[3]) / 2 == pytest.approx((rect[1] + rect[3]) / 2)

    def test_uses_world_proportional_projection(self):
        fake = FakeCmds(world_m=3.0)
        _run(fake, names=["|box"], cols=4, rows=4, patch=0, world_scale=3.0)
        assert "polyAutoProjection:sm=0" in fake.calls

    def test_does_not_normalise(self):
        # Normalising would destroy the world proportion this mode depends on.
        fake = FakeCmds(world_m=3.0)
        out = _run(fake, names=["|box"], cols=4, rows=4, patch=0, world_scale=3.0)
        assert "polyNormalizeUV" not in fake.calls
        assert out["normalized"] is False

    def test_a_piece_too_big_for_the_density_is_reported_not_hidden(self):
        # 6 m of geometry at 3 m per patch cannot fit; it must come back with
        # inside_patch false rather than silently spilling into the neighbour.
        fake = FakeCmds(world_m=6.0)
        out = _run(fake, names=["|box"], cols=4, rows=4, patch=0,
                   margin=0.0, world_scale=3.0)
        assert out["meshes"][0]["inside_patch"] is False
        assert out["all_inside"] is False

    def test_world_scale_is_reported(self):
        out = _run(FakeCmds(), names=["|box"], cols=4, rows=4, patch=0,
                   world_scale=3.0)
        assert out["world_scale"] == 3.0
        assert out["projection"] == "world"

    @pytest.mark.parametrize("bad", [0, -1.0, "3m", True])
    def test_rejects_a_nonsense_world_scale(self, bad):
        with pytest.raises(HandlerError):
            _run(FakeCmds(), names=["|box"], cols=4, rows=4, patch=0,
                 world_scale=bad)


class TestTheFakeRefusesWhatMayaRefuses:
    """The regression barrier for #799's hardening of THIS fake.

    Round 1 taught the fake to refuse what Maya refuses. A round-2 review
    then measured that forcing `_live` to True - a complete revert to the
    answers-anything fake - left the suite green, because no assertion read
    the refusal. Each test below pins one contract point, so loosening the
    fake goes RED here.
    """

    def test_a_query_about_a_node_that_never_existed_raises(self):
        fake = FakeCmds()
        with pytest.raises(RuntimeError):
            fake.nodeType("|ghost")
        with pytest.raises(RuntimeError):
            fake.polyEvaluate("|ghost", boundingBox2d=True)
        with pytest.raises(RuntimeError):
            fake.polyAutoProjection("|ghost", scaleMode=0)

    def test_a_query_about_a_node_that_stopped_existing_raises(self):
        # uv_atlas deletes nothing itself, but assemble hands it shapes
        # between a taper bake and a polyUnite that consumes them.
        fake = FakeCmds()
        fake.objects.remove("|box")
        fake.shapes.pop("|box")
        fake.deleted.append("|box")
        with pytest.raises(RuntimeError):
            fake.nodeType("|boxShape")
        with pytest.raises(RuntimeError):
            fake.polyEditUV("|boxShape.map[*]", scaleU=0.5, scaleV=0.5)

    def test_a_component_names_its_shape_and_is_answered(self):
        # The strict direction is a defect too: ".map[*]" and ".f[*]" are
        # components of a shape that DOES exist, and every call this handler
        # makes is addressed that way.
        fake = FakeCmds()
        fake.polyEditUV("|boxShape.map[*]", scaleU=1.0, scaleV=1.0)
        assert fake.calls == ["polyEditUV"]

    def test_a_name_freed_by_a_delete_is_live_again_once_recreated(self):
        fake = FakeCmds()
        fake.objects.remove("|box")
        fake.shapes.pop("|box")
        fake.deleted.append("|box")
        fake.objects.append("|box")
        fake.shapes["|box"] = ("|boxShape", "mesh")
        assert fake.nodeType("|boxShape") == "mesh"

    def test_an_unmodelled_polyevaluate_flag_refuses_rather_than_answering_0(self):
        # The removed answers-anything tail: a flag this fixture never
        # modelled used to come back as a plausible-looking 0.
        fake = FakeCmds()
        with pytest.raises(AssertionError):
            fake.polyEvaluate("|boxShape", triangle=True)

    def test_a_shape_that_exists_still_answers_its_own_type(self):
        # The refusal must not swallow the ordinary case: a node that IS
        # there answers, and a non-mesh answers non-mesh rather than raising
        # - which is what keeps _require_mesh's "not a polygon mesh" message
        # reachable and distinct from "no object matches name".
        curve = FakeCmds(objects=("|box",),
                         shapes={"|box": ("|boxShape", "nurbsCurve")})
        assert curve.nodeType("|boxShape") == "nurbsCurve"
        with pytest.raises(HandlerError) as exc:
            _run(curve, names=["|box"], cols=4, rows=4, patch=0)
        assert "mesh" in str(exc.value).lower()


class TestTheBranchDropsIt:
    """#797: a param world-scale mode drops is REFUSED, not silently applied.

    `project="keep"` under world_scale was DESTRUCTIVE, not merely ignored:
    the world branch box-autoprojects unconditionally, so a caller asking to
    preserve an authored layout got it overwritten and was told the packing
    succeeded.

    Every refusal here fires before uv_atlas touches Maya - `_no_maya`
    replaces `_cmds` with a raiser, so a refusal that slipped back below it
    fails with that AssertionError instead of a HandlerError.
    """

    @pytest.fixture
    def _no_maya(self, monkeypatch):
        def boom():
            raise AssertionError(
                "uv_atlas reached Maya before refusing the inert param")

        monkeypatch.setattr(uvatlas, "_cmds", boom)

    # --- row 8: world_scale box-projects whatever project asked for -------

    @pytest.mark.parametrize("mode", ["keep", "planar"])
    def test_project_is_refused_under_world_scale(self, _no_maya, mode):
        with pytest.raises(HandlerError) as exc:
            uvatlas.uv_atlas({"names": ["|box"], "world_scale": 2.0,
                              "project": mode})
        assert "does not use 'project'" in str(exc.value)
        assert "world_scale" in str(exc.value)

    def test_project_box_is_what_world_mode_does_so_it_stands(self):
        out = _run(FakeCmds(), names=["|box"], cols=4, rows=4, patch=0,
                   world_scale=3.0, project="box")
        assert out["projection"] == "world"

    def test_an_unpassed_project_is_not_a_passed_one(self):
        """The wrapper sends project=None on every call since #797; keying
        the refusal on the key rather than the value would refuse every
        world-scale pack ever made."""
        out = _run(FakeCmds(), names=["|box"], cols=4, rows=4, patch=0,
                   world_scale=3.0, project=None)
        assert out["projection"] == "world"

    # --- the wrapper's new None defaults --------------------------------

    def test_a_null_normalize_still_normalises(self):
        """`normalize=None` is the wrapper saying the caller said nothing -
        the isinstance(bool) check would have refused it outright."""
        fake = FakeCmds()
        out = _run(fake, names=["|box"], cols=2, rows=2, patch=0,
                   normalize=None)
        assert "polyNormalizeUV" in fake.calls
        assert out["normalized"] is True

    def test_a_null_project_still_box_projects(self):
        fake = FakeCmds()
        _run(fake, names=["|box"], cols=2, rows=2, patch=0, project=None)
        assert any(c.startswith("polyAutoProjection") for c in fake.calls)

    # --- row 10: uv_per_metre is the world-scale density constant ---------

    def test_uv_per_metre_without_world_scale_is_refused(self, _no_maya):
        with pytest.raises(HandlerError) as exc:
            uvatlas.uv_atlas({"names": ["|box"], "uv_per_metre": 1.0})
        assert "does not use 'uv_per_metre'" in str(exc.value)
        assert "world_scale" in str(exc.value)

    def test_the_normalising_modes_report_no_density_constant(self):
        """It used to echo autoproj_uv_per_metre(cmds) on every call, world
        mode or not - a stated texel density for a pack that fitted the mesh
        to the patch instead, which is a different density per mesh."""
        out = _run(FakeCmds(linear="m"), names=["|box"], cols=4, rows=4,
                   patch=0)
        assert out["uv_per_metre"] is None

    def test_world_mode_reports_the_constant_it_applied(self):
        out = _run(FakeCmds(linear="m"), names=["|box"], cols=4, rows=4,
                   patch=0, margin=0.0, world_scale=3.0)
        assert out["uv_per_metre"] == 100.0

    # --- the result field protocol.md already promised --------------------

    def test_the_result_carries_the_warnings_list_it_documents(self):
        out = _run(FakeCmds(), names=["|box"], cols=4, rows=4, patch=0)
        assert out["warnings"] == []


class TestNormalisationMode:
    def test_normalises_collectively_not_per_face(self):
        """redmine #845. MEASURED on Maya 2027: polyNormalizeUV normalizeType=0
        normalises EACH FACE separately - every face of a projected cube came
        back spanning the whole 0..1 square - and normalizeType=1 is the
        collective mode. The tool sent 0 for its whole life with a comment
        claiming the opposite; the overall bbox is 0..1 either way, so
        uv_bounds could never tell."""
        fake = FakeCmds()
        _run(fake, names=["|box"], cols=4, rows=4, patch=0)
        assert fake.normalize_types == [1]
