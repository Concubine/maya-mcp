"""author_physics (#676) orchestration under a FakeCmds.

Real meshes and the real OpenMaya reader are mayapy's job
(tests/test_handlers_mayapy.py); this file pins chunk collection, parent
derivation, override validation, the warnings taxonomy, read-only purity
and every refusal path. The geometry seam physics._points_and_triangles
is monkeypatched per test - FakeCmds cannot fake OpenMaya, and that is
exactly why the seam is module-level (the rigging._set_skin_weights
precedent).
"""

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import physics, physmath

# The unit cube from test_physmath, restated locally so this file stands
# alone: 8 corners, 12 outward triangles, volume 1, COM at the centre.
CUBE_POINTS = [
    (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0),
    (0.0, 0.0, 1.0), (1.0, 0.0, 1.0), (1.0, 1.0, 1.0), (0.0, 1.0, 1.0),
]
CUBE_TRIS = [
    (0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7),
    (0, 1, 5), (0, 5, 4), (2, 3, 7), (2, 7, 6),
    (0, 4, 7), (0, 7, 3), (1, 2, 6), (1, 6, 5),
]


def cube_at(offset):
    pts = [(p[0] + offset[0], p[1] + offset[1], p[2] + offset[2])
           for p in CUBE_POINTS]
    return pts, list(CUBE_TRIS)


class FakeCmds:
    """Transforms live in `objects`/`parents`; shapes ONLY in `shapes`
    (transform long name -> shape long name). nodeType is by the project's
    naming convention, the same trick test_rigging's fake uses."""

    def __init__(self):
        self.objects = []      # transform long names
        self.parents = {}      # child long -> parent long (transforms only)
        self.shapes = {}       # transform long -> shape long

    def ls(self, pattern=None, long=False, type=None, **kw):
        if pattern is None:
            return list(self.objects)
        names = pattern if isinstance(pattern, list) else [pattern]
        out = []
        for n in names:
            out.extend(o for o in self.objects
                       if o == n or o.split("|")[-1] == n)
        return out

    def listRelatives(self, node, parent=False, allDescendents=False,
                      shapes=False, fullPath=False, type=None,
                      noIntermediate=False, **kw):
        if parent:
            p = self.parents.get(node)
            return [p] if p else None
        if shapes:
            s = self.shapes.get(node)
            return [s] if s else None
        kids = [o for o, p in self.parents.items() if p == node]
        if allDescendents:
            out = []
            frontier = list(kids)
            while frontier:
                k = frontier.pop()
                out.append(k)
                frontier.extend(o for o, p in self.parents.items() if p == k)
            return out or None
        return kids or None

    def nodeType(self, node):
        return "mesh" if node.endswith("Shape") else "transform"


@pytest.fixture
def fake(monkeypatch):
    fake = FakeCmds()
    fake.geoms = {}   # chunk SHORT name -> (points, triangles)
    monkeypatch.setattr(physics, "_cmds", lambda: fake)
    monkeypatch.setattr(
        physics, "_points_and_triangles",
        lambda transform: fake.geoms[transform.split("|")[-1]])
    return fake


def _scene(fake):
    """|golem (group)
         |golem|pelvis (mesh)
           |golem|pelvis|grp (group)
             |golem|pelvis|grp|belly (mesh)   parent chunk = pelvis
           |golem|pelvis|thigh (mesh)         parent chunk = pelvis
         |golem|tracer (mesh)                 parent chunk = None (DAG)
    """
    fake.objects = ["|golem", "|golem|pelvis", "|golem|pelvis|grp",
                    "|golem|pelvis|grp|belly", "|golem|pelvis|thigh",
                    "|golem|tracer"]
    fake.parents = {"|golem|pelvis": "|golem",
                    "|golem|pelvis|grp": "|golem|pelvis",
                    "|golem|pelvis|grp|belly": "|golem|pelvis|grp",
                    "|golem|pelvis|thigh": "|golem|pelvis",
                    "|golem|tracer": "|golem"}
    fake.shapes = {"|golem|pelvis": "|golem|pelvis|pelvisShape",
                   "|golem|pelvis|grp|belly": "|golem|pelvis|grp|belly|bellyShape",
                   "|golem|pelvis|thigh": "|golem|pelvis|thigh|thighShape",
                   "|golem|tracer": "|golem|tracer|tracerShape"}
    fake.geoms = {"pelvis": cube_at([0.0, 0.0, 0.0]),
                  "belly": cube_at([0.0, 1.0, 0.0]),
                  "thigh": cube_at([0.5, -1.0, 0.0]),
                  "tracer": cube_at([0.0, 3.0, 0.0])}


class TestChunkCollection:
    def test_root_walk_keeps_mesh_bearers_sorted_by_long_name(self, fake):
        _scene(fake)
        out = physics.author_physics({"root": "golem"})
        assert [b["chunk"] for b in out["bodies"]] == [
            "|golem|pelvis", "|golem|pelvis|grp|belly",
            "|golem|pelvis|thigh", "|golem|tracer"]

    def test_chunks_mode_keeps_caller_order(self, fake):
        _scene(fake)
        out = physics.author_physics({"chunks": ["thigh", "pelvis"]})
        assert [b["chunk"] for b in out["bodies"]] == [
            "|golem|pelvis|thigh", "|golem|pelvis"]

    def test_exclude_filters_and_warns(self, fake):
        _scene(fake)
        out = physics.author_physics({"root": "golem",
                                      "exclude": ["TRACER"]})
        assert all("tracer" not in b["chunk"] for b in out["bodies"])
        assert any("excluded" in w and "tracer" in w
                   for w in out["warnings"])

    def test_refusals(self, fake):
        _scene(fake)
        with pytest.raises(HandlerError, match="exactly one"):
            physics.author_physics({})
        with pytest.raises(HandlerError, match="exactly one"):
            physics.author_physics({"root": "golem", "chunks": ["pelvis"]})
        with pytest.raises(HandlerError, match="non-empty list"):
            physics.author_physics({"chunks": []})
        with pytest.raises(HandlerError, match="no mesh shape"):
            physics.author_physics({"chunks": ["grp"]})
        with pytest.raises(HandlerError, match="not found"):
            physics.author_physics({"chunks": ["nope"]})
        with pytest.raises(HandlerError, match="no mesh-bearing"):
            physics.author_physics({"root": "golem",
                                    "exclude": ["pelvis", "belly", "thigh", "tracer"]})  # exclude everything by short name - the refusal, not the matching, is under test (brief's ["golem"] assumed path matching, contradicting the short-name contract)
        with pytest.raises(HandlerError, match="density"):
            physics.author_physics({"root": "golem", "density": 0})
        with pytest.raises(HandlerError, match="density"):
            physics.author_physics({"root": "golem", "density": True})

    def test_exclude_refused_in_chunks_mode(self, fake):
        _scene(fake)
        with pytest.raises(HandlerError, match="root-mode only"):
            physics.author_physics({"chunks": ["pelvis"], "exclude": ["x"]})

    def test_duplicate_short_names_refused(self, fake):
        _scene(fake)
        fake.objects.append("|other|thigh")
        fake.parents["|other|thigh"] = None
        fake.shapes["|other|thigh"] = "|other|thigh|thighShape"
        with pytest.raises(HandlerError, match="collide"):
            physics.author_physics({
                "chunks": ["|golem|pelvis|thigh", "|other|thigh"]})


class TestParents:
    def test_nearest_mesh_bearing_ancestor_skips_plain_groups(self, fake):
        _scene(fake)
        out = physics.author_physics({"root": "golem"})
        by = {b["chunk"].split("|")[-1]: b for b in out["bodies"]}
        assert by["belly"]["parent"] == "|golem|pelvis"
        assert by["thigh"]["parent"] == "|golem|pelvis"
        assert by["pelvis"]["parent"] is None

    def test_multiple_parentless_bodies_warn(self, fake):
        _scene(fake)
        out = physics.author_physics({"root": "golem"})
        assert any("parentless" in w for w in out["warnings"])

    def test_parent_override_wins_and_must_be_a_chunk(self, fake):
        _scene(fake)
        out = physics.author_physics({
            "root": "golem",
            "overrides": {"tracer": {"parent": "pelvis"}}})
        by = {b["chunk"].split("|")[-1]: b for b in out["bodies"]}
        assert by["tracer"]["parent"] == "|golem|pelvis"
        with pytest.raises(HandlerError, match="parent"):
            physics.author_physics({
                "root": "golem",
                "overrides": {"tracer": {"parent": "grp"}}})


class TestMeasurement:
    def test_mass_volume_com_measured_from_the_geometry(self, fake):
        _scene(fake)
        out = physics.author_physics({"chunks": ["belly"]})
        body = out["bodies"][0]
        assert body["volume"] == pytest.approx(1.0)
        assert body["mass"] == pytest.approx(1.0)     # density defaults 1.0
        assert body["com"] == pytest.approx([0.5, 1.5, 0.5])
        assert body["watertight"] is True and body["open_edges"] == 0
        assert body["verts"] == 8 and body["tris"] == 12
        assert out["total_volume"] == pytest.approx(1.0)

    def test_density_scales_mass_only(self, fake):
        _scene(fake)
        out = physics.author_physics({"chunks": ["belly"], "density": 2.5})
        assert out["bodies"][0]["mass"] == pytest.approx(2.5)
        assert out["bodies"][0]["volume"] == pytest.approx(1.0)
        assert out["density"] == 2.5

    def test_open_mesh_warns_with_the_edge_count(self, fake):
        _scene(fake)
        pts, tris = cube_at([0.0, 0.0, 0.0])
        fake.geoms["belly"] = (pts, tris[1:])      # 3 boundary edges
        out = physics.author_physics({"chunks": ["belly"]})
        body = out["bodies"][0]
        assert body["watertight"] is False and body["open_edges"] == 3
        assert any("3 boundary edge" in w for w in out["warnings"])

    def test_inverted_winding_warns_and_reports_magnitude(self, fake):
        _scene(fake)
        pts, tris = cube_at([0.0, 0.0, 0.0])
        fake.geoms["belly"] = (pts, [(a, c, b) for a, b, c in tris])
        out = physics.author_physics({"chunks": ["belly"]})
        body = out["bodies"][0]
        assert body["signed_volume"] == pytest.approx(-1.0)
        assert body["volume"] == pytest.approx(1.0)
        assert any("INWARD" in w for w in out["warnings"])

    def test_collider_is_the_physmath_fit(self, fake):
        _scene(fake)
        out = physics.author_physics({"chunks": ["belly"]})
        col = out["bodies"][0]["collider"]
        assert col["kind"] == "box"
        assert sorted(col["size"]) == pytest.approx([1.0, 1.0, 1.0])
        assert col["volume_ratio"] == pytest.approx(1.0)
        assert col["max_escape"] == 0.0

    def test_poor_fit_warns_with_numbers(self, fake, monkeypatch):
        _scene(fake)
        monkeypatch.setattr(physmath, "fit_collider", lambda flat, sv: {
            "kind": "box", "centre": [0, 0, 0],
            "rotation_deg": [0, 0, 0], "size": [1, 1, 1],
            "radius": None, "height": None, "axis": None,
            "volume_ratio": 3.1, "max_escape": 0.9})
        out = physics.author_physics({"chunks": ["belly"]})
        assert any("volume_ratio 3.1" in w for w in out["warnings"])
        assert any("max_escape" in w for w in out["warnings"])


class TestJoints:
    def test_override_converts_to_the_cone(self, fake):
        _scene(fake)
        out = physics.author_physics({
            "root": "golem",
            "overrides": {"thigh": {"hinge_axis": [1, 0, 0],
                                    "hinge_range_deg": [0, 110]}}})
        by = {b["chunk"].split("|")[-1]: b for b in out["bodies"]}
        joint = by["thigh"]["joint"]
        assert joint["swing1"] == pytest.approx(55.0)
        assert joint["swing2"] == 0.0
        assert joint["swing_centre_deg"] == pytest.approx(55.0)
        assert joint["source"] == "override"

    def test_missing_override_emits_locked_joint_and_warns(self, fake):
        _scene(fake)
        out = physics.author_physics({"root": "golem"})
        by = {b["chunk"].split("|")[-1]: b for b in out["bodies"]}
        joint = by["belly"]["joint"]
        assert joint["swing1"] == 0.0 and joint["source"] == "default_locked"
        assert any("LOCKED joint" in w and "belly" in w
                   for w in out["warnings"])

    def test_parentless_chunk_has_no_joint(self, fake):
        _scene(fake)
        out = physics.author_physics({"root": "golem"})
        by = {b["chunk"].split("|")[-1]: b for b in out["bodies"]}
        assert by["pelvis"]["joint"] is None

    def test_range_excluding_rest_pose_warns(self, fake):
        _scene(fake)
        out = physics.author_physics({
            "root": "golem",
            "overrides": {"thigh": {"hinge_axis": [1, 0, 0],
                                    "hinge_range_deg": [10, 20]}}})
        assert any("EXCLUDES the rest pose" in w for w in out["warnings"])

    def test_unknown_override_name_warns(self, fake):
        _scene(fake)
        out = physics.author_physics({
            "root": "golem",
            "overrides": {"elbow": {"hinge_axis": [1, 0, 0],
                                    "hinge_range_deg": [0, 90]}}})
        assert any("elbow" in w and "ignored" in w for w in out["warnings"])

    def test_override_refusals(self, fake):
        _scene(fake)
        cases = [
            {"thigh": {"hinge_axis": [1, 0, 0]}},                 # no range
            {"thigh": {"hinge_range_deg": [0, 90]}},              # no axis
            {"thigh": {"hinge_axis": [0, 0, 0],
                       "hinge_range_deg": [0, 90]}},              # zero axis
            {"thigh": {"hinge_axis": [1, 0, 0],
                       "hinge_range_deg": [90, 0]}},              # lo > hi
            {"thigh": {"twist_range_deg": [0, 1]}},               # twist alone
            {"thigh": {"hinge": "x"}},                            # stray key
            {"thigh": "x"},                                       # not a dict
        ]
        for overrides in cases:
            with pytest.raises(HandlerError):
                physics.author_physics({"root": "golem",
                                        "overrides": overrides})


class TestReadOnly:
    def test_no_session_import_no_mutation(self, fake):
        # physics.py must not even import session (Global Constraints):
        assert not hasattr(physics, "session")
        _scene(fake)
        first = physics.author_physics({"root": "golem"})
        second = physics.author_physics({"root": "golem"})
        assert first == second     # deterministic, and the fake has no
                                   # mutators - any write would AttributeError
