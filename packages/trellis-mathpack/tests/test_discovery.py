"""Discovery / entry-point wiring tests for trellis-mathpack.

Two tiers exist for this package:

* **Tier 1 (here): hermetic.** mathpack is NOT installed; we feed a fake entry
  point to ``trellis.load_plugins([...])`` — the same duck-typed
  ``FakeEntryPoint`` pattern core uses in ``tests/test_plugin_discovery.py`` —
  and confirm the wiring registers every function. No install, fast, runs in
  the normal suite. Run with PYTHONPATH=../../src:src python -m pytest tests/.
* **Tier 2 (the real gate, NOT here): editable install.** ``pip install -e``
  the package into a clean venv, then a fresh interpreter does only
  ``import trellis`` and confirms ``=COSH(0)`` already works — proving
  auto-discovery at import time. That is Part 4 #7, scripted separately
  (it needs an off-mount venv).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pytest

from trellis import Sheet, load_plugins
from trellis.formula import Context, evaluate, parse_formula
from trellis.formula.functions import _REGISTRY

import trellis_mathpack


@dataclass
class FakeEntryPoint:
    """Duck-types ``importlib.metadata.EntryPoint`` — only ``.name`` + ``.load()``."""
    name: str
    setup: Callable[[], None]

    def load(self) -> Callable[[], None]:
        return self.setup


@pytest.fixture(autouse=True)
def isolate_registry():
    """Snapshot/restore the function registry so registrations don't leak."""
    saved = dict(_REGISTRY)
    try:
        yield
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(saved)


def _names():
    from trellis.formula import registered_function_names
    return set(registered_function_names())


# --- The package exposes the right surface -----------------------------

def test_setup_is_a_no_arg_callable():
    assert callable(trellis_mathpack.setup)


def test_functions_listing_matches_what_setup_registers():
    before = _names()
    trellis_mathpack.setup()
    added = _names() - before
    assert added == set(trellis_mathpack.FUNCTIONS)
    assert len(trellis_mathpack.FUNCTIONS) == 20


def test_version_is_declared():
    assert trellis_mathpack.__version__ == "0.1.0"


# --- The entry-point contract ------------------------------------------

def test_import_alone_registers_nothing():
    # Importing the module must NOT register functions — that only happens when
    # setup() runs. The Tier-2 auto-discovery proof depends on this being true.
    assert set(trellis_mathpack.FUNCTIONS).isdisjoint(_names())


def test_load_plugins_discovers_mathpack_via_fake_entry_point():
    # Exactly what `import trellis` does, but with our entry point injected
    # instead of scanning installed metadata.
    loaded = load_plugins([FakeEntryPoint("mathpack", trellis_mathpack.setup)])
    assert loaded == ["mathpack"]
    # And every function is now live through the parser -> evaluator stack.
    assert set(trellis_mathpack.FUNCTIONS) <= _names()
    out = evaluate(parse_formula("COSH(0)"), Context(sheet=Sheet("T")))
    assert out == 1.0


def test_a_broken_sibling_plugin_does_not_stop_mathpack():
    # load_plugins warns-and-skips a failing plugin; mathpack still loads.
    def boom():
        raise RuntimeError("nope")

    with pytest.warns(RuntimeWarning):
        loaded = load_plugins([
            FakeEntryPoint("broken", boom),
            FakeEntryPoint("mathpack", trellis_mathpack.setup),
        ])
    assert loaded == ["mathpack"]
    assert "COSH" in _names()
