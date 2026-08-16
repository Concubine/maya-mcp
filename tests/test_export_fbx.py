"""maya-mcp #642: the export tool, and the gate it runs on its own bytes.

Nothing here imports Maya. The handler's Maya calls are faked, because the
point of this suite is the logic that decides whether a written file is
allowed to survive - and that logic must be checkable without a Maya licence.
"""
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
    node = fbxbytes.FbxNode(name="kit_root", kind="Null", uid=1,
                            scaling=(0.01, 0.01, 0.01))
    violations = export.gate_violations(_facts([node]))
    assert len(violations) == 1
    assert "kit_root" in violations[0]
    assert "identity" in violations[0]


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
    path, nodes = export._validate(_params(tmp_path))
    assert path.endswith("/out.fbx")
    assert "\\" not in path
    assert nodes is None


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
    _path, nodes = export._validate(_params(tmp_path, nodes=["golem_C_pelvis"]))
    assert nodes == ["golem_C_pelvis"]


class FakeCmds:
    """Just enough Maya to drive the handler: record the calls, write a file."""

    def __init__(self, existing=("golem_C_pelvis",)):
        self.existing = set(existing)
        self.calls = []

    def loadPlugin(self, name, quiet=False):
        self.calls.append(("loadPlugin", name))

    def objExists(self, name):
        return name in self.existing

    def select(self, names, replace=False):
        self.calls.append(("select", names))

    def file(self, path, **kw):
        self.calls.append(("file", path, kw))
        with open(path, "wb") as fh:
            fh.write(b"not really an fbx")


class FakeMel:
    def __init__(self):
        self.evaluated = []

    def eval(self, statement):
        self.evaluated.append(statement)


def _install(monkeypatch, cmds, facts, mel=None):
    mel = mel or FakeMel()
    monkeypatch.setattr(export, "_cmds", lambda: cmds)
    monkeypatch.setattr(export, "_mel", lambda: mel)
    monkeypatch.setattr(export.fbxbytes, "set_unit_scale_factor",
                        lambda _p, value=100.0: value)
    monkeypatch.setattr(export.fbxbytes, "read_fbx", lambda _p: facts)
    return mel


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
    # The measured preamble ran, in order, with the factor last.
    assert mel.evaluated == list(export.FBX_PREAMBLE_MEL) + ["FBXExportScaleFactor 1"]


def test_a_violating_file_is_deleted_not_returned(monkeypatch, tmp_path):
    bad = fbxbytes.FbxNode(name="kit_root", kind="Null", uid=1,
                           scaling=(0.01, 0.01, 0.01))
    path = tmp_path / "bad.fbx"
    _install(monkeypatch, FakeCmds(), _facts([bad]))

    with pytest.raises(HandlerError) as exc:
        export.export_fbx({"path": str(path), "metres_per_unit": 1.0})

    assert "kit_root" in str(exc.value)
    assert not path.exists(), "a file that fails the gate must not reach a delivery"


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
