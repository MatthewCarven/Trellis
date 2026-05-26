"""Tests for trellis.core.events — the Emitter mixin and Subscription handle."""

import pytest

from trellis.core.events import Emitter, Subscription


class Bell(Emitter):
    """A trivial Emitter subclass used by the tests."""

    def ring(self, tone: str = "ding") -> None:
        self.emit("ring", tone=tone)


# --- Subscribe / emit basics -----------------------------------------------


def test_subscribe_and_emit():
    b = Bell()
    heard = []
    b.on("ring", lambda tone: heard.append(tone))
    b.ring("ding")
    b.ring("dong")
    assert heard == ["ding", "dong"]


def test_on_returns_a_subscription():
    b = Bell()
    sub = b.on("ring", lambda tone: None)
    assert isinstance(sub, Subscription)
    assert sub.active


def test_emit_with_no_subscribers_is_a_noop():
    Bell().emit("anything", foo=1, bar=2)  # must not raise


# --- Unsubscribe ------------------------------------------------------------


def test_unsubscribe_via_handle():
    b = Bell()
    heard = []
    sub = b.on("ring", lambda tone: heard.append(tone))
    b.ring()
    sub()
    b.ring()
    assert heard == ["ding"]


def test_unsubscribe_via_method():
    b = Bell()
    heard = []
    sub = b.on("ring", lambda tone: heard.append(tone))
    sub.unsubscribe()
    b.ring()
    assert heard == []


def test_unsubscribe_via_off():
    b = Bell()
    heard = []

    def handler(tone):
        heard.append(tone)

    b.on("ring", handler)
    b.off("ring", handler)
    b.ring()
    assert heard == []


def test_off_unknown_handler_is_silent():
    b = Bell()
    b.off("ring", lambda tone: None)  # no error before any subscription
    b.on("ring", lambda tone: None)
    b.off("ring", lambda tone: None)  # different lambda; no error


def test_subscription_is_idempotent():
    b = Bell()
    sub = b.on("ring", lambda tone: None)
    assert sub.active
    sub()
    assert not sub.active
    sub()  # second call must not raise


def test_subscription_repr():
    sub = Bell().on("ring", lambda tone: None)
    assert "active" in repr(sub)
    assert "'ring'" in repr(sub)
    sub()
    assert "inactive" in repr(sub)


# --- Handler ordering ------------------------------------------------------


def test_handlers_called_in_registration_order():
    b = Bell()
    order = []
    b.on("ring", lambda tone: order.append("first"))
    b.on("ring", lambda tone: order.append("second"))
    b.on("ring", lambda tone: order.append("third"))
    b.ring()
    assert order == ["first", "second", "third"]


# --- Wildcard --------------------------------------------------------------


def test_wildcard_receives_every_event():
    b = Bell()
    seen = []
    b.on("*", lambda event, **kw: seen.append((event, kw)))
    b.ring("ding")
    b.emit("ping", note="hello")
    assert seen == [("ring", {"tone": "ding"}), ("ping", {"note": "hello"})]


def test_wildcard_fires_after_specific():
    b = Bell()
    order = []
    b.on("ring", lambda tone: order.append("specific"))
    b.on("*", lambda event, **kw: order.append("wildcard"))
    b.ring()
    assert order == ["specific", "wildcard"]


def test_wildcard_does_not_satisfy_specific():
    b = Bell()
    heard = []
    b.on("*", lambda event, **kw: heard.append("wild"))
    b.emit("unique", x=1)
    assert heard == ["wild"]


# --- Exception propagation -------------------------------------------------


def test_exception_in_handler_propagates_and_stops_chain():
    b = Bell()
    later = []

    def boom(tone):
        raise RuntimeError("plugin bug")

    b.on("ring", boom)
    b.on("ring", lambda tone: later.append(tone))

    with pytest.raises(RuntimeError, match="plugin bug"):
        b.ring()
    assert later == []  # second handler never ran


def test_exception_in_wildcard_propagates():
    b = Bell()

    def boom(event, **kw):
        raise RuntimeError("wildcard bug")

    b.on("*", boom)
    with pytest.raises(RuntimeError, match="wildcard bug"):
        b.ring()


# --- Lazy allocation -------------------------------------------------------


def test_lazy_allocation_no_listeners_no_attribute():
    b = Bell()
    assert "_trellis_listeners" not in b.__dict__
    b.ring()  # emit with no subscribers must not allocate
    assert "_trellis_listeners" not in b.__dict__


def test_lazy_allocation_attribute_appears_on_first_on():
    b = Bell()
    assert "_trellis_listeners" not in b.__dict__
    b.on("ring", lambda tone: None)
    assert "_trellis_listeners" in b.__dict__


# --- Bucket cleanup --------------------------------------------------------


def test_empty_bucket_is_dropped_on_last_unsubscribe():
    b = Bell()

    def handler(tone):
        pass

    b.on("ring", handler)
    assert b.listener_count("ring") == 1
    b.off("ring", handler)
    assert b.listener_count("ring") == 0
    assert "ring" not in b.__dict__["_trellis_listeners"]


# --- listener_count --------------------------------------------------------


def test_listener_count():
    b = Bell()
    assert b.listener_count() == 0
    assert b.listener_count("ring") == 0
    b.on("ring", lambda tone: None)
    b.on("ring", lambda tone: None)
    b.on("ping", lambda **kw: None)
    assert b.listener_count("ring") == 2
    assert b.listener_count("ping") == 1
    assert b.listener_count() == 3


# --- Iteration safety ------------------------------------------------------


def test_handler_unsubscribes_another_mid_emit_does_not_break():
    """If a handler unsubscribes another mid-emit, the snapshotted list still
    iterates cleanly. The unsubscription affects *future* emits."""
    b = Bell()
    received = []
    holder: dict = {}

    def first(tone):
        received.append("first")
        holder["sub2"].unsubscribe()

    def second(tone):
        received.append("second")

    b.on("ring", first)
    holder["sub2"] = b.on("ring", second)
    b.ring()
    # 'second' was in the snapshot when emit started, so it still fires.
    assert received == ["first", "second"]
    b.ring()
    # On the next ring, 'second' is gone.
    assert received == ["first", "second", "first"]


def test_handler_subscribes_during_emit_does_not_reenter():
    """A new subscription added during emit() is not called in the same emit."""
    b = Bell()
    received = []

    def adder(tone):
        received.append("adder")
        b.on("ring", lambda tone: received.append("added"))

    b.on("ring", adder)
    b.ring()
    assert received == ["adder"]
    b.ring()
    # On the second ring: 'adder' fires (and registers yet another listener),
    # then the listener added during the *previous* ring fires too.
    assert received == ["adder", "adder", "added"]


def test_reentrant_emit_works():
    """A handler emitting a different event mid-emit is allowed."""
    b = Bell()
    chain = []

    def on_ring(tone):
        chain.append(f"ring:{tone}")
        b.emit("echo", from_tone=tone)

    def on_echo(from_tone):
        chain.append(f"echo:{from_tone}")

    b.on("ring", on_ring)
    b.on("echo", on_echo)
    b.ring("ding")
    assert chain == ["ring:ding", "echo:ding"]


# --- Mixin behaviour -------------------------------------------------------


def test_mixin_does_not_require_super_init():
    """Subclasses can drop Emitter in without calling super().__init__."""

    class NoSuper(Emitter):
        def __init__(self):
            self.my_field = 42  # deliberately not calling super().__init__()

    obj = NoSuper()
    heard = []
    obj.on("anything", lambda **kw: heard.append(kw))
    obj.emit("anything", x=1)
    assert heard == [{"x": 1}]


def test_independent_instances_have_independent_listeners():
    a = Bell()
    b = Bell()
    a_heard = []
    a.on("ring", lambda tone: a_heard.append(tone))
    b.ring("only on b")
    assert a_heard == []
    a.ring("hello")
    assert a_heard == ["hello"]
