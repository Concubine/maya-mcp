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
