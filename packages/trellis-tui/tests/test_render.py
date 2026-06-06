"""Table-driven tests for the display policy (Part 5 #3).

The policy is pure (no textual), so these are plain unit tests — and the
CASES table IS the spec: if a rendering changes, change it here on
purpose, not by accident.
"""

from __future__ import annotations

import pytest

from trellis import CIRC, DIV0, NA, NAME, NULL, REF, VALUE, FormulaError
from trellis_tui.render import DisplayText, display

# (value, expected text, expected align, expected error-flag)
CASES = [
    # empties and strings
    pytest.param(None, "", "left", False, id="none-empty"),
    pytest.param("", "", "left", False, id="empty-string"),
    pytest.param("hello", "hello", "left", False, id="plain-string"),
    pytest.param("  padded ", "  padded ", "left", False, id="whitespace-kept"),
    pytest.param("=SUM(A1:A3)", "=SUM(A1:A3)", "left", False, id="literal-eq-string"),
    pytest.param("#DIV/0!", "#DIV/0!", "left", False, id="error-LOOKING-string-is-not-an-error"),
    pytest.param("01234", "01234", "left", False, id="leading-zero-string"),
    # booleans (before-int ordering!)
    pytest.param(True, "TRUE", "center", False, id="true"),
    pytest.param(False, "FALSE", "center", False, id="false"),
    # ints
    pytest.param(0, "0", "right", False, id="int-zero"),
    pytest.param(42, "42", "right", False, id="int"),
    pytest.param(-7, "-7", "right", False, id="int-negative"),
    pytest.param(10**20, "100000000000000000000", "right", False, id="int-huge-stays-exact"),
    # floats: the #3 rule
    pytest.param(3.14, "3.14", "right", False, id="float-plain"),
    pytest.param(-2.5, "-2.5", "right", False, id="float-negative"),
    pytest.param(0.1 + 0.2, "0.3", "right", False, id="float-noise-trimmed"),
    pytest.param(1 / 3, "0.333333333333333", "right", False, id="float-15-sig-digits"),
    pytest.param(4.0, "4", "right", False, id="float-integral-drops-point-zero"),
    pytest.param(-0.0, "0", "right", False, id="float-negative-zero"),
    pytest.param(2.0**53, "9007199254740992", "right", False, id="float-integral-exact-at-2^53"),
    pytest.param(1e16, "1e+16", "right", False, id="float-integral-past-limit-goes-sci"),
    pytest.param(1e20, "1e+20", "right", False, id="float-large-sci"),
    pytest.param(1.5e-10, "1.5e-10", "right", False, id="float-small-sci"),
    pytest.param(123456.789, "123456.789", "right", False, id="float-mixed"),
    pytest.param(float("nan"), "NaN", "right", False, id="float-nan-is-a-value-not-an-error"),
    pytest.param(float("inf"), "Infinity", "right", False, id="float-inf"),
    pytest.param(float("-inf"), "-Infinity", "right", False, id="float-neg-inf"),
    # errors are values — and render as their codes
    pytest.param(DIV0, "#DIV/0!", "center", True, id="error-div0"),
    pytest.param(VALUE, "#VALUE!", "center", True, id="error-value"),
    pytest.param(NA, "#N/A", "center", True, id="error-na"),
]


@pytest.mark.parametrize("value, text, align, error", CASES)
def test_display_table(value, text, align, error):
    got = display(value)
    assert (got.text, got.align, got.error) == (text, align, error)


def test_bool_is_checked_before_int():
    """bool subclasses int; a regression here would render True as '1'."""
    assert display(True).text == "TRUE"
    assert display(1).text == "1"
    assert display(True).align == "center"
    assert display(1).align == "right"


def test_every_core_error_constant_renders_its_code():
    for err in (CIRC, DIV0, NA, NAME, NULL, REF, VALUE):
        got = display(err)
        assert got == DisplayText(err.code, align="center", error=True)


def test_minted_errors_render_like_builtins():
    """Errors are values you construct (the mathpack lesson) — the
    renderer must not assume a closed set of codes."""
    num = FormulaError("#NUM!", "domain error")
    assert display(num) == DisplayText("#NUM!", align="center", error=True)


def test_unknown_objects_render_via_str_and_never_raise():
    class Odd:
        def __str__(self):
            return "<odd plugin payload>"

    got = display(Odd())
    assert got == DisplayText("<odd plugin payload>", align="left", error=False)


def test_display_text_is_frozen():
    with pytest.raises(Exception):
        display(1).text = "mutated"
