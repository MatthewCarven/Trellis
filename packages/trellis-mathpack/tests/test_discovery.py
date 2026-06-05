"""Tier 2 — entry_points / setup() discovery integration for trellis-mathpack.

The real gate proof: after ``pip install -e packages/trellis-mathpack`` in a
clean venv, a fresh interpreter does only ``import trellis`` and confirms a
mathpack formula (e.g. ``=COSH(0)`` -> 1.0) already works — proving
``load_plugins()`` auto-found the entry point at import time with no manual
``setup()`` call.

SCAFFOLD (Part 4 #2): placeholder. The scripted install + fresh-interpreter
check is written in Part 4 #7.
"""


def test_discovery_placeholder():
    """Entry point is declared in pyproject; real discovery test lands in #7."""
    import trellis_mathpack

    assert trellis_mathpack.__version__ == "0.1.0"
