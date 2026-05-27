"""Plugin auto-discovery via ``entry_points``.

Trellis scans the ``trellis.plugins`` entry point group on package import
and invokes each registered callable with no arguments. A plugin's setup
function typically calls :func:`trellis.register_function` to add formula
functions, but is free to do anything — subscribe to events, register
custom Cell/Sheet subclasses, monkey-patch the world, whatever. The
design here is deliberately permissive (see the project's "open
extensibility / chaotic good" philosophy).

To expose a plugin from your own package, declare an entry point in your
``pyproject.toml``::

    [project.entry-points."trellis.plugins"]
    mathpack = "trellis_mathpack:setup"

where ``trellis_mathpack.setup`` is a no-argument callable. Trellis will
``ep.load()()`` it once, on import of ``trellis``.

Failure handling: a plugin that raises during load is reported via
:func:`warnings.warn` (category ``RuntimeWarning``) with the plugin name
and exception, and discovery moves on to the next plugin. One broken
third-party package can't take the engine down with it.

Kill switch: set ``TRELLIS_DISABLE_PLUGIN_DISCOVERY`` to any non-empty
value in the environment to skip the scan entirely. Useful for tests,
reproducible scripts, and "is this Trellis or a plugin?" debugging.
"""

from __future__ import annotations

import os
import warnings
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from importlib.metadata import EntryPoint


ENV_DISABLE = "TRELLIS_DISABLE_PLUGIN_DISCOVERY"
ENTRY_POINT_GROUP = "trellis.plugins"


def load_plugins(
    entry_points: Iterable["EntryPoint"] | None = None,
) -> list[str]:
    """Discover and load Trellis plugins. Return the names of those that loaded successfully.

    By default, scans the ``trellis.plugins`` entry point group from the
    running Python environment via :mod:`importlib.metadata`. Tests (and
    advanced callers who want to inject a custom set) can pass an explicit
    iterable of entry-point-like objects: anything with a ``.name``
    attribute and a ``.load()`` method that returns a no-arg callable.

    A plugin that raises during load is reported via
    :func:`warnings.warn` and skipped. Other plugins still load.

    Honours :data:`ENV_DISABLE`: if that environment variable is set to a
    non-empty value, the function returns ``[]`` without scanning.

    This is called once automatically at the bottom of ``trellis/__init__.py``.
    Re-invoking it manually is safe and useful for tests or for picking up
    plugins installed at runtime.
    """
    if os.environ.get(ENV_DISABLE):
        return []

    if entry_points is None:
        from importlib.metadata import entry_points as _ep
        entry_points = _ep(group=ENTRY_POINT_GROUP)

    loaded: list[str] = []
    for ep in entry_points:
        try:
            setup = ep.load()
            setup()
        except Exception as e:
            warnings.warn(
                f"Trellis plugin {ep.name!r} failed to load: "
                f"{type(e).__name__}: {e}",
                RuntimeWarning,
                stacklevel=2,
            )
            continue
        loaded.append(ep.name)
    return loaded


__all__ = ["ENTRY_POINT_GROUP", "ENV_DISABLE", "load_plugins"]
