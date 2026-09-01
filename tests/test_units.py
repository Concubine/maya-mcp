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
    """The scene's linear unit, and nothing else.

    #799. Points 1 and 2 do not apply - units.py names no node, so there is
    nothing here to vanish and no plug to write. Point 3 does: `currentUnit`
    answers what it was ASKED for rather than one stored string whatever the
    flags say, and refuses a unit Maya does not know instead of storing it.
    """

    _KNOWN = ("mm", "cm", "m", "km", "in", "ft", "yd", "mi")

    def __init__(self, linear="cm"):
        self.linear = linear
        self.set_calls = []

    def currentUnit(self, query=False, linear=None, angle=None, time=None):
        if query:
            # Maya answers ONE unit per query, whichever flag was raised.
            # Answering the linear unit to an angle query is how a fake
            # certifies a conversion that would silently be wrong.
            if angle or time:
                raise AssertionError(
                    "units_block must ask for the linear unit, not %s"
                    % ("angle" if angle else "time")
                )
            assert linear is True, "query must ask for the linear unit"
            return self.linear
        # `currentUnit -linear furlong` is an error in Maya, not a stored
        # string: require_known_unit is what keeps the call from getting
        # here, so the fake has to be able to notice if it ever stopped.
        if linear not in self._KNOWN:
            raise RuntimeError("Invalid unit name: %s" % (linear,))
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


class FakeAngleCmds:
    """The scene's ANGLE unit.

    #799 contract point 3: this used to return its one string for every
    question asked of it - a linear query, a time query, even a set - so a
    handler that asked for the wrong unit got a plausible answer back and no
    test could see it. It answers the angle query and refuses the rest.
    """

    def __init__(self, unit):
        self._unit = unit

    def currentUnit(self, query=False, angle=False, linear=None, time=None):
        if not query:
            raise AssertionError("degrees_to_ui/ui_to_degrees must only query")
        if not angle:
            raise AssertionError(
                "the angle conversion must ask for the ANGLE unit, not %s"
                % ("linear" if linear else "time")
            )
        return self._unit


class TestAngleUnits:
    def test_degrees_pass_through_a_degree_scene(self):
        assert units.degrees_to_ui(FakeAngleCmds("deg"), 90.0) == 90.0
        assert units.ui_to_degrees(FakeAngleCmds("deg"), 90.0) == 90.0

    def test_a_radian_scene_gets_radians(self):
        import math
        assert units.degrees_to_ui(FakeAngleCmds("rad"), 180.0) == pytest.approx(math.pi)
        assert units.ui_to_degrees(FakeAngleCmds("rad"), math.pi) == pytest.approx(180.0)

    def test_the_two_directions_round_trip(self):
        cmds = FakeAngleCmds("min")
        assert units.ui_to_degrees(cmds, units.degrees_to_ui(cmds, 33.3)) == pytest.approx(33.3)

    def test_an_unknown_angle_unit_is_refused_not_guessed(self):
        from maya_plugin.dispatcher import HandlerError
        with pytest.raises(HandlerError, match="angle unit"):
            units.degrees_to_ui(FakeAngleCmds("grad"), 1.0)


class TestTheFakeRefusesWhatMayaRefuses:
    """#799 round 2: the hardening in the two fakes above has to be ASSERTED.

    Both fakes used to answer their one stored string to whatever they were
    asked, so a handler reading the wrong unit - a conversion silently wrong
    by a factor of 57.3, or by 100 - looked exactly like a correct one. If
    someone loosens either fake back, these go red. Points 1 and 2 of the
    contract have nothing to pin here: units.py names no node and writes no
    plug, so there is no vanished name and no connected attribute to refuse.
    """

    def test_the_linear_fake_answers_only_the_linear_query(self):
        fake = FakeCmds("cm")
        assert fake.currentUnit(query=True, linear=True) == "cm"
        with pytest.raises(AssertionError, match="angle"):
            fake.currentUnit(query=True, angle=True)
        with pytest.raises(AssertionError, match="time"):
            fake.currentUnit(query=True, time=True)
        with pytest.raises(AssertionError):
            fake.currentUnit(query=True)  # no flag names no unit

    def test_the_linear_fake_refuses_a_unit_maya_does_not_know(self):
        fake = FakeCmds("cm")
        with pytest.raises(RuntimeError, match="Invalid unit name"):
            fake.currentUnit(linear="furlong")
        assert fake.set_calls == []
        assert fake.linear == "cm"

    def test_the_angle_fake_answers_only_the_angle_query(self):
        fake = FakeAngleCmds("deg")
        assert fake.currentUnit(query=True, angle=True) == "deg"
        with pytest.raises(AssertionError, match="linear"):
            fake.currentUnit(query=True, linear=True)
        with pytest.raises(AssertionError, match="time"):
            fake.currentUnit(query=True, time=True)
        with pytest.raises(AssertionError, match="only query"):
            fake.currentUnit(angle="rad")
