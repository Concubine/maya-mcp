"""maya-mcp #642: the export tool, and the gate it runs on its own bytes.

Nothing here imports Maya. The handler's Maya calls are faked, because the
point of this suite is the logic that decides whether a written file is
allowed to survive - and that logic must be checkable without a Maya licence.
"""
import json
import os
import sys
from pathlib import Path

import pytest

_EVALS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "evals")
if _EVALS not in sys.path:
    sys.path.insert(0, _EVALS)

import fbx_probe                                    # noqa: E402
from maya_plugin.handlers import fbxbytes           # noqa: E402
import maya_export                                  # noqa: E402
from maya_plugin.handlers import export             # noqa: E402
from maya_plugin.handlers import rigging            # noqa: E402

REPO = Path(__file__).resolve().parents[1]
GOLEM = REPO / "evals" / "golem_delivery" / "golem.fbx"


def test_the_reader_lives_in_the_plugin_now():
    # It has to: maya_export_fbx reads back a file on the MAYA machine's disk,
    # and the server cannot assume it shares that filesystem.
    facts = fbxbytes.read_fbx(GOLEM)
    assert facts.unit_scale_factor == fbxbytes.DECLARES_METRES


def test_the_eval_shim_is_the_same_names():
    # evals/delivery_units.py resolves fbx_probe.read_fbx as an ATTRIBUTE at
    # call time and tests/test_delivery_units.py monkeypatches it in seven
    # places, so patch and lookup have to land on the same module object.
    for name in ("read_fbx", "world_vertex_bounds", "set_unit_scale_factor",
                 "FbxNode", "FbxFacts", "DECLARES_METRES"):
        assert getattr(fbx_probe, name) is getattr(fbxbytes, name), name


def test_the_shim_stays_patchable(monkeypatch):
    import delivery_units
    sentinel = fbxbytes.FbxFacts(version=7700, nodes=[], meshes=[],
                                 unit_scale_factor=fbxbytes.DECLARES_METRES)
    monkeypatch.setattr(fbx_probe, "read_fbx", lambda _p: sentinel)
    assert delivery_units.check_delivery("ignored.fbx", ceiling_m=2.0) == []


# Copied verbatim from evals/maya_export.py as it stood at commit 7df1863,
# BEFORE this task rewrote it. This literal is the contract: demigol_kit.py,
# demigol_structures.py and units_live.py all ship their deliveries through
# this exact string, and re-validating a change to it would cost a live art
# run. Composing it from the handler is only safe because this assertion
# proves the composition produced the same bytes.
SHIPPED_PREAMBLE = (
    "\n"
    "import maya.cmds as cmds\n"
    "import maya.mel as mel\n"
    'cmds.loadPlugin("fbxmaya", quiet=True)\n'
    "mel.eval('FBXResetExport')\n"
    "mel.eval('FBXExportFileVersion -v FBX202000')\n"
    "mel.eval('FBXExportUpAxis y')\n"
    "mel.eval('FBXExportInputConnections -v false')\n"
    "mel.eval('FBXExportEmbeddedTextures -v false')\n"
    "mel.eval('FBXExportScaleFactor %g' % EXPORT_SCALE_FACTOR)\n"
)


def test_the_composed_preamble_is_byte_identical():
    assert maya_export.EXPORT_PREAMBLE == SHIPPED_PREAMBLE


def test_the_scale_factor_has_one_definition():
    assert maya_export.EXPORT_SCALE_FACTOR is export.EXPORT_SCALE_FACTOR
    assert export.EXPORT_SCALE_FACTOR == 1.0


def test_the_dead_end_is_not_in_the_preamble():
    # FBXExportConvertUnitString runs without error and does NOTHING - six
    # selector/dynamic-conversion combinations were byte-identical. It must not
    # come back as decoration.
    assert not any("ConvertUnit" in s for s in export.FBX_PREAMBLE_MEL)
    # And the -v form of the scale factor RAISES; both generators used to
    # swallow that inside `except Exception: pass`.
    assert not any(s.startswith("FBXExportScaleFactor") for s in export.FBX_PREAMBLE_MEL)


def test_the_preamble_is_the_measured_five_in_order():
    # FBXResetExport first, or a setting from a previous export survives.
    assert export.FBX_PREAMBLE_MEL == (
        "FBXResetExport",
        "FBXExportFileVersion -v FBX202000",
        "FBXExportUpAxis y",
        "FBXExportInputConnections -v false",
        "FBXExportEmbeddedTextures -v false",
    )


def test_the_scene_content_flags_are_pinned_outside_the_shipped_preamble():
    # #646: the whole-scene branch's content must not be decided by whatever
    # FBXResetExport defaults to. They are pinned separately because
    # FBX_PREAMBLE_MEL composes the string three delivery generators ship
    # through, asserted byte-for-byte above.
    assert export.FBX_SCENE_CONTENT_MEL == (
        "FBXExportCameras -v true",
        "FBXExportLights -v true",
    )
    assert not set(export.FBX_SCENE_CONTENT_MEL) & set(export.FBX_PREAMBLE_MEL)


def test_the_skin_switches_are_the_measured_pair():
    # #602 P1. Both states stated so FBXResetExport's defaults never decide it,
    # and the True branch is `FBXExportSkins` ALONE: measured under mayapy,
    # nodes=[mesh, root] wrote byte-identical files with and without
    # FBXExportInputConnections, and turning that on would silently widen a
    # selected export beyond the nodes the caller named.
    assert export.FBX_SKINS_MEL == {
        True: ("FBXExportSkins -v true",),
        False: ("FBXExportSkins -v false",),
    }
    assert not any("InputConnections" in s
                   for s in export.FBX_SKINS_MEL[True])
    # The preamble's own `-v false` must survive: it is the shipped setting
    # three delivery generators export through.
    assert "FBXExportInputConnections -v false" in export.FBX_PREAMBLE_MEL


def _facts(nodes=(), unit=None):
    return fbxbytes.FbxFacts(
        version=7700, nodes=list(nodes), meshes=[],
        unit_scale_factor=fbxbytes.DECLARES_METRES if unit is None else unit)


def test_a_clean_file_has_no_violations():
    node = fbxbytes.FbxNode(name="golem_C_pelvis", kind="Mesh", uid=1)
    assert export.gate_violations(_facts([node])) == []


def test_a_compensating_node_scale_is_a_violation():
    # The exact shape of maya-mcp #629: vertices 100x too large, a 0.01 on the
    # root, and the prefab renders correctly while the bare mesh does not.
    # The mesh child is what makes the root's scale reach a vertex, and #629's
    # root did carry one - without it this is an empty group scaled in an
    # otherwise empty file, which is nobody's defect.
    root = fbxbytes.FbxNode(name="kit_root", kind="Null", uid=1,
                            scaling=(0.01, 0.01, 0.01))
    mesh = fbxbytes.FbxNode(name="kit_piece", kind="Mesh", uid=2, parent=1,
                            geometry=99)
    violations = export.gate_violations(_facts([root, mesh]))
    assert len(violations) == 1
    assert "kit_root" in violations[0]
    assert "identity" in violations[0]


# --- #646: the scale rule only means something where a vertex can feel it ----


def test_a_scaled_light_does_not_refuse_a_whole_scene_export():
    # A whole-scene export writes lights as Model records (measured live: three
    # of them from an ordinary lit scene). A scale on one cannot hide a vertex
    # magnitude, and "freeze transforms" is not an action for a light.
    mesh = fbxbytes.FbxNode(name="asset", kind="Mesh", uid=1, geometry=99)
    light = fbxbytes.FbxNode(name="mcpLight_key", kind="Light", uid=2,
                             scaling=(4.0, 4.0, 4.0))
    assert export.gate_violations(_facts([mesh, light])) == []


def test_a_scaled_annotation_locator_does_not_refuse_the_export():
    # A locator and a group are BOTH "Null" in the file, so this and the test
    # below are the pair that proves the check is structural, not by kind.
    mesh = fbxbytes.FbxNode(name="asset", kind="Mesh", uid=1, geometry=99)
    locator = fbxbytes.FbxNode(name="annotation", kind="Null", uid=2,
                               scaling=(3.0, 3.0, 3.0))
    assert export.gate_violations(_facts([mesh, locator])) == []


def test_a_scaled_group_ABOVE_geometry_is_still_a_violation():
    group = fbxbytes.FbxNode(name="assetGRP", kind="Null", uid=1,
                             scaling=(0.8, 0.8, 0.8))
    mesh = fbxbytes.FbxNode(name="asset", kind="Mesh", uid=2, parent=1,
                            geometry=99)
    violations = export.gate_violations(_facts([group, mesh]))
    assert len(violations) == 1
    assert "assetGRP" in violations[0]


def test_a_scaled_light_that_PARENTS_geometry_is_still_a_violation():
    # setup_lighting's own tests build a light transform with a locator under
    # it, so a light with children is a real scene shape - and then its scale
    # does reach the vertices.
    light = fbxbytes.FbxNode(name="mcpLight_key", kind="Light", uid=1,
                             scaling=(4.0, 4.0, 4.0))
    mesh = fbxbytes.FbxNode(name="badge", kind="Mesh", uid=2, parent=1,
                            geometry=99)
    violations = export.gate_violations(_facts([light, mesh]))
    assert len(violations) == 1
    assert "mcpLight_key" in violations[0]


def test_a_mesh_whose_geometry_link_did_not_resolve_is_still_gated():
    # Exempting by mistake costs #629; gating by mistake costs a warning. The
    # kind is trusted in that one direction only.
    node = fbxbytes.FbxNode(name="orphan", kind="Mesh", uid=1,
                            scaling=(0.01, 0.01, 0.01))
    assert len(export.gate_violations(_facts([node]))) == 1


# --- #602 P1: joints gate like meshes, and the skin records gate themselves ---


def test_a_scaled_joint_is_a_violation():
    # A skinned joint's scale multiplies vertices without being the mesh's
    # ancestor, so LimbNodes are gated like meshes.
    facts = _facts(nodes=[fbxbytes.FbxNode(name="hip", kind="LimbNode",
                                           scaling=(2.0, 2.0, 2.0))])
    assert any("hip" in v for v in export.gate_violations(facts))


def test_an_identity_joint_is_not():
    facts = _facts(nodes=[fbxbytes.FbxNode(name="hip", kind="LimbNode")])
    assert export.gate_violations(facts) == []


# --- #703: segment scale compensate reaches Unity as InheritType 2 ---


def test_a_segment_scale_compensate_joint_is_a_violation():
    # Maya writes InheritType 2 for a joint whose segmentScaleCompensate is
    # on. Unity does not implement that inheritance: with the metres
    # declaration it materialises the unit conversion as localScale 100 on
    # every such joint and then compounds it per level (#703, measured in
    # Unity 6000.0.47f1 - a 12-joint serpent reached world scale 10^22).
    facts = _facts(nodes=[fbxbytes.FbxNode(name="spine_03", kind="LimbNode",
                                           inherit_type=2)])
    out = export.gate_violations(facts)
    assert any("spine_03" in v and "InheritType 2" in v for v in out)


def test_an_inherit_type_1_joint_is_not():
    # SSC off exports as InheritType 1, which every consumer composes plainly.
    facts = _facts(nodes=[fbxbytes.FbxNode(name="spine_03", kind="LimbNode",
                                           inherit_type=1)])
    assert export.gate_violations(facts) == []


def test_inherit_type_2_is_gated_on_joints_only():
    # Maya's SSC flag exists only on joints, so only LimbNodes can carry the
    # measured defect; gating a Mesh or Null on it would refuse a file this
    # server cannot produce for a reason nobody measured (#646's lesson).
    facts = _facts(nodes=[fbxbytes.FbxNode(name="tube", kind="Mesh", uid=1,
                                           inherit_type=2)])
    assert export.gate_violations(facts) == []


def test_skin_violations_compose():
    # include_skins=true with no skin in the bytes is the false-green class.
    sfacts = {"deformers": 0, "clusters": 0, "influenced_models": 0,
              "bind_pose_present": False, "max_weight_sum_error": None,
              "unweighted_file_vertices": 0, "unavailable_reason": None}
    out = export.skin_violations(sfacts)
    assert any("no skin deformer" in v for v in out)


def test_a_good_skin_block_raises_nothing():
    sfacts = {"deformers": 1, "clusters": 3, "influenced_models": 3,
              "bind_pose_present": True, "max_weight_sum_error": 2e-7,
              "unweighted_file_vertices": 0, "unavailable_reason": None}
    assert export.skin_violations(sfacts) == []


def test_bad_sums_missing_bindpose_and_unweighted_all_fire():
    sfacts = {"deformers": 1, "clusters": 3, "influenced_models": 3,
              "bind_pose_present": False, "max_weight_sum_error": 0.4,
              "unweighted_file_vertices": 7, "unavailable_reason": None}
    out = export.skin_violations(sfacts)
    assert len(out) == 3


def test_a_deformer_with_no_clusters_names_the_missing_skeleton():
    # MEASURED: a selected export listing the mesh but not the skeleton root
    # writes exactly this - one deformer record, zero clusters, and every
    # vertex unweighted. The unweighted count alone reads like a bad bind, so
    # the short selection is named on its own.
    sfacts = {"deformers": 1, "clusters": 0, "influenced_models": 0,
              "bind_pose_present": True, "max_weight_sum_error": None,
              "unweighted_file_vertices": 140, "unavailable_reason": None}
    out = export.skin_violations(sfacts)
    assert len(out) == 1
    assert "skeleton root" in out[0]


def test_multi_deformer_totals_say_they_are_file_wide():
    sfacts = {"deformers": 2, "clusters": 6, "influenced_models": 2,
              "bind_pose_present": True, "unweighted_file_vertices": 3,
              "max_weight_sum_error": None, "unavailable_reason": None}
    out = export.skin_violations(sfacts)
    assert any("file-wide" in v and "2 skin deformers" in v for v in out)


def test_single_deformer_totals_stay_unqualified():
    sfacts = {"deformers": 1, "clusters": 3, "influenced_models": 1,
              "bind_pose_present": True, "unweighted_file_vertices": 3,
              "max_weight_sum_error": None, "unavailable_reason": None}
    out = export.skin_violations(sfacts)
    assert not any("file-wide" in v for v in out)


def test_no_cluster_message_reports_before_it_diagnoses():
    sfacts = {"deformers": 1, "clusters": 0, "influenced_models": 0,
              "bind_pose_present": True, "unweighted_file_vertices": 0,
              "max_weight_sum_error": None, "unavailable_reason": None}
    out = export.skin_violations(sfacts)
    assert any("links no joints" in v and "one measured cause" in v
               for v in out)


def test_the_tolerance_clears_the_exporters_own_weight_pruning():
    # Maya's FBX exporter drops every weight below 1e-3 without renormalising,
    # so a vertex loses up to (influences - 1) x 1e-3 - one measured at
    # 1.381872e-3 under the original 1e-3. Derived from
    # rigging.MAX_INFLUENCES_CEILING rather than the literal 7e-3 so that if
    # the ceiling ever rises, this bound rises with it instead of silently
    # letting the pruning worst case exceed WEIGHT_SUM_TOL unnoticed.
    assert export.WEIGHT_SUM_TOL > (rigging.MAX_INFLUENCES_CEILING - 1) * 1e-3
    good_but_pruned = {"deformers": 1, "clusters": 8, "influenced_models": 8,
                       "bind_pose_present": True,
                       "max_weight_sum_error": 1.381872e-3,
                       "unweighted_file_vertices": 0,
                       "unavailable_reason": None}
    assert export.skin_violations(good_but_pruned) == []
    # And it still catches what it is for: an unnormalised bind.
    unnormalised = dict(good_but_pruned, max_weight_sum_error=0.4)
    assert any("weight sums" in v for v in export.skin_violations(unnormalised))


def test_a_wrong_declaration_is_a_violation():
    violations = export.gate_violations(_facts(unit=1.0))
    assert len(violations) == 1
    assert "UnitScaleFactor" in violations[0]


def test_forty_one_roots_is_not_a_violation():
    # The one-root rule belongs to check_rig_delivery. The demigol kit exports
    # 41 roots and is correct; a universal gate that rejected it would be wrong.
    nodes = [fbxbytes.FbxNode(name="kit_piece_%02d" % i, kind="Mesh", uid=i)
             for i in range(41)]
    assert export.gate_violations(_facts(nodes)) == []


def test_a_big_vertex_is_not_this_gates_business():
    # The ceiling is a per-delivery contract envelope and stays in evals/.
    facts = _facts([fbxbytes.FbxNode(name="tower", kind="Mesh", uid=1)])
    facts.meshes = [(0.0, 0.0, 0.0, 900.0, 900.0, 900.0)]
    assert export.gate_violations(facts) == []


def test_the_shipped_golem_passes_the_gate():
    # A real 33-chunk artifact, committed. If this ever fails, either the gate
    # is wrong or a delivery regressed - both worth stopping for.
    assert export.gate_violations(fbxbytes.read_fbx(GOLEM)) == []


from maya_plugin.dispatcher import HandlerError    # noqa: E402


def _params(tmp_path, **over):
    out = {"path": str(tmp_path / "out.fbx"), "metres_per_unit": 1.0}
    out.update(over)
    return out


def test_a_good_call_normalises_the_path(tmp_path):
    path, nodes, include_skins, include_animation, require_baked = (
        export._validate(_params(tmp_path)))
    assert path.endswith("/out.fbx")
    assert "\\" not in path
    assert nodes is None
    assert include_skins is False
    assert include_animation is False
    assert require_baked is False


def test_metres_per_unit_has_no_default(tmp_path):
    params = _params(tmp_path)
    del params["metres_per_unit"]
    with pytest.raises(HandlerError) as exc:
        export._validate(params)
    assert "metres_per_unit" in str(exc.value)
    # The hint must say WHY there is no default, or the next caller invents one.
    assert "629" in (exc.value.hint or "")


def test_a_hundred_metres_per_unit_is_refused_not_converted(tmp_path):
    with pytest.raises(HandlerError) as exc:
        export._validate(_params(tmp_path, metres_per_unit=100.0))
    assert "only 1.0" in str(exc.value)
    # Refused, not fixed: the only way to "convert" is the compensating root
    # scale, which is the defect. The hint has to point at baking instead.
    assert "freeze" in (exc.value.hint or "")


@pytest.mark.parametrize("bad", [None, "1.0", True, [1.0]])
def test_metres_per_unit_must_be_a_number(tmp_path, bad):
    with pytest.raises(HandlerError):
        export._validate(_params(tmp_path, metres_per_unit=bad))


def test_the_path_must_be_an_fbx(tmp_path):
    with pytest.raises(HandlerError) as exc:
        export._validate(_params(tmp_path, path=str(tmp_path / "out.obj")))
    assert ".fbx" in str(exc.value)


def test_the_path_must_be_absolute(tmp_path):
    with pytest.raises(HandlerError) as exc:
        export._validate(_params(tmp_path, path="out.fbx"))
    assert "absolute" in str(exc.value)


def test_a_missing_directory_is_refused(tmp_path):
    with pytest.raises(HandlerError) as exc:
        export._validate(_params(tmp_path, path=str(tmp_path / "nope" / "out.fbx")))
    assert "does not exist" in str(exc.value)


def test_an_empty_node_list_is_refused(tmp_path):
    # [] would silently export nothing; omitting the param means "everything".
    with pytest.raises(HandlerError) as exc:
        export._validate(_params(tmp_path, nodes=[]))
    assert "omit" in (exc.value.hint or "")


def test_a_node_list_survives_validation(tmp_path):
    _path, nodes, _skins, _anim, _req_baked = export._validate(
        _params(tmp_path, nodes=["golem_C_pelvis"]))
    assert nodes == ["golem_C_pelvis"]


def test_include_skins_must_be_a_bool(tmp_path):
    with pytest.raises(HandlerError, match="include_skins"):
        export._validate(_params(tmp_path, include_skins="yes"))


class FakeCmds:
    """Just enough Maya to drive the handler: record the calls, write a file."""

    def __init__(self, existing=("golem_C_pelvis",), load_plugin_raises=None,
                 plugin_loaded=True):
        self.existing = set(existing)
        self.calls = []
        self.load_plugin_raises = load_plugin_raises
        self.plugin_loaded = plugin_loaded

    def loadPlugin(self, name, quiet=False):
        self.calls.append(("loadPlugin", name))
        if self.load_plugin_raises is not None:
            raise self.load_plugin_raises
        self.plugin_loaded = True

    def pluginInfo(self, name, query=False, loaded=False):
        self.calls.append(("pluginInfo", name))
        return self.plugin_loaded

    def unloadPlugin(self, name, force=False):
        self.calls.append(("unloadPlugin", name))
        self.plugin_loaded = False

    def currentUnit(self, query=False, time=False):
        return "ntsc"

    def objExists(self, name):
        return name in self.existing

    def select(self, names, replace=False):
        self.calls.append(("select", names))

    def file(self, path, **kw):
        self.calls.append(("file", path, kw))
        with open(path, "wb") as fh:
            fh.write(b"not really an fbx")

    def ls(self, nodes=None, **kw):
        """Stub for listing objects. For shape-less test scenes, return empty."""
        # The fake cmds needs to support ls calls for _scene_shape_aliases.
        # By default, return empty list (no shapes/blendShapes in test scenes).
        return []

    def listHistory(self, node, **kw):
        """Stub for listHistory. For shape-less test scenes, return empty."""
        return []

    def listAttr(self, attr, **kw):
        """Stub for listAttr. For shape-less test scenes, return empty."""
        return []

    def listSets(self, object=None, type=None):
        """Stub for listSets - the texclaim walker's entry point. Empty by
        default so an un-monkeypatched export never reaches a shader."""
        return []

    def attributeQuery(self, attr, node=None, exists=False):
        """Stub for attributeQuery - the texclaim walker's slot probe.
        False by default so an un-monkeypatched export claims nothing."""
        return False


class FakeMel:
    def __init__(self):
        self.evaluated = []

    def eval(self, statement):
        self.evaluated.append(statement)


def _install(monkeypatch, cmds, facts, mel=None):
    mel = mel or FakeMel()
    monkeypatch.setattr(export, "_cmds", lambda: cmds)
    monkeypatch.setattr(export, "_mel", lambda: mel)
    # Recorded on the mel object, the same way FakeMel.evaluated records the
    # preamble: a lambda whose return nobody reads proves nothing about
    # whether the handler actually called it, only about what it would get
    # back if it did.
    mel.unit_scale_factor_calls = []

    def _fake_set_unit_scale_factor(p, value=100.0):
        mel.unit_scale_factor_calls.append(p)
        return value

    monkeypatch.setattr(export.fbxbytes, "set_unit_scale_factor",
                        _fake_set_unit_scale_factor)
    monkeypatch.setattr(export.fbxbytes, "read_fbx", lambda _p: facts)
    return mel


@pytest.fixture(autouse=True)
def _reset_fbx_loaded_time_unit():
    """export._fbx_loaded_time_unit is a plain module-level global (export.py
    assigns it directly at the point a real load happens, not through any
    test seam), so a real export in one test leaves it set for every test
    that runs after unless each test resets it itself - previously only
    test_a_fresh_load_records_the_scene_time_unit did. Reset it around every
    test in this file so none of them can see another's leftover value."""
    saved = export._fbx_loaded_time_unit
    export._fbx_loaded_time_unit = None
    yield
    export._fbx_loaded_time_unit = saved


class TestFbxReloadGuard:
    """#729: fbxmaya force-reload only when the scene's frame rate changed.

    See export.py's module-level comment above _fbx_reload_needed for the
    measured crash this replaces (a running total of 3 unload/reload
    cycles in one mayapy process corrupts the Windows heap, 3/3
    reproduced - t718-10b-report.md)."""

    def test_reload_decision_truth_table(self):
        # (loaded, cached, scene) -> reload?
        assert export._fbx_reload_needed(False, None, "ntsc") is False
        assert export._fbx_reload_needed(False, "film", "ntsc") is False
        assert export._fbx_reload_needed(True, None, "ntsc") is True
        assert export._fbx_reload_needed(True, "film", "ntsc") is True
        assert export._fbx_reload_needed(True, "ntsc", "ntsc") is False

    def test_a_static_export_never_unloads_the_plugin(self, monkeypatch,
                                                       tmp_path):
        node = fbxbytes.FbxNode(name="golem_C_pelvis", kind="Mesh", uid=1,
                                geometry=7)
        cmds = FakeCmds()
        _install(monkeypatch, cmds, _facts([node]))
        export.export_fbx(_params(tmp_path))
        assert not any(c[0] == "unloadPlugin" for c in cmds.calls)

    def test_a_fresh_load_records_the_scene_time_unit(self, monkeypatch,
                                                       tmp_path):
        node = fbxbytes.FbxNode(name="golem_C_pelvis", kind="Mesh", uid=1,
                                geometry=7)
        cmds = FakeCmds(plugin_loaded=False)
        _install(monkeypatch, cmds, _facts([node]))
        monkeypatch.setattr(export, "_fbx_loaded_time_unit", None)
        export.export_fbx(_params(tmp_path))
        assert export._fbx_loaded_time_unit == "ntsc"


def test_a_clean_export_reports_the_file_not_the_scene(monkeypatch, tmp_path):
    node = fbxbytes.FbxNode(name="golem_C_pelvis", kind="Mesh", uid=1, geometry=7)
    facts = _facts([node])
    facts.meshes = [(0.0, 0.0, 0.0, 1.0, 4.02173, 1.0)]
    facts.geometries = {7: facts.meshes[0]}
    cmds = FakeCmds()
    mel = _install(monkeypatch, cmds, facts)

    out = export.export_fbx({"path": str(tmp_path / "golem.fbx"),
                             "metres_per_unit": 1.0})

    assert out["fbx_version"] == 7700
    assert out["node_count"] == 1
    assert out["root_nodes"] == ["golem_C_pelvis"]
    assert out["unit_scale_factor"] == 100.0
    assert out["metres_per_unit"] == 1.0
    assert out["bytes"] == len(b"not really an fbx")
    assert abs(out["height_m"] - 4.02173) < 1e-6
    assert out["bounds_unavailable_reason"] is None
    # The measured preamble ran, in order, then the scene-content flags, with
    # the factor last.
    assert mel.evaluated == (list(export.FBX_PREAMBLE_MEL)
                             + list(export.FBX_SCENE_CONTENT_MEL)
                             + list(export.FBX_SHAPES_MEL)
                             + list(export.FBX_SKINS_MEL[False])
                             + list(export.FBX_ANIM_MEL[False])
                             + ["FBXExportScaleFactor 1"])
    # The unit declaration must actually be patched, on the exact file just
    # written - which is the TEMP file, not the final path: the write and
    # patch happen before the gate has passed, and only os.replace at the end
    # touches the real path.
    assert mel.unit_scale_factor_calls == [out["path"] + ".part.fbx"]
    # The default is skinless, stated rather than left to FBXResetExport's
    # defaults, and the result says so with a null rather than an absent key.
    assert "FBXExportSkins -v false" in mel.evaluated
    assert out["skin"] is None


def test_a_failed_plugin_load_raises_a_clear_handler_error(monkeypatch, tmp_path):
    # #695 regression: loadPlugin's failure used to be swallowed by a bare
    # `except Exception: pass`, so a genuinely missing plugin surfaced later
    # as an obscure MEL error ("Cannot find procedure ...") instead of here,
    # where the cause is known.
    node = fbxbytes.FbxNode(name="golem_C_pelvis", kind="Mesh", uid=1, geometry=7)
    facts = _facts([node])
    cmds = FakeCmds(load_plugin_raises=RuntimeError("fbxmaya not found"))
    _install(monkeypatch, cmds, facts)

    with pytest.raises(HandlerError, match="fbxmaya plugin failed to load"):
        export.export_fbx({"path": str(tmp_path / "golem.fbx"),
                           "metres_per_unit": 1.0})


def _good_skin_block():
    return {"deformers": 1, "clusters": 3, "influenced_models": 3,
            "bind_pose_present": True, "max_weight_sum_error": 2e-7,
            "unweighted_file_vertices": 0, "unavailable_reason": None}


def test_include_skins_switches_the_mel_and_reports_the_block(
        monkeypatch, tmp_path):
    node = fbxbytes.FbxNode(name="tube", kind="Mesh", uid=1, geometry=7)
    joint = fbxbytes.FbxNode(name="j1", kind="LimbNode", uid=2)
    facts = _facts([node, joint])
    facts.meshes = [(0.0, 0.0, 0.0, 1.0, 2.0, 1.0)]
    facts.geometries = {7: facts.meshes[0]}
    cmds = FakeCmds()
    mel = _install(monkeypatch, cmds, facts)
    monkeypatch.setattr(export.fbxbytes, "skin_facts",
                        lambda _f: _good_skin_block())

    out = export.export_fbx({"path": str(tmp_path / "skinned.fbx"),
                             "metres_per_unit": 1.0, "include_skins": True})

    assert "FBXExportSkins -v true" in mel.evaluated
    assert "FBXExportSkins -v false" not in mel.evaluated
    assert out["skin"] == _good_skin_block()


def test_a_skinless_file_refuses_an_include_skins_export(monkeypatch, tmp_path):
    # The false-green class: the caller asked for skins and the bytes hold
    # none, so the file must not reach `path`.
    facts = _facts([fbxbytes.FbxNode(name="tube", kind="Mesh", uid=1)])
    _install(monkeypatch, FakeCmds(), facts)
    empty = {"deformers": 0, "clusters": 0, "influenced_models": 0,
             "bind_pose_present": False, "max_weight_sum_error": None,
             "unweighted_file_vertices": 0, "unavailable_reason": None}
    monkeypatch.setattr(export.fbxbytes, "skin_facts", lambda _f: empty)

    path = tmp_path / "dry.fbx"
    with pytest.raises(HandlerError) as exc:
        export.export_fbx({"path": str(path), "metres_per_unit": 1.0,
                           "include_skins": True})

    assert "no skin deformer" in str(exc.value)
    # A skin violation is not a unit violation, and "freeze transforms" is not
    # the action: the hint has to name the one that is.
    assert "maya_bind_skin" in (exc.value.hint or "")
    assert not path.exists()
    assert not (tmp_path / "dry.fbx.part.fbx").exists()


def test_a_violating_file_is_deleted_not_returned(monkeypatch, tmp_path):
    bad = fbxbytes.FbxNode(name="kit_root", kind="Null", uid=1,
                           scaling=(0.01, 0.01, 0.01))
    # The mesh under it is what makes the root's scale reach a vertex - #629's
    # root carried one, and the gate only asserts identity where it can matter.
    under = fbxbytes.FbxNode(name="kit_piece", kind="Mesh", uid=2, parent=1,
                             geometry=99)
    path = tmp_path / "bad.fbx"
    _install(monkeypatch, FakeCmds(), _facts([bad, under]))

    with pytest.raises(HandlerError) as exc:
        export.export_fbx({"path": str(path), "metres_per_unit": 1.0})

    assert "kit_root" in str(exc.value)
    assert not path.exists(), "a file that fails the gate must not reach a delivery"
    assert not (tmp_path / "bad.fbx.part.fbx").exists(), \
        "the temp file must be cleaned up too, not just left as 'not path'"


def test_a_pre_existing_file_survives_a_failed_export(monkeypatch, tmp_path):
    # Finding A: `cmds.file(..., force=True)` overwrites whatever sits at
    # `path`, so re-exporting over a shipped delivery after a scene edit that
    # trips the gate must not cost that delivery its good file. This is the
    # test that matters most for this finding.
    bad = fbxbytes.FbxNode(name="kit_root", kind="Null", uid=1,
                           scaling=(0.01, 0.01, 0.01))
    # The mesh under it is what makes the root's scale reach a vertex - #629's
    # root carried one, and the gate only asserts identity where it can matter.
    under = fbxbytes.FbxNode(name="kit_piece", kind="Mesh", uid=2, parent=1,
                             geometry=99)
    path = tmp_path / "golem.fbx"
    original = b"THE SHIPPED, ALREADY-GATED, GOOD FBX BYTES"
    path.write_bytes(original)
    _install(monkeypatch, FakeCmds(), _facts([bad, under]))

    with pytest.raises(HandlerError):
        export.export_fbx({"path": str(path), "metres_per_unit": 1.0})

    assert path.read_bytes() == original, \
        "a failed export must never touch a pre-existing file at path"
    assert not (tmp_path / "golem.fbx.part.fbx").exists()


def test_a_violating_file_that_wont_unlink_says_so_and_names_the_path(
        monkeypatch, tmp_path):
    # A Windows AV scanner or a lingering Maya handle can hold the file open.
    # If unlink fails, the message must not claim the file was deleted - that
    # is precisely the false-green report this tool exists to prevent (#642).
    bad = fbxbytes.FbxNode(name="kit_root", kind="Null", uid=1,
                           scaling=(0.01, 0.01, 0.01))
    # The mesh under it is what makes the root's scale reach a vertex - #629's
    # root carried one, and the gate only asserts identity where it can matter.
    under = fbxbytes.FbxNode(name="kit_piece", kind="Mesh", uid=2, parent=1,
                             geometry=99)
    path = tmp_path / "bad.fbx"
    _install(monkeypatch, FakeCmds(), _facts([bad, under]))

    def _refuse_to_unlink(_p):
        raise OSError("file is in use by another process")

    monkeypatch.setattr(export.os, "unlink", _refuse_to_unlink)

    with pytest.raises(HandlerError) as exc:
        export.export_fbx({"path": str(path), "metres_per_unit": 1.0})

    message = str(exc.value)
    assert "kit_root" in message
    # The success path's exact claim must not appear here - that claim would
    # be a lie in this branch.
    assert "was DELETED" not in message
    assert "NOT" in message and "DELETE" in message
    temp_file = tmp_path / "bad.fbx.part.fbx"
    # It is the TEMP file that survives now, not `path` itself - `path` was
    # never written to. The message must still name a path a human can find
    # and remove by hand.
    assert str(temp_file) in message or temp_file.name in message
    assert temp_file.exists(), "the fake unlink never actually removed the file"
    assert not path.exists(), "path itself must never have been written to"


def test_an_exception_between_write_and_gate_does_not_leave_a_file(
        monkeypatch, tmp_path):
    # Finding B: set_unit_scale_factor / read_fbx can raise for reasons that
    # are not HandlerErrors (a truncated write, a UnitScaleFactor-less file,
    # an unrecognised typecode). Whatever it is must not be swallowed, and
    # must not leave an ungated, unpatched FBX on disk for a later run - or a
    # delivery - to trip over.
    cmds = FakeCmds()
    _install(monkeypatch, cmds, _facts([]))

    def _boom(_p):
        raise ValueError("%s declares no UnitScaleFactor" % _p)

    monkeypatch.setattr(export.fbxbytes, "set_unit_scale_factor", _boom)

    path = tmp_path / "explodes.fbx"
    with pytest.raises(ValueError, match="declares no UnitScaleFactor"):
        export.export_fbx({"path": str(path), "metres_per_unit": 1.0})

    assert not path.exists()
    assert not (tmp_path / "explodes.fbx.part.fbx").exists(), \
        "an unjudged, unpatched temp file must not survive the exception"


def test_bounds_unavailable_reason_distinguishes_empty_file_from_reader_error(
        monkeypatch, tmp_path):
    # Finding C: the schema claims world_bounds_min is null only when "the
    # file holds no geometry" - but _bounds also went null for a rotation
    # order the reader cannot compose (fbxbytes.py's ValueError), which is
    # ordinary rigging practice on a shoulder or hip, not an empty file. The
    # caller must be able to tell the two apart.
    cmds = FakeCmds()

    # (a) genuinely empty - no nodes at all.
    _install(monkeypatch, cmds, _facts([]))
    out = export.export_fbx({"path": str(tmp_path / "empty.fbx"),
                             "metres_per_unit": 1.0})
    assert out["world_bounds_min"] is None
    assert out["height_m"] is None
    assert out["bounds_unavailable_reason"] == "the file holds no geometry"

    # (b) real geometry, but a rotation order fbxbytes does not implement.
    node = fbxbytes.FbxNode(name="shoulder", kind="Mesh", uid=1, geometry=1,
                            rotation_order=2)
    facts = _facts([node])
    facts.meshes = [(0.0, 0.0, 0.0, 1.0, 1.0, 1.0)]
    facts.geometries = {1: facts.meshes[0]}
    _install(monkeypatch, cmds, facts)
    out2 = export.export_fbx({"path": str(tmp_path / "rigged.fbx"),
                              "metres_per_unit": 1.0})
    assert out2["world_bounds_min"] is None
    assert out2["height_m"] is None
    # The reader's own message, propagated verbatim - not the "no geometry"
    # wording, which would be false here: mesh_count would be 1.
    assert out2["bounds_unavailable_reason"] == \
        "rotation order 2 is not implemented"
    assert out2["bounds_unavailable_reason"] != "the file holds no geometry"


def test_exporting_named_nodes_selects_them(monkeypatch, tmp_path):
    cmds = FakeCmds()
    _install(monkeypatch, cmds, _facts([]))
    export.export_fbx({"path": str(tmp_path / "one.fbx"), "metres_per_unit": 1.0,
                       "nodes": ["golem_C_pelvis"]})
    assert ("select", ["golem_C_pelvis"]) in cmds.calls
    kw = [c for c in cmds.calls if c[0] == "file"][0][2]
    assert kw.get("es") is True and "ea" not in kw


def test_exporting_everything_does_not_select(monkeypatch, tmp_path):
    cmds = FakeCmds()
    _install(monkeypatch, cmds, _facts([]))
    export.export_fbx({"path": str(tmp_path / "all.fbx"), "metres_per_unit": 1.0})
    assert not any(c[0] == "select" for c in cmds.calls)
    kw = [c for c in cmds.calls if c[0] == "file"][0][2]
    assert kw.get("ea") is True and "es" not in kw


def test_an_unknown_node_fails_before_writing_anything(monkeypatch, tmp_path):
    cmds = FakeCmds()
    _install(monkeypatch, cmds, _facts([]))
    path = tmp_path / "ghost.fbx"
    with pytest.raises(HandlerError) as exc:
        export.export_fbx({"path": str(path), "metres_per_unit": 1.0,
                           "nodes": ["no_such_thing"]})
    assert "no_such_thing" in str(exc.value)
    assert not path.exists()


def test_the_command_is_registered():
    from maya_plugin import maya_mcp_plugin
    assert maya_mcp_plugin._build_handlers()["export_fbx"] is export.export_fbx


def test_the_result_model_accepts_the_handler_payload():
    from maya_mcp.schemas import ExportFbxResult
    payload = {
        "path": "D:/deliver/golem.fbx", "bytes": 481232, "fbx_version": 7700,
        "node_count": 33, "mesh_count": 33, "root_nodes": ["golem_C_pelvis"],
        "unit_scale_factor": 100.0, "metres_per_unit": 1.0,
        "world_bounds_min": [-0.9, 0.0, -0.5],
        "world_bounds_max": [0.9, 4.02173, 0.5], "height_m": 4.02173,
    }
    result = ExportFbxResult.model_validate(payload)
    assert result.height_m == 4.02173
    assert result.root_nodes == ["golem_C_pelvis"]


def test_the_result_model_tolerates_a_geometryless_export():
    from maya_mcp.schemas import ExportFbxResult
    result = ExportFbxResult.model_validate({
        "path": "D:/deliver/empty.fbx", "bytes": 1024, "fbx_version": 7700,
        "node_count": 0, "mesh_count": 0, "root_nodes": [],
        "unit_scale_factor": 100.0, "metres_per_unit": 1.0,
    })
    assert result.height_m is None


class TestShapeViolations:
    """#691: the shapes-ride-along contract, judged from the BYTES against
    what the SCENE declared."""

    def _clean(self, names=("brow_raise",)):
        return {"blend_deformers": 1, "channels": len(names),
                "shapes": [{"name": n, "points": 6, "indexes": 6}
                           for n in names],
                "unavailable_reason": None}

    def test_a_matching_file_passes(self):
        assert export.shape_violations(self._clean(), ["brow_raise"]) == []

    def test_nothing_declared_nothing_carried_passes(self):
        empty = {"blend_deformers": 0, "channels": 0, "shapes": [],
                 "unavailable_reason": None}
        assert export.shape_violations(empty, []) == []

    def test_a_declared_target_missing_from_the_file_fails(self):
        out = export.shape_violations(self._clean(), ["brow_raise",
                                                      "bulge_up"])
        assert any("bulge_up" in v and "absent" in v for v in out)

    def test_an_empty_delta_payload_fails(self):
        sfacts = self._clean()
        sfacts["shapes"][0]["points"] = 0
        out = export.shape_violations(sfacts, ["brow_raise"])
        assert any("no delta vertices" in v for v in out)

    def test_an_index_point_mismatch_fails(self):
        sfacts = self._clean()
        sfacts["shapes"][0]["indexes"] = 4
        out = export.shape_violations(sfacts, ["brow_raise"])
        assert any("6" in v and "4" in v for v in out)

    def test_unreadable_records_fail(self):
        sfacts = self._clean()
        sfacts["unavailable_reason"] = "channel 'x' links no shape geometry"
        out = export.shape_violations(sfacts, ["brow_raise"])
        assert any("unreadable" in v for v in out)

    def test_the_preamble_now_pins_shapes_on(self):
        assert export.FBX_SHAPES_MEL == ("FBXExportShapes -v true",)
        # ...and the delivery generators' composed preamble is untouched:
        # FBX_PREAMBLE_MEL is pinned byte-for-byte elsewhere in this file.


def _good_shapes_block(names=("brow_raise",)):
    """A shapes_block with matching channels and shapes."""
    return {"blend_deformers": 1, "channels": len(names),
            "shapes": [{"name": n, "points": 6, "indexes": 6}
                       for n in names],
            "unavailable_reason": None}


def test_a_shape_less_export_reports_shapes_none(monkeypatch, tmp_path):
    """A shape-less scene exports with shapes: None in the result."""
    node = fbxbytes.FbxNode(name="golem_C_pelvis", kind="Mesh", uid=1, geometry=7)
    facts = _facts([node])
    facts.meshes = [(0.0, 0.0, 0.0, 1.0, 4.02173, 1.0)]
    facts.geometries = {7: facts.meshes[0]}
    cmds = FakeCmds()
    _install(monkeypatch, cmds, facts)
    # Default monkeypatch has empty shapes block (no channels, no shapes)
    monkeypatch.setattr(export.fbxbytes, "shape_facts",
                        lambda _f: {"blend_deformers": 0, "channels": 0,
                                    "shapes": [], "unavailable_reason": None})

    out = export.export_fbx({"path": str(tmp_path / "shapeless.fbx"),
                             "metres_per_unit": 1.0})

    assert out["shapes"] is None


def test_a_shaped_export_with_matching_alias_reports_the_block(
        monkeypatch, tmp_path):
    """An export where the file's channels match declared aliases reports
    the shapes block with channels and shapes populated."""
    node = fbxbytes.FbxNode(name="tube", kind="Mesh", uid=1, geometry=7)
    facts = _facts([node])
    facts.meshes = [(0.0, 0.0, 0.0, 1.0, 2.0, 1.0)]
    facts.geometries = {7: facts.meshes[0]}
    cmds = FakeCmds()
    _install(monkeypatch, cmds, facts)
    # Override FakeCmds to return a blendShape + alias for this test
    block = _good_shapes_block(["brow_raise"])
    monkeypatch.setattr(export.fbxbytes, "shape_facts", lambda _f: block)
    # Make FakeCmds.listHistory return a blendShape, and listAttr return the alias
    cmds.listHistory = lambda node, **kw: ["brow_raiseBlendShape"]
    cmds.listAttr = lambda attr, **kw: ["brow_raise"]
    cmds.ls = lambda nodes=None, **kw: [node.name]  # ls with type="mesh" returns the mesh

    out = export.export_fbx({"path": str(tmp_path / "shaped.fbx"),
                             "metres_per_unit": 1.0})

    assert out["shapes"] == block
    assert out["shapes"]["channels"] == 1
    assert len(out["shapes"]["shapes"]) == 1
    assert out["shapes"]["shapes"][0]["name"] == "brow_raise"


def test_a_shape_violation_in_export_raises_with_hint_and_deletes_tmp(
        monkeypatch, tmp_path):
    """An export where the scene declares an alias the file doesn't carry
    raises with shape hint and cleans up the temp file."""
    node = fbxbytes.FbxNode(name="tube", kind="Mesh", uid=1, geometry=7)
    facts = _facts([node])
    facts.meshes = [(0.0, 0.0, 0.0, 1.0, 2.0, 1.0)]
    facts.geometries = {7: facts.meshes[0]}
    cmds = FakeCmds()
    _install(monkeypatch, cmds, facts)
    # File carries brow_raise, but scene declares both brow_raise and bulge_up
    file_block = _good_shapes_block(["brow_raise"])
    monkeypatch.setattr(export.fbxbytes, "shape_facts", lambda _f: file_block)
    # Scene declares two aliases but file only carries one
    cmds.listHistory = lambda node, **kw: ["brow_raiseBlendShape"]
    cmds.listAttr = lambda attr, **kw: ["brow_raise", "bulge_up"]
    cmds.ls = lambda nodes=None, **kw: [node.name]

    path = tmp_path / "shape_violation.fbx"
    with pytest.raises(HandlerError) as exc:
        export.export_fbx({"path": str(path), "metres_per_unit": 1.0})

    # The violation message must name the missing shape
    assert "bulge_up" in str(exc.value)
    assert "absent" in str(exc.value)
    # The shape hint must be in the error
    assert "shaped mesh itself" in (exc.value.hint or "")
    # The temp file must be cleaned up
    assert not path.exists()
    assert not (tmp_path / "shape_violation.fbx.part.fbx").exists()


def test_the_tool_is_exposed():
    source = (REPO / "src" / "maya_mcp" / "server.py").read_text(encoding="utf-8")
    assert "def maya_export_fbx(" in source
    # Named for the format it writes. #640 is open about naming papercuts and a
    # bare maya_export would promise OBJ and USD this tool does not have.
    assert "def maya_export(" not in source


class TestAnimViolations:
    """#695/#718: the include_animation contract, judged from the BYTES
    against what the SCENE's clip metadata declared - now per clip."""

    def _record(self, name, start, end, **kw):
        record = {"name": name, "fps": 30, "start_frame": start,
                  "end_frame": end, "duration_s": (end - start) / 30.0,
                  "loop": False, "interpolation": "linear",
                  "joints": ["L_hip"], "weight_channels": [],
                  "root_position_used": False}
        record.update(kw)
        return record

    def _declared(self):
        return {"root": "pelvis", "fps": 30, "span_frames": 62,
                "clips": [
                    self._record("idle", 0, 30, weight_channels=["blink"]),
                    self._record("walk", 32, 62, root_position_used=True),
                ]}

    def _take(self, name, start, stop):
        return {"name": name, "start_s": start / 30.0,
                "stop_s": stop / 30.0, "duration_s": (stop - start) / 30.0}

    def _clean(self):
        # MEASURED (#718 Task 10, t718-10-report.md finding #3): a two-clip
        # file carries THREE AnimationCurveNode records per animated plug,
        # not one - one full-span record under Maya's own always-present
        # default take ("Take 001", 63 keys over the whole 0..62 range),
        # plus one per named take carrying that take's own range (31 keys
        # each for these two 31-frame clips). Every channel any clip
        # declares (L_hip rotation, pelvis translation, blink) rides along
        # in every take - the split-into-takes call crops the SAME baked
        # channel set, it does not filter which channels a take carries.
        targets = []
        for take, keys in (("Take 001", 63), ("idle", 31), ("walk", 31)):
            duration = (keys - 1) / 30.0
            targets.append({"target": "L_hip", "property": "Lcl Rotation",
                            "curves": 3, "key_count": keys,
                            "duration_s": duration, "take": take})
            targets.append({"target": "pelvis",
                            "property": "Lcl Translation", "curves": 3,
                            "key_count": keys, "duration_s": duration,
                            "take": take})
            targets.append({"target": "blink", "property": "DeformPercent",
                            "curves": 1, "key_count": keys,
                            "duration_s": duration, "take": take})
        return {"stacks": 3, "layers": 3, "curves": 21, "curve_nodes": 9,
                "takes": [self._take("Take 001", 0, 62),
                          self._take("idle", 0, 30),
                          self._take("walk", 32, 62)],
                "targets": targets,
                "unavailable_reason": None}

    def test_a_matching_file_passes(self):
        assert export.anim_violations(self._clean(), self._declared()) == []

    def test_every_declared_clip_needs_its_own_take(self):
        afacts = self._clean()
        afacts["takes"] = [t for t in afacts["takes"] if t["name"] != "walk"]
        out = export.anim_violations(afacts, self._declared())
        # Exactly one violation, and it is walk's missing take - idle's own
        # take is present and correct and earns no violation of its own.
        # (Not a bare "'idle' not in any v": the one violation about walk
        # legitimately NAMES idle in its "has: ..." diagnostic listing of
        # the takes the file DOES carry - the same pattern
        # test_include_animation_false_asserts_zero_curves's "has: none"
        # relies on - so a substring check would pass even if idle's own
        # take were silently broken too.)
        assert (len(out) == 1
                and out[0].startswith("the file carries no take named 'walk'"))

    def test_a_take_at_the_wrong_place_on_the_timeline_fails(self):
        afacts = self._clean()
        afacts["takes"][2] = self._take("walk", 0, 30)
        out = export.anim_violations(afacts, self._declared())
        assert any("'walk'" in v and "frames 32-62" in v for v in out)

    def test_a_take_off_by_exactly_one_frame_fails(self):
        # tol is half a frame, not a whole one (#718 review): a take that
        # slips by exactly one frame - on either boundary - must still be
        # caught. Clips sit two frames apart (one unowned gap frame), so a
        # one-frame boundary error is exactly the mistake this gate exists
        # to catch, and a whole-frame tolerance let it through undetected.
        afacts = self._clean()
        afacts["takes"][1] = self._take("idle", 1, 30)   # start slips by 1
        out = export.anim_violations(afacts, self._declared())
        assert any("'idle'" in v and "frames 0-30" in v for v in out)

        afacts = self._clean()
        afacts["takes"][1] = self._take("idle", 0, 29)   # stop slips by 1
        out = export.anim_violations(afacts, self._declared())
        assert any("'idle'" in v and "frames 0-30" in v for v in out)

    def test_overlapping_or_repeated_declarations_fail(self):
        declared = self._declared()
        declared["clips"][1]["start_frame"] = 30
        out = export.anim_violations(self._clean(), declared)
        assert any("overlap" in v for v in out)

    def test_extra_takes_are_not_violations(self):
        # Maya's own default take ("Take 001") rides along with every
        # animated export this tool makes - MEASURED in phase 6. An
        # UNDECLARED extra take beyond that (e.g. a leftover from a
        # previous author_clip) must not be flagged either - only a
        # missing declared take is a violation, per the shape_violations
        # precedent this docstring cites.
        afacts = self._clean()
        afacts["takes"].append(self._take("Take 002", 0, 30))
        assert export.anim_violations(afacts, self._declared()) == []

    def test_curves_are_required_for_every_channel_any_clip_declared(self):
        afacts = self._clean()
        afacts["targets"] = [t for t in afacts["targets"]
                             if t["target"] != "blink"]
        out = export.anim_violations(afacts, self._declared())
        assert any("blink" in v for v in out)
        afacts = self._clean()
        afacts["targets"] = [t for t in afacts["targets"]
                             if t["target"] != "pelvis"]
        out = export.anim_violations(afacts, self._declared())
        assert any("root translation" in v for v in out)

    def test_keys_are_counted_by_the_takes_own_span(self):
        """#718 Task 10b: the expected key count is the TAKE's own span
        (end_frame - start_frame + 1), never the file's whole span - the
        old whole-span assumption this test used to pin is exactly the bug
        that made the byte gate non-deterministic (t718-10-report.md
        finding #3). "Take 001"'s own full-span record is excluded from
        this check entirely (see anim_violations's docstring), so
        corrupting IT must not be what this test catches - only a named
        take's own record counts."""
        afacts = self._clean()
        for t in afacts["targets"]:
            if t["target"] == "L_hip" and t["take"] == "idle":
                t["key_count"] = 30   # one short of idle's own 31-key span
        out = export.anim_violations(afacts, self._declared())
        assert any("L_hip" in v and "'idle'" in v and "31" in v for v in out)

    def test_include_animation_false_asserts_zero_curves(self):
        empty = {"stacks": 0, "layers": 0, "curves": 0, "curve_nodes": 0,
                 "takes": [], "targets": [], "unavailable_reason": None}
        assert export.anim_violations(empty, None) == []
        out = export.anim_violations(self._clean(), None)
        assert any("include_animation" in v for v in out)

    def test_the_per_clip_block_is_read_back_from_the_bytes(self):
        """#718: the result grows a per-clip list - name, the frame range
        the FILE says the take spans, its duration and the curve count
        measured back from the records, never echoed from the scene."""
        clips = export.anim_clip_facts(self._clean(), self._declared())
        assert [c["name"] for c in clips] == ["idle", "walk"]
        assert (clips[0]["start_frame"], clips[0]["end_frame"]) == (0, 30)
        assert (clips[1]["start_frame"], clips[1]["end_frame"]) == (32, 62)
        assert clips[0]["duration_s"] == pytest.approx(1.0)
        # idle declares L_hip (3 curves) and blink (1)
        assert clips[0]["curves"] == 4
        # walk declares L_hip (3) and the root's translation (3)
        assert clips[1]["curves"] == 6
        # a take the file does not carry reports its range as None, and
        # says so rather than inventing one
        afacts = self._clean()
        afacts["takes"] = [t for t in afacts["takes"] if t["name"] != "walk"]
        clips = export.anim_clip_facts(afacts, self._declared())
        assert clips[1]["start_frame"] is None
        assert clips[1]["curves"] == 6

    # --- pre-#718 behaviour that must survive, updated to the per-clip
    # `declared` shape (a dict of clips, not a single clip dict). The
    # take-name/duration case is now covered above by
    # test_every_declared_clip_needs_its_own_take (a missing take) and
    # test_a_take_at_the_wrong_place_on_the_timeline_fails (a take whose
    # start_s/stop_s do not match the declared range, which is how a wrong
    # duration surfaces now that a take's range is read from LocalTime
    # instead of compared as a bare duration); the "blink" presence half of
    # the old weight-channel test is likewise already covered above by
    # test_curves_are_required_for_every_channel_any_clip_declared.

    def test_missing_or_miscounted_joint_curves_fail(self):
        afacts = self._clean()
        afacts["targets"] = [t for t in afacts["targets"]
                             if t["target"] != "L_hip"]
        out = export.anim_violations(afacts, self._declared())
        assert any("L_hip" in v and "no rotation curves" in v
                   and "'idle'" in v for v in out)
        assert any("L_hip" in v and "no rotation curves" in v
                   and "'walk'" in v for v in out)
        afacts = self._clean()
        for t in afacts["targets"]:
            if t["target"] == "L_hip" and t["take"] == "idle":
                t["curves"] = 2
        out = export.anim_violations(afacts, self._declared())
        assert any("L_hip" in v and "2 curve" in v and "'idle'" in v
                   for v in out)

    def test_root_translation_gates_only_when_a_clip_uses_it(self):
        afacts = self._clean()
        afacts["targets"] = [t for t in afacts["targets"]
                             if t["property"] != "Lcl Translation"]
        out = export.anim_violations(afacts, self._declared())
        assert any("root" in v and "translation" in v for v in out)
        declared = self._declared()
        for record in declared["clips"]:
            record["root_position_used"] = False
        assert export.anim_violations(afacts, declared) == []

    def test_weight_channel_short_key_count_fails(self):
        # Whether Maya bakes DeformPercent curves or carries them as
        # authored is a mayapy measurement (contract decision 10) - so the
        # gate is presence + >=2 keys, never a full frame count.
        afacts = self._clean()
        for t in afacts["targets"]:
            if t["target"] == "blink" and t["take"] == "idle":
                t["key_count"] = 1
        out = export.anim_violations(afacts, self._declared())
        assert any("blink" in v and "1 key" in v and "'idle'" in v
                   for v in out)

    def test_extra_targets_are_not_violations(self):
        afacts = self._clean()
        afacts["targets"].append(
            {"target": "hand_keyed", "property": "Lcl Rotation",
             "curves": 3, "key_count": 31, "duration_s": 1.0,
             "take": "idle"})
        assert export.anim_violations(afacts, self._declared()) == []

    def test_unreadable_records_fail(self):
        afacts = self._clean()
        afacts["unavailable_reason"] = "curve node 'T' drives nothing"
        out = export.anim_violations(afacts, self._declared())
        assert any("unreadable" in v for v in out)

    def test_the_anim_preamble_is_pinned_both_ways(self):
        assert export.FBX_ANIM_MEL[False] == (
            'FBXProperty "Export|IncludeGrp|Animation" -v false',
            "FBXExportBakeComplexAnimation -v false",
        )
        assert export.FBX_ANIM_MEL[True] == (
            'FBXProperty "Export|IncludeGrp|Animation" -v true',
            "FBXExportBakeComplexAnimation -v true",
            "FBXExportBakeComplexStep -v 1",
            # MEASURED under mayapy (TestClipExportInMaya, #695 battery item
            # 4): without this, FBXExportBakeComplexAnimation alone left the
            # 3 raw authored keyframes untouched instead of resampling to
            # one key per frame - a 1.0 s/30 fps clip measured key_count=3,
            # not the expected 31. Adding this flag alone (bake step/range
            # unchanged) took every curve's key_count from 3 to 31.
            "FBXExportBakeResampleAnimation -v true",
        )


class TestSceneClips:
    def test_two_rigs_carrying_clips_refuse_with_the_corrected_message(self):
        import json

        from maya_plugin.dispatcher import HandlerError

        class Cmds:
            def ls(self, type=None, long=False):
                return ["|rig_a", "|rig_b"]

            def attributeQuery(self, attr, node=None, exists=False):
                return True

            def getAttr(self, plug):
                return json.dumps([{"name": "idle", "fps": 30,
                                    "start_frame": 0, "end_frame": 30,
                                    "duration_s": 1.0}])

        with pytest.raises(HandlerError) as excinfo:
            export._scene_clips(Cmds())
        message = str(excinfo.value)
        assert "rig_a" in message and "rig_b" in message
        assert "several clips" in message and "two skeletons" in message


class TestExportFbxReportsClips:
    """#718 fix wave 2: fix wave 1 fixed a real mutation bug (export_fbx used
    to write anim_clip_facts's output onto the SAME dict fbxbytes.anim_facts
    returned, which breaks the byte-honesty cross-checks in
    tests/test_handlers_mayapy.py and evals/clip_live.py) but over-corrected
    by dropping the "clips" field from the result entirely. The design spec
    (docs/superpowers/specs/2026-08-22-multi-take-fbx-design.md:151) still
    requires it: "animation in the result grows a per-clip list: name, frame
    range, duration and the curve count measured back from the bytes." These
    two tests pin the restored behaviour end to end through export_fbx,
    using the same declared/clean fixture shapes TestAnimViolations already
    proved pass the gate cleanly (test_a_matching_file_passes)."""

    def _declared(self):
        # Identical in shape and values to TestAnimViolations._declared() -
        # proven by test_a_matching_file_passes to earn zero violations
        # against _clean() below, so this export takes the "gate passed"
        # path all the way to the return statement.
        return {"root": "pelvis", "fps": 30, "span_frames": 62,
                "clips": [
                    {"name": "idle", "fps": 30, "start_frame": 0,
                     "end_frame": 30, "duration_s": 1.0, "loop": False,
                     "interpolation": "linear", "joints": ["L_hip"],
                     "weight_channels": ["blink"],
                     "root_position_used": False},
                    {"name": "walk", "fps": 30, "start_frame": 32,
                     "end_frame": 62, "duration_s": 1.0, "loop": False,
                     "interpolation": "linear", "joints": ["L_hip"],
                     "weight_channels": [], "root_position_used": True},
                ]}

    def _clean(self):
        def take(name, start, stop):
            return {"name": name, "start_s": start / 30.0,
                    "stop_s": stop / 30.0,
                    "duration_s": (stop - start) / 30.0}
        # Same segmented-per-take shape as TestAnimViolations._clean() -
        # MEASURED (#718 Task 10, t718-10-report.md finding #3): three
        # AnimationCurveNode records per plug, not one.
        targets = []
        for take_name, keys in (("Take 001", 63), ("idle", 31),
                                ("walk", 31)):
            duration = (keys - 1) / 30.0
            targets.append({"target": "L_hip", "property": "Lcl Rotation",
                            "curves": 3, "key_count": keys,
                            "duration_s": duration, "take": take_name})
            targets.append({"target": "pelvis",
                            "property": "Lcl Translation", "curves": 3,
                            "key_count": keys, "duration_s": duration,
                            "take": take_name})
            targets.append({"target": "blink", "property": "DeformPercent",
                            "curves": 1, "key_count": keys,
                            "duration_s": duration, "take": take_name})
        return {"stacks": 3, "layers": 3, "curves": 21, "curve_nodes": 9,
                "takes": [take("Take 001", 0, 62),
                          take("idle", 0, 30),
                          take("walk", 32, 62)],
                "targets": targets,
                "unavailable_reason": None}

    def _export(self, monkeypatch, tmp_path, name, declared, clean):
        node = fbxbytes.FbxNode(name="golem_C_pelvis", kind="Mesh", uid=1)
        facts = _facts([node])

        class AnimFakeCmds(FakeCmds):
            def pluginInfo(self, plugin, query=False, loaded=False):
                # False skips the unload/reload branch (mayapy-only
                # behaviour, irrelevant to what this test pins).
                return False

        cmds = AnimFakeCmds()
        _install(monkeypatch, cmds, facts)
        monkeypatch.setattr(export, "_scene_clips", lambda _cmds: declared)
        monkeypatch.setattr(export.fbxbytes, "anim_facts", lambda _f: clean)
        return export.export_fbx({"path": str(tmp_path / name),
                                  "metres_per_unit": 1.0,
                                  "include_animation": True})

    def test_animated_export_reports_a_clips_list(self, monkeypatch, tmp_path):
        declared = self._declared()
        clean = self._clean()
        out = self._export(monkeypatch, tmp_path, "clip.fbx", declared, clean)

        anim = out["animation"]
        assert anim is not None
        clips = anim["clips"]
        assert [c["name"] for c in clips] == ["idle", "walk"]
        assert (clips[0]["start_frame"], clips[0]["end_frame"]) == (0, 30)
        assert (clips[1]["start_frame"], clips[1]["end_frame"]) == (32, 62)
        assert clips[0]["duration_s"] == pytest.approx(1.0)
        # idle declares L_hip (3 curves) + blink (1); walk declares L_hip
        # (3) + the root's translation (3) - same measured counts
        # test_the_per_clip_block_is_read_back_from_the_bytes pins directly
        # against anim_clip_facts, now proven to survive the trip through
        # export_fbx's result too.
        assert clips[0]["curves"] == 4
        assert clips[1]["curves"] == 6
        # the reader's own keys ride along untouched, alongside "clips"
        assert anim["takes"] == clean["takes"]
        assert anim["targets"] == clean["targets"]

    def test_the_reported_block_is_not_the_readers_object(
            self, monkeypatch, tmp_path):
        """Fix wave 1's good half must survive: result["animation"] is a
        NEW dict, never fbxbytes.anim_facts's own return value with "clips"
        spliced into it in place. A regression back to `anim_block["clips"]
        = ...; return {"animation": anim_block}` would pass the previous
        test on VALUE alone (dict equality doesn't care how the dict was
        built) but is caught here: it would leave "clips" sitting on `clean`
        itself (the exact object monkeypatched in as anim_facts's return
        value) and make `out["animation"]` the same object as `clean`,
        both of which this test asserts against."""
        declared = self._declared()
        clean = self._clean()
        out = self._export(monkeypatch, tmp_path, "clip2.fbx", declared, clean)

        assert out["animation"] is not clean
        assert "clips" not in clean


class FakeClipSceneCmds:
    """Only what _scene_clips touches: joints, the mcp_clip attr."""
    def __init__(self, attrs):
        # attrs: {joint_long_name: mcp_clip string or None}
        self.attrs = attrs

    def ls(self, type=None, long=False):
        return list(self.attrs)

    def attributeQuery(self, attr, node=None, exists=False):
        return self.attrs.get(node) is not None

    def getAttr(self, key):
        node = key.rsplit(".", 1)[0]
        return self.attrs[node]


class TestSceneClipsPredicate:
    def _records(self):
        return json.dumps([{"name": "idle", "fps": 30,
                            "start_frame": 0, "end_frame": 30}])

    def test_an_empty_attr_beside_a_real_rig_does_not_refuse(self):
        cmds = FakeClipSceneCmds({"|rig": self._records(), "|junk": "[]"})
        declared = export._scene_clips(cmds)
        assert declared is not None and declared["root"] == "rig"

    def test_two_real_rigs_still_refuse(self):
        cmds = FakeClipSceneCmds({"|a": self._records(),
                                  "|b": self._records()})
        with pytest.raises(HandlerError, match="skeletons carry clips"):
            export._scene_clips(cmds)

    def test_only_empty_attrs_means_no_clips(self):
        cmds = FakeClipSceneCmds({"|junk": "[]"})
        assert export._scene_clips(cmds) is None


def _tfacts(basenames=(), names=()):
    return {"texture_records": len(basenames), "video_records": len(basenames),
            "textures": [{"name": n, "basename": b}
                         for n, b in zip(names or basenames, basenames)],
            "videos": [{"name": n, "basename": b}
                       for n, b in zip(names or basenames, basenames)],
            "unavailable_reason": None}


def _file_claim(basename="grain.png", on_disk=True, semantics_lost=(),
                material="skin_mat", attr="baseColor"):
    return {"mesh": "|bodyShape", "meshes": ["|bodyShape"],
            "material": material, "sg": "bodySG", "attr": attr,
            "slot": "color", "classification": "file",
            "terminals": [{"node": "tex", "type": "file",
                           "file_path": "C:/t/" + basename,
                           "basename": basename, "on_disk": on_disk,
                           "colorspace": "sRGB"}],
            "via": [], "semantics_lost": list(semantics_lost)}


def _multi_file_claim(basename_a="diffuse.png", basename_b="grain.png",
                      on_disk_b=False, semantics_lost=(),
                      material="skin_mat", attr="baseColor"):
    """A two-terminal file claim (fix round 2). texclaim legitimately
    produces these: once the walk steps through a bump2d/reverse it queries
    the bare node, so two file-fed attributes of one such node yield two
    file terminals in one claim. Terminal A is basename_a (found by
    default); terminal B is basename_b, defaulting to on_disk=False so it
    only warns rather than violating."""
    return {"mesh": "|bodyShape", "meshes": ["|bodyShape"],
            "material": material, "sg": "bodySG", "attr": attr,
            "slot": "color", "classification": "file",
            "terminals": [
                {"node": "texA", "type": "file",
                 "file_path": "C:/t/" + basename_a,
                 "basename": basename_a, "on_disk": True,
                 "colorspace": "Raw"},
                {"node": "texB", "type": "file",
                 "file_path": "C:/t/" + basename_b,
                 "basename": basename_b, "on_disk": on_disk_b,
                 "colorspace": "sRGB"},
            ],
            "via": [], "semantics_lost": list(semantics_lost)}


def _procedural_claim(terminal="mcpTex_noise", ttype="noise"):
    return {"mesh": "|bodyShape", "meshes": ["|bodyShape"],
            "material": "skin_mat", "sg": "bodySG", "attr": "normalCamera",
            "slot": "normal", "classification": "procedural",
            "terminals": [{"node": terminal, "type": ttype,
                           "file_path": None, "basename": None,
                           "on_disk": None, "colorspace": None}],
            "via": ["bump2d"], "semantics_lost": []}


class TestTextureViolations:
    def test_a_surviving_file_claim_is_clean(self):
        bad, warn = export.texture_violations(
            _tfacts(["grain.png"]), [_file_claim()], False)
        assert bad == [] and warn == []

    def test_a_file_claim_absent_from_the_bytes_refuses_in_both_modes(self):
        # Never-observed loss class: file-backed maps always survived in
        # every measurement, so its absence is an exporter regression and
        # refusing it breaks nobody.
        for strict in (False, True):
            bad, _warn = export.texture_violations(
                _tfacts([]), [_file_claim()], strict)
            assert len(bad) == 1
            assert "grain.png" in bad[0] and "skin_mat" in bad[0]

    def test_basename_matching_is_case_insensitive(self):
        bad, _warn = export.texture_violations(
            _tfacts(["GRAIN.PNG"]), [_file_claim("grain.png")], False)
        assert bad == []

    def test_a_claim_whose_image_is_not_on_disk_only_warns(self):
        # The exporter's behaviour for a missing image is UNMEASURED
        # (#714 probe P5) - warn until it is.
        bad, warn = export.texture_violations(
            _tfacts([]), [_file_claim(on_disk=False)], True)
        assert bad == []
        assert any("not on disk" in w for w in warn)

    def test_a_procedural_claim_warns_by_default(self):
        bad, warn = export.texture_violations(
            _tfacts([]), [_procedural_claim()], False)
        assert bad == []
        assert any("mcpTex_noise" in w and "silently drops" in w
                   for w in warn)

    def test_a_procedural_claim_violates_under_require_baked(self):
        bad, _warn = export.texture_violations(
            _tfacts([]), [_procedural_claim()], True)
        assert len(bad) == 1
        assert "normalCamera" in bad[0] or "normal" in bad[0]

    def test_semantics_lost_warns_and_never_refuses(self):
        claim = _file_claim(semantics_lost=["channel swizzle outColorR"])
        for strict in (False, True):
            bad, warn = export.texture_violations(
                _tfacts(["grain.png"]), [claim], strict)
            assert bad == []
            assert any("outColorR" in w for w in warn)

    def test_an_unclaimed_record_warns(self):
        bad, warn = export.texture_violations(
            _tfacts(["mystery.png"]), [], False)
        assert bad == []
        assert any("mystery.png" in w for w in warn)

    def test_a_procedural_name_in_the_bytes_warns_that_the_model_is_stale(
            self):
        bad, warn = export.texture_violations(
            _tfacts(["x.png"], names=["mcpTex_noise"]),
            [_procedural_claim()], False)
        assert bad == []
        assert any("stale" in w for w in warn)

    def test_an_unreadable_texture_block_warns_and_refuses_nothing(self):
        tfacts = dict(_tfacts([]), unavailable_reason="record truncated")
        bad, warn = export.texture_violations(
            tfacts, [_file_claim()], True)
        assert bad == []
        assert any("record truncated" in w for w in warn)

    def test_an_unparseable_basename_warns_about_the_parser_gap(self):
        # Important 1 (final review): texture_facts() reports a record it
        # could not read a filename for with an empty basename rather than
        # dropping it. Nothing else here names such a record, so the gate
        # must say so itself rather than silently having no match for it.
        tfacts = _tfacts([""], names=["mysteryTex"])
        bad, warn = export.texture_violations(tfacts, [], False)
        assert bad == []
        assert any("could not parse" in w for w in warn)

    def test_the_parser_gap_warning_pairs_with_a_missing_claim_violation(
            self):
        # The whole point of naming the count: when a claim ALSO refuses
        # for "no Texture/Video record for it", the parser-gap warning must
        # be sitting right beside it, since the refusal might be this
        # reader's gap and not the exporter's.
        tfacts = _tfacts([""], names=["mysteryTex"])
        bad, warn = export.texture_violations(tfacts, [_file_claim()], False)
        assert len(bad) == 1 and "grain.png" in bad[0]
        assert any("could not parse" in w for w in warn)

    def test_unclaimed_record_warnings_are_suppressed_when_the_walk_failed(
            self):
        # Minor 3 (final review): a failed claim walk claimed nothing, so
        # every basename in the file would otherwise be reported as
        # unexplained for a reason unrelated to this export. The caller's
        # claims_unavailable warning already names the real cause.
        bad, warn = export.texture_violations(
            _tfacts(["mystery.png"]), [], False,
            claims_unavailable="the walk broke")
        assert bad == []
        assert not any("mystery.png" in w for w in warn)

    def test_a_missing_file_claim_with_semantics_lost_does_not_also_claim_survival(
            self):
        # Fix round 1, defect 1: the semantics_lost warning says the image
        # SURVIVES as a reference. A basename absent from the bytes gets the
        # violation only - asserting both at once would contradict itself.
        claim = _file_claim(semantics_lost=["channel swizzle outColorR"])
        bad, warn = export.texture_violations(_tfacts([]), [claim], False)
        assert len(bad) == 1
        assert not any("survives as an image reference" in w for w in warn)

    def test_require_baked_violation_does_not_assert_exporter_capability(
            self):
        # Fix round 1, defect 2: require_baked_textures is a contract about
        # the SCENE, not a prediction about the exporter - the refusal must
        # not claim the exporter "cannot write" this while a same-result
        # stale-model warning says that evidence is unmeasured.
        bad, warn = export.texture_violations(
            _tfacts(["x.png"], names=["mcpTex_noise"]),
            [_procedural_claim()], True)
        assert len(bad) == 1
        assert "cannot write" not in bad[0]
        assert "require_baked_textures" in bad[0]
        assert any("stale" in w for w in warn)

    def test_a_pattern_token_claim_only_warns(self):
        bad, warn = export.texture_violations(
            _tfacts([]), [_file_claim("body_<udim>.png")], False)
        assert bad == []
        assert any("body_<udim>.png" in w for w in warn)

    def test_a_pattern_token_claim_only_warns_under_require_baked_too(self):
        # The unmeasured-exporter-behaviour rule holds in both modes: a
        # sequence token never refuses, even when the caller demands
        # baked-only cargo.
        bad, warn = export.texture_violations(
            _tfacts([]), [_file_claim("body_<udim>.png")], True)
        assert bad == []
        assert any("body_<udim>.png" in w for w in warn)

    def test_semantics_lost_is_reported_when_one_of_two_terminals_survives(
            self):
        # Fix round 2: the gate over-corrected to ALL terminals found. A
        # multi-terminal claim (e.g. a bump2d feeding two file-backed
        # attributes) can have one terminal survive in the bytes and one
        # not (here: not on disk, so it only warns) - the surviving
        # terminal's semantics_lost is still true and actionable, and must
        # not be suppressed by the other terminal's unrelated warning.
        claim = _multi_file_claim(semantics_lost=["Raw colorspace"])
        bad, warn = export.texture_violations(
            _tfacts(["diffuse.png"]), [claim], False)
        assert bad == []
        assert any("Raw colorspace" in w for w in warn)

    def test_semantics_lost_is_suppressed_when_no_terminal_survives(self):
        # The pre-fix contradiction stays fixed: with NO terminal found,
        # "survives as an image reference only" would itself be false, so
        # it must not be asserted.
        claim = _multi_file_claim(semantics_lost=["Raw colorspace"])
        bad, warn = export.texture_violations(_tfacts([]), [claim], False)
        assert not any("Raw colorspace" in w for w in warn)

    def test_stale_warning_skips_file_type_terminals_in_a_mixed_procedural_claim(
            self):
        # Regression for the type == "file" skip (fix round 1, Minor 4): a
        # layeredTexture mixing real files is itself procedural, so a
        # genuine file terminal's NAME can legitimately appear among the
        # bytes' records without that being evidence the #714 drop model
        # is stale.
        claim = {"mesh": "|bodyShape", "meshes": ["|bodyShape"],
                "material": "skin_mat", "sg": "bodySG",
                "attr": "normalCamera", "slot": "normal",
                "classification": "procedural",
                "terminals": [
                    {"node": "mixTex", "type": "file",
                     "file_path": "C:/t/mixTex.png",
                     "basename": "mixTex.png", "on_disk": True,
                     "colorspace": "sRGB"},
                    {"node": "layerNode", "type": "layeredTexture",
                     "file_path": None, "basename": None,
                     "on_disk": None, "colorspace": None},
                ],
                "via": ["bump2d"], "semantics_lost": []}
        bad, warn = export.texture_violations(
            _tfacts(["x.png"], names=["mixTex"]), [claim], False)
        assert not any("stale" in w for w in warn)


class TestRequireBakedTextures:
    def test_it_must_be_a_bool(self, tmp_path):
        with pytest.raises(HandlerError, match="require_baked_textures"):
            export._validate(_params(tmp_path, require_baked_textures="yes"))

    def test_a_procedural_claim_refuses_before_anything_is_written(
            self, monkeypatch, tmp_path):
        # Pre-write refusal: the cost-nothing principle. Nothing is written,
        # so there is no temp file to clean up and no path to protect.
        node = fbxbytes.FbxNode(name="golem_C_pelvis", kind="Mesh", uid=1,
                                geometry=7)
        cmds = FakeCmds()
        _install(monkeypatch, cmds, _facts([node]))
        monkeypatch.setattr(export.texclaim, "material_claims",
                            lambda _c, _s: [_procedural_claim()])
        params = _params(tmp_path, require_baked_textures=True)
        with pytest.raises(HandlerError, match="procedural"):
            export.export_fbx(params)
        assert not any(c[0] == "file" for c in cmds.calls)

    def test_a_procedural_claim_passes_by_default_and_is_named(
            self, monkeypatch, tmp_path):
        node = fbxbytes.FbxNode(name="golem_C_pelvis", kind="Mesh", uid=1,
                                geometry=7)
        cmds = FakeCmds()
        _install(monkeypatch, cmds, _facts([node]))
        monkeypatch.setattr(export.texclaim, "material_claims",
                            lambda _c, _s: [_procedural_claim()])
        out = export.export_fbx(_params(tmp_path))
        assert out["textures"]["dropped_maps"][0]["terminal"] == "mcpTex_noise"
        assert out["textures"]["dropped_maps"][0]["material"] == "skin_mat"
        assert any("silently drops" in w for w in out["warnings"])

    def test_a_textureless_export_reports_no_texture_block(
            self, monkeypatch, tmp_path):
        node = fbxbytes.FbxNode(name="golem_C_pelvis", kind="Mesh", uid=1,
                                geometry=7)
        _install(monkeypatch, FakeCmds(), _facts([node]))
        monkeypatch.setattr(export.texclaim, "material_claims",
                            lambda _c, _s: [])
        out = export.export_fbx(_params(tmp_path))
        assert out["textures"] is None
        assert out["warnings"] == []


def _raise_boom(_c, _s):
    raise RuntimeError("boom")


class TestClaimWalkFailure:
    """The claim walk (texclaim.material_claims) is unguarded internally -
    only _file_terminal's two getAttr reads are wrapped - and export_fbx
    puts it on the critical path of EVERY export. The claim is a
    MEASUREMENT of the scene (the _bounds() precedent): a failure there
    must cost the measurement, not a good export."""

    def test_a_failing_claim_walk_does_not_break_the_export(
            self, monkeypatch, tmp_path):
        node = fbxbytes.FbxNode(name="golem_C_pelvis", kind="Mesh", uid=1,
                                geometry=7)
        _install(monkeypatch, FakeCmds(), _facts([node]))
        monkeypatch.setattr(export.texclaim, "material_claims", _raise_boom)
        out = export.export_fbx(_params(tmp_path))
        assert "boom" in out["textures"]["unavailable_reason"]
        assert any("boom" in w for w in out["warnings"])

    def test_a_failing_claim_walk_refuses_under_require_baked(
            self, monkeypatch, tmp_path):
        node = fbxbytes.FbxNode(name="golem_C_pelvis", kind="Mesh", uid=1,
                                geometry=7)
        cmds = FakeCmds()
        _install(monkeypatch, cmds, _facts([node]))
        monkeypatch.setattr(export.texclaim, "material_claims", _raise_boom)
        params = _params(tmp_path, require_baked_textures=True)
        with pytest.raises(HandlerError, match="could not be read"):
            export.export_fbx(params)
        assert not any(c[0] == "file" for c in cmds.calls)

    def test_both_unavailable_reasons_are_reported_together(
            self, monkeypatch, tmp_path):
        node = fbxbytes.FbxNode(name="golem_C_pelvis", kind="Mesh", uid=1,
                                geometry=7)
        _install(monkeypatch, FakeCmds(), _facts([node]))
        monkeypatch.setattr(export.texclaim, "material_claims", _raise_boom)
        monkeypatch.setattr(
            export.fbxbytes, "texture_facts",
            lambda _f: {"texture_records": 0, "video_records": 0,
                       "textures": [], "videos": [],
                       "unavailable_reason": "byte-reason-xyz"})
        out = export.export_fbx(_params(tmp_path))
        reason = out["textures"]["unavailable_reason"]
        assert "boom" in reason
        assert "byte-reason-xyz" in reason

    def test_a_video_only_file_still_reports_a_textures_block(
            self, monkeypatch, tmp_path):
        # Important 2 (final review): docs/protocol.md says `textures` is
        # null only when there are no Texture AND no Video records - the
        # original condition checked texture_records alone, so a
        # Video-only file (0 Texture, >0 Video) reported no block at all.
        node = fbxbytes.FbxNode(name="golem_C_pelvis", kind="Mesh", uid=1,
                                geometry=7)
        _install(monkeypatch, FakeCmds(), _facts([node]))
        monkeypatch.setattr(export.texclaim, "material_claims",
                            lambda _c, _s: [])
        monkeypatch.setattr(
            export.fbxbytes, "texture_facts",
            lambda _f: {"texture_records": 0, "video_records": 1,
                       "textures": [], "videos": [{"name": "v", "basename": "clip.mov"}],
                       "unavailable_reason": None})
        out = export.export_fbx(_params(tmp_path))
        assert out["textures"] is not None
        assert out["textures"]["video_records"] == 1

    def test_a_byte_side_only_failure_still_reports_a_textures_block(
            self, monkeypatch, tmp_path):
        # Important 2 (final review): a byte-side-only failure (the scene
        # claim walk succeeded with nothing to claim, but the bytes could
        # not be parsed) used to lose its structured unavailable_reason by
        # reporting no block at all.
        node = fbxbytes.FbxNode(name="golem_C_pelvis", kind="Mesh", uid=1,
                                geometry=7)
        _install(monkeypatch, FakeCmds(), _facts([node]))
        monkeypatch.setattr(export.texclaim, "material_claims",
                            lambda _c, _s: [])
        monkeypatch.setattr(
            export.fbxbytes, "texture_facts",
            lambda _f: {"texture_records": 0, "video_records": 0,
                       "textures": [], "videos": [],
                       "unavailable_reason": "byte-only-fail"})
        out = export.export_fbx(_params(tmp_path))
        assert out["textures"] is not None
        assert out["textures"]["unavailable_reason"] == "byte-only-fail"
