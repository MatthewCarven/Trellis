"""Tests for entry_points-based plugin auto-discovery (task #5).

The contract: at ``import trellis`` time, Trellis scans the
``trellis.plugins`` entry-point group and invokes each registered
callable with no arguments. A broken plugin warns and is skipped;
others still load. ``TRELLIS_DISABLE_PLUGIN_DISCOVERY`` disables the
scan entirely.

These tests inject duck-typed entry points rather than installing real
fixture packages — that keeps the test suite hermetic and fast.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable
from unittest import mock

import pytest

import trellis
from trellis import (
    VALUE,
    Workbook,
    get_function,
    load_plugins,
    register_function,
    unregister_function,
)
from trellis._plugins import ENTRY_POINT_GROUP, ENV_DISABLE
from trellis.formula.functions import _REGISTRY


# --- Fixtures ----------------------------------------------------------


@dataclass
class FakeEntryPoint:
    """Duck-types ``importlib.metadata.EntryPoint`` for hermetic testing.

    The real type only requires ``.name`` and ``.load()`` on the surface
    Trellis uses, so a plain dataclass suffices.
    """
    name: str
    setup: Callable[[], None]

    def load(self) -> Callable[[], None]:
        return self.setup


@pytest.fixture(autouse=True)
def isolate_registry():
    """Snapshot/restore the function registry so plugin registrations don't leak."""
    saved = dict(_REGISTRY)
    try:
        yield
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(saved)


@pytest.fixture(autouse=True)
def clear_disable_env(monkeypatch):
    """Ensure each test starts with the disable env var unset."""
    monkeypatch.delenv(ENV_DISABLE, raising=False)


# --- Public API ---------------------------------------------------------


def test_load_plugins_is_re_exported_from_trellis():
    assert hasattr(trellis, "load_plugins")
    assert "load_plugins" in trellis.__all__


def test_entry_point_group_constant_matches_pyproject():
    # The pyproject's [project.entry-points."trellis.plugins"] section is
    # the single source of truth; this constant must match.
    assert ENTRY_POINT_GROUP == "trellis.plugins"


# --- Happy path ---------------------------------------------------------


def test_load_plugins_invokes_each_entry_point_with_no_args():
    called: list[str] = []

    def plugin_a():
        called.append("a")

    def plugin_b():
        called.append("b")

    loaded = load_plugins([
        FakeEntryPoint("a", plugin_a),
        FakeEntryPoint("b", plugin_b),
    ])

    assert called == ["a", "b"]
    assert loaded == ["a", "b"]


def test_load_plugins_returns_empty_for_empty_input():
    assert load_plugins([]) == []


def test_load_plugins_default_scan_runs_without_error():
    # The actual entry_points scan in a clean test env returns no
    # ``trellis.plugins`` entries. We mainly want to confirm it doesn't
    # crash on the importlib.metadata import path.
    result = load_plugins()
    assert isinstance(result, list)


def test_plugin_can_register_a_formula_function():
    def plugin():
        @register_function("MYFN")
        def _myfn(ctx, x):
            return x + 1

    loaded = load_plugins([FakeEntryPoint("p", plugin)])

    assert loaded == ["p"]
    assert get_function("MYFN") is not None


def test_plugin_registered_function_is_callable_from_a_formula():
    """End-to-end: plugin registers a function, then a formula uses it."""

    def plugin():
        @register_function("PLUGIN_DOUBLE")
        def _double(ctx, x):
            if isinstance(x, bool) or not isinstance(x, (int, float)):
                return VALUE
            return x * 2

    load_plugins([FakeEntryPoint("doubler", plugin)])

    wb = Workbook()
    sh = wb.add_sheet("S")
    sh["A1"] = 21
    sh["B1"] = "=PLUGIN_DOUBLE(A1)"
    assert sh["B1"].value == 42


# --- Failure handling --------------------------------------------------


def test_broken_plugin_warns_and_others_still_load():
    other_called: list[str] = []

    def broken():
        raise RuntimeError("kaboom")

    def working():
        other_called.append("ok")

    with pytest.warns(RuntimeWarning, match="broken"):
        loaded = load_plugins([
            FakeEntryPoint("broken", broken),
            FakeEntryPoint("working", working),
        ])

    assert loaded == ["working"]
    assert other_called == ["ok"]


def test_broken_plugin_warning_includes_exception_type_and_message():
    def broken():
        raise ValueError("bad config")

    with pytest.warns(RuntimeWarning, match="ValueError.*bad config"):
        load_plugins([FakeEntryPoint("badplug", broken)])


def test_broken_plugin_warning_includes_plugin_name():
    def broken():
        raise RuntimeError("nope")

    with pytest.warns(RuntimeWarning, match="badplug"):
        load_plugins([FakeEntryPoint("badplug", broken)])


def test_load_failure_during_ep_load_is_caught():
    """If ep.load() itself raises (e.g. ModuleNotFoundError), we warn and skip."""

    class ImportFailingEntryPoint:
        name = "ghost"

        def load(self):
            raise ModuleNotFoundError("trellis_ghost")

    with pytest.warns(RuntimeWarning, match="ghost"):
        loaded = load_plugins([ImportFailingEntryPoint()])

    assert loaded == []


def test_multiple_broken_plugins_each_get_their_own_warning():
    def b1():
        raise RuntimeError("first")

    def b2():
        raise RuntimeError("second")

    with pytest.warns(RuntimeWarning) as record:
        load_plugins([
            FakeEntryPoint("p1", b1),
            FakeEntryPoint("p2", b2),
        ])

    messages = [str(w.message) for w in record]
    assert any("p1" in m and "first" in m for m in messages)
    assert any("p2" in m and "second" in m for m in messages)


# --- Kill switch -------------------------------------------------------


def test_env_var_disables_discovery(monkeypatch):
    called: list[str] = []

    def plugin():
        called.append("ran")

    monkeypatch.setenv(ENV_DISABLE, "1")
    loaded = load_plugins([FakeEntryPoint("p", plugin)])

    assert loaded == []
    assert called == []


def test_env_var_any_non_empty_value_disables(monkeypatch):
    called: list[str] = []

    def plugin():
        called.append("ran")

    # Truthiness is "non-empty string", not "value is '1'".
    monkeypatch.setenv(ENV_DISABLE, "yes please")
    load_plugins([FakeEntryPoint("p", plugin)])
    assert called == []


def test_env_var_empty_string_does_not_disable(monkeypatch):
    called: list[str] = []

    def plugin():
        called.append("ran")

    monkeypatch.setenv(ENV_DISABLE, "")
    load_plugins([FakeEntryPoint("p", plugin)])
    assert called == ["ran"]


def test_env_var_disables_real_scan_too(monkeypatch):
    monkeypatch.setenv(ENV_DISABLE, "1")
    # No entry_points arg -> defaults to real scan; should still return [].
    assert load_plugins() == []


# --- Auto-discovery at package import ---------------------------------


def test_init_calls_load_plugins_at_import(monkeypatch):
    """Smoke test: re-importing trellis triggers load_plugins().

    We can't easily re-run ``trellis/__init__.py`` in-process, so instead
    we patch importlib.metadata.entry_points and confirm a manual
    ``load_plugins()`` call hits it the same way the import-time call does.
    """
    sentinel: list[str] = []

    def plugin():
        sentinel.append("via-metadata")

    fake_ep = FakeEntryPoint("via_metadata", plugin)
    with mock.patch("importlib.metadata.entry_points") as ep_mock:
        ep_mock.return_value = [fake_ep]
        load_plugins()  # no arg -> takes the importlib.metadata path

    assert sentinel == ["via-metadata"]
    ep_mock.assert_called_once_with(group=ENTRY_POINT_GROUP)
