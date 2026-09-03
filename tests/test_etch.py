"""#797 row 28: etch_text's `or DEFAULT` idiom silently ate three params.

`str(params.get("font") or DEFAULT_FONT)` reads an empty string as "Arial",
and `float(params.get("width") or DEFAULT_WIDTH)` reads a literal 0 as 0.6.
Every one of those is a value the caller PASSED and the handler dropped -
`font=""` is the MCP-reachable one, and it carved in a font nobody asked
for and said nothing.

tests/test_etch_math.py holds the pure placement math. This file is the
param half, and it runs with no Maya at all: the validation must fire
before `_cmds()`, because everything after it - the Type-node glyph, the
auto-checkpoint, the boolean - is work that has to be undone if a param was
wrong.
"""

import pytest

from maya_plugin.dispatcher import HandlerError
from maya_plugin.handlers import etch


def _no_maya(monkeypatch):
    """_cmds() must never be reached: etch_text auto-checkpoints and builds a
    Type network, so a refusal after it is a refusal after the cost."""

    def boom():
        raise AssertionError("_cmds() was reached - the refusal ran too late")

    monkeypatch.setattr(etch, "_cmds", boom)


def _call(monkeypatch, **over):
    _no_maya(monkeypatch)
    params = {"mesh": "|box", "text": "A", "face": 0}
    params.update(over)
    return etch.etch_text(params)


class TestEmptyFontIsRefused:
    def test_empty_font_refused_as_inert(self, monkeypatch):
        with pytest.raises(HandlerError) as exc:
            _call(monkeypatch, font="")
        message = str(exc.value)
        assert "does not use" in message
        assert "font" in message
        assert "empty" in message
        assert "Arial" in message

    def test_whitespace_font_refused_too(self, monkeypatch):
        # " " is not empty by `or`, so it slipped past the old idiom and
        # reached the Type node, which then fell back to its own default.
        with pytest.raises(HandlerError) as exc:
            _call(monkeypatch, font="   ")
        assert "font" in str(exc.value)

    def test_named_font_is_kept(self, monkeypatch):
        # The branch that is NOT refused: a real font name gets past every
        # pure check and only then asks for Maya.
        with pytest.raises(AssertionError, match="_cmds"):
            _call(monkeypatch, font="Times New Roman")

    def test_font_unset_still_defaults(self, monkeypatch):
        # None means "not passed" - the MCP wrapper sends every declared
        # param on every call - so the default still applies.
        with pytest.raises(AssertionError, match="_cmds"):
            _call(monkeypatch, font=None)


class TestZeroSizesAreRefused:
    @pytest.mark.parametrize("key", ["width", "depth"])
    def test_zero_is_refused_not_defaulted(self, monkeypatch, key):
        # `float(params.get("width") or DEFAULT_WIDTH)` turned a literal 0
        # into 0.6 - the caller asked for nothing and got the default carve.
        with pytest.raises(HandlerError) as exc:
            _call(monkeypatch, **{key: 0})
        assert key in str(exc.value)

    @pytest.mark.parametrize("key", ["width", "depth"])
    def test_negative_is_refused(self, monkeypatch, key):
        with pytest.raises(HandlerError) as exc:
            _call(monkeypatch, **{key: -1.0})
        assert key in str(exc.value)

    @pytest.mark.parametrize("key", ["width", "depth"])
    def test_non_numeric_is_refused_as_a_handler_error(self, monkeypatch, key):
        # `float("wide")` raised a bare ValueError through the MCP boundary
        # instead of a HandlerError with a hint.
        with pytest.raises(HandlerError) as exc:
            _call(monkeypatch, **{key: "wide"})
        assert key in str(exc.value)

    @pytest.mark.parametrize("key", ["width", "depth"])
    def test_a_boolean_is_not_a_size(self, monkeypatch, key):
        # bool is a subclass of int, so True would otherwise pass as 1.0.
        with pytest.raises(HandlerError) as exc:
            _call(monkeypatch, **{key: True})
        assert key in str(exc.value)

    @pytest.mark.parametrize("key", ["width", "depth"])
    def test_unset_still_defaults(self, monkeypatch, key):
        with pytest.raises(AssertionError, match="_cmds"):
            _call(monkeypatch, **{key: None})

    def test_a_real_size_is_kept(self, monkeypatch):
        with pytest.raises(AssertionError, match="_cmds"):
            _call(monkeypatch, width=1.2, depth=0.25)


class TestRotateDegIsValidatedToo:
    """Review fix round 1: `float(params.get("rotate_deg") or 0.0)` was the
    last survivor of the idiom row 28 removed from font/width/depth. Its
    `or` is harmless (0 IS the default) but its `float()` is not: a string
    raised a bare ValueError across the MCP boundary."""

    def test_non_numeric_is_refused_as_a_handler_error(self, monkeypatch):
        with pytest.raises(HandlerError) as exc:
            _call(monkeypatch, rotate_deg="spin")
        assert "rotate_deg" in str(exc.value)

    def test_a_boolean_is_not_an_angle(self, monkeypatch):
        # bool is a subclass of int, so True would otherwise be 1 degree.
        with pytest.raises(HandlerError) as exc:
            _call(monkeypatch, rotate_deg=True)
        assert "rotate_deg" in str(exc.value)

    @pytest.mark.parametrize("value", [0, 180, -90, 12.5])
    def test_every_real_angle_is_kept(self, monkeypatch, value):
        # 0 and negatives are both meaningful here, unlike width/depth.
        with pytest.raises(AssertionError, match="_cmds"):
            _call(monkeypatch, rotate_deg=value)

    def test_unset_still_defaults(self, monkeypatch):
        with pytest.raises(AssertionError, match="_cmds"):
            _call(monkeypatch, rotate_deg=None)


class TestPureValidationRunsBeforeMaya:
    """#767's proof shape: every check that needs no scene runs before the
    handler asks for one, so a bad call never reaches the auto-checkpoint."""

    def test_missing_text_refused_before_maya(self, monkeypatch):
        _no_maya(monkeypatch)
        with pytest.raises(HandlerError) as exc:
            etch.etch_text({"mesh": "|box", "face": 0})
        assert "text" in str(exc.value)

    def test_missing_face_refused_before_maya(self, monkeypatch):
        _no_maya(monkeypatch)
        with pytest.raises(HandlerError) as exc:
            etch.etch_text({"mesh": "|box", "text": "A"})
        assert "face" in str(exc.value)

    def test_unknown_key_still_refused_first(self, monkeypatch):
        _no_maya(monkeypatch)
        with pytest.raises(HandlerError) as exc:
            etch.etch_text({"mesh": "|box", "text": "A", "face": 0, "bogus": 1})
        assert "bogus" in str(exc.value) or "bogus" in (exc.value.hint or "")
