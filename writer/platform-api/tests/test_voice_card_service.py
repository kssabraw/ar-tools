"""Unit tests for services.voice_card_service — fingerprinting + cache logic.

No network: `get_voice_card`'s nlp call is exercised via a stubbed `_post_nlp`,
everything else is pure. The distillation itself and the deterministic
compliance checks live in nlp-api and are tested there
(`writer/nlp-api/tests/test_voice_card.py`).
"""

from __future__ import annotations

import asyncio
import sys
import types
from unittest.mock import patch

from services import voice_card_service as vcs


# ---------------------------------------------------------------------------
# card_fingerprint
# ---------------------------------------------------------------------------
def test_fingerprint_is_stable_and_whitespace_insensitive():
    a = vcs.card_fingerprint("guide", "icp")
    assert a == vcs.card_fingerprint("  guide  ", "icp\n")


def test_fingerprint_changes_when_either_document_changes():
    base = vcs.card_fingerprint("guide", "icp")
    assert base != vcs.card_fingerprint("guide v2", "icp")
    assert base != vcs.card_fingerprint("guide", "icp v2")


def test_fingerprint_separator_prevents_field_boundary_collision():
    """Without the separator, ("ab","c") and ("a","bc") would hash identically
    and a guide edit could go unnoticed."""
    assert vcs.card_fingerprint("ab", "c") != vcs.card_fingerprint("a", "bc")


def test_fingerprint_matches_the_nlp_implementation():
    """The two services hash independently; if they ever disagree, every client
    re-distills on every page. This test is the lock on that pair."""
    sys.path.insert(0, "../nlp-api")
    try:
        import voice_card as nlp_voice_card
    except ImportError:  # nlp-api not on the path in this checkout
        return
    finally:
        sys.path.pop(0)
    for brand, icp in [("", ""), ("guide", "icp"), ("a" * 5000, "b" * 100)]:
        assert vcs.card_fingerprint(brand, icp) == nlp_voice_card.card_fingerprint(brand, icp)


# ---------------------------------------------------------------------------
# cached_card
# ---------------------------------------------------------------------------
def _client(brand_text="the guide", icp_text="the icp", stored=None):
    return {
        "id": "client-1",
        "brand_voice": {"raw_text": brand_text} if brand_text else None,
        "detected_icp": {"raw_text": icp_text} if icp_text else None,
        "voice_card": stored,
    }


def _stored_for(client, card):
    brand, icp = vcs.source_texts(client)
    return {"fingerprint": vcs.card_fingerprint(brand, icp), "card": card}


def test_cached_card_returns_a_matching_card():
    client = _client()
    client["voice_card"] = _stored_for(client, {"person": "first"})
    assert vcs.cached_card(client) == {"person": "first"}


def test_cached_card_rejects_a_stale_card():
    """A card built from an older guide would enforce rules the client has
    already changed — worse than having no card."""
    client = _client()
    client["voice_card"] = _stored_for(client, {"person": "first"})
    client["brand_voice"] = {"raw_text": "the guide, rewritten"}
    assert vcs.cached_card(client) is None


def test_cached_card_handles_missing_and_malformed_storage():
    assert vcs.cached_card(_client(stored=None)) is None
    assert vcs.cached_card(_client(stored={})) is None
    assert vcs.cached_card(_client(stored="not a dict")) is None
    assert vcs.cached_card(_client(stored={"fingerprint": "x"})) is None


# ---------------------------------------------------------------------------
# get_voice_card
# ---------------------------------------------------------------------------
def _run(coro):
    # asyncio.run, not get_event_loop().run_until_complete: the latter reuses a
    # process-wide loop that another test in the suite may already have closed,
    # which makes these pass in isolation and fail in a full run.
    return asyncio.run(coro)


def _stub_nlp(response=None, raises=None):
    """Install a fake services.local_seo_service so the lazy import inside
    get_voice_card resolves without pulling in the real module (Supabase, httpx,
    the whole nlp transport)."""
    calls = []

    async def _post_nlp(path, payload, user_id=None):
        calls.append((path, payload, user_id))
        if raises is not None:
            raise raises
        return response or {}

    module = types.ModuleType("services.local_seo_service")
    module._post_nlp = _post_nlp
    return module, calls


def test_no_guide_on_file_returns_empty_without_calling_nlp():
    module, calls = _stub_nlp()
    with patch.dict(sys.modules, {"services.local_seo_service": module}):
        assert _run(vcs.get_voice_card(_client(brand_text="", icp_text=""))) == {}
    assert calls == []


def test_cached_card_short_circuits_the_distillation():
    client = _client()
    client["voice_card"] = _stored_for(client, {"person": "third"})
    module, calls = _stub_nlp()
    with patch.dict(sys.modules, {"services.local_seo_service": module}):
        assert _run(vcs.get_voice_card(client)) == {"person": "third"}
    assert calls == []


def test_distills_and_persists_on_a_cache_miss():
    client = _client()
    module, calls = _stub_nlp({"voice_card": {"person": "first"}, "fingerprint": "fp-1"})
    with patch.dict(sys.modules, {"services.local_seo_service": module}), \
            patch.object(vcs, "_persist") as persist:
        assert _run(vcs.get_voice_card(client, user_id="u1")) == {"person": "first"}
    assert calls[0][0] == "/distill-voice-card"
    assert calls[0][2] == "u1"
    persist.assert_called_once_with("client-1", "fp-1", {"person": "first"})


def test_distillation_failure_degrades_to_no_enforcement():
    """A page must never fail to generate because we could not summarise the
    client's brand guide."""
    module, _ = _stub_nlp(raises=RuntimeError("nlp down"))
    with patch.dict(sys.modules, {"services.local_seo_service": module}), \
            patch.object(vcs, "_persist") as persist:
        assert _run(vcs.get_voice_card(_client())) == {}
    persist.assert_not_called()


def test_unextractable_guide_caches_the_empty_result():
    """Otherwise every page for that client re-pays for the same non-answer."""
    client = _client()
    module, _ = _stub_nlp({"voice_card": {"person": "", "tone_adjectives": []}})
    with patch.dict(sys.modules, {"services.local_seo_service": module}), \
            patch.object(vcs, "_persist") as persist:
        assert _run(vcs.get_voice_card(client)) == {}
    assert persist.call_args[0][2] == {}


# ---------------------------------------------------------------------------
# reoptimize_verdict — the bulk-reoptimize gate
# ---------------------------------------------------------------------------
def _voice(score=None, critical=0):
    return {"score": score, "critical_count": critical}


def test_skips_when_both_scores_clear():
    reopt, reason = vcs.reoptimize_verdict(85, _voice(score=92), 75)
    assert reopt is False
    assert "85/100 on SEO" in reason
    assert "92/100 on brand voice" in reason


def test_reoptimizes_when_seo_is_low():
    reopt, reason = vcs.reoptimize_verdict(60, _voice(score=95), 75)
    assert reopt is True
    assert "Below the SEO threshold" in reason


def test_reoptimizes_a_strong_seo_page_that_is_off_voice():
    """The case the SEO-only gate silently skipped: good SEO, bad voice."""
    reopt, reason = vcs.reoptimize_verdict(78, _voice(score=40), 75)
    assert reopt is True
    assert "SEO is fine at 78/100" in reason
    assert "40/100" in reason


def test_reoptimizes_a_strong_seo_page_with_a_forbidden_word():
    reopt, reason = vcs.reoptimize_verdict(90, _voice(score=95, critical=1), 75)
    assert reopt is True
    assert "forbids" in reason


def test_voice_score_exactly_at_the_bar_passes():
    reopt, _ = vcs.reoptimize_verdict(80, _voice(score=80), 75)
    assert reopt is False
    reopt, _ = vcs.reoptimize_verdict(80, _voice(score=79.9), 75)
    assert reopt is True


def test_clients_without_a_guide_behave_exactly_as_before():
    """No voice score means no voice opinion — the SEO threshold alone decides."""
    for voice in (None, {}, _voice(score=None)):
        assert vcs.reoptimize_verdict(85, voice, 75)[0] is False
        assert vcs.reoptimize_verdict(60, voice, 75)[0] is True


def test_unscoreable_seo_still_reoptimizes():
    assert vcs.reoptimize_verdict(None, _voice(score=95), 75)[0] is True


def test_skip_reason_omits_voice_when_there_is_none():
    _, reason = vcs.reoptimize_verdict(85, None, 75)
    assert "brand voice" not in reason
    assert "85/100 on SEO" in reason


# ---------------------------------------------------------------------------
# assert_voice_publishable — the publish gate
# ---------------------------------------------------------------------------
import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402


def test_publish_blocked_by_a_forbidden_word():
    verdict = {"critical_count": 1, "passed": False,
               "violations": [{"check": "never_use_terms", "severity": "critical"}]}
    with pytest.raises(HTTPException) as exc:
        vcs.assert_voice_publishable(verdict)
    assert exc.value.status_code == 409
    # No terms on this verdict, so the detail stays the bare code.
    assert exc.value.detail == "voice_violation"


def test_publish_block_names_the_forbidden_terms():
    """The offending words ride along in the detail so a surface that only sees
    the error can name them — while the code stays parseable before the colon."""
    verdict = {
        "critical_count": 1,
        "passed": False,
        "violations": [
            {"check": "never_use_terms", "severity": "critical",
             "terms": ["cheapest", "Cheapest", "budget"]},
            {"check": "must_use_terms", "severity": "warning", "terms": ["Expert"]},
        ],
    }
    with pytest.raises(HTTPException) as exc:
        vcs.assert_voice_publishable(verdict)
    detail = exc.value.detail
    assert detail.split(":")[0] == "voice_violation"
    assert "voice_violation" in detail
    # De-duplicated case-insensitively, warnings excluded.
    assert detail == "voice_violation: cheapest, budget"


def test_publish_allowed_when_only_warnings():
    """A missing preferred term is advisory. Blocking on it would make the gate
    something people route around."""
    vcs.assert_voice_publishable({"critical_count": 0, "warning_count": 3, "passed": False})


def test_publish_allowed_on_a_low_score_without_criticals():
    """A low score is a judgement, not a fact — it does not stop a publish."""
    vcs.assert_voice_publishable({"critical_count": 0, "score": 41, "passed": False})


def test_force_overrides_the_block():
    """A wrong extraction from the guide must not deadlock the team forever."""
    vcs.assert_voice_publishable({"critical_count": 2}, force=True)


def test_publish_allowed_when_there_is_no_verdict():
    for verdict in (None, {}, "not a dict", []):
        vcs.assert_voice_publishable(verdict)
