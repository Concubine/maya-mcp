"""#770: what maya_bake_mesh_maps refuses, bakes, and composites.

Every refusal and shape here is grounded in a MEASURED probe finding
(evals/meshmaps_probe_770*.py), not caution:
- a UV-less mesh does not fail at bake time - arnoldRenderToTexture returns
  normally and writes a CORRUPT EXR that only fails later, at read (P Q5);
- the -shader flag bakes without assigning, so the bake phase mutates
  nothing (Q2);
- a flat map can be HONEST (concave curvature on a beveled cube is all-zero,
  Q3; a lone convex mesh's AO is all-white) - so flat is a warning here,
  never the refusal it is in texbake;
- MImage's EXR->PNG conversion is LINEAR (0.5 lands on 127/128, T1), so the
  AO composite decodes sRGB bases but takes AO values straight.
"""

import os
import struct
import zlib

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import meshmaps, pngprobe


def _png(path, rows, colour_type=2):
    """A real PNG with arbitrary colour type (RGBA models what MImage
    actually writes for a converted bake - measured colour_type 6)."""
    raw = bytearray()
    for row in rows:
        raw.append(0)
        for px in row:
            raw.extend(px)

    def chunk(tag, payload):
        body = tag + payload
        return (struct.pack(">I", len(payload)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    width, height = len(rows[0]), len(rows)
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8,
                                        colour_type, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(bytes(raw)))
           + chunk(b"IEND", b""))
    with open(str(path), "wb") as fh:
        fh.write(png)
    return str(path)


def _rich_rgba_rows(size=4, alpha=255):
    return [[(x * 60 % 256, y * 60 % 256, 128, alpha) for x in range(size)]
            for y in range(size)]


class FakeCmds:
    """|limb (shape |limbShape) wears limbSG -> limb_mat (standardSurface),
    baseColor unconnected (a plain value). Per-test knobs mirror
    tests/test_texbake.py's fake - model Maya, never dodge it."""

    def __init__(self):
        self.meshes = {"|limb": "|limbShape"}
        self.uv_counts = {"|limbShape": 64}
        self.types = {"limb_mat": "standardSurface"}
        self.shape_sgs = {"|limbShape": ["limbSG"]}
        self.sg_members = {"limbSG": ["|limbShape"]}
        self.conns = {"limbSG.surfaceShader": ["limb_mat.outColor"]}
        self.existing_attrs = {"limb_mat.baseColor"}
        self.attr_values = {"limb_mat.baseColor": [(1.0, 1.0, 1.0)]}
        self.connected = []
        self.deleted = []
        self.created = []
        self.checkpoints = []
        self.selection = ["|limb"]
        self.plugins_loaded = ["mtoa"]

    # resolution ------------------------------------------------------
    def ls(self, *args, **kw):
        if kw.get("selection"):
            return list(self.selection)
        name = args[0] if args else kw.get("name")
        if name in self.meshes:
            return [name]
        return [n for n in self.meshes if n.split("|")[-1] == name] or []

    def objExists(self, name):
        return (name in self.meshes or name in self.types
                or name in self.meshes.values())

    def listRelatives(self, node, shapes=False, fullPath=False, **kw):
        return [self.meshes[node]] if shapes and node in self.meshes else None

    def nodeType(self, node):
        if node in self.meshes.values():
            return "mesh"
        return self.types.get(node, "transform")

    def polyEvaluate(self, node, uvcoord=False, **kw):
        return self.uv_counts.get(node, 0) if uvcoord else 0

    # graph -----------------------------------------------------------
    def listSets(self, object=None, type=None):
        return list(self.shape_sgs.get(object, []))

    def sets(self, name, query=False, **kw):
        if query:
            return list(self.sg_members.get(name, []))
        raise NotImplementedError("query only")

    def listConnections(self, plug, source=False, destination=True,
                        plugs=False, **kw):
        node = plug.split(".")[0]
        has_attr = "." in plug
        if source:
            if has_attr:
                srcs = list(self.conns.get(plug) or [])
            else:
                srcs = []
                for dst, srclist in self.conns.items():
                    if dst.split(".")[0] == node:
                        srcs.extend(srclist)
            if not srcs:
                return None
            return srcs if plugs else [s.split(".")[0] for s in srcs]
        dsts = []
        for dst, srclist in self.conns.items():
            for src in srclist:
                matched = (src == plug) if has_attr else (
                    src.split(".")[0] == node)
                if matched:
                    dsts.append(dst)
                    break
        return (dsts if plugs else [d.split(".")[0] for d in dsts]) or None

    def attributeQuery(self, attr, node=None, exists=False):
        return ("%s.%s" % (node, attr)) in self.existing_attrs

    def getAttr(self, plug, **kw):
        return self.attr_values.get(plug, "")

    # mutation --------------------------------------------------------
    def shadingNode(self, node_type, name=None, **kw):
        self.types[name] = node_type
        self.created.append(name)
        return name

    def setAttr(self, plug, *values, **kw):
        self.attr_values[plug] = list(values) if len(values) > 1 else (
            values[0] if values else None)

    def connectAttr(self, src, dst, force=False):
        self.connected.append((src, dst))
        self.conns[dst] = [src]

    def delete(self, *nodes):
        for n in nodes:
            self.deleted.append(n)
            self.types.pop(n, None)
            for dst in list(self.conns):
                if dst.split(".")[0] == n:
                    del self.conns[dst]
                    continue
                self.conns[dst] = [s for s in self.conns[dst]
                                   if s.split(".")[0] != n]
                if not self.conns[dst]:
                    del self.conns[dst]

    def select(self, *args, **kw):
        if kw.get("clear"):
            self.selection = []
        elif args:
            arg = args[0]
            self.selection = list(arg) if isinstance(arg, list) else [arg]

    def pluginInfo(self, name, query=False, loaded=False, path=False):
        if path:
            return getattr(self, "plugin_path", "")
        return name in self.plugins_loaded

    def loadPlugin(self, name, quiet=False):
        self.plugins_loaded.append(name)
        return [name]


def _fake_bake(fake, exr_name="bakeShape.exr"):
    """Stand in for arnoldRenderToTexture: drop one EXR-named file into the
    private folder, the way the real command was measured to."""
    def _bake(cmds, shape, folder, resolution, shader, extend_edges):
        with open(os.path.join(folder, exr_name), "wb") as fh:
            fh.write(b"exr")
        fake.baked_calls.append((shape, resolution, shader, extend_edges))
    fake.baked_calls = []
    return _bake


def _fake_convert(rows=None, colour_type=6):
    """Stand in for the MImage EXR->PNG conversion: write a REAL png so the
    stats machinery runs for real."""
    def _convert(cmds, src, dst):
        _png(dst, rows or _rich_rgba_rows(), colour_type=colour_type)
    return _convert


@pytest.fixture
def fake(monkeypatch):
    cmds = FakeCmds()
    monkeypatch.setattr(meshmaps, "_cmds", lambda: cmds)
    monkeypatch.setattr(meshmaps, "_ensure_mtoa", lambda c: None)
    monkeypatch.setattr(meshmaps, "_arnold_bake", _fake_bake(cmds))
    monkeypatch.setattr(meshmaps, "_exr_to_png", _fake_convert())
    monkeypatch.setattr(meshmaps.session, "auto_checkpoint",
                        lambda reason: (cmds.checkpoints.append(reason)
                                        or {"checkpoint_id": "cp",
                                            "path": "cp.ma"}))
    return cmds


def _params(tmp_path, **kw):
    base = {"meshes": ["|limb"], "out_dir": str(tmp_path)}
    base.update(kw)
    return base


class TestValidation:
    def test_meshes_is_required(self, fake, tmp_path):
        with pytest.raises(HandlerError, match="meshes"):
            meshmaps.validate({"out_dir": str(tmp_path)}, fake)

    def test_out_dir_must_exist(self, fake, tmp_path):
        with pytest.raises(HandlerError, match="does not exist"):
            meshmaps.validate(_params(tmp_path,
                                      out_dir=str(tmp_path / "nope")), fake)

    def test_out_dir_must_be_absolute(self, fake, tmp_path):
        with pytest.raises(HandlerError, match="absolute"):
            meshmaps.validate(_params(tmp_path, out_dir="rel/dir"), fake)

    def test_resolution_must_be_supported(self, fake, tmp_path):
        with pytest.raises(HandlerError, match="resolution"):
            meshmaps.validate(_params(tmp_path, resolution=1000), fake)

    def test_an_unknown_map_refuses(self, fake, tmp_path):
        with pytest.raises(HandlerError, match="tangent_normal"):
            meshmaps.validate(_params(tmp_path, maps=["tangent_normal"]),
                              fake)

    def test_an_unknown_param_refuses_with_the_764_guard(self, fake,
                                                         tmp_path):
        with pytest.raises(HandlerError, match="map"):
            meshmaps.validate(_params(tmp_path, map=["ao"]), fake)

    def test_defaults(self, fake, tmp_path):
        out = meshmaps.validate(_params(tmp_path), fake)
        assert out["maps"] == ["ao", "curvature", "world_normal"]
        assert out["resolution"] == 1024
        assert out["apply_ao"] is False
        assert out["curvature_output"] == "convex"
        assert out["meshes"] == [("|limb", "|limbShape")]

    def test_a_uv_less_mesh_refuses_naming_the_fix(self, fake, tmp_path):
        # MEASURED (Q5): the bake RETURNS NORMALLY and writes a corrupt EXR
        # that only fails at read - Maya raises in the wrong place, too late.
        fake.uv_counts["|limbShape"] = 0
        with pytest.raises(HandlerError, match="no UVs") as exc:
            meshmaps.validate(_params(tmp_path), fake)
        assert "maya_uv_atlas" in (exc.value.hint or "")

    def test_short_name_collisions_refuse(self, fake, tmp_path):
        # MEASURED (Q4): Arnold names the output file itself, and renames on
        # collision - this tool refuses rather than parsing that rule.
        fake.meshes["|left|limb"] = "|left|limbShape"
        fake.uv_counts["|left|limbShape"] = 8
        with pytest.raises(HandlerError, match="short name"):
            meshmaps.validate(_params(tmp_path,
                                      meshes=["|limb", "|left|limb"]), fake)

    def test_curvature_output_must_be_an_enum_value(self, fake, tmp_path):
        with pytest.raises(HandlerError, match="curvature_output"):
            meshmaps.validate(_params(tmp_path, curvature_output="edges"),
                              fake)


class TestPlanApply:
    def test_a_plain_colour_material_is_a_value_base(self, fake, tmp_path):
        settings = meshmaps.validate(_params(tmp_path, apply_ao=True), fake)
        jobs, warnings = meshmaps.plan_apply(fake, settings["meshes"])
        assert len(jobs) == 1
        job = jobs[0]
        assert job["material"] == "limb_mat"
        assert job["attr"] == "baseColor"
        assert job["base"]["kind"] == "value"
        assert job["base"]["rgb"] == (1.0, 1.0, 1.0)
        assert [w[0] for w in job["wearers"]] == ["|limb"]

    def test_a_png_backed_colour_is_a_file_base(self, fake, tmp_path):
        base = _png(tmp_path / "albedo.png", [[(200, 100, 50)]])
        fake.types["kit_file"] = "file"
        fake.conns["limb_mat.baseColor"] = ["kit_file.outColor"]
        fake.attr_values["kit_file.fileTextureName"] = base
        fake.attr_values["kit_file.colorSpace"] = "sRGB"
        settings = meshmaps.validate(_params(tmp_path, apply_ao=True), fake)
        jobs, _w = meshmaps.plan_apply(fake, settings["meshes"])
        assert jobs[0]["base"]["kind"] == "file"
        assert jobs[0]["base"]["path"] == base
        assert jobs[0]["base"]["colorspace"] == "sRGB"
        assert jobs[0]["base"]["file_node"] == "kit_file"

    def test_a_procedural_colour_refuses_naming_bake_textures(self, fake,
                                                              tmp_path):
        fake.types["mcpTex_noise"] = "noise"
        fake.conns["limb_mat.baseColor"] = ["mcpTex_noise.outColor"]
        settings = meshmaps.validate(_params(tmp_path, apply_ao=True), fake)
        with pytest.raises(HandlerError, match="procedural") as exc:
            meshmaps.plan_apply(fake, settings["meshes"])
        assert "maya_bake_textures" in (exc.value.hint or "")

    def test_a_wearer_outside_the_request_refuses(self, fake, tmp_path):
        fake.meshes["|other"] = "|otherShape"
        fake.uv_counts["|otherShape"] = 8
        fake.sg_members["limbSG"] = ["|limbShape", "|otherShape"]
        settings = meshmaps.validate(_params(tmp_path, apply_ao=True), fake)
        with pytest.raises(HandlerError, match="otherShape"):
            meshmaps.plan_apply(fake, settings["meshes"])

    def test_a_shared_material_becomes_one_masked_job(self, fake, tmp_path):
        fake.meshes["|collar"] = "|collarShape"
        fake.uv_counts["|collarShape"] = 8
        fake.shape_sgs["|collarShape"] = ["limbSG"]
        fake.sg_members["limbSG"] = ["|limbShape", "|collarShape"]
        settings = meshmaps.validate(
            _params(tmp_path, apply_ao=True, meshes=["|limb", "|collar"]),
            fake)
        jobs, _w = meshmaps.plan_apply(fake, settings["meshes"])
        assert len(jobs) == 1
        assert sorted(w[0] for w in jobs[0]["wearers"]) == ["|collar",
                                                            "|limb"]
        assert jobs[0]["masked"] is True

    def test_a_non_png_file_base_refuses(self, fake, tmp_path):
        fake.types["kit_file"] = "file"
        fake.conns["limb_mat.baseColor"] = ["kit_file.outColor"]
        fake.attr_values["kit_file.fileTextureName"] = str(
            tmp_path / "albedo.jpg")
        settings = meshmaps.validate(_params(tmp_path, apply_ao=True), fake)
        with pytest.raises(HandlerError, match="cannot be read"):
            meshmaps.plan_apply(fake, settings["meshes"])


class TestBake:
    def test_a_bake_lands_files_and_stats(self, fake, tmp_path):
        out = meshmaps.bake_mesh_maps(_params(tmp_path, maps=["ao"]))
        assert len(out["baked"]) == 1
        entry = out["baked"][0]
        assert entry["mesh"] == "|limb"
        assert entry["map"] == "ao"
        assert entry["basename"] == "limb_ao.png"
        assert os.path.isfile(entry["file"])
        assert entry["stats"]["non_uniform"] is True
        assert entry["stats"]["blank"] is False
        assert not list(tmp_path.glob("*.part*"))
        assert out["checkpoint_id"] is None  # nothing applied, no mutation

    def test_every_requested_map_bakes(self, fake, tmp_path):
        out = meshmaps.bake_mesh_maps(_params(tmp_path))
        assert [b["map"] for b in out["baked"]] == ["ao", "curvature",
                                                    "world_normal"]

    def test_temp_shader_nodes_are_deleted(self, fake, tmp_path):
        meshmaps.bake_mesh_maps(_params(tmp_path, maps=["ao", "curvature"]))
        assert fake.created  # shaders were made...
        for node in fake.created:
            assert node in fake.deleted  # ...and none survive

    def test_a_flat_map_warns_but_ships(self, fake, tmp_path, monkeypatch):
        # MEASURED (Q3): concave curvature on convex-only geometry is
        # honestly all-zero; refusing a flat map here would refuse the truth.
        monkeypatch.setattr(
            meshmaps, "_exr_to_png",
            _fake_convert(rows=[[(0, 0, 0, 255)] * 4] * 4))
        out = meshmaps.bake_mesh_maps(
            _params(tmp_path, maps=["curvature"],
                    curvature_output="concave"))
        assert len(out["baked"]) == 1
        assert out["baked"][0]["stats"]["non_uniform"] is False
        assert any("flat" in w for w in out["warnings"])

    def test_a_bake_that_writes_nothing_refuses(self, fake, tmp_path,
                                                monkeypatch):
        monkeypatch.setattr(meshmaps, "_arnold_bake",
                            lambda *a, **kw: None)
        with pytest.raises(HandlerError, match="no EXR"):
            meshmaps.bake_mesh_maps(_params(tmp_path, maps=["ao"]))
        assert not list(tmp_path.glob("*"))  # nothing committed

    def test_an_unreadable_bake_refuses_and_sweeps(self, fake, tmp_path,
                                                   monkeypatch):
        # MEASURED (Q5): this is where a UV-less-style corrupt EXR actually
        # surfaces - the conversion, not the bake.
        def _boom(cmds, src, dst):
            raise RuntimeError("(kFailure): Unexpected Internal Failure")
        monkeypatch.setattr(meshmaps, "_exr_to_png", _boom)
        with pytest.raises(HandlerError, match="could not be read"):
            meshmaps.bake_mesh_maps(_params(tmp_path, maps=["ao"]))
        assert not list(tmp_path.glob("*.part*"))

    def test_selection_is_restored(self, fake, tmp_path):
        fake.selection = ["|somethingElse"]
        meshmaps.bake_mesh_maps(_params(tmp_path, maps=["ao"]))
        assert fake.selection == ["|somethingElse"]


class TestConversionTooling:
    """MEASURED (live gate, first run): MImage.writeToFile('png') zeroes
    the ALPHA CHANNEL in a GUI Maya session while the same call on the
    same EXR is correct under maya.standalone - every headless test was
    green while the live bake read as 'drew nothing'. The conversion
    therefore runs through Arnold's own oiiotool, a subprocess that
    behaves identically everywhere (byte-identical output measured)."""

    def test_oiiotool_is_found_next_to_the_mtoa_plugin(self, fake, tmp_path):
        plugin_dir = tmp_path / "Arnold" / "plug-ins"
        bin_dir = tmp_path / "Arnold" / "bin"
        plugin_dir.mkdir(parents=True)
        bin_dir.mkdir(parents=True)
        exe = bin_dir / ("oiiotool.exe" if os.name == "nt" else "oiiotool")
        exe.write_bytes(b"")
        fake.plugin_path = str(plugin_dir / "mtoa.mll")
        assert meshmaps._find_oiiotool(fake) == str(exe)

    def test_a_missing_oiiotool_refuses_rather_than_falling_back(
            self, fake, tmp_path):
        # The MImage path is measured BROKEN in GUI sessions - silently
        # falling back to it would resurrect the exact defect the live
        # gate caught.
        fake.plugin_path = str(tmp_path / "nowhere" / "mtoa.mll")
        with pytest.raises(HandlerError, match="oiiotool"):
            meshmaps._find_oiiotool(fake)


class TestEvidenceKeeping:
    def test_a_blank_bake_keeps_its_part_file_for_inspection(
            self, fake, tmp_path, monkeypatch):
        # The refusal hint names the part file as left on disk - so it
        # must actually BE left (live gate, first run: the hint promised
        # a file the sweep had already deleted).
        monkeypatch.setattr(
            meshmaps, "_exr_to_png",
            _fake_convert(rows=[[(9, 9, 9, 0)] * 4] * 4))
        with pytest.raises(HandlerError, match="drew nothing"):
            meshmaps.bake_mesh_maps(_params(tmp_path, maps=["ao"]))
        assert list(tmp_path.glob("*.part.png"))  # evidence kept

    def test_earlier_good_parts_are_still_swept_on_a_later_refusal(
            self, fake, tmp_path, monkeypatch):
        calls = {"n": 0}
        good = _fake_convert()

        def _convert(cmds_arg, src, dst):
            calls["n"] += 1
            if calls["n"] == 2:
                _png(dst, [[(9, 9, 9, 0)] * 4] * 4, colour_type=6)
            else:
                good(cmds_arg, src, dst)
        monkeypatch.setattr(meshmaps, "_exr_to_png", _convert)
        with pytest.raises(HandlerError, match="drew nothing"):
            meshmaps.bake_mesh_maps(_params(tmp_path,
                                            maps=["ao", "curvature"]))
        parts = [p.name for p in tmp_path.glob("*.part.png")]
        assert parts == ["limb_curvature.png.part.png"]  # only the evidence


class TestCompositeMath:
    def test_half_ao_on_a_white_value_base_encodes_srgb(self):
        # MEASURED (T1): the AO png holds LINEAR values - 127 is 0.5. A
        # white base at half AO must come out sRGB-encoded (~188), not 127:
        # multiplying display bytes directly would double-darken every
        # contact shadow.
        ao = {"pixels": [(127, 0, 0, 255)], "width": 1, "height": 1,
              "masked": False}
        out = meshmaps.composite_ao({"kind": "value", "rgb": (1.0, 1.0, 1.0)},
                                    [ao], 1)
        assert out["overlap_fraction"] == 0.0
        r = out["pixels"][0][0]
        assert 185 <= r <= 191

    def test_full_ao_leaves_an_srgb_file_base_untouched(self, tmp_path):
        base_png = _png(tmp_path / "b.png", [[(200, 100, 50)]])
        base = meshmaps.load_base_pixels({"kind": "file", "path": base_png,
                                          "colorspace": "sRGB"})
        ao = {"pixels": [(255, 0, 0, 255)], "width": 1, "height": 1,
              "masked": False}
        out = meshmaps.composite_ao(base, [ao], 1)
        assert out["pixels"][0] == (200, 100, 50)

    def test_masked_layers_apply_only_where_opaque(self):
        # Two wearers of one atlas: each bake's alpha marks its own shells
        # (MEASURED: unpadded bakes keep alpha honest; extend_edges floods
        # it to 1.0, which is why masked layers bake unpadded).
        # left claims the left column (opaque, AO=0), right the right
        # column (opaque, AO=127); each is transparent over the other's.
        left = {"pixels": [(0, 0, 0, 255), (0, 0, 0, 0)] * 2, "width": 2,
                "height": 2, "masked": True}
        right = {"pixels": [(0, 0, 0, 0), (127, 0, 0, 255)] * 2, "width": 2,
                 "height": 2, "masked": True}
        out = meshmaps.composite_ao({"kind": "value", "rgb": (1.0, 1.0, 1.0)},
                                    [left, right], 2)
        assert out["pixels"][0] == (0, 0, 0)       # left's zone: fully dark
        assert 185 <= out["pixels"][1][0] <= 191   # right's zone: half AO
        assert out["overlap_fraction"] == 0.0

    def test_overlapping_masks_are_reported(self):
        both = {"pixels": [(127, 0, 0, 255)], "width": 1, "height": 1,
                "masked": True}
        out = meshmaps.composite_ao({"kind": "value", "rgb": (1.0, 1.0, 1.0)},
                                    [both, dict(both)], 1)
        assert out["overlap_fraction"] == 1.0


class TestApply:
    def test_apply_rewires_and_checkpoints(self, fake, tmp_path):
        out = meshmaps.bake_mesh_maps(_params(tmp_path, maps=["ao"],
                                              apply_ao=True))
        assert fake.checkpoints == ["bake_mesh_maps"]
        assert out["checkpoint_id"] == "cp"
        assert len(out["applied"]) == 1
        applied = out["applied"][0]
        assert applied["material"] == "limb_mat"
        assert os.path.isfile(applied["file"])
        assert applied["basename"] == "limb_mat_color_ao.png"
        # the slot now reads the composite through a file node
        assert any(dst == "limb_mat.baseColor"
                   for _src, dst in fake.connected)

    def test_apply_replaces_a_file_base_and_sweeps_the_old_node(
            self, fake, tmp_path):
        base = _png(tmp_path / "albedo.png", [[(200, 100, 50)]])
        fake.types["kit_file"] = "file"
        fake.conns["limb_mat.baseColor"] = ["kit_file.outColor"]
        fake.attr_values["kit_file.fileTextureName"] = base
        fake.attr_values["kit_file.colorSpace"] = "sRGB"
        out = meshmaps.bake_mesh_maps(_params(tmp_path, maps=["ao"],
                                              apply_ao=True))
        assert "kit_file" in fake.deleted
        assert os.path.isfile(base)  # the input atlas is NEVER overwritten
        assert out["applied"][0]["replaced_file"] == base

    def test_apply_refusals_fire_before_any_bake(self, fake, tmp_path):
        fake.types["mcpTex_noise"] = "noise"
        fake.conns["limb_mat.baseColor"] = ["mcpTex_noise.outColor"]
        with pytest.raises(HandlerError, match="procedural"):
            meshmaps.bake_mesh_maps(_params(tmp_path, maps=["ao"],
                                            apply_ao=True))
        assert fake.baked_calls == []  # planned refusal, no wasted bake
        assert not list(tmp_path.glob("*"))

    def test_apply_without_ao_in_maps_refuses(self, fake, tmp_path):
        with pytest.raises(HandlerError, match="apply_ao"):
            meshmaps.validate(_params(tmp_path, maps=["curvature"],
                                      apply_ao=True), fake)
