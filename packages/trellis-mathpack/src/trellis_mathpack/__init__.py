"""trellis-mathpack — a reference math-function plugin for Trellis.

This package adds ~20 math functions (trig, hyperbolic, powers/logs, a few
misc helpers, and range statistics) to the Trellis formula engine. It exists
for two reasons:

1. **It is the publication-gate consumer.** It exercises Trellis's public
   extension surface end-to-end — ``register_function``, the
   ``fn(ctx, *args)`` calling convention, ``FormulaError`` as a value you
   *construct*, and ``entry_points`` auto-discovery — proving the API works
   from outside the core distribution.
2. **It is the reference plugin.** A maintained example to copy when writing
   your own Trellis plugin package.

How discovery works
-------------------
``pyproject.toml`` declares an entry point::

    [project.entry-points."trellis.plugins"]
    mathpack = "trellis_mathpack:setup"

When ``import trellis`` runs, Trellis scans the ``trellis.plugins`` group and
calls :func:`setup` once, with no arguments. ``setup`` registers every
mathpack function. Nothing else is needed — no manual wiring at the call site.

Design notes
-----------
* **Public surface only.** Everything here goes through ``from trellis import
  ...``. If mathpack ever needs a core internal, that's a gap in the core's
  public surface to fix in core.
* **Minting a custom error.** Trellis core has no ``#NUM!``. mathpack defines
  its own :data:`NUM` for domain errors (``SQRT(-1)``, ``LN(0)``,
  ``ASIN(2)``). This is the package's headline demonstration that errors are
  ordinary values you construct, not a closed core enum.
* **No built-in overrides.** Every function name here is new; mathpack never
  shadows a core built-in.

SCAFFOLD STATUS (Part 4 #2): structure only. The function registrations,
the ``NUM`` constant, and the ``_num`` / ``_collect_numerics`` helpers land in
Part 4 #3-#5. ``setup()`` is intentionally a no-op placeholder for now.
"""

from __future__ import annotations

__version__ = "0.1.0"
__all__ = ["setup"]


def setup() -> None:
    """Register all mathpack functions with the Trellis formula engine.

    Called automatically once at ``import trellis`` time via the
    ``trellis.plugins`` entry point. Safe to call again manually (each call
    re-registers the same names).

    SCAFFOLD: no functions registered yet — implementations land in Part 4
    #3 (scalar fns), #4 (range stats), and #5 (this wiring).
    """
    # TODO(#3-#5): register trig / hyperbolic / powers-logs / misc / stats.
    return None
