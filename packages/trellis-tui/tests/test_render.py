"""Scaffold tests for the display policy (real suite lands with #3)."""

from __future__ import annotations

import pytest

from trellis_tui import render


def test_display_is_a_placeholder_until_part5_3():
    with pytest.raises(NotImplementedError):
        render.display(42)
