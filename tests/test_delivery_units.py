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
    assert len(facts.meshes) == 58          # revision 3: 41 + 11 steel + 6 damage


def test_the_kit_manifest_agrees_with_the_fbx_node_names():
    """"FBX node names are truth and the manifest must agree with them" is a
    contract clause that nothing checked. It is checkable against the two
    delivered files alone, with no Maya in the loop, and the failure it
    guards is the one #596 shipped: a manifest describing pieces the file
    does not contain under those names.
    """
    import json
    facts = fbx_probe.read_fbx(KIT)
    manifest = json.loads(
        (REPO / "evals" / "demigol_kit" / "manifest.json").read_text())
    in_file = sorted(n.name for n in facts.nodes
                     if facts.geometries.get(n.geometry))
    declared = sorted(p["name"] for p in manifest["pieces"])
    assert in_file == declared, (
        "only in the FBX: %s | only in the manifest: %s"
        % (sorted(set(in_file) - set(declared)),
           sorted(set(declared) - set(in_file))))
    assert len(in_file) == len(set(in_file)), "duplicate node names"


def test_the_kit_manifest_declares_the_outset_the_fbx_delivers():
    """`outset_m` is what the consumer plans collision headroom around, and
    until revision 3 it was derived from the box SPEC - which a `taper`
    silently shrinks afterwards. Measured off the vertices here, so the
    declaration cannot drift from the delivery again.
    """
    import json
    facts = fbx_probe.read_fbx(KIT)
    manifest = json.loads(
        (REPO / "evals" / "demigol_kit" / "manifest.json").read_text())
    declared = {p["name"]: p["outset_m"] for p in manifest["pieces"]}
    allowance = manifest["envelope"]["max_outset_m"]
    for node in facts.nodes:
        verts = facts.geometries.get(node.geometry)
        if not verts:
            continue
        reach = max(max(abs(verts[i]), abs(verts[i + 1]), abs(verts[i + 2]))
                    for i in range(0, len(verts), 3))
        measured = max(0.0, reach - 1.5)
        assert measured <= allowance + 1e-3, (
            "%s oversails %.4f m, past the %.2f allowance"
            % (node.name, measured, allowance))
        assert measured <= declared[node.name] + 1e-3, (
            "%s delivers %.4f m of outset but declares %.4f"
            % (node.name, measured, declared[node.name]))


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


POSES = REPO / "evals" / "golem_delivery" / "poses.json"


def _poses():
    with open(POSES) as fh:
        return json.load(fh)


def test_every_pose_composes_to_its_declared_height():
    # The strongest cross-check in the delivery: Maya measured these heights by
    # posing the live rig, and this re-derives them from the FBX bytes with an
    # independent composer. crouch 3.502 / rest 4.022 / extend 5.063.
    violations = delivery_units.check_poses(GOLEM, _poses())
    assert violations == [], "\n".join(violations)


def test_pose_check_catches_a_pose_that_drifted_from_the_geometry():
    poses = _poses()
    poses["extend"]["bbox_height_m"] = 4.64      # the figure the spec pinned
    violations = delivery_units.check_poses(GOLEM, poses)
    assert any("extend" in v and "4.64" in v for v in violations), violations


def test_pose_check_catches_a_chunk_the_file_does_not_have():
    poses = _poses()
    poses["rest"]["rotations_deg"]["golem_C_tail"] = [0, 0, 0]
    violations = delivery_units.check_poses(GOLEM, poses)
    assert any("golem_C_tail" in v for v in violations), violations


CHUNKS = REPO / "evals" / "golem_delivery" / "chunks.json"


def _chunks():
    with open(CHUNKS) as fh:
        return json.load(fh)


def test_every_chunk_declares_a_primitive_its_sculpt_stays_inside():
    import golem_delivery_package as pkg
    violations = pkg.check_colliders(_chunks())
    assert violations == [], "\n".join(violations)


def test_collider_check_catches_a_left_right_disagreement():
    # The right side carries no rest rotation - its tilt is baked into its
    # vertices - so a fit done in each chunk's own local axes came out
    # asymmetric: a capsule on the left thigh and a box on the right. Invisible
    # in a render, obvious in play.
    import golem_delivery_package as pkg
    chunks = _chunks()
    chunks["golem_R_thigh"]["collider"] = dict(chunks["golem_R_thigh"]["collider"],
                                               type="box", size_m=[1, 1, 1])
    violations = pkg.check_colliders(chunks)
    assert any("golem_L_thigh" in v and "golem_R_thigh" in v for v in violations), violations


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
