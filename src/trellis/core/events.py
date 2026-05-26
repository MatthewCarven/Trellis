"""Emitter mixin — the connective tissue for Trellis extensibility.

Any class that inherits :class:`Emitter` gains synchronous publish/subscribe::

    obj.on(event, handler)         -> Subscription (callable to unsubscribe)
    obj.off(event, handler)        -> None
    obj.emit(event, **payload)     -> None
    obj.listener_count(event=None) -> int

Events are colon-namespaced strings, e.g. ``"cell:change"``, ``"sheet:add"``.
Handlers fire synchronously, in registration order. **Exceptions in handlers
propagate** — buggy plugins should be loud, not silent. The first handler that
raises stops the chain; later handlers (including wildcards) are not called.
If you want isolation, wrap your handler in try/except yourself.

Wildcard subscription::

    obj.on("*", lambda event, **kw: ...)

Wildcard handlers receive the event name as the first positional argument,
followed by the event's keyword payload. They fire after specific handlers.

Storage is lazy: an Emitter with no listeners pays no extra memory beyond a
single dict-miss on every emit. Cheap enough to mix into anything.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

Handler = Callable[..., Any]

# Stored as an entry in the instance __dict__ rather than as a slot, so the
# mixin can drop onto any class without conflicting with __slots__ definitions
# in subclasses. The prefix avoids collisions with subclass attributes.
_LISTENERS = "_trellis_listeners"


class Subscription:
    """Handle returned by :meth:`Emitter.on`. Call to unsubscribe.

    Calling :meth:`unsubscribe` (or invoking the subscription as a callable)
    removes the handler from the emitter. Idempotent — calling twice is fine.
    """

    __slots__ = ("_emitter", "_event", "_handler", "_active")

    def __init__(self, emitter: "Emitter", event: str, handler: Handler):
        self._emitter = emitter
        self._event = event
        self._handler = handler
        self._active = True

    def __call__(self) -> None:
        self.unsubscribe()

    def unsubscribe(self) -> None:
        if self._active:
            self._emitter.off(self._event, self._handler)
            self._active = False

    @property
    def active(self) -> bool:
        return self._active

    def __repr__(self) -> str:
        state = "active" if self._active else "inactive"
        return f"Subscription({self._event!r}, {state})"


class Emitter:
    """Mixin: synchronous, in-process pub/sub.

    Subclasses do not need to call ``super().__init__()`` — listener storage is
    created lazily on the first :meth:`on` call. This makes the mixin safe to
    drop onto existing classes without touching their ``__init__``.
    """

    def on(self, event: str, handler: Handler) -> Subscription:
        """Subscribe ``handler`` to ``event``. Returns a handle for unsubscribing.

        Use ``event="*"`` to subscribe to every event on this emitter.
        """
        listeners = self.__dict__.get(_LISTENERS)
        if listeners is None:
            listeners = {}
            self.__dict__[_LISTENERS] = listeners
        listeners.setdefault(event, []).append(handler)
        return Subscription(self, event, handler)

    def off(self, event: str, handler: Handler) -> None:
        """Remove ``handler`` from ``event``. No-op if not subscribed.

        Empty buckets are dropped from the listener dict to keep
        :meth:`listener_count` honest and to free memory.
        """
        listeners = self.__dict__.get(_LISTENERS)
        if not listeners:
            return
        bucket = listeners.get(event)
        if not bucket:
            return
        try:
            bucket.remove(handler)
        except ValueError:
            return
        if not bucket:
            del listeners[event]

    def emit(self, event: str, **payload: Any) -> None:
        """Fire ``event`` to all subscribers, in registration order.

        Wildcard subscribers (``"*"``) are called after specific subscribers,
        receiving the event name as the first positional argument.

        Exceptions propagate. The first handler that raises stops the chain;
        later handlers (including wildcards) are not called.
        """
        listeners = self.__dict__.get(_LISTENERS)
        if not listeners:
            return
        # Snapshot so handlers may on/off during emit without corrupting iteration.
        for handler in list(listeners.get(event, ())):
            handler(**payload)
        for handler in list(listeners.get("*", ())):
            handler(event, **payload)

    def listener_count(self, event: str | None = None) -> int:
        """Return the number of handlers listening on ``event``.

        With ``event=None`` (the default), returns the total across all events.
        """
        listeners = self.__dict__.get(_LISTENERS)
        if not listeners:
            return 0
        if event is None:
            return sum(len(bucket) for bucket in listeners.values())
        return len(listeners.get(event, ()))
