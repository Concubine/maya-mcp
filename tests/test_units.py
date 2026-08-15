"""The scene's linear unit, and what it means for a delivery (maya-mcp #634).

The tool surface quotes geometry numbers - bboxes, translations, pivots - with
no unit attached, and nothing on it sets or reports the scene's linear unit. The
same authored number exports as 3.0 or 300.0 depending only on that ambient,
which is the mechanism behind #629's three broken deliveries.

`export_metres_per_unit` is the discriminator. Maya's internal linear unit is
centimetres whatever `currentUnit` reports, and the FBX exporter writes those
internal numbers, so the metres one scene unit becomes in the exported file IS
the cm-per-unit table. 1.0 is the only value that yields a metre-true delivery.
"""

import pytest

from maya_plugin.handlers import units


class FakeCmds:
    def __init__(self, linear="cm"):
        self.linear = linear
        self.set_calls = []

    def currentUnit(self, query=False, linear=None):
        if query:
            assert linear is True, "query must ask for the linear unit"
            return self.linear
        self.set_calls.append(linear)
        self.linear = linear
        return linear


class TestUnitsBlock:
    def test_reports_the_scenes_raw_linear_unit(self):
        assert units.units_block(FakeCmds("m"))["linear_unit"] == "m"

    def test_centimetres_is_one_metre_per_unit(self):
        # The #629 authoring convention: author metre NUMBERS in a cm scene and
        # the exporter writes them unchanged. This is the only correct value.
        block = units.units_block(FakeCmds("cm"))
        assert block["export_metres_per_unit"] == 1.0

    def test_metres_is_a_hundred_metres_per_unit(self):
        # The defect itself: a scene set to "m" writes 300.0 for the number 3.0,
        # so one scene unit lands as 100 m in the file.
        block = units.units_block(FakeCmds("m"))
        assert block["export_metres_per_unit"] == 100.0

    @pytest.mark.parametrize(
        "unit,metres",
        [("mm", 0.1), ("cm", 1.0), ("m", 100.0), ("km", 100000.0),
         ("in", 2.54), ("ft", 30.48), ("yd", 91.44), ("mi", 160934.4)],
    )
    def test_covers_every_unit_maya_can_report(self, unit, metres):
        assert units.units_block(FakeCmds(unit))["export_metres_per_unit"] == metres

    def test_an_unrecognised_unit_reports_null_rather_than_raising(self):
        # units_block is embedded in query responses (get_scene_graph and
        # friends). An unknown string must not take the whole query down - but
        # it must not silently claim 1.0 either, which would read as metre-true.
        block = units.units_block(FakeCmds("furlong"))
        assert block["linear_unit"] == "furlong"
        assert block["export_metres_per_unit"] is None

    def test_it_only_queries_never_sets(self):
        fake = FakeCmds("m")
        units.units_block(fake)
        assert fake.set_calls == []


class TestSetLinearUnit:
    def test_sets_the_requested_unit_and_returns_the_new_block(self):
        fake = FakeCmds("m")
        block = units.set_linear_unit(fake, "cm")
        assert fake.set_calls == ["cm"]
        assert block == {"linear_unit": "cm", "export_metres_per_unit": 1.0}

    def test_rejects_a_unit_maya_does_not_know(self):
        fake = FakeCmds("cm")
        with pytest.raises(units.HandlerError) as exc:
            units.set_linear_unit(fake, "furlong")
        assert "furlong" in str(exc.value)
        assert fake.set_calls == [], "a rejected unit must not touch the scene"

    def test_none_leaves_the_scene_alone_and_reports_what_it_found(self):
        fake = FakeCmds("m")
        block = units.set_linear_unit(fake, None)
        assert fake.set_calls == []
        assert block["linear_unit"] == "m"


class TestRequireKnownUnit:
    """Validation split out so a caller can check BEFORE doing damage.

    new_scene needs exactly this: it destroys the scene, so a bad
    `linear_unit` has to be rejected before the destructive call, not by
    set_linear_unit afterwards.
    """

    def test_a_known_unit_passes(self):
        assert units.require_known_unit("cm") is None

    def test_none_passes_meaning_leave_it_alone(self):
        assert units.require_known_unit(None) is None

    def test_an_unknown_unit_raises_with_the_valid_list(self):
        with pytest.raises(units.HandlerError) as exc:
            units.require_known_unit("furlong")
        assert "furlong" in str(exc.value)
        assert "cm" in exc.value.hint
