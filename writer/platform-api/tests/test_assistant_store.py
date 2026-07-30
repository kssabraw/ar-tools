"""Unit tests for the assistant conversation store's pure helpers (no I/O)."""

from __future__ import annotations

from services import assistant_store


# --- derive_title ------------------------------------------------------------
def test_title_from_short_message_is_verbatim():
    assert assistant_store.derive_title("how is BSA Claims going?") == "how is BSA Claims going?"


def test_title_collapses_whitespace():
    assert assistant_store.derive_title("  how   is\nBSA  going? ") == "how is BSA going?"


def test_title_truncates_on_a_word_boundary():
    msg = "what should we do about the ranking drop on emergency plumber Sydney " \
          "and the local pack slipping in the western suburbs too"
    title = assistant_store.derive_title(msg)
    assert len(title) <= assistant_store._TITLE_MAX + 1  # +1 for the ellipsis
    assert title.endswith("…")
    # Cut between words, not mid-word.
    assert not title.removesuffix("…").endswith(" ")
    assert msg.startswith(title.removesuffix("…"))


def test_title_hard_cuts_when_there_is_no_word_boundary():
    # A pasted URL has no spaces to break on — still bounded, never raises.
    title = assistant_store.derive_title("https://example.com/" + "a" * 200)
    assert len(title) <= assistant_store._TITLE_MAX + 1


def test_title_placeholder_for_empty_message():
    assert assistant_store.derive_title("") == "New conversation"
    assert assistant_store.derive_title("   ") == "New conversation"


# --- can_read / can_write ----------------------------------------------------
CONVO = {"id": "conv1", "owner_id": "u1", "surface": "sermastr"}


def test_owner_can_read_and_write():
    assert assistant_store.can_read(CONVO, "u1", "team_member")
    assert assistant_store.can_write(CONVO, "u1")


def test_admin_reads_but_never_writes():
    # Diagnosing a bad answer needs the transcript; appending to it does not.
    assert assistant_store.can_read(CONVO, "u2", "admin")
    assert not assistant_store.can_write(CONVO, "u2")


def test_other_user_gets_nothing():
    for role in ("team_member", "staff", "client", None):
        assert not assistant_store.can_read(CONVO, "u2", role)
    assert not assistant_store.can_write(CONVO, "u2")


def test_missing_conversation_or_actor_denied():
    assert not assistant_store.can_read(None, "u1", "admin")
    assert not assistant_store.can_read(CONVO, None, "admin")
    assert not assistant_store.can_write(None, "u1")
    assert not assistant_store.can_write(CONVO, None)


# --- to_history --------------------------------------------------------------
def test_to_history_maps_rows_and_drops_noise():
    rows = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": ""},        # failed turn — must not
        {"role": "assistant", "content": "   "},     # inject an empty message
        {"role": "system", "content": "nope"},       # not a chat role
        {"role": "assistant", "content": "hello"},
    ]
    assert assistant_store.to_history(rows) == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]


def test_to_history_empty_input():
    assert assistant_store.to_history([]) == []
    assert assistant_store.to_history(None) == []
