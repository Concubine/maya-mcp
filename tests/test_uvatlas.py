"""maya_uv_atlas: do the UVs actually LAND in the patch?

The fake carries real UV coordinates and applies polyEditUV to them, so these
tests measure the resulting bounds instead of asserting that a command ran.
That distinction is the #587 lesson: the flare was "verified" by the mesh still
having vertices, which proved nothing about the feature.
"""

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import uvatlas, uvmath


class FakeCmds:
    """A mesh whose UVs start somewhere unhelpful, so normalisation matters."""

    def __init__(self, objects=("|box",), shapes=None, uvs=None):
        self.objects = list(objects)
        self.shapes = (
            dict(shapes)
            if shapes is not None
            else {o: (o + "Shape", "mesh") for o in self.objects}
        )
        # deliberately NOT 0..1: a raw polyCube's UVs span a bigger range
        self.uvs = list(uvs if uvs is not None else [(-2.0, 3.0), (4.0, 7.0)])
        self.calls = []

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
        if shapes:
            entry = self.shapes.get(node)
            return [entry[0]] if entry else None
        return None

    def nodeType(self, node):
        for _t, (shape, kind) in self.shapes.items():
            if shape == node:
                return kind
        return "transform"

    # --- uv operations -----------------------------------------------------
    def polyAutoProjection(self, target, **kwargs):
        self.calls.append("polyAutoProjection")
        self.uvs = [(0.0, 0.0), (1.0, 1.0)]

    def polyProjection(self, target, **kwargs):
        self.calls.append("polyProjection:%s" % kwargs.get("type"))
        self.uvs = [(0.0, 0.0), (1.0, 1.0)]

    def polyNormalizeUV(self, target, **kwargs):
        self.calls.append("polyNormalizeUV")
        us = [u for u, _ in self.uvs]
        vs = [v for _, v in self.uvs]
        du = (max(us) - min(us)) or 1.0
        dv = (max(vs) - min(vs)) or 1.0
        self.uvs = [((u - min(us)) / du, (v - min(vs)) / dv) for u, v in self.uvs]

    def polyEditUV(self, target=None, **kwargs):
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
        return 0


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
        assert "polyAutoProjection" in fake.calls

    def test_keep_does_not_reproject(self):
        fake = FakeCmds(uvs=[(0.0, 0.0), (1.0, 1.0)])
        _run(fake, names=["|box"], cols=2, rows=2, patch=0, project="keep")
        assert not any(c.startswith("poly" + "AutoProjection") for c in fake.calls)
        assert not any(c.startswith("polyProjection") for c in fake.calls)

    def test_planar_projection_is_requested_by_name(self):
        fake = FakeCmds()
        _run(fake, names=["|box"], cols=2, rows=2, patch=0, project="planar")
        assert "polyProjection:Planar" in fake.calls

    def test_normalisation_can_be_declined(self):
        fake = FakeCmds(uvs=[(0.0, 0.0), (1.0, 1.0)])
        _run(fake, names=["|box"], cols=2, rows=2, patch=0,
             project="keep", normalize=False)
        assert "polyNormalizeUV" not in fake.calls


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
