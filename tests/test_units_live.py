"""evals/units_live.py's contract, pinned headlessly (maya-mcp #634).

Two things this gate must get right, neither of which its own green run can
prove:

  * **it must be able to fail.** The whole point is that
    `export_metres_per_unit` DISCRIMINATES - it predicts 3.0 in a cm scene and
    300.0 in an m scene. A gate that would pass whatever the file contained
    would have waved through every one of #629's three broken ships.
  * **it must leave the session metre-true.** It deliberately sets the scene to
    "m" halfway through. If it can exit with that still in place it has become
    the exact hazard it exists to close.

Loads the real script by path and monkeypatches its `call`/`fbx_probe` names so
main() runs for real against stubs - no socket, no Maya, no FBX on disk, and
evals/units_live.py itself is untouched. Same technique as
tests/test_assemble_pivots_live.py.
"""

import importlib.util
import os

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_script():
    path = os.path.join(REPO_ROOT, "evals", "units_live.py")
    spec = importlib.util.spec_from_file_location("evals_units_live", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.CHECKS = []  # a module-level accumulator; isolate each test
    return module


class FakeFacts:
    def __init__(self, span):
        # One cube's worth of flat (x,y,z...) vertices spanning `span`.
        h = span / 2.0
        self.meshes = [tuple(
            v for corner in (
                (-h, -h, -h), (h, -h, -h), (h, h, -h), (-h, h, -h),
                (-h, -h, h), (h, -h, h), (h, h, h), (-h, h, h),
            ) for v in corner
        )]


def _install_stubs(monkeypatch, module, *, spans=None, export_raises_on=None):
    """Stub the wire and the FBX reader.

    `spans` maps the scene unit at export time to the span the "file" contains,
    so a test can hand the gate a file that contradicts the prediction.
    """
    spans = spans or {"cm": 3.0, "m": 300.0}
    state = {"unit": "cm"}
    log = {"units_set": [], "deleted": [], "exported": []}

    def fake_call(command, params, timeout_s=60.0, port=None):
        if command == "execute_python":
            code = params["code"]
            if "currentUnit(linear=" in code:
                unit = code.split("currentUnit(linear=")[1].split(")")[0].strip("'\"")
                state["unit"] = unit
                log["units_set"].append(unit)
                return {"result": {"result_repr": "'set'", "result_truncated": False}}
            if "currentUnit(q=True" in code:
                return {"result": {"result_repr": repr(state["unit"]),
                                   "result_truncated": False}}
            if "cmds.delete" in code:
                log["deleted"].append(code)
                return {"result": {"result_repr": "'deleted'", "result_truncated": False}}
            if "FBXExport" in code or "es=True" in code:
                log["exported"].append(state["unit"])
                if export_raises_on == state["unit"]:
                    return {"error": "simulated export failure"}
                return {"result": {"result_repr": "'exported'", "result_truncated": False}}
            return {"result": {"result_repr": "'ok'", "result_truncated": False}}
        if command == "new_scene":
            state["unit"] = "cm"
            return {"result": {"new_scene": True, "pre_checkpoint": "001_auto",
                               "units": {"linear_unit": "cm",
                                         "export_metres_per_unit": 1.0}}}
        if command == "get_scene_graph":
            per = {"mm": 0.1, "cm": 1.0, "m": 100.0}[state["unit"]]
            return {"result": {"objects": [], "total": 0, "cursor": None,
                               "units": {"linear_unit": state["unit"],
                                         "export_metres_per_unit": per}}}
        if command == "get_object_info":
            return {"result": {"name": "|unitGateCube", "transform": {},
                               "units": {"linear_unit": state["unit"],
                                         "export_metres_per_unit": 1.0}}}
        raise AssertionError("unexpected command %r" % command)

    class FakeProbe:
        @staticmethod
        def read_fbx(path):
            unit = log["exported"][-1]
            return FakeFacts(spans[unit])

    monkeypatch.setattr(module, "call", fake_call)
    monkeypatch.setattr(module, "fbx_probe", FakeProbe)
    return log


class TestItCanActuallyFail:
    def test_the_happy_path_is_green(self, monkeypatch):
        module = _load_script()
        _install_stubs(monkeypatch, module)
        assert module.main() == 0

    def test_a_metre_scene_exporting_metre_true_is_a_FAILURE(self, monkeypatch):
        # The gate's own inverse: if an "m" scene produced a 3.0 file, then
        # export_metres_per_unit=100.0 was a lie and the field is not
        # discriminating. This must go red, not green.
        module = _load_script()
        _install_stubs(monkeypatch, module, spans={"cm": 3.0, "m": 3.0})
        assert module.main() == 1

    def test_a_cm_scene_exporting_100x_is_a_FAILURE(self, monkeypatch):
        # The #629 defect itself, in the unit that is supposed to be safe.
        module = _load_script()
        _install_stubs(monkeypatch, module, spans={"cm": 300.0, "m": 300.0})
        assert module.main() == 1


class TestItLeavesTheSessionMetreTrue:
    def test_the_unit_is_restored_after_a_clean_run(self, monkeypatch):
        module = _load_script()
        log = _install_stubs(monkeypatch, module)
        module.main()
        assert log["units_set"][-1] == "cm"

    def test_the_unit_is_restored_even_when_a_measurement_raises(self, monkeypatch):
        # It sets "m" on purpose. Blowing up mid-measurement must not leave the
        # session there for the next build to inherit - that is the hazard.
        module = _load_script()
        log = _install_stubs(monkeypatch, module, export_raises_on="m")
        with pytest.raises(RuntimeError, match="simulated export failure"):
            module.main()
        assert log["units_set"][-1] == "cm"

    def test_the_probe_cube_is_deleted_on_every_exit_path(self, monkeypatch):
        module = _load_script()
        log = _install_stubs(monkeypatch, module)
        module.main()
        # one per measured unit, plus the get_object_info cube
        assert len(log["deleted"]) == 3
