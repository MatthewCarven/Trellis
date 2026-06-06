"""Smoke test for the public ``trellis`` package surface.

These tests deliberately import EVERYTHING from ``trellis`` directly,
no reaching into ``trellis.formula`` or ``trellis.core``. They lock in
the top-level re-exports: if someone removes a name from
``trellis/__init__.py`` by accident, these tests fail loud.

Coverage targets the surface a casual user would touch: the
README's "Quick taste" pattern, the "Extending §3" decorator pattern,
and the AST/error-value plumbing exposed for advanced users.
"""

from __future__ import annotations

import pytest

import trellis
from trellis import (
    CIRC,
    Cell,
    Context,
    DIV0,
    Emitter,
    FormulaError,
    NA,
    NAME,
    NULL,
    ParseError,
    REF,
    Range,
    RecalcEngine,
    Sheet,
    Subscription,
    VALUE,
    Workbook,
    evaluate,
    get_function,
    parse_address,
    parse_formula,
    register_function,
    registered_function_names,
    to_a1,
    unregister_function,
)
from trellis.formula.functions import _REGISTRY


@pytest.fixture(autouse=True)
def isolate_registry():
    """Snapshot the function registry so a test's register_function
    decorations don't leak into other tests."""
    saved = dict(_REGISTRY)
    try:
        yield
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(saved)


# --- The names exist and resolve to the right things -------------------


def test_all_promised_names_are_exported():
    expected = {
        # Core
        "Cell", "Emitter", "Range", "Sheet", "Subscription", "Workbook",
        "parse_address", "to_a1",
        # Formula engine
        "CIRC", "Context", "DIV0", "FormulaError", "NA", "NAME", "NULL",
        "ParseError", "REF", "RecalcEngine", "VALUE",
        "evaluate", "get_function", "parse_formula",
        "register_function", "registered_function_names",
        "unregister_function",
        # Plugin discovery
        "load_plugins",
        # File I/O
        "infer_value", "read_csv",
    }
    missing = expected - set(trellis.__all__)
    assert not missing, f"missing from __all__: {missing}"
    for name in expected:
        assert hasattr(trellis, name), f"trellis.{name} missing"


def test_version_string():
    assert isinstance(trellis.__version__, str)
    assert trellis.__version__  # non-empty


def test_infer_value_is_the_csv_loaders_rule():
    """Promoted in Part 5: frontends reuse the loader's inference rule
    so typed input behaves exactly like loaded data."""
    from trellis.io.csv import infer_value as canonical

    assert trellis.infer_value is canonical
    assert trellis.infer_value("42") == 42
    assert trellis.infer_value("01234") == "01234"  # leading zero stays text


# --- README "Quick taste" pattern --------------------------------------


def test_quick_taste_works_with_top_level_imports_only():
    wb = Workbook()
    sh = wb.add_sheet("Demo")
    sh["A1"] = 10
    sh["A2"] = 20
    sh["A3"] = 30
    sh["B1"] = "=SUM(A1:A3)"
    sh["B2"] = '=IF(B1 > 50, "big", "small")'

    assert sh["B1"].value == 60
    assert sh["B2"].value == "big"

    sh["A1"] = 100
    assert sh["B1"].value == 150
    assert sh["B2"].value == "big"


# --- Extending §3: register a custom function --------------------------


def test_register_function_decorator_works_via_top_level_import():
    @register_function("DOUBLE")
    def _double(ctx, *args):
        if len(args) != 1:
            return FormulaError("#N/A", "DOUBLE takes 1 arg")
        x = args[0]
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            return VALUE
        return x * 2

    wb = Workbook()
    sh = wb.add_sheet("D")
    sh["A1"] = 21
    sh["B1"] = "=DOUBLE(A1)"
    assert sh["B1"].value == 42


def test_get_function_lookup():
    @register_function("MYFN")
    def _fn(ctx):
        return "ok"

    entry = get_function("MYFN")
    assert entry is not None
    fn, lazy = entry
    assert fn is _fn
    assert lazy is False


def test_registered_function_names_includes_builtins():
    names = set(registered_function_names())
    # Sample a few from each batch
    for name in ("SUM", "IF", "IFERROR", "CONCAT", "ISNUMBER"):
        assert name in names


def test_unregister_function_round_trip():
    @register_function("TRANSIENT")
    def _fn(ctx):
        return 1

    assert get_function("TRANSIENT") is not None
    assert unregister_function("TRANSIENT") is True
    assert get_function("TRANSIENT") is None


# --- Parser + evaluator from the top level -----------------------------


def test_parse_formula_returns_ast():
    ast = parse_formula("=1+2")
    # We don't pin the exact AST shape here — it's tested elsewhere.
    # Just make sure something parseable comes back and re-evaluates correctly.
    assert ast is not None
    sh = Sheet()
    assert evaluate(ast, Context(sheet=sh)) == 3


def test_parse_error_is_an_exception():
    with pytest.raises(ParseError):
        parse_formula("=SUM(unclosed")


def test_error_constants_are_formula_errors():
    for err in (CIRC, DIV0, NA, NAME, NULL, REF, VALUE):
        assert isinstance(err, FormulaError)
    # And they all have distinct codes
    assert len({e.code for e in (CIRC, DIV0, NA, NAME, NULL, REF, VALUE)}) == 7


# --- RecalcEngine + Emitter + Subscription identities ------------------


def test_recalc_engine_re_exported_and_attached_to_workbook():
    wb = Workbook()
    assert isinstance(wb.recalc, RecalcEngine)


def test_emitter_and_subscription_re_exported_for_subclassing():
    class Bell(Emitter):
        pass

    b = Bell()
    sub = b.on("ring", lambda: None)
    assert isinstance(sub, Subscription)
    sub()  # unsubscribe via call (idempotent handle)


# --- Address helpers ---------------------------------------------------


def test_parse_address_and_to_a1_roundtrip():
    assert parse_address("B5") == (4, 1)
    assert to_a1(4, 1) == "B5"
