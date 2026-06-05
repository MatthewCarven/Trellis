"""Tier 1 — hermetic unit tests for trellis-mathpack.

Run without installing: PYTHONPATH=../../src:src python -m pytest tests/

These call ``trellis_mathpack.setup()`` directly (or feed a FakeEntryPoint to
``trellis.load_plugins([...])``) and then parse+evaluate formulas, checking
both happy paths and the error paths (#NUM!, #VALUE!, #DIV/0!).

SCAFFOLD (Part 4 #2): placeholder. Per-function tests land with the
implementations in Part 4 #3-#5 (#6 is the full Tier-1 pass).
"""


def test_scaffold_placeholder():
    """Package imports and setup() is callable. Replaced by real tests in #3+."""
    import trellis_mathpack

    assert callable(trellis_mathpack.setup)
    assert trellis_mathpack.setup() is None
