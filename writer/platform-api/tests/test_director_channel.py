"""Director-of-Operations (DORA) Slack channel routing.

DORA's outbound kinds (ops_seam / ops_digest) route to its OWN #dora channel
when configured, and post under a dedicated DORA bot token when one is set —
otherwise they degrade to the PACE channel / PACE bot (never the strategy
channel), because they stay in PACE_CHANNEL_KINDS as well. Pure functions, no
mocking.
"""

from services import notifications as n


def test_director_kinds_are_the_ops_kinds():
    assert n.DIRECTOR_CHANNEL_KINDS == frozenset({"ops_digest", "ops_seam", "ops_efficiency", "guide_sync"})
    # Kept in PACE_CHANNEL_KINDS too, so an unset DORA channel falls back to PACE.
    assert n.DIRECTOR_CHANNEL_KINDS <= n.PACE_CHANNEL_KINDS


def test_resolve_channel_prefers_director_channel():
    assert n.resolve_slack_channel("ops_seam", {}, "CPACE", director_channel="CDORA") == "CDORA"
    assert n.resolve_slack_channel("ops_digest", {}, "CPACE", director_channel="CDORA") == "CDORA"


def test_resolve_channel_falls_back_to_pace_when_no_director_channel():
    # Unset DORA channel → the ops kind still routes to the PACE channel, never
    # the default (strategy) channel.
    assert n.resolve_slack_channel("ops_seam", {}, "CPACE", director_channel="") == "CPACE"
    assert n.resolve_slack_channel("ops_seam", {}, "CPACE", director_channel=None) == "CPACE"
    # No PACE channel either → None (sender uses slack_default_channel).
    assert n.resolve_slack_channel("ops_seam", {}, "", director_channel="") is None


def test_resolve_channel_explicit_override_still_wins():
    assert (
        n.resolve_slack_channel("ops_seam", {"slack_channel": "COVR"}, "CPACE", director_channel="CDORA")
        == "COVR"
    )


def test_resolve_channel_non_director_pace_kind_unaffected():
    # A plain PACE kind must not be pulled into the DORA channel.
    assert n.resolve_slack_channel("task_due", {}, "CPACE", director_channel="CDORA") == "CPACE"
    assert (
        n.resolve_slack_channel("task_mention", {}, "CPACE", client_channel="CCLIENT", director_channel="CDORA")
        == "CCLIENT"
    )


def test_resolve_token_uses_director_token_for_ops_kinds():
    assert (
        n.resolve_slack_token("CDORA", "CPACE", "pacetok", "deftok",
                              kind="ops_seam", director_channel="CDORA", director_token="doratok")
        == "doratok"
    )


def test_resolve_token_falls_back_to_pace_without_director_token():
    # No dedicated DORA app → the ops kind (still a PACE kind) posts under the PACE bot.
    assert (
        n.resolve_slack_token("CDORA", "CPACE", "pacetok", "deftok",
                              kind="ops_seam", director_channel="CDORA", director_token="")
        == "pacetok"
    )


def test_resolve_token_non_director_kind_unchanged():
    assert n.resolve_slack_token("CPACE", "CPACE", "pacetok", "deftok", kind="task_due") == "pacetok"
    assert n.resolve_slack_token("CX", "CPACE", "pacetok", "deftok", kind="strategy_review") == "deftok"


def test_master_fallback_from_director_channel():
    # A failed #dora send falls back to the master PACE channel (then default).
    assert n.master_fallback_channel("CDORA", None, "CPACE", "CDEF", director_channel="CDORA") == "CPACE"
    assert n.master_fallback_channel("CDORA", None, "", "CDEF", director_channel="CDORA") == "CDEF"
    # A non-DORA, non-client channel has nowhere to fall back to.
    assert n.master_fallback_channel("CX", None, "CPACE", "CDEF", director_channel="CDORA") is None


def test_director_bot_token_precedence(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "director_slack_bot_token", "doratok", raising=False)
    assert n.director_bot_token() == "doratok"
    monkeypatch.setattr(settings, "director_slack_bot_token", "", raising=False)
    monkeypatch.setattr(settings, "pace_slack_bot_token", "pacetok", raising=False)
    assert n.director_bot_token() == "pacetok"
    monkeypatch.setattr(settings, "pace_slack_bot_token", "", raising=False)
    monkeypatch.setattr(settings, "slack_bot_token", "sharedtok", raising=False)
    assert n.director_bot_token() == "sharedtok"
