"""The FBX transform composition, maya-mcp #645.

FBX composes a node's local transform as

    T . Roff . Rp . Rpre . R . Rpost-1 . Rp-1 . Soff . Sp . S . Sp-1

and this reader kept only T, R, Rp and S-about-the-origin. The dropped records
are not exotic - Maya writes RotationOffset whenever a pivot is moved and
PreRotation whenever a joint is oriented - and dropping them reported a height
21% wrong for a file this server built.

These tests fix the algebra. That it is the algebra MAYA implements is settled
by evals/fbx_probe_live.py, which hands the same bytes to Maya and compares
world-space vertex positions; nothing headless can establish that.
"""

import collections
import os

import pytest

from maya_plugin.handlers import fbxbytes
from maya_plugin.handlers.fbxbytes import FbxFacts, FbxNode

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def place(node, point):
    """Where `point`, in this node's space, ends up in its parent's."""
    M, off = fbxbytes._local(node)
    return tuple(round(sum(point[r] * M[r][c] for r in range(3)) + off[c], 9)
                 for c in range(3))


class TestTheRecordsThatWereDropped:
    def test_rotation_offset_shifts_the_node(self):
        # Maya's rotatePivotTranslate. It is a plain translation, applied even
        # when the node does not rotate - which is why ignoring it moved a
        # whole subtree of the clock tower.
        node = FbxNode(name="n", kind="Mesh", rotation_offset=(0.0, 5.0, 0.0))
        assert place(node, (1.0, 0.0, 0.0)) == (1.0, 5.0, 0.0)

    def test_rotation_offset_is_not_rotated_by_the_node_itself(self):
        # It sits OUTSIDE the rotation in the FBX chain (T . Roff . Rp . R ...),
        # so a rotated node must not spin its own offset.
        node = FbxNode(name="n", kind="Mesh", rotation=(0.0, 0.0, 90.0),
                       rotation_offset=(0.0, 5.0, 0.0))
        assert place(node, (0.0, 0.0, 0.0)) == (0.0, 5.0, 0.0)

    def test_scaling_is_about_the_scaling_pivot(self):
        # Sp . S . Sp-1 collapses to identity only when the scale is identity;
        # the delivery gates force that first, which is what kept this quiet.
        node = FbxNode(name="n", kind="Mesh", scaling=(3.0, 1.0, 1.0),
                       scaling_pivot=(2.0, 0.0, 0.0))
        assert place(node, (2.0, 0.0, 0.0)) == (2.0, 0.0, 0.0)  # the pivot holds
        assert place(node, (3.0, 0.0, 0.0)) == (5.0, 0.0, 0.0)

    def test_scaling_offset_translates_after_scaling(self):
        node = FbxNode(name="n", kind="Mesh", scaling=(2.0, 2.0, 2.0),
                       scaling_offset=(0.0, 1.0, 0.0))
        assert place(node, (1.0, 0.0, 0.0)) == (2.0, 1.0, 0.0)

    def test_pre_rotation_applies_after_the_local_rotation(self):
        # FBX orders it Rpre . R (column), so R turns the point first and Rpre
        # turns the result - Maya's jointOrient. Swapping the two would send
        # this point to (-1, 0, 0), so the test discriminates.
        node = FbxNode(name="n", kind="Mesh", rotation=(90.0, 0.0, 0.0),
                       pre_rotation=(0.0, 0.0, 90.0))
        assert place(node, (0.0, 1.0, 0.0)) == (0.0, 0.0, 1.0)

    def test_post_rotation_is_applied_inverted_and_first(self):
        node = FbxNode(name="n", kind="Mesh", post_rotation=(0.0, 0.0, 90.0))
        assert place(node, (1.0, 0.0, 0.0)) == (0.0, -1.0, 0.0)

    def test_the_whole_chain_composes_in_fbx_order(self):
        # One node carrying every record at once: a point at the rotate pivot
        # can only land on T + Roff if the terms cancel in the right order.
        node = FbxNode(name="n", kind="Mesh",
                       translation=(1.0, 2.0, 3.0), rotation=(0.0, 40.0, 0.0),
                       rotation_pivot=(0.5, 0.0, -0.5), rotation_offset=(0.0, 7.0, 0.0),
                       scaling=(1.0, 1.0, 1.0), scaling_pivot=(9.0, 9.0, 9.0))
        assert place(node, (0.5, 0.0, -0.5)) == (1.5, 9.0, 2.5)


class TestGeometricTransformBelongsToTheVertices:
    """FBX applies Geometric* to the node's own vertices and never hands it to
    a child. Composing it into the chain would move the whole subtree."""

    def _facts(self, geometric):
        parent = FbxNode(name="parent", kind="Mesh", uid=1, geometry=10,
                         **geometric)
        child = FbxNode(name="child", kind="Mesh", uid=2, parent=1, geometry=11)
        return FbxFacts(version=7500, nodes=[parent, child],
                        geometries={10: (1.0, 0.0, 0.0), 11: (1.0, 0.0, 0.0)})

    def test_it_moves_the_nodes_own_vertices(self):
        facts = self._facts({"geometric_translation": (0.0, 4.0, 0.0)})
        lo, hi = fbxbytes.world_vertex_bounds(facts)
        assert (lo[1], hi[1]) == (0.0, 4.0)  # child at 0, parent lifted to 4

    def test_it_is_not_inherited_by_children(self):
        facts = self._facts({"geometric_translation": (0.0, 4.0, 0.0)})
        # Without the parent's own vertices there is nothing at y=4 at all.
        facts.geometries.pop(10)
        lo, hi = fbxbytes.world_vertex_bounds(facts)
        assert (lo[1], hi[1]) == (0.0, 0.0)

    def test_geometric_scaling_and_rotation_apply_too(self):
        facts = self._facts({"geometric_scaling": (2.0, 1.0, 1.0),
                             "geometric_rotation": (0.0, 0.0, 90.0)})
        lo, hi = fbxbytes.world_vertex_bounds(facts)
        assert round(hi[1], 9) == 2.0  # (1,0,0) scaled to (2,0,0), turned to +y


class TestItRefusesRatherThanGuessing:
    """A number this reader reports has to be one a consumer can trust, so the
    unhandled cases raise instead of composing something plausible."""

    def _facts(self, inherit_type, parent_scale, child_rotation):
        parent = FbxNode(name="parent", kind="Null", uid=1, scaling=parent_scale)
        child = FbxNode(name="child", kind="Mesh", uid=2, parent=1, geometry=10,
                        rotation=child_rotation, inherit_type=inherit_type)
        return FbxFacts(version=7500, nodes=[parent, child],
                        geometries={10: (1.0, 0.0, 0.0)})

    def test_a_rotated_child_under_a_scaled_parent_is_refused(self):
        facts = self._facts(1, (2.0, 1.0, 1.0), (0.0, 0.0, 45.0))
        with pytest.raises(ValueError, match="InheritType"):
            fbxbytes.world_vertex_bounds(facts)

    def test_an_unrotated_child_under_a_scaled_parent_is_fine(self):
        # The composition is the same for every inherit type when nothing
        # rotates, and this is the shape every delivery actually has.
        facts = self._facts(1, (2.0, 1.0, 1.0), fbxbytes.ORIGIN)
        lo, hi = fbxbytes.world_vertex_bounds(facts)
        assert hi[0] == 2.0

    def test_inherit_type_zero_composes_normally(self):
        facts = self._facts(0, (2.0, 1.0, 1.0), (0.0, 0.0, 45.0))
        fbxbytes.world_vertex_bounds(facts)  # must not raise

    def test_an_unimplemented_rotation_order_still_raises(self):
        node = FbxNode(name="n", kind="Mesh", rotation=(10.0, 0.0, 0.0),
                       rotation_order=3)
        with pytest.raises(ValueError, match="rotation order"):
            fbxbytes._local(node)


class TestAgainstTheCommittedArtifact:
    def test_the_clock_tower_reads_the_height_maya_measures(self):
        """The #645 regression, pinned to a number Maya produced.

        evals/fbx_probe_live.py imported this same file into Maya and measured
        37.10 from world-space vertex positions; the reader shipped 44.90.
        """
        facts = fbxbytes.read_fbx(
            os.path.join(REPO, "evals", "structures", "clock_tower.fbx"))
        lo, hi = fbxbytes.world_vertex_bounds(facts)
        assert hi[1] - lo[1] == pytest.approx(37.10, abs=1e-3)

    def test_the_golem_still_reads_its_delivered_height(self):
        # Unchanged by #645 - guards against a fix that moves a correct number.
        facts = fbxbytes.read_fbx(
            os.path.join(REPO, "evals", "golem_delivery", "golem.fbx"))
        lo, hi = fbxbytes.world_vertex_bounds(facts)
        assert hi[1] - lo[1] == pytest.approx(4.02173, abs=1e-5)


class TestSkinRecordMath:
    """skin_facts on synthetic facts - the algebra, no file needed."""

    def _facts(self, indexes, weights, verts=4):
        facts = FbxFacts(version=7500)
        facts.geometries = {10: tuple([0.0] * (verts * 3))}
        facts.skins = {20: {"geometry": 10, "clusters": [30]}}
        facts.clusters = {30: {"indexes": tuple(indexes),
                               "weights": tuple(weights), "model": 40}}
        facts.bind_pose_count = 1
        return facts

    def test_full_ownership_sums_to_one(self):
        facts = self._facts([0, 1, 2, 3], [1.0, 1.0, 1.0, 1.0])
        out = fbxbytes.skin_facts(facts)
        assert out["deformers"] == 1
        assert out["clusters"] == 1
        assert out["influenced_models"] == 1
        assert out["bind_pose_present"] is True
        assert out["max_weight_sum_error"] == pytest.approx(0.0)
        assert out["unweighted_file_vertices"] == 0
        assert out["unavailable_reason"] is None

    def test_a_vertex_with_no_weight_is_counted(self):
        facts = self._facts([0, 1, 2], [1.0, 1.0, 1.0])
        assert fbxbytes.skin_facts(facts)["unweighted_file_vertices"] == 1

    def test_an_unnormalised_sum_is_an_error_magnitude(self):
        facts = self._facts([0, 1, 2, 3], [1.0, 1.0, 1.0, 0.7])
        assert fbxbytes.skin_facts(facts)["max_weight_sum_error"] == pytest.approx(0.3)

    def test_mismatched_arrays_null_the_number_with_a_reason(self):
        facts = self._facts([0, 1], [1.0])
        out = fbxbytes.skin_facts(facts)
        assert out["max_weight_sum_error"] is None
        assert "indexes" in out["unavailable_reason"]

    def test_a_file_with_no_skins_reads_as_zero_not_error(self):
        out = fbxbytes.skin_facts(FbxFacts(version=7500))
        assert out["deformers"] == 0
        assert out["bind_pose_present"] is False


class TestSkinRecordsFromTheCommittedArtifact:
    def _facts(self):
        return fbxbytes.read_fbx(os.path.join(
            REPO, "evals", "rigging_fixtures", "skinned_cylinder.fbx"))

    def test_the_skin_and_its_clusters_are_found(self):
        facts = self._facts()
        assert len(facts.skins) == 1
        assert len(facts.clusters) == 3          # one per joint
        skin = next(iter(facts.skins.values()))
        assert skin["geometry"] in facts.geometries
        assert sorted(skin["clusters"]) == sorted(facts.clusters)

    def test_every_cluster_links_a_limb_model(self):
        facts = self._facts()
        limb_uids = {n.uid for n in facts.nodes if n.kind == "LimbNode"}
        assert len(limb_uids) == 3
        assert {c["model"] for c in facts.clusters.values()} == limb_uids

    def test_weight_sums_read_from_the_bytes(self):
        out = fbxbytes.skin_facts(self._facts())
        assert out["bind_pose_present"] is True
        assert out["unweighted_file_vertices"] == 0
        # 9.568305e-4 in this artifact, and NOT float noise: Maya's own
        # in-scene sums are 1.0 to 2.2e-16, but its FBX exporter drops every
        # weight below 1e-3 and does not renormalise what is left, so 40 of
        # these 140 vertices lost one influence on the way out. The reader is
        # reporting that faithfully; what a gate should tolerate is
        # export.WEIGHT_SUM_TOL's problem, and it is 1e-2 for this reason.
        assert out["max_weight_sum_error"] < 1e-3
        assert out["max_weight_sum_error"] > 1e-9

    def test_joint_hierarchy_survives_the_extra_connections(self):
        # The Model->Cluster connection must not clobber the Model->Model
        # parent link - the regression the wiring rework risks.
        facts = self._facts()
        limbs = [n for n in facts.nodes if n.kind == "LimbNode"]
        parents = [n.parent for n in limbs]
        assert sum(1 for p in parents if p is None) <= 1
        assert sum(1 for p in parents if p is not None) >= 2

    def test_the_unskinned_golem_still_reads_clean(self):
        facts = fbxbytes.read_fbx(
            os.path.join(REPO, "evals", "golem_delivery", "golem.fbx"))
        assert facts.skins == {}
        assert fbxbytes.skin_facts(facts)["deformers"] == 0


class TestShapeFacts:
    """Blend-shape records (#691). Synthetic facts here; that these shapes
    match what Maya WRITES is pinned under mayapy
    (TestBlendshapeExportInMaya), which is also where the channel-naming
    measurement lives."""

    def _facts(self):
        facts = FbxFacts(version=7500)
        facts.nodes.append(FbxNode(name="humanoid", kind="Mesh", uid=1,
                                   geometry=10))
        facts.geometries[10] = (0.0, 0.0, 0.0)
        facts.shape_geoms[20] = {"name": "brow_raise", "points": 6,
                                 "indexes": (0, 1, 2, 3, 4, 5)}
        facts.blend_channels[30] = {"name": "brow_raise", "shape": 20,
                                    "deformer": 40}
        facts.blend_deformers[40] = {"geometry": 10, "channels": [30]}
        return facts

    def test_a_healthy_file_reads_clean(self):
        out = fbxbytes.shape_facts(self._facts())
        assert out["blend_deformers"] == 1 and out["channels"] == 1
        assert out["shapes"] == [
            {"name": "brow_raise", "points": 6, "indexes": 6}]
        assert out["unavailable_reason"] is None

    def test_channel_names_are_cleaned_to_the_alias(self):
        facts = self._facts()
        facts.blend_channels[30]["name"] = "humanoid_shapes.brow_raise"
        out = fbxbytes.shape_facts(facts)
        assert out["shapes"][0]["name"] == "brow_raise"

    def test_orphan_links_are_reasons_never_guesses(self):
        facts = self._facts()
        facts.blend_channels[30]["shape"] = None
        facts.blend_deformers[40]["geometry"] = None
        out = fbxbytes.shape_facts(facts)
        assert "links no shape geometry" in out["unavailable_reason"]
        assert "deforms no geometry" in out["unavailable_reason"]
        assert out["shapes"][0]["points"] == 0

    def test_shapes_are_sorted_by_name(self):
        facts = self._facts()
        facts.shape_geoms[21] = {"name": "a_first", "points": 3,
                                 "indexes": (0, 1, 2)}
        facts.blend_channels[31] = {"name": "a_first", "shape": 21,
                                    "deformer": 40}
        facts.blend_deformers[40]["channels"].append(31)
        out = fbxbytes.shape_facts(facts)
        assert [s["name"] for s in out["shapes"]] == ["a_first",
                                                      "brow_raise"]

    def test_a_shapeless_facts_reads_empty(self):
        out = fbxbytes.shape_facts(FbxFacts(version=7500))
        assert out == {"blend_deformers": 0, "channels": 0, "shapes": [],
                       "unavailable_reason": None}


class TestAnimFacts:
    """Animation records (#695). Synthetic facts here; that these shapes
    match what Maya WRITES - tick size, property strings, take naming - is
    pinned under mayapy (TestClipExportInMaya)."""

    def _facts(self):
        facts = FbxFacts(version=7500)
        facts.nodes.append(FbxNode(name="L_hip", kind="LimbNode", uid=1))
        tick = fbxbytes.KTIME_PER_SECOND
        facts.anim_curves[10] = {"key_count": 31, "first_tick": 0,
                                 "last_tick": tick}
        facts.anim_curves[11] = {"key_count": 31, "first_tick": 0,
                                 "last_tick": tick}
        facts.anim_curves[12] = {"key_count": 31, "first_tick": 0,
                                 "last_tick": tick}
        facts.anim_nodes[20] = {"name": "R", "target": 1,
                                "target_kind": "model",
                                "property": "Lcl Rotation",
                                "curves": [10, 11, 12]}
        facts.anim_stacks = 1
        facts.anim_layers = {30}
        facts.takes = [{"name": "walk", "start_tick": 0, "stop_tick": tick}]
        return facts

    def test_a_healthy_file_reads_clean(self):
        out = fbxbytes.anim_facts(self._facts())
        assert out["stacks"] == 1 and out["layers"] == 1
        assert out["curves"] == 3 and out["curve_nodes"] == 1
        assert out["takes"] == [{"name": "walk", "start_s": 0.0,
                                 "stop_s": 1.0, "duration_s": 1.0}]
        assert out["targets"] == [{"target": "L_hip",
                                   "property": "Lcl Rotation", "curves": 3,
                                   "key_count": 31, "duration_s": 1.0,
                                   "take": None}]
        assert out["unavailable_reason"] is None

    def test_a_curve_node_reports_the_take_it_belongs_to(self):
        """#718 Task 10 MEASURED: a multi-take file carries one curve node
        per plug PER TAKE, plus the full-span one belonging to Maya's own
        default take. Without attribution the gate cannot tell them apart,
        and which one it happens to read is decided by an unstable UID
        (t718-10-report.md finding #3)."""
        facts = self._facts()
        tick = fbxbytes.KTIME_PER_SECOND
        facts.anim_stacks_by_uid = {70: "Take 001", 71: "idle", 72: "walk"}
        facts.anim_layers_by_uid = {80: 70, 81: 71, 82: 72}
        facts.anim_nodes[20]["layer"] = 80          # the full-span one
        facts.anim_curves[13] = {"key_count": 31, "first_tick": 0,
                                 "last_tick": tick}
        facts.anim_nodes[21] = {"name": "R", "target": 1,
                                "target_kind": "model",
                                "property": "Lcl Rotation", "curves": [13],
                                "layer": 81}
        by_take = {t["take"]: t for t in fbxbytes.anim_facts(facts)["targets"]}
        assert "idle" in by_take
        assert by_take["idle"]["property"] == "Lcl Rotation"
        assert by_take["Take 001"]["property"] == "Lcl Rotation"
        # No layer connection at all - the reader reports None, never a guess.
        facts2 = self._facts()
        assert fbxbytes.anim_facts(facts2)["targets"][0]["take"] is None

    def test_a_take_reports_where_it_sits_not_only_how_long_it_is(self):
        """#718: several takes share one timeline, so the gate needs each
        take's own start and stop, not just its length."""
        facts = self._facts()
        tick = fbxbytes.KTIME_PER_SECOND
        facts.takes = [
            {"name": "idle", "start_tick": 0, "stop_tick": 2 * tick},
            {"name": "walk", "start_tick": 62 * tick // 30,
             "stop_tick": 98 * tick // 30},
            {"name": "nolocaltime", "start_tick": None, "stop_tick": None},
        ]
        takes = {t["name"]: t for t in fbxbytes.anim_facts(facts)["takes"]}
        assert takes["idle"]["start_s"] == 0.0
        assert takes["idle"]["stop_s"] == 2.0
        assert takes["walk"]["start_s"] == pytest.approx(62 / 30.0, abs=1e-6)
        assert takes["walk"]["duration_s"] == pytest.approx(36 / 30.0,
                                                            abs=1e-6)
        assert takes["nolocaltime"] == {"name": "nolocaltime",
                                        "start_s": None, "stop_s": None,
                                        "duration_s": None}

    def test_a_channel_target_reads_by_alias(self):
        facts = self._facts()
        facts.blend_channels[40] = {"name": "shapes.blink", "shape": None,
                                    "deformer": None}
        facts.anim_curves[13] = {"key_count": 5, "first_tick": 0,
                                 "last_tick": fbxbytes.KTIME_PER_SECOND}
        facts.anim_nodes[21] = {"name": "DeformPercent", "target": 40,
                                "target_kind": "channel",
                                "property": "DeformPercent",
                                "curves": [13]}
        out = fbxbytes.anim_facts(facts)
        by = {(t["target"], t["property"]): t for t in out["targets"]}
        assert by[("blink", "DeformPercent")]["key_count"] == 5

    def test_orphans_and_mismatches_are_reasons_never_guesses(self):
        facts = self._facts()
        facts.anim_nodes[21] = {"name": "T", "target": None,
                                "target_kind": None, "property": None,
                                "curves": []}
        facts.anim_curves[11]["key_count"] = 30
        out = fbxbytes.anim_facts(facts)
        assert "drives nothing" in out["unavailable_reason"]
        assert "disagree on key count" in out["unavailable_reason"]
        by = {t["target"]: t for t in out["targets"] if t["target"]}
        assert by["L_hip"]["key_count"] is None

    def test_an_animation_less_facts_reads_empty(self):
        out = fbxbytes.anim_facts(FbxFacts(version=7500))
        assert out == {"stacks": 0, "layers": 0, "curves": 0,
                       "curve_nodes": 0, "takes": [], "targets": [],
                       "unavailable_reason": None}


class TestAnimFactsFromTheCommittedArtifact:
    """#718 Task 10b: the two elif arms this fix added to read_fbx's
    connection loop (curve node -> layer, layer -> stack) are what the
    whole attribution fix rests on, and until now nothing exercised them -
    TestAnimFacts above hand-builds FbxFacts and never calls read_fbx, and
    the only fixture test_fbxbytes.py read (skinned_cylinder.fbx) carries
    no animation at all. This reads a real multi-take FBX through the
    actual binary parser, so a broken connection arm (wrong record name, a
    swapped child/parent, a typo in the uid lookup) fails here even though
    the synthetic tests above would stay green.
    """

    def _anim(self):
        facts = fbxbytes.read_fbx(
            os.path.join(REPO, "evals", "clip_live", "idle.fbx"))
        return fbxbytes.anim_facts(facts)

    def test_every_curve_node_is_fully_attributed(self):
        out = self._anim()
        assert out["curve_nodes"] > 0
        assert out["unavailable_reason"] is None
        # A None here means the layer/stack chain failed to resolve for
        # that row - the exact failure this test exists to catch.
        assert all(t["take"] is not None for t in out["targets"])

    def test_the_take_names_are_read_from_the_bytes_not_assumed(self):
        """Maya's own default take always rides along with the named one
        (see clip_live.py's module docstring) - both must come out of the
        AnimationCurveNode -> AnimationLayer -> AnimationStack chain, not
        from a hardcoded guess."""
        out = self._anim()
        histogram = collections.Counter(t["take"] for t in out["targets"])
        assert set(histogram) == {"Take 001", "idle"}
        # Every plug is keyed once per take, so the two takes' curve-node
        # counts must match exactly - a stray/missing connection would
        # unbalance them.
        assert histogram["Take 001"] == histogram["idle"] > 0
        assert {t["name"] for t in out["takes"]} == {"Take 001", "idle"}


# #714: fbxbytes must see the records the exporter DOES write for a file
# texture, so the gate can prove a claimed image reached the file. MEASURED
# directly off the committed fixture below (a python -c walk of the raw
# records, not evals/drifter_live.py's own probe, since that probe is a
# fresh Maya export and this reader is pinned against the byte-identical
# committed artifact): exactly one Texture and one Video object; the image
# basename is "drifter_basecolor.png". The fixture exercises BOTH filename
# shapes at once - Video carries a nested Properties70 P "Path"/"RelPath"
# pair AND a bare RelativeFilename child; Texture carries only the bare
# FileName/RelativeFilename children - so both parser paths are exercised
# by one file.
FIXTURE_WITH_TEXTURE = os.path.join(REPO, "evals", "drifter_live", "drifter.fbx")
FIXTURE_TEXTURE_BASENAME = "drifter_basecolor.png"
# MEASURED (standalone record-count walk, independent of fbxbytes.py, plus a
# raw substring grep as a second check): 0 Texture records, 0 Video records;
# the literal bytes b"Texture" and b"Video" do not occur anywhere in this
# file at all (count() == 0 for both). Genuinely textureless, not merely
# under-counted by the parser.
FIXTURE_WITHOUT_TEXTURE = os.path.join(
    REPO, "evals", "rigging_fixtures", "skinned_cylinder.fbx")


class TestTextureRecords:
    """#714: the reader must see the records the exporter DOES write for a
    file texture, so the gate can prove a claimed image reached the file.

    MEASURED (a direct byte walk of the committed drifter fixture): a
    file-textured export carries exactly one Texture and one Video object,
    and the image basename is in the bytes.
    """

    def test_the_committed_fixture_carries_one_texture_and_video(self):
        facts = fbxbytes.read_fbx(FIXTURE_WITH_TEXTURE)
        assert len(facts.textures) == 1
        assert len(facts.videos) == 1

    def test_texture_facts_reports_names_and_basenames(self):
        facts = fbxbytes.read_fbx(FIXTURE_WITH_TEXTURE)
        block = fbxbytes.texture_facts(facts)
        assert block["texture_records"] == 1
        assert block["video_records"] == 1
        assert block["unavailable_reason"] is None
        # Asserted separately, not unioned: Video's filename is filled by
        # the nested-P "Path" arm, Texture's ONLY by the bare
        # FileName/RelativeFilename child-record arm - a union would let a
        # break in either arm hide behind the other's basename.
        assert {t["basename"] for t in block["textures"]} == {
            FIXTURE_TEXTURE_BASENAME}
        assert {v["basename"] for v in block["videos"]} == {
            FIXTURE_TEXTURE_BASENAME}

    def test_a_textureless_fixture_reports_zero_not_an_error(self):
        facts = fbxbytes.read_fbx(FIXTURE_WITHOUT_TEXTURE)
        block = fbxbytes.texture_facts(facts)
        assert block == {"texture_records": 0, "video_records": 0,
                         "textures": [], "videos": [],
                         "unavailable_reason": None}
