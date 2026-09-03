"""#797 rows 15/16/27: what sculpt_ops and deform drop on a branch.

tests/test_modeling.py holds this module's older behaviour tests and its
big FakeCmds. This file is the branch-contract half: every refusal here is
about a param the caller PASSED that the branch it selected never reads,
and every one of them must fire BEFORE the handler touches Maya - before
the auto-checkpoint, before the lattice is built. That is why the fake
below raises when it is asked for `cmds` at all: reaching Maya is the
failure being tested for, not an implementation detail.
"""

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import sculpt

# The phrase that makes the LIVE lattice hint wrong for a baked one.
_ONLY_BUILDS_IT = "this call only builds it"


def _no_maya(monkeypatch):
    """_cmds() must never be reached - a refusal after it is a refusal after
    the auto-checkpoint (#767's proof shape, here as an explicit failure)."""

    def boom():
        raise AssertionError("_cmds() was reached - the refusal ran too late")

    monkeypatch.setattr(sculpt, "_cmds", boom)


class MiniCmds:
    """The smallest scene sculpt_ops/deform need: one mesh, one handle set.

    Deliberately not test_modeling.FakeCmds - the tests here only need to
    prove that a call which is NOT refused still reaches Maya and comes back
    with the right shape, so a fake anyone can read in one screen is worth
    more than a shared one nobody can hold in their head.
    """

    def __init__(self, mesh="|box"):
        self.mesh = mesh
        self.calls = []
        # 2 verts, 2 units apart: bbox_extent 2.0, so the 1% inert threshold
        # is 0.02 - a lattice handle move either clears it or does not.
        self.verts = [0.0, 0.0, 0.0, 0.0, 2.0, 0.0]
        self.moved_verts = None
        self.existing = {mesh, mesh + "|boxShape",
                         "ffd1Lattice", "ffd1Base"}

    # --- naming.require_mesh ---------------------------------------------
    def ls(self, *args, **kwargs):
        if not args:
            return []
        name = args[0]
        return [name] if name in self.existing else []

    def listRelatives(self, node, **kwargs):
        return [node + "|boxShape"] if node == self.mesh else []

    def nodeType(self, node):
        return "mesh" if node.endswith("Shape") else "transform"

    # --- geometry ---------------------------------------------------------
    def xform(self, target, **kwargs):
        if kwargs.get("query"):
            if self.moved_verts is not None and any(
                c[0] == "lattice" for c in self.calls
            ):
                return list(self.moved_verts)
            return list(self.verts)
        self.calls.append(("xform", target, kwargs))
        return None

    def polySmooth(self, *args, **kwargs):
        self.calls.append(("polySmooth", args, kwargs))

    def polyEvaluate(self, *args, **kwargs):
        self.calls.append(("polyEvaluate", args, kwargs))
        return 12

    def lattice(self, *args, **kwargs):
        self.calls.append(("lattice", args, kwargs))
        return ["ffd1", "ffd1Lattice", "ffd1Base"]

    def objExists(self, node):
        return node in self.existing

    def delete(self, *args, **kwargs):
        self.calls.append(("delete", args, kwargs))
        self.existing.discard(args[0])


# --------------------------------------------------------------- row 15/16

class TestOpKeysAreDeclaredPerOp:
    """Row 16: the eight pre-cage ops declare their keys like the four cage
    ops already did. Measured worst case: `displace_noise` with
    center/radius/falloff read NONE of them and displaced the WHOLE mesh -
    a call that reported success having done something else entirely."""

    def test_displace_noise_refuses_soft_move_keys(self):
        with pytest.raises(HandlerError) as exc:
            sculpt.validate_ops([{"op": "displace_noise", "amp": 0.1,
                                  "center": [0, 0, 0], "radius": 1}])
        message = str(exc.value)
        assert "does not take" in message
        assert "displace_noise" in message
        assert "center" in message and "radius" in message

    def test_smooth_refuses_amount(self):
        with pytest.raises(HandlerError) as exc:
            sculpt.validate_ops([{"op": "smooth", "amount": 2}])
        message = str(exc.value)
        assert "does not take" in message
        assert "smooth" in message and "amount" in message
        assert "divisions" in (exc.value.hint or "")

    def test_bevel_edges_refuses_crease_amount(self):
        with pytest.raises(HandlerError) as exc:
            sculpt.validate_ops([{"op": "bevel_edges", "edges": "e[1]",
                                  "amount": 2}])
        assert "bevel_edges" in str(exc.value)
        assert "amount" in str(exc.value)

    def test_extrude_faces_refuses_a_translate(self):
        # `translate` is extrude_EDGES' word; extrude_faces takes `distance`.
        with pytest.raises(HandlerError) as exc:
            sculpt.validate_ops([{"op": "extrude_faces", "faces": "f[1]",
                                  "translate": [0, 1, 0]}])
        assert "extrude_faces" in str(exc.value)
        assert "translate" in str(exc.value)

    @pytest.mark.parametrize("op", [
        {"op": "soft_move", "vertex_id": 0, "radius": 1, "falloff": "linear",
         "delta": [0, 1, 0]},
        {"op": "soft_move", "center": [0, 0, 0], "radius": 1, "delta": [0, 1, 0]},
        {"op": "inflate_region", "center": [0, 0, 0], "radius": 1,
         "falloff": "smooth", "amount": 0.1},
        {"op": "displace_noise", "amp": 0.1, "freq": 2.6, "octaves": 2,
         "soften_angle": 30},
        {"op": "smooth", "divisions": 2},
        {"op": "extrude_faces", "faces": "f[1]", "distance": 0.2,
         "keep_together": False},
        {"op": "bevel_edges", "edges": "e[1]", "segments": 2, "width": 0.1},
        {"op": "crease_edges", "edges": "e[1]", "amount": 3},
        {"op": "bridge", "edges_a": "e[0:3]", "edges_b": "e[8:11]"},
    ])
    def test_every_read_key_is_accepted(self, op):
        assert sculpt.validate_ops([op]) == [op["op"]]

    def test_the_four_cage_ops_are_validated_in_the_same_pass(self):
        # They already had _KEYS sets, but only checked them INSIDE the op -
        # after the auto-checkpoint. The pre-pass covers all twelve.
        with pytest.raises(HandlerError) as exc:
            sculpt.validate_ops([{"op": "insert_loop", "edge": "e[1]",
                                  "bogus": 1}])
        assert "bogus" in str(exc.value)

    def test_every_registered_op_declares_a_key_set(self):
        assert set(sculpt._OP_KEYS) == set(sculpt._OPS)

    def test_unknown_op_tag_still_wins_over_key_checking(self):
        with pytest.raises(HandlerError) as exc:
            sculpt.validate_ops([{"op": "melt", "amp": 1}])
        assert "melt" in str(exc.value)

    def test_op_keys_are_refused_before_maya(self, monkeypatch):
        _no_maya(monkeypatch)
        with pytest.raises(HandlerError) as exc:
            sculpt.sculpt_ops({"mesh": "|box",
                               "ops": [{"op": "smooth", "amount": 2}]})
        assert "does not take" in str(exc.value)


class TestCenterIsInertUnderVertexId:
    """Row 15: `_resolve_center` returns on `vertex_id` before it ever looks
    at `center` - a caller who passes both gets the vertex, silently."""

    @pytest.mark.parametrize("op,extra", [
        ("soft_move", {"delta": [0, 1, 0]}),
        ("inflate_region", {"amount": 0.1}),
    ])
    def test_both_refused(self, op, extra):
        with pytest.raises(HandlerError) as exc:
            sculpt.validate_ops([dict({"op": op, "vertex_id": 0,
                                       "center": [0, 0, 0], "radius": 1},
                                      **extra)])
        message = str(exc.value)
        assert "does not use" in message
        assert "center" in message and "vertex_id" in message

    def test_vertex_id_alone_accepted(self):
        assert sculpt.validate_ops([{"op": "soft_move", "vertex_id": 4,
                                     "radius": 1, "delta": [0, 1, 0]}]) == ["soft_move"]

    def test_center_alone_accepted(self):
        assert sculpt.validate_ops([{"op": "soft_move", "center": [0, 1, 0],
                                     "radius": 1, "delta": [0, 1, 0]}]) == ["soft_move"]

    def test_refused_before_maya(self, monkeypatch):
        _no_maya(monkeypatch)
        with pytest.raises(HandlerError) as exc:
            sculpt.sculpt_ops({"mesh": "|box", "ops": [
                {"op": "soft_move", "vertex_id": 0, "center": [0, 0, 0],
                 "radius": 1, "delta": [0, 1, 0]}]})
        assert "does not use" in str(exc.value)


def test_a_valid_op_list_still_reaches_maya(monkeypatch):
    """The other half of every refusal: the call that is NOT refused runs."""
    fake = MiniCmds()
    monkeypatch.setattr(sculpt, "_cmds", lambda: fake)
    result = sculpt.sculpt_ops({"mesh": "|box",
                                "ops": [{"op": "smooth", "divisions": 2}]})
    assert result["applied"] == 1
    assert any(c[0] == "polySmooth" for c in fake.calls)


# ------------------------------------------------------------------ row 27

class TestLatticeBakeWithNoHandleMove:
    """Row 27: `deform(deformer='lattice', delete_history_after=True)` with
    no translate/rotate returned
    `{deformer_nodes: [], baked: true, warnings: [], max_displacement: 0.0}` -
    a success report for a call in which nothing happened at all. The lattice
    is built, deforms nothing (it deforms nothing until its points move), and
    is then deleted again along with its handles."""

    def test_refused(self, monkeypatch):
        _no_maya(monkeypatch)
        with pytest.raises(HandlerError) as exc:
            sculpt.deform({"mesh": "|box", "deformer": "lattice",
                           "delete_history_after": True})
        message = str(exc.value)
        assert "does not use" in message
        assert "delete_history_after" in message
        assert "lattice" in message

    def test_refused_with_divisions_but_no_handle_move(self, monkeypatch):
        # divisions shapes the lattice; it does not move a point.
        _no_maya(monkeypatch)
        with pytest.raises(HandlerError):
            sculpt.deform({"mesh": "|box", "deformer": "lattice",
                           "params": {"divisions": [3, 3, 3]},
                           "delete_history_after": True})

    def test_lattice_with_a_handle_move_and_a_bake_is_legal(self, monkeypatch):
        fake = MiniCmds()
        fake.moved_verts = [0.0, 0.0, 0.0, 0.0, 3.0, 0.0]  # 1.0 > the 0.02 floor
        monkeypatch.setattr(sculpt, "_cmds", lambda: fake)
        result = sculpt.deform({"mesh": "|box", "deformer": "lattice",
                                "params": {"translate": [0, 1, 0]},
                                "delete_history_after": True})
        assert result["baked"] is True
        assert result["deformer_nodes"] == []
        assert result["max_displacement"] == pytest.approx(1.0)
        assert result["warnings"] == []

    def test_an_unbaked_lattice_needs_no_handle_move(self, monkeypatch):
        fake = MiniCmds()
        monkeypatch.setattr(sculpt, "_cmds", lambda: fake)
        result = sculpt.deform({"mesh": "|box", "deformer": "lattice",
                                "params": {}})
        assert result["baked"] is False
        assert result["warnings"] == []  # a live lattice awaits its points

    def test_other_deformers_may_still_bake_without_a_handle_move(self, monkeypatch):
        # Only the lattice branch builds something inert BY DESIGN; a bend
        # with a curvature and no handle move is a real deformation.
        fake = MiniCmds()
        fake.moved_verts = [0.0, 0.0, 0.0, 0.0, 2.5, 0.0]
        fake.nonLinear = lambda *a, **k: ["bend1", "bend1Handle"]
        fake.getAttr = lambda plug, **k: "double"
        fake.setAttr = lambda plug, value: fake.calls.append(("setAttr", plug, value))
        monkeypatch.setattr(sculpt, "_cmds", lambda: fake)
        result = sculpt.deform({"mesh": "|box", "deformer": "bend",
                                "params": {"curvature": 45},
                                "delete_history_after": True})
        assert result["baked"] is True


class TestInertWarningsLatticeExemption:
    """The exemption is "a lattice awaits its points", not "a lattice never
    warns": once history is deleted there are no points left to move, so a
    baked lattice that moved nothing is as inert as any other deformer."""

    def test_live_lattice_is_exempt(self):
        assert sculpt._inert_warnings("lattice", 0.0, 2.0, baked=False) == []

    def test_baked_lattice_that_moved_nothing_warns(self):
        warnings = sculpt._inert_warnings("lattice", 0.0, 2.0, baked=True)
        assert len(warnings) == 1
        assert "lattice" in warnings[0]

    def test_the_baked_lattice_warning_carries_its_own_hint(self):
        # Review fix round 1. The generic lattice hint says "this call only
        # builds it", which is exactly what a baked lattice did NOT do:
        # row 27 refuses the bake with no handle move, so the only bake that
        # reaches this warning is one whose handle moved. Sending the
        # build-only hint would point the reader at a step they took.
        warning = sculpt._inert_warnings("lattice", 0.0, 2.0, baked=True)[0]
        assert sculpt._BAKED_LATTICE_HINT in warning
        assert "the handle moved but the mesh barely followed" in warning
        assert "divisions" in warning
        assert "delete_history_after" in warning
        assert _ONLY_BUILDS_IT not in warning

    def test_the_live_lattice_hint_is_unchanged_for_every_other_use(self):
        # The build-only hint still exists and still belongs to the lattice -
        # it is simply not what a BAKED one is told.
        assert _ONLY_BUILDS_IT in sculpt._INERT_HINTS["lattice"]
        assert _ONLY_BUILDS_IT not in sculpt._BAKED_LATTICE_HINT

    def test_baked_lattice_that_moved_does_not_warn(self):
        assert sculpt._inert_warnings("lattice", 1.0, 2.0, baked=True) == []

    def test_other_deformers_are_unchanged_by_the_bake_flag(self):
        assert len(sculpt._inert_warnings("bend", 0.0, 2.0, baked=False)) == 1
        assert len(sculpt._inert_warnings("bend", 0.0, 2.0, baked=True)) == 1
