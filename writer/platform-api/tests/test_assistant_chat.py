"""Unit tests for the dashboard-chat helpers (pure logic; no I/O)."""

from __future__ import annotations

from services import assistant_chat


CLIENTS = [
    {"id": "c1", "name": "First Class Roofing", "website_url": "https://fcr.example"},
    {"id": "c2", "name": "Acme Plumbing", "website_url": "https://acme.example"},
]


def setup_function(_fn):
    assistant_chat._pending.clear()


# --- resolve_chat_client -----------------------------------------------------
def test_named_client_wins_over_sticky():
    c = assistant_chat.resolve_chat_client("how is acme plumbing doing?", "c1", CLIENTS)
    assert c and c["id"] == "c2"


def test_sticky_fallback_when_message_names_nobody():
    c = assistant_chat.resolve_chat_client("what should we improve next?", "c1", CLIENTS)
    assert c and c["id"] == "c1"


def test_no_client_at_all():
    assert assistant_chat.resolve_chat_client("what should we improve?", None, CLIENTS) is None


def test_sticky_id_unknown_returns_none():
    assert assistant_chat.resolve_chat_client("anything", "gone", CLIENTS) is None


# --- pending store -----------------------------------------------------------
def test_pending_roundtrip():
    token = assistant_chat.store_pending("run_maps_scan", CLIENTS[0], {"a": 1}, now=1000.0)
    entry = assistant_chat.take_pending(token, now=1001.0)
    assert entry == {
        "action": "run_maps_scan",
        "client_id": "c1",
        "client_name": "First Class Roofing",
        "args": {"a": 1},
        "created": 1000.0,
    }
    # One-time: a second take misses.
    assert assistant_chat.take_pending(token, now=1002.0) is None


def test_pending_expires_after_ttl():
    token = assistant_chat.store_pending("run_maps_scan", CLIENTS[0], None, now=1000.0)
    late = 1000.0 + assistant_chat._PENDING_TTL_SECONDS + 1
    assert assistant_chat.take_pending(token, now=late) is None


def test_pending_none_token():
    assert assistant_chat.take_pending(None) is None


def test_pending_store_evicts_expired_and_caps_size():
    old = assistant_chat.store_pending("a", CLIENTS[0], None, now=0.0)
    # A write far past the TTL evicts the stale entry.
    assistant_chat.store_pending("b", CLIENTS[0], None, now=10_000.0)
    assert old not in assistant_chat._pending
    # The cap holds: the oldest entry is evicted once the store is full.
    assistant_chat._pending.clear()
    tokens = [
        assistant_chat.store_pending("x", CLIENTS[0], None, now=100.0 + i)
        for i in range(assistant_chat._PENDING_MAX)
    ]
    assistant_chat.store_pending("y", CLIENTS[0], None, now=200.0 + assistant_chat._PENDING_MAX)
    assert len(assistant_chat._pending) <= assistant_chat._PENDING_MAX
    assert tokens[0] not in assistant_chat._pending
    assert tokens[-1] in assistant_chat._pending
