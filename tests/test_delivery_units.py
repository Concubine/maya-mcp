"""The delivery unit gate, checked against the artifact rather than the scene.

This suite exists because every in-Maya check is structurally blind to the
defect it guards. Measured on 2026-08-15: a probe cube reads 3.0 m at scale
[1,1,1] with transforms frozen in Maya, and exports as 300.0. The scene was
never wrong - the exporter writes the error - so `geometry_self_check` passed
green on all three ships of maya-mcp #629.

Nothing here imports Maya, so it runs in the normal suite on every run.
"""
import json
import os
import sys
from pathlib import Path

import pytest

_EVALS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "evals")
if _EVALS not in sys.path:
    sys.path.insert(0, _EVALS)

import delivery_units     # noqa: E402
import fbx_probe          # noqa: E402

REPO = Path(__file__).resolve().parents[1]
KIT = REPO / "evals" / "demigol_kit" / "demigol_kit.fbx"
STRUCTURES = REPO / "evals" / "demigol_structures"
TOWER = STRUCTURES / "tower.fbx"
HEROES = ["tower", "block", "slab", "stump"]


def test_reader_finds_every_kit_mesh():
    facts = fbx_probe.read_fbx(KIT)
    assert facts.version == 7700
    assert len(facts.meshes) == 41


def test_reader_strips_the_fbx_name_separator():
    facts = fbx_probe.read_fbx(TOWER)
    names = [n.name for n in facts.nodes]
    assert "tower" in names, names[:5]
    assert not any("\x00" in n for n in names)


def test_every_delivery_declares_metres():
    # Maya writes 1.0 (centimetres) for a metre-native scene and offers no way
    # to change it, so the generator corrects the declaration on the artifact.
    # Without this the file contradicts itself and Demigol, who MEASURE unit
    # scale on import rather than trusting the header, would read 0.01 again.
    for path in [KIT] + [STRUCTURES / ("%s.fbx" % h) for h in HEROES]:
        facts = fbx_probe.read_fbx(path)
        assert facts.unit_scale_factor == fbx_probe.DECLARES_METRES, (
            "%s declares %r" % (path.name, facts.unit_scale_factor))


def test_reader_defaults_absent_records_to_identity():
    facts = fbx_probe.read_fbx(TOWER)
    # 673 chunks are written without an Lcl Scaling record; only the group Null
    # carries one. Absent must read as identity, never as missing.
    assert all(n.scaling == (1.0, 1.0, 1.0)
               for n in facts.nodes if n.name != "tower")


@pytest.mark.parametrize("hero", HEROES)
def test_hero_is_metre_true(hero):
    violations = delivery_units.check_delivery(
        STRUCTURES / ("%s.fbx" % hero), delivery_units.HERO_CEILING_M)
    assert violations == [], "\n".join(violations)


def test_kit_is_metre_true():
    violations = delivery_units.check_delivery(KIT, delivery_units.KIT_CEILING_M)
    assert violations == [], "\n".join(violations)


def test_check_names_the_node_carrying_a_bad_scale(monkeypatch):
    # The message has to identify the offending node, because the two
    # deliveries put the scale in different places: the heroes on one group
    # Null, the kit on all 41 Mesh nodes.
    #
    # Built here rather than read from a delivery. This assertion first ran
    # against the shipped centimetre kit, which is what proved it could see the
    # defect - but a test that needs a broken artifact to pass goes green the
    # moment the artifact is fixed, and then guards nothing.
    facts = fbx_probe.FbxFacts(
        version=7700,
        nodes=[fbx_probe.FbxNode(name="kit_steel_column_a", kind="Mesh",
                                 scaling=(0.01, 0.01, 0.01))],
        meshes=[(0.0, 0.0, 0.0)])
    monkeypatch.setattr(fbx_probe, "read_fbx", lambda _path: facts)

    violations = delivery_units.check_delivery("fake.fbx",
                                               delivery_units.KIT_CEILING_M)
    assert any("kit_steel_column_a" in v for v in violations), violations
    assert any("0.01" in v for v in violations), violations


GOLEM = REPO / "evals" / "golem_delivery" / "golem.fbx"


def test_golem_is_metre_true():
    violations = delivery_units.check_rig_delivery(
        GOLEM, delivery_units.GOLEM_HEIGHT_M, delivery_units.GOLEM_CEILING_M)
    assert violations == [], "\n".join(violations)


def test_reader_composes_the_rig_hierarchy():
    # The delivered height is the one number no chunk carries: every chunk's own
    # vertices are under a metre and the 4 m comes entirely from the tree. This
    # measured 4.021730 from the bytes against 4.021730 in Maya.
    facts = fbx_probe.read_fbx(GOLEM)
    assert len(facts.nodes) == 33
    assert sum(1 for n in facts.nodes if n.parent is None) == 1
    assert all(n.geometry in facts.geometries for n in facts.nodes)
    lo, hi = fbx_probe.world_vertex_bounds(facts)
    assert abs((hi[1] - lo[1]) - 4.02173) < 1e-4


def _fake_rig(scaling=(1.0, 1.0, 1.0), height=4.02173):
    root = fbx_probe.FbxNode(name="golem_C_pelvis", kind="Mesh", uid=1,
                             geometry=10, scaling=scaling)
    child = fbx_probe.FbxNode(name="golem_C_head", kind="Mesh", uid=2,
                              parent=1, geometry=11,
                              translation=(0.0, height, 0.0))
    return fbx_probe.FbxFacts(
        version=7700, nodes=[root, child],
        meshes=[(0.0, 0.0, 0.0), (0.0, 0.0, 0.0)],
        geometries={10: (0.0, 0.0, 0.0), 11: (0.0, 0.0, 0.0)},
        unit_scale_factor=fbx_probe.DECLARES_METRES)


def test_rig_check_passes_a_clean_rig(monkeypatch):
    monkeypatch.setattr(fbx_probe, "read_fbx", lambda _p: _fake_rig())
    assert delivery_units.check_rig_delivery(
        "fake.fbx", delivery_units.GOLEM_HEIGHT_M,
        delivery_units.GOLEM_CEILING_M) == []


def test_rig_check_catches_a_scaled_chunk(monkeypatch):
    # The scale the golem's chunks actually carried in the scene, before the
    # bake: assemble left 21 of 33 non-uniform. Shipped, it would deform the
    # chunk the moment the engine turned its parent.
    monkeypatch.setattr(fbx_probe, "read_fbx",
                        lambda _p: _fake_rig(scaling=(0.62, 1.2, 0.62)))
    violations = delivery_units.check_rig_delivery(
        "fake.fbx", delivery_units.GOLEM_HEIGHT_M, delivery_units.GOLEM_CEILING_M)
    assert any("golem_C_pelvis" in v and "1.2" in v for v in violations), violations


def test_rig_check_catches_a_centimetre_rig(monkeypatch):
    # The #629 defect in rig form. Every chunk's vertices stay small, the header
    # can still say metres, and only the composed height gives it away.
    monkeypatch.setattr(fbx_probe, "read_fbx", lambda _p: _fake_rig(height=402.173))
    violations = delivery_units.check_rig_delivery(
        "fake.fbx", delivery_units.GOLEM_HEIGHT_M, delivery_units.GOLEM_CEILING_M)
    assert any("factor of 100" in v for v in violations), violations


def test_check_passes_a_clean_delivery(monkeypatch):
    facts = fbx_probe.FbxFacts(
        version=7700,
        nodes=[fbx_probe.FbxNode(name="kit_steel_column_a", kind="Mesh",
                                 translation=(1.5, 0.0, 3.0))],
        meshes=[(1.5, -1.5, 0.75)],
        unit_scale_factor=fbx_probe.DECLARES_METRES)
    monkeypatch.setattr(fbx_probe, "read_fbx", lambda _path: facts)

    assert delivery_units.check_delivery(
        "fake.fbx", delivery_units.KIT_CEILING_M) == []
