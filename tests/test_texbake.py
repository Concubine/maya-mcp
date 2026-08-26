"""#714 phase 2: what maya_bake_textures refuses, before it touches anything.

Every refusal here is grounded in a MEASURED probe finding, not caution:
convertSolidTx does not raise on a UV-less mesh (it writes a flat, useless
image), so the tool must catch that itself; and a normal slot with no
bump2d in the chain has no measured surviving wiring shape.
"""

import os

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import texbake


def _fake_bake(fake):
    """Stand in for convertSolidTx: write a real (tiny) PNG at the path the
    tool asked for, so the part-file/commit machinery is exercised for
    real while the pixels come from the monkeypatched uniformity check."""
    def _bake(cmds, source_plug, target, path, resolution):
        with open(path, "wb") as fh:
            fh.write(b"\x89PNG\r\n\x1a\n" + b"x" * 64)
        fake.baked_calls.append((source_plug, target, path, resolution))
    return _bake


class FakeCmds:
    """|body (shape |bodyShape) wears bodySG -> skin_mat; a noise drives
    baseColor. UV count and shading graph are per-test knobs."""

    def __init__(self, uv_count=64):
        self.uv_count = uv_count
        self.meshes = {"|body": "|bodyShape"}
        self.types = {"skin_mat": "standardSurface", "mcpTex_noise": "noise"}
        self.sets = {"|bodyShape": ["bodySG"]}
        self.conns = {"bodySG.surfaceShader": ["skin_mat.outColor"],
                      "skin_mat.baseColor": ["mcpTex_noise.outColor"]}
        self.existing_attrs = {"skin_mat.baseColor"}
        self.connected = []
        self.deleted = []
        self.checkpoints = []
        self.baked_calls = []
        self.created = []

    # resolution ------------------------------------------------------
    def ls(self, name=None, long=False, **kw):
        if name in self.meshes:
            return [name]
        return [n for n in self.meshes if n.split("|")[-1] == name] or []

    def objExists(self, name):
        return name in self.meshes or name in self.types

    def listRelatives(self, node, shapes=False, fullPath=False, **kw):
        return [self.meshes[node]] if shapes and node in self.meshes else None

    def nodeType(self, node):
        if node in self.meshes.values():
            return "mesh"
        return self.types.get(node, "transform")

    def polyEvaluate(self, node, uvcoord=False, **kw):
        return self.uv_count if uvcoord else 0

    # graph -----------------------------------------------------------
    def listSets(self, object=None, type=None):
        return list(self.sets.get(object, []))

    def listConnections(self, plug, source=False, destination=True,
                        plugs=False, **kw):
        srcs = self.conns.get(plug) or []
        if not srcs:
            return None
        return list(srcs) if plugs else [s.split(".")[0] for s in srcs]

    def attributeQuery(self, attr, node=None, exists=False):
        return ("%s.%s" % (node, attr)) in self.existing_attrs

    def getAttr(self, plug):
        return ""

    # mutation (two-phase bake) ---------------------------------------
    def shadingNode(self, node_type, name=None, asTexture=False,
                    asUtility=False, **kw):
        self.types[name] = node_type
        self.created.append(name)
        return name

    def setAttr(self, plug, *values, **kw):
        pass

    def connectAttr(self, src, dst, force=False):
        self.connected.append((src, dst))
        self.conns[dst] = [src]

    def delete(self, *nodes):
        for n in nodes:
            self.deleted.append(n)
            self.types.pop(n, None)


@pytest.fixture
def fake(monkeypatch):
    cmds = FakeCmds()
    monkeypatch.setattr(texbake, "_cmds", lambda: cmds)
    monkeypatch.setattr(texbake.session, "auto_checkpoint",
                        lambda reason: (cmds.checkpoints.append(reason)
                                        or {"checkpoint_id": "cp",
                                            "path": "cp.ma"}))
    return cmds


def _params(tmp_path, **kw):
    base = {"meshes": ["|body"], "out_dir": str(tmp_path)}
    base.update(kw)
    return base


class TestValidation:
    def test_meshes_is_required(self, fake, tmp_path):
        with pytest.raises(HandlerError, match="meshes"):
            texbake.validate({"out_dir": str(tmp_path)}, fake)

    def test_out_dir_must_exist(self, fake, tmp_path):
        params = _params(tmp_path, out_dir=str(tmp_path / "nope"))
        with pytest.raises(HandlerError, match="does not exist"):
            texbake.validate(params, fake)

    def test_out_dir_must_be_absolute(self, fake, tmp_path):
        with pytest.raises(HandlerError, match="absolute"):
            texbake.validate(_params(tmp_path, out_dir="relative/dir"), fake)

    def test_resolution_must_be_a_supported_power_of_two(self, fake, tmp_path):
        with pytest.raises(HandlerError, match="resolution"):
            texbake.validate(_params(tmp_path, resolution=1000), fake)

    def test_an_unknown_slot_refuses(self, fake, tmp_path):
        with pytest.raises(HandlerError, match="slot"):
            texbake.validate(_params(tmp_path, slots=["shininess"]), fake)

    def test_defaults_are_1024_and_every_slot(self, fake, tmp_path):
        out = texbake.validate(_params(tmp_path), fake)
        assert out["resolution"] == 1024
        assert out["slots"] is None
        assert out["meshes"] == ["|bodyShape"]


class TestRefusals:
    def test_a_mesh_with_no_uvs_refuses_naming_uv_atlas(self, fake, tmp_path):
        # MEASURED: convertSolidTx does NOT raise here - it writes a flat,
        # useless image. Maya will not catch this for us.
        fake.uv_count = 0
        params = texbake.validate(_params(tmp_path), fake)
        with pytest.raises(HandlerError, match="no UVs"):
            texbake.plan_bakes(fake, params["meshes"], params["slots"])

    def test_the_no_uv_refusal_hint_names_the_fix(self, fake, tmp_path):
        fake.uv_count = 0
        params = texbake.validate(_params(tmp_path), fake)
        try:
            texbake.plan_bakes(fake, params["meshes"], params["slots"])
        except HandlerError as exc:
            assert "maya_uv_atlas" in (exc.hint or "")
        else:
            pytest.fail("expected a refusal")

    def test_a_procedural_normal_without_a_bump2d_refuses(self, fake, tmp_path):
        fake.existing_attrs = {"skin_mat.normalCamera"}
        fake.conns = {"bodySG.surfaceShader": ["skin_mat.outColor"],
                      "skin_mat.normalCamera": ["mcpTex_noise.outColor"]}
        params = texbake.validate(_params(tmp_path), fake)
        with pytest.raises(HandlerError, match="bump2d"):
            texbake.plan_bakes(fake, params["meshes"], params["slots"])

    def test_a_file_backed_slot_is_skipped_not_baked(self, fake, tmp_path):
        fake.types["mcpTex_file"] = "file"
        fake.conns["skin_mat.baseColor"] = ["mcpTex_file.outColor"]
        params = texbake.validate(_params(tmp_path), fake)
        jobs, warnings = texbake.plan_bakes(fake, params["meshes"],
                                            params["slots"])
        assert jobs == []
        assert any("already file-backed" in w for w in warnings)

    def test_nothing_to_bake_refuses_rather_than_no_opping(self, fake,
                                                           tmp_path):
        fake.conns.pop("skin_mat.baseColor")
        params = texbake.validate(_params(tmp_path), fake)
        with pytest.raises(HandlerError, match="no procedural"):
            texbake.plan_bakes(fake, params["meshes"], params["slots"])


class TestPlan:
    def test_a_procedural_colour_slot_becomes_one_job(self, fake, tmp_path):
        params = texbake.validate(_params(tmp_path), fake)
        jobs, _warnings = texbake.plan_bakes(fake, params["meshes"],
                                             params["slots"])
        assert len(jobs) == 1
        job = jobs[0]
        assert job["material"] == "skin_mat"
        assert job["slot"] == "color"
        assert job["attr"] == "baseColor"
        assert job["kind"] == "color"
        assert job["terminal_plug"] == "mcpTex_noise.outColor"
        assert job["bump_node"] is None
        assert job["basename"] == "skin_mat_color_baked.png"

    def test_the_slots_filter_narrows_the_jobs(self, fake, tmp_path):
        params = texbake.validate(_params(tmp_path, slots=["roughness"]), fake)
        with pytest.raises(HandlerError, match="no procedural"):
            texbake.plan_bakes(fake, params["meshes"], params["slots"])


class TestGuardStructure:
    """## Fix round 1: the empty-jobs refusal is gated on the explicit
    `skipped_file_backed` flag, not on `warnings` being non-empty -
    `warnings` is a bag other paths (placement, shared-mesh) write into
    too, always alongside a job. No claim shape in plan_bakes today can
    produce "a warning but no job for a reason other than file-backed", so
    this pins the guard function directly with synthetic inputs rather
    than trying to fabricate a claim that reaches it.
    """

    def test_no_jobs_and_no_file_backed_skip_refuses(self):
        with pytest.raises(HandlerError, match="no procedural"):
            texbake._refuse_if_nothing_to_bake([], False, None)

    def test_no_jobs_but_a_file_backed_skip_does_not_refuse(self):
        texbake._refuse_if_nothing_to_bake([], True, None)  # must not raise

    def test_a_job_present_does_not_refuse_even_without_the_flag(self):
        texbake._refuse_if_nothing_to_bake(
            [{"material": "m"}], False, None)  # must not raise


class TestUnknownSlotRefuses:
    def test_an_unknown_slot_on_the_claim_refuses_rather_than_guessing(
            self, fake, tmp_path, monkeypatch):
        # Synthetic: no real texclaim walk produces a slot outside
        # pbr.SLOTS today (SLOT_FOR_ATTR is derived from the same tables),
        # but a future material.SHADER_SLOTS entry could. Fabricate the
        # claim material_claims would then hand back, and pin the refusal
        # that replaced a silent "color" default (which would have baked
        # outColor where a scalar/normal slot needs outColorR).
        def fake_claims(cmds, shapes):
            return [{
                "mesh": "|bodyShape", "meshes": ["|bodyShape"],
                "material": "skin_mat", "sg": "bodySG", "attr": "shininess",
                "slot": "shininess", "classification": "procedural",
                "terminals": [{"node": "mcpTex_noise", "type": "noise",
                               "file_path": None, "basename": None,
                               "on_disk": None, "colorspace": None}],
                "via": [], "semantics_lost": [],
            }]

        monkeypatch.setattr(texbake.texclaim, "material_claims", fake_claims)
        params = texbake.validate(_params(tmp_path), fake)
        with pytest.raises(HandlerError, match="shininess"):
            texbake.plan_bakes(fake, params["meshes"], params["slots"])


class TestUVCountFailureIsReported:
    def test_a_polyevaluate_failure_is_not_diagnosed_as_no_uvs(
            self, fake, tmp_path, monkeypatch):
        def boom(node, uvcoord=False, **kw):
            raise RuntimeError("kMFnMesh: object does not exist")

        monkeypatch.setattr(fake, "polyEvaluate", boom)
        params = texbake.validate(_params(tmp_path), fake)
        with pytest.raises(HandlerError, match="could not determine"):
            texbake.plan_bakes(fake, params["meshes"], params["slots"])


class TestMeshesRobustness:
    def test_a_non_iterable_meshes_value_refuses_cleanly(self, fake, tmp_path):
        with pytest.raises(HandlerError, match="meshes"):
            texbake.validate(_params(tmp_path, meshes=5), fake)

    def test_a_bool_meshes_value_refuses_cleanly(self, fake, tmp_path):
        with pytest.raises(HandlerError, match="meshes"):
            texbake.validate(_params(tmp_path, meshes=True), fake)


class TestTwoPhaseBake:
    """Phase A writes and verifies with ZERO scene mutation; phase B
    rewires only if every bake verified. A caller is therefore always in
    one of exactly two states."""

    def test_a_failed_bake_leaves_the_scene_untouched(self, fake, tmp_path,
                                                       monkeypatch):
        monkeypatch.setattr(texbake, "_convert_solid_tx",
                            lambda *a, **kw: None)   # writes no file
        with pytest.raises(HandlerError, match="produced no file"):
            texbake.bake_textures(_params(tmp_path))
        assert fake.connected == []          # nothing rewired
        assert fake.deleted == []            # nothing deleted
        assert fake.checkpoints == []        # not even a checkpoint

    def test_a_degenerate_bake_refuses_before_rewiring(self, fake, tmp_path,
                                                        monkeypatch):
        # MEASURED failure mode: a flat image is what a UV-less mesh bakes.
        # The UV guard catches that case; this proves the pixel check is a
        # real second net, not decoration.
        monkeypatch.setattr(texbake, "_convert_solid_tx", _fake_bake(fake))
        monkeypatch.setattr(texbake.pngprobe, "uniformity",
                            lambda _p: {"pixel_count": 1024,
                                        "distinct_values": 1,
                                        "non_uniform": False,
                                        "unavailable_reason": None})
        with pytest.raises(HandlerError, match="flat"):
            texbake.bake_textures(_params(tmp_path))
        assert fake.connected == []
        assert not list(tmp_path.glob("*.part.png"))   # swept

    def test_a_good_bake_rewires_and_commits(self, fake, tmp_path,
                                             monkeypatch):
        monkeypatch.setattr(texbake, "_convert_solid_tx", _fake_bake(fake))
        monkeypatch.setattr(texbake.pngprobe, "uniformity",
                            lambda _p: {"pixel_count": 1024,
                                        "distinct_values": 186,
                                        "non_uniform": True,
                                        "unavailable_reason": None})
        out = texbake.bake_textures(_params(tmp_path))

        assert len(out["baked"]) == 1
        entry = out["baked"][0]
        assert entry["basename"] == "skin_mat_color_baked.png"
        assert os.path.isfile(entry["file"])          # committed, not .part
        assert not list(tmp_path.glob("*.part.png"))  # nothing left behind
        assert entry["pixel_check"]["non_uniform"] is True
        assert out["checkpoint_id"]                   # checkpointed first
        # the shader now reads the baked file, and the old noise is gone
        assert any(dst == "skin_mat.baseColor" for _src, dst in fake.connected)
        assert "mcpTex_noise" in fake.deleted

    def test_an_unmeasurable_bake_refuses_rather_than_shipping(
            self, fake, tmp_path, monkeypatch):
        monkeypatch.setattr(texbake, "_convert_solid_tx", _fake_bake(fake))
        monkeypatch.setattr(texbake.pngprobe, "uniformity",
                            lambda _p: {"pixel_count": 0,
                                        "distinct_values": 0,
                                        "non_uniform": None,
                                        "unavailable_reason": "unreadable"})
        with pytest.raises(HandlerError, match="could not be measured"):
            texbake.bake_textures(_params(tmp_path))
        assert fake.connected == []
