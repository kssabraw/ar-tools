"""Unit tests for the dashboard-chat helpers (pure logic; no I/O)."""

from __future__ import annotations

import pytest

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


# --- surface separation: SerMaStr's chat never answers as PACE ----------------
async def test_pace_shaped_message_is_not_delegated_to_pace(monkeypatch):
    """The SerMaStr chat page is SerMaStr's alone.

    A delivery-shaped message ("what's stuck", "reassign the task") used to be
    handed to PACE here, so clicking the SerMaStr icon could return a reply in
    PACE's persona — which disclaims strategy — while the UI still said
    SerMaStr. PACE has its own surface now (`POST /pace/chat`); this asserts the
    delegate is gone even with `pace_enabled` on and an actor supplied.
    """
    from services import pace_agent

    called = {"pace": False}

    async def _boom(*a, **k):
        called["pace"] = True
        return {"reply": "PACE answered"}

    monkeypatch.setattr(pace_agent, "maybe_handle_web", _boom)
    monkeypatch.setattr("config.settings.pace_enabled", True)
    # Stop the turn right after routing — resolving the client is the first
    # thing the SerMaStr flow does, so reaching it proves PACE was bypassed.
    reached = {"sermastr": False}

    def _clients():
        reached["sermastr"] = True
        raise RuntimeError("stop here")

    monkeypatch.setattr(assistant_chat, "_list_clients", _clients)

    with pytest.raises(RuntimeError, match="stop here"):
        await assistant_chat.handle_chat(
            "what's stuck on Acme? reassign the overdue task to Ivy",
            [], None, None,
            action_context=object(),
        )
    assert called["pace"] is False
    assert reached["sermastr"] is True


# ---------------------------------------------------------------------------
# Follow-up regression (2026-07-31, live): "whenever I ask a follow up question
# it just repeats the last answer."
#
# The chain: #516 raised the reply cap so director answers run 9-10k chars; the
# ChatTurn history items were capped at 8,000 chars with a REJECTING
# max_length, so every follow-up carrying the previous answer 422'd; and the
# frontend's stream-recovery path masked the 422 by re-showing the thread's
# last stored answer. The Henson conversation proves it: one user message, one
# reply, and every follow-up invisible.
# ---------------------------------------------------------------------------


def test_follow_up_with_a_long_previous_answer_is_accepted_not_rejected():
    from routers.assistant import ChatRequest

    req = ChatRequest(
        message="what about the maps side?",
        history=[{"role": "assistant", "content": "x" * 9905}],  # the Henson reply's size
        conversation_id="47db8f32-e681-4c47-99cf-5f77f20d57c4",
    )
    # Clipped as a seed, never a 422 — history is only a seed; the store is
    # the real history.
    assert len(req.history[0].content) == 8000


def test_pace_follow_up_is_clipped_the_same_way():
    from routers.pace import PaceChatRequest

    req = PaceChatRequest(message="and the board?", history=[{"role": "user", "content": "y" * 20000}])
    assert len(req.history[0].content) == 8000


def test_short_history_passes_through_unclipped():
    from routers.assistant import ChatRequest

    req = ChatRequest(message="hi", history=[{"role": "user", "content": "short"}])
    assert req.history[0].content == "short"
