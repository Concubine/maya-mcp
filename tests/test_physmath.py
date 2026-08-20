"""Pure physics-body math (#676) - no Maya anywhere in this file.

The golem numbers these functions must eventually reproduce live in
evals/golem_delivery/chunks.json; here the fixtures are synthetic solids
whose answers are exact, placed FAR from the classification thresholds so
a threshold calibration in Task 3 cannot silently break this file.
"""

import math

import pytest

from maya_plugin.handlers import arraymath, physmath

# A unit cube, outward winding: verts 0..7, 12 triangles.
CUBE_POINTS = [
    (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0),
    (0.0, 0.0, 1.0), (1.0, 0.0, 1.0), (1.0, 1.0, 1.0), (0.0, 1.0, 1.0),
]
CUBE_TRIS = [
    (0, 2, 1), (0, 3, 2),          # bottom (-z)
    (4, 5, 6), (4, 6, 7),          # top (+z)
    (0, 1, 5), (0, 5, 4),          # front (-y)
    (2, 3, 7), (2, 7, 6),          # back (+y)
    (0, 4, 7), (0, 7, 3),          # left (-x)
    (1, 2, 6), (1, 6, 5),          # right (+x)
]


def translated(points, offset):
    return [(p[0] + offset[0], p[1] + offset[1], p[2] + offset[2])
            for p in points]


def flatten(points):
    return [v for p in points for v in p]


class TestSolidComAndVolume:
    def test_unit_cube(self):
        signed, com = physmath.solid_com(CUBE_POINTS, CUBE_TRIS)
        assert signed == pytest.approx(1.0)
        assert com == pytest.approx([0.5, 0.5, 0.5])

    def test_matches_arraymath_signed_volume(self):
        signed, _ = physmath.solid_com(CUBE_POINTS, CUBE_TRIS)
        assert signed == pytest.approx(
            arraymath.signed_volume(CUBE_POINTS, CUBE_TRIS))

    def test_translated_cube_moves_the_com_not_the_volume(self):
        pts = translated(CUBE_POINTS, [10.0, -2.0, 0.5])
        signed, com = physmath.solid_com(pts, CUBE_TRIS)
        assert signed == pytest.approx(1.0)
        assert com == pytest.approx([10.5, -1.5, 1.0])

    def test_inverted_winding_flips_the_sign_only(self):
        flipped = [(a, c, b) for a, b, c in CUBE_TRIS]
        signed, com = physmath.solid_com(CUBE_POINTS, flipped)
        assert signed == pytest.approx(-1.0)
        assert com == pytest.approx([0.5, 0.5, 0.5])

    def test_com_is_tessellation_invariant(self):
        # Split the top face around a centre vertex: 4 triangles where 2
        # were. A vertex-average COM would drift toward the denser face;
        # the SOLID com must not move - that is why the contract ships it.
        pts = CUBE_POINTS + [(0.5, 0.5, 1.0)]
        tris = [t for t in CUBE_TRIS if t not in ((4, 5, 6), (4, 6, 7))]
        tris += [(4, 5, 8), (5, 6, 8), (6, 7, 8), (7, 4, 8)]
        signed, com = physmath.solid_com(pts, tris)
        assert signed == pytest.approx(1.0)
        assert com == pytest.approx([0.5, 0.5, 0.5])

    def test_degenerate_returns_none_com(self):
        flat_tris = [(0, 1, 2)]
        signed, com = physmath.solid_com(
            [(0, 0, 0), (1, 0, 0), (0, 1, 0)], flat_tris)
        assert abs(signed) < 1e-9
        assert com is None


class TestOpenEdges:
    def test_closed_cube_has_none(self):
        assert physmath.open_edge_count(CUBE_TRIS) == 0

    def test_missing_triangle_opens_three_edges(self):
        assert physmath.open_edge_count(CUBE_TRIS[1:]) == 3

    def test_tessellated_top_stays_closed(self):
        tris = [t for t in CUBE_TRIS if t not in ((4, 5, 6), (4, 6, 7))]
        tris += [(4, 5, 8), (5, 6, 8), (6, 7, 8), (7, 4, 8)]
        assert physmath.open_edge_count(tris) == 0


class TestEigenAndFrame:
    def test_diagonal_matrix_is_its_own_answer(self):
        values, vectors = physmath.eigen_symmetric3(
            [[2.0, 0.0, 0.0], [0.0, 5.0, 0.0], [0.0, 0.0, 1.0]])
        assert sorted(values) == pytest.approx([1.0, 2.0, 5.0])
        # eigenvectors are the basis (any order/sign)
        for vec in vectors:
            assert max(abs(c) for c in vec) == pytest.approx(1.0)

    def test_off_diagonal_2x2_block(self):
        # [[2,1],[1,2]] block: eigenvalues 3 and 1, vectors [1,1] and [1,-1]
        values, vectors = physmath.eigen_symmetric3(
            [[2.0, 1.0, 0.0], [1.0, 2.0, 0.0], [0.0, 0.0, 7.0]])
        assert sorted(values) == pytest.approx([1.0, 3.0, 7.0])

    def test_principal_frame_finds_the_long_axis(self):
        # a cloud stretched along y
        flat = []
        for t in range(-5, 6):
            for (x, z) in ((0.1, 0.0), (-0.1, 0.0), (0.0, 0.1), (0.0, -0.1)):
                flat.extend([x, 0.4 * t, z])
        centroid, axes = physmath.principal_frame(flat)
        assert centroid == pytest.approx([0.0, 0.0, 0.0], abs=1e-9)
        assert abs(axes[0][1]) == pytest.approx(1.0, abs=1e-6)
        # canonical sign: the dominant component is positive
        assert axes[0][1] > 0
        # right-handed unit frame
        cx = [axes[0][1] * axes[1][2] - axes[0][2] * axes[1][1],
              axes[0][2] * axes[1][0] - axes[0][0] * axes[1][2],
              axes[0][0] * axes[1][1] - axes[0][1] * axes[1][0]]
        assert cx == pytest.approx(axes[2], abs=1e-9)

    def test_cube_corners_keep_the_identity_frame(self):
        # isotropic covariance: Jacobi must not invent a rotation
        _, axes = physmath.principal_frame(flatten(CUBE_POINTS))
        for k in range(3):
            assert max(abs(c) for c in axes[k]) == pytest.approx(1.0)


class TestEuler:
    IDENTITY = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]

    def test_identity_is_zero(self):
        assert physmath.frame_to_euler_xyz_deg(self.IDENTITY) == pytest.approx(
            [0.0, 0.0, 0.0])

    def test_pure_z_rotation(self):
        c, s = math.cos(math.radians(90)), math.sin(math.radians(90))
        axes = [[c, s, 0.0], [-s, c, 0.0], [0.0, 0.0, 1.0]]
        assert physmath.frame_to_euler_xyz_deg(axes) == pytest.approx(
            [0.0, 0.0, 90.0], abs=1e-9)

    def test_pure_x_rotation(self):
        c, s = math.cos(math.radians(30)), math.sin(math.radians(30))
        axes = [[1.0, 0.0, 0.0], [0.0, c, s], [0.0, -s, c]]
        assert physmath.frame_to_euler_xyz_deg(axes) == pytest.approx(
            [30.0, 0.0, 0.0], abs=1e-9)

    def test_pure_y_rotation(self):
        c, s = math.cos(math.radians(40)), math.sin(math.radians(40))
        axes = [[c, 0.0, -s], [0.0, 1.0, 0.0], [s, 0.0, c]]
        assert physmath.frame_to_euler_xyz_deg(axes) == pytest.approx(
            [0.0, 40.0, 0.0], abs=1e-9)


class TestFitCollider:
    def _cylinder_cloud(self, radius=0.2, half=1.0):
        # square rings along x - radial max is exactly `radius`
        flat = []
        for x in (-half, -half / 2, 0.0, half / 2, half):
            for (y, z) in ((radius, 0.0), (-radius, 0.0),
                           (0.0, radius), (0.0, -radius)):
                flat.extend([x, y, z])
        return flat

    def test_cube_is_a_box(self):
        # 8 corners fill their box exactly: fill 1.0 >> BOX_FILL_MIN
        out = physmath.fit_collider(flatten(CUBE_POINTS), 1.0)
        assert out["kind"] == "box"
        assert sorted(out["size"]) == pytest.approx([1.0, 1.0, 1.0])
        assert out["centre"] == pytest.approx([0.5, 0.5, 0.5])
        assert out["max_escape"] == 0.0
        assert out["volume_ratio"] == pytest.approx(1.0)

    def test_ball_cloud_is_a_sphere(self):
        # octahedron + inset corners: near-isotropic, low fill
        s = 1.0 / math.sqrt(3.0)
        pts = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0),
               (0, 0, 1), (0, 0, -1)]
        pts += [(a * s, b * s, c * s)
                for a in (1, -1) for b in (1, -1) for c in (1, -1)]
        # mesh volume chosen so fill = 4.0 / 8.0 = 0.5 < BOX_FILL_MIN
        out = physmath.fit_collider(flatten(pts), 4.0)
        assert out["kind"] == "sphere"
        assert out["radius"] == pytest.approx(1.0, abs=1e-6)
        assert out["max_escape"] == 0.0
        assert out["volume_ratio"] == pytest.approx(
            4.0 / 3.0 * math.pi / 4.0)

    def test_long_cylinder_is_a_capsule(self):
        flat = self._cylinder_cloud()
        out = physmath.fit_collider(flat, 0.25)
        assert out["kind"] == "capsule"
        assert out["radius"] == pytest.approx(0.2, abs=1e-9)
        # height = axial span 2.0 minus two cap radii
        assert out["height"] == pytest.approx(1.6, abs=1e-9)
        assert abs(out["axis"][0]) == pytest.approx(1.0, abs=1e-6)
        # the end-ring corners poke past the hemispherical caps - MEASURED
        expected = math.sqrt(0.2 ** 2 + 0.2 ** 2) - 0.2
        assert out["max_escape"] == pytest.approx(expected, abs=1e-6)

    def test_rotated_cylinder_recovers_its_frame(self):
        c, s = math.cos(math.radians(30)), math.sin(math.radians(30))
        flat = self._cylinder_cloud()
        rotated = []
        for i in range(len(flat) // 3):
            x, y, z = flat[3 * i], flat[3 * i + 1], flat[3 * i + 2]
            rotated.extend([c * x - s * y, s * x + c * y, z])
        out = physmath.fit_collider(rotated, 0.25)
        assert out["kind"] == "capsule"
        dot = out["axis"][0] * c + out["axis"][1] * s
        assert abs(dot) == pytest.approx(1.0, abs=1e-6)
        assert out["radius"] == pytest.approx(0.2, abs=1e-6)

    def test_flat_ring_falls_through_to_box(self):
        # a ring is neither elongated (a = b) nor isotropic (c tiny) nor
        # box-filling - the delivered gaskets landed exactly here
        flat = []
        for k in range(8):
            ang = math.tau * k / 8.0
            for z in (0.1, -0.1):
                flat.extend([math.cos(ang), math.sin(ang), z])
        out = physmath.fit_collider(flat, 0.2)
        assert out["kind"] == "box"

    def test_unmeasurable_volume_reports_none_ratio(self):
        out = physmath.fit_collider(flatten(CUBE_POINTS), 0.0)
        assert out["volume_ratio"] is None

    def test_a_box_wearing_capsule_proportions_still_reads_as_a_box(self):
        # #676 Task 6's live gate caught this on golem_C_chest_girdle: an
        # anisotropic BOX (corners fill their bounding box exactly, fill
        # 1.0) can still pass the old capsule test on aspect ratio alone
        # (a/b=1.2, b/c=1.11 both clear the thresholds). A real capsule's
        # rounded caps can never reach that fill - CAPSULE_FILL_MAX is the
        # guard that keeps a box a box regardless of its proportions.
        half = (1.2, 1.0, 0.9)
        corners = [(sx * half[0], sy * half[1], sz * half[2])
                   for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
        box_vol = 8.0 * half[0] * half[1] * half[2]
        out = physmath.fit_collider(flatten(corners), box_vol)
        assert out["kind"] == "box"

    def test_a_moderately_elongated_round_limb_reads_as_a_capsule(self):
        # #676 Task 6's live gate caught this on golem_L/R_thigh and
        # golem_L/R_shin: a round-cross-section limb only 1.2x longer than
        # it is wide (well short of the old 1.6 elongation floor) is still
        # closer to a capsule than a sphere - forcing the old sphere fit
        # wasted 2.9-3.3x volume where a capsule sits near parity.
        flat = self._cylinder_cloud(radius=0.5, half=0.6)  # a/b = 1.2
        out = physmath.fit_collider(flat, 0.6)  # fill = 0.5, well under
        assert out["kind"] == "capsule"


class TestConeFromHinge:
    def test_the_knee_rule_verbatim(self):
        # shin (0, 110): axis along the hinge, swing2 = 0, swing1 covers
        # the arc, twist locked, neutral at the extreme
        cone = physmath.cone_from_hinge([1, 0, 0], [0, 110])
        assert cone["axis"] == pytest.approx([1.0, 0.0, 0.0])
        assert cone["swing1"] == pytest.approx(55.0)
        assert cone["swing2"] == 0.0
        assert cone["twist_lo"] == 0.0 and cone["twist_hi"] == 0.0
        assert cone["swing_centre_deg"] == pytest.approx(55.0)
        # neutral (0 deg) sits ON the cone edge: centre - swing1 == 0
        assert cone["swing_centre_deg"] - cone["swing1"] == pytest.approx(0.0)

    def test_two_sided_range_centres_the_cone(self):
        cone = physmath.cone_from_hinge([1, 0, 0], [-30, 15])
        assert cone["swing1"] == pytest.approx(22.5)
        assert cone["swing_centre_deg"] == pytest.approx(-7.5)

    def test_axis_is_normalized_and_swing_axis_perpendicular(self):
        cone = physmath.cone_from_hinge([0, 0, 2], [-10, 10])
        assert cone["axis"] == pytest.approx([0.0, 0.0, 1.0])
        dot = sum(a * b for a, b in zip(cone["axis"], cone["swing_axis"]))
        assert dot == pytest.approx(0.0, abs=1e-9)
        norm = math.sqrt(sum(v * v for v in cone["swing_axis"]))
        assert norm == pytest.approx(1.0)

    def test_swing_axis_is_deterministic(self):
        a = physmath.cone_from_hinge([1, 0, 0], [0, 90])
        b = physmath.cone_from_hinge([1, 0, 0], [0, 90])
        assert a["swing_axis"] == b["swing_axis"] == pytest.approx(
            [0.0, 1.0, 0.0])

    def test_locked_hinge_is_a_locked_cone(self):
        cone = physmath.cone_from_hinge([1, 0, 0], [0, 0])
        assert cone["swing1"] == 0.0 and cone["swing_centre_deg"] == 0.0

    def test_twist_range_carries_through(self):
        cone = physmath.cone_from_hinge([1, 0, 0], [0, 90], (-2.0, 3.0))
        assert cone["twist_lo"] == -2.0 and cone["twist_hi"] == 3.0

    def test_zero_axis_raises(self):
        with pytest.raises(ValueError):
            physmath.cone_from_hinge([0, 0, 0], [0, 90])
