"""Tests for trellis.formula.functions — the function registry."""

import pytest

from trellis import Sheet
from trellis.formula import (
    DIV0, NAME, VALUE, FormulaError, evaluate, parse_formula,
)
from trellis.formula.ast import Number
from trellis.formula.evaluator import Context
from trellis.formula.functions import (
    _REGISTRY,
    get_function,
    register_function,
    registered_function_names,
    unregister_function,
)


@pytest.fixture(autouse=True)
def isolate_registry():
    """Snapshot the registry before each test and restore after — so test-
    local registrations don't bleed across tests, and built-ins (when they
    land in #22/#23) survive intact."""
    saved = dict(_REGISTRY)
    try:
        yield
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(saved)


def evalstr(src, sheet=None):
    if sheet is None:
        sheet = Sheet("Test")
    return evaluate(parse_formula(src), Context(sheet=sheet))


# --- Registration & lookup ---------------------------------------


def test_register_and_lookup():
    @register_function("MYFUN")
    def _fn(ctx):
        return 42

    entry = get_function("MYFUN")
    assert entry is not None
    fn, lazy = entry
    assert fn is _fn
    assert lazy is False


def test_register_uppercases_name():
    @register_function("mylower")
    def _fn(ctx):
        return 1

    assert get_function("MYLOWER") is not None
    assert get_function("mylower") is not None
    assert get_function("MyLower") is not None


def test_get_function_returns_none_for_unknown():
    assert get_function("DOES_NOT_EXIST") is None


def test_register_with_lazy_flag():
    @register_function("LAZY_FN", lazy=True)
    def _fn(ctx, *args):
        return None

    fn, lazy = get_function("LAZY_FN")
    assert lazy is True


def test_re_registration_replaces():
    @register_function("REPL")
    def _v1(ctx):
        return 1

    @register_function("REPL")
    def _v2(ctx):
        return 2

    fn, _ = get_function("REPL")
    assert fn is _v2
    assert fn(None) == 2


def test_registered_function_names_is_sorted():
    @register_function("Z_FN")
    def _z(ctx):
        return 1

    @register_function("A_FN")
    def _a(ctx):
        return 1

    names = registered_function_names()
    assert "A_FN" in names
    assert "Z_FN" in names
    assert names == sorted(names)


def test_unregister_function_returns_true_when_present():
    @register_function("DROPME")
    def _fn(ctx):
        return 1

    assert unregister_function("DROPME") is True
    assert get_function("DROPME") is None


def test_unregister_function_returns_false_when_absent():
    assert unregister_function("NEVER_EXISTED") is False


def test_unregister_is_case_insensitive():
    @register_function("MIXED")
    def _fn(ctx):
        return 1

    assert unregister_function("mixed") is True


def test_register_returns_the_function():
    """The decorator returns the original function (so chained decorators work)."""
    def _raw(ctx):
        return 1

    decorated = register_function("RAW")(_raw)
    assert decorated is _raw


# --- Evaluator integration: eager functions ----------------------


def test_calling_registered_eager_function():
    @register_function("DOUBLE")
    def _double(ctx, x):
        return x * 2

    assert evalstr("DOUBLE(21)") == 42


def test_eager_function_receives_evaluated_args():
    captured = []

    @register_function("CAPTURE")
    def _capture(ctx, *args):
        captured.extend(args)
        return None

    evalstr("CAPTURE(1+2, 3*4, A1)", Sheet())
    # 1+2 = 3, 3*4 = 12, A1 (empty) = None
    assert captured == [3, 12, None]


def test_eager_function_arg_error_short_circuits():
    """If any arg evaluates to a FormulaError, the function isn't called."""
    called = []

    @register_function("NOOP")
    def _noop(ctx, *args):
        called.append(True)
        return "ok"

    result = evalstr("NOOP(1/0)")
    assert result == DIV0
    assert called == []


def test_eager_function_with_no_args():
    @register_function("MAGIC")
    def _magic(ctx):
        return 42

    assert evalstr("MAGIC()") == 42


def test_eager_function_with_multiple_args():
    @register_function("ADD3")
    def _add3(ctx, a, b, c):
        return a + b + c

    assert evalstr("ADD3(1, 2, 3)") == 6


def test_eager_function_with_range_arg():
    """Range args arrive as a list of values."""
    captured = []

    @register_function("TAKE_RANGE")
    def _take(ctx, x):
        captured.append(x)
        return len(x) if isinstance(x, list) else None

    s = Sheet()
    s["A1"] = 10
    s["A2"] = 20
    s["A3"] = 30
    result = evalstr("TAKE_RANGE(A1:A3)", s)
    assert captured == [[10, 20, 30]]
    assert result == 3


def test_eager_function_can_return_formulaerror():
    @register_function("MAYBE_BROKEN")
    def _mb(ctx, x):
        if x < 0:
            return VALUE
        return x * 2

    assert evalstr("MAYBE_BROKEN(5)") == 10
    assert evalstr("MAYBE_BROKEN(-1)") == VALUE


def test_eager_function_receives_context_as_first_arg():
    captured_ctx = []

    @register_function("GIMME_CTX")
    def _fn(ctx):
        captured_ctx.append(ctx)
        return None

    s = Sheet("MySheet")
    evalstr("GIMME_CTX()", s)
    assert len(captured_ctx) == 1
    assert captured_ctx[0].sheet is s


# --- Evaluator integration: lazy functions -----------------------


def test_lazy_function_receives_ast_nodes():
    """Lazy functions get raw AST nodes, not evaluated values."""
    captured = []

    @register_function("CAPTURE_NODES", lazy=True)
    def _capture(ctx, *args):
        captured.extend(args)
        return None

    evalstr("CAPTURE_NODES(1, 2, 3)")
    assert captured == [Number(1), Number(2), Number(3)]


def test_lazy_function_uses_ctx_evaluate():
    """Lazy function evaluates AST nodes selectively via ctx.evaluate()."""
    @register_function("FIRST", lazy=True)
    def _first(ctx, a, b):
        return ctx.evaluate(a)  # never touches b

    assert evalstr("FIRST(10, 20)") == 10


def test_lazy_does_not_evaluate_unselected_arg():
    """The IF-style semantics: the unselected branch is not evaluated.

    If lazy were broken, the second arg (1/0) would raise DIV0 before the
    function got to choose. We verify the function returns the first arg
    unscathed."""
    @register_function("FAKE_IF", lazy=True)
    def _fake_if(ctx, cond, then_branch, else_branch):
        if ctx.evaluate(cond):
            return ctx.evaluate(then_branch)
        return ctx.evaluate(else_branch)

    assert evalstr("FAKE_IF(TRUE, 42, 1/0)") == 42
    assert evalstr("FAKE_IF(FALSE, 1/0, 42)") == 42


def test_lazy_function_does_not_short_circuit_on_error_arg():
    """A lazy function is called even if an arg WOULD evaluate to an error
    — the function can choose to catch the error (IFERROR-style)."""
    @register_function("CATCHER", lazy=True)
    def _catcher(ctx, broken, fallback):
        result = ctx.evaluate(broken)
        if isinstance(result, FormulaError):
            return ctx.evaluate(fallback)
        return result

    assert evalstr("CATCHER(1/0, 99)") == 99


# --- Unknown function dispatch ----------------------------------


def test_unknown_function_returns_name():
    assert evalstr("NONESUCH()") == NAME


def test_unknown_function_includes_name_in_message():
    result = evalstr("NONESUCH()")
    assert isinstance(result, FormulaError)
    assert "NONESUCH" in result.message


def test_unknown_function_args_not_evaluated():
    """When the function name is unknown, args are NOT evaluated. The
    registry lookup happens first; if it fails, args are skipped."""
    # If args were evaluated, 1/0 would give DIV0 not NAME.
    assert evalstr("NONESUCH(1/0)") == NAME


# --- Case insensitivity at call site ----------------------------


def test_case_insensitive_call():
    @register_function("MIXED_CASE_FN")
    def _fn(ctx):
        return "ok"

    assert evalstr("mixed_case_fn()") == "ok"
    assert evalstr("Mixed_Case_FN()") == "ok"
    assert evalstr("MIXED_CASE_FN()") == "ok"
