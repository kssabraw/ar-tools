"""Unit tests for Social P4 (Phase C): the deterministic social QA rubric + the gate
helpers + review_draft (primitives mocked) + the manual-publish CRITICAL block."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from config import settings
from services import qa_signals
from services.social import fanout, qa


@pytest.fixture(autouse=True)
def _enabled(monkeypatch):
    monkeypatch.setattr(settings, "social_enabled", True)


# ── the pure rubric (check_social_draft + build_verdict) ─────────────────────

def _verdict(**kw):
    defaults = dict(forbidden_terms=[], banned_claims=[], has_cta_flag=True,
                    platform_ok=True, has_media=True)
    defaults.update(kw)
    return qa_signals.build_verdict(qa_signals.check_social_draft(**defaults))


def test_all_pass():
    assert _verdict()["verdict"] == qa_signals.PASS


def test_forbidden_voice_is_critical_fail():
    v = _verdict(forbidden_terms=["cheapest"])
    assert v["verdict"] == qa_signals.FAIL
    assert v["critical"]                      # social_voice is a critical key


def test_banned_claim_is_critical_fail():
    v = _verdict(banned_claims=["cures cancer"])
    assert v["verdict"] == qa_signals.FAIL
    assert v["critical"]


def test_missing_cta_is_blocking_not_critical():
    v = _verdict(has_cta_flag=False)
    # one non-critical blocking failure → minor_revisions (fixable), not FAIL
    assert v["verdict"] == qa_signals.MINOR_REVISIONS
    assert not v["critical"]


def test_platform_violation_blocks():
    v = _verdict(platform_ok=False)
    assert v["verdict"] == qa_signals.MINOR_REVISIONS


def test_no_image_is_advisory_only():
    # a text-only post where the platform allows one is ADVISORY, never blocking
    v = _verdict(has_media=False)
    assert v["verdict"] == qa_signals.ADVISORY


# ── gate helpers ─────────────────────────────────────────────────────────────

def test_blocks_auto_queue():
    assert qa.blocks_auto_queue({"verdict": "pass"}) is False
    assert qa.blocks_auto_queue({"verdict": "advisory"}) is False       # advisory still queues
    assert qa.blocks_auto_queue({"verdict": "minor_revisions"}) is True  # any blocking failure
    assert qa.blocks_auto_queue({"verdict": "fail", "critical": ["x"]}) is True
    assert qa.blocks_auto_queue(None) is False


def test_is_critical_fail():
    assert qa.is_critical_fail({"verdict": "fail", "critical": ["voice"]}) is True
    assert qa.is_critical_fail({"verdict": "fail", "critical": []}) is False   # count-net fail, not critical
    assert qa.is_critical_fail({"verdict": "minor_revisions"}) is False
    assert qa.is_critical_fail(None) is False


# ── review_draft (primitives mocked) ─────────────────────────────────────────

def _mock_primitives(monkeypatch, *, forbidden=None, findings=None, hard=None):
    from services import content_compliance, gbp_posts_service
    from services.social import publish
    monkeypatch.setattr(gbp_posts_service, "voice_forbidden_hits", lambda copy, card: forbidden or [])
    monkeypatch.setattr(content_compliance, "scan_text",
                        lambda text, mode="peptide": SimpleNamespace(findings=findings or []))
    monkeypatch.setattr(publish, "_platform_spec", lambda p: {"requires_image": False})
    monkeypatch.setattr(publish, "validate_post",
                        lambda *a, **k: {"hard": hard or []})


def test_review_draft_clean_pass(monkeypatch):
    _mock_primitives(monkeypatch)
    v = qa.review_draft(client_id="c1", platform="facebook", copy="Call us today to book!",
                        media=[{"type": "image", "url": "u"}], card={}, client={"content_compliance_mode": "off"})
    assert v["verdict"] == qa_signals.PASS
    assert v["rubric"] == qa_signals.RUBRIC_SOCIAL


def test_review_draft_forbidden_term_is_critical(monkeypatch):
    _mock_primitives(monkeypatch, forbidden=["cheapest"])
    v = qa.review_draft(client_id="c1", platform="facebook", copy="the cheapest! call now",
                        media=[{"type": "image", "url": "u"}], card={}, client={"content_compliance_mode": "off"})
    assert qa.is_critical_fail(v) is True


def test_review_draft_banned_claim_regulated(monkeypatch):
    _mock_primitives(monkeypatch, findings=[SimpleNamespace(severity="critical", evidence="cures cancer")])
    v = qa.review_draft(client_id="c1", platform="facebook", copy="this cures cancer — buy now",
                        media=[{"type": "image", "url": "u"}], card={}, client={"content_compliance_mode": "peptide"})
    assert qa.is_critical_fail(v) is True


def test_review_draft_story_skips_cta(monkeypatch):
    _mock_primitives(monkeypatch)
    # a story has no caption; its CTA check must not fail on empty copy
    v = qa.review_draft(client_id="c1", platform="instagram", copy="", fmt="story",
                        media=[{"type": "image", "url": "u"}], card={}, client={"content_compliance_mode": "off"})
    assert v["verdict"] == qa_signals.PASS


def test_qa_gate_enabled_reads_policy(monkeypatch):
    class _Q:
        def __init__(self, on):
            self.on = on

        def select(self, *a, **k):
            return self

        def eq(self, *a, **k):
            return self

        def limit(self, *a, **k):
            return self

        def execute(self):
            return SimpleNamespace(data=[{"qa_gate": self.on}])

    monkeypatch.setattr(qa, "_sb", lambda: SimpleNamespace(table=lambda t: _Q(True)))
    assert qa.qa_gate_enabled("c1") is True
    monkeypatch.setattr(qa, "_sb", lambda: SimpleNamespace(table=lambda t: _Q(False)))
    assert qa.qa_gate_enabled("c1") is False


# ── manual publish: CRITICAL blocks (with force override) ────────────────────

def _draft_row(status="ready"):
    return {"id": "d1", "client_id": "c1", "platform": "facebook", "status": status,
            "format": "feed", "copy": "buy the cheapest now", "image_urls": ["u"],
            "media": [{"type": "image", "url": "u"}], "platform_metadata": None}


def test_publish_blocks_on_critical_qa(monkeypatch):
    from services.social import publish as social_publish
    monkeypatch.setattr(fanout, "get_draft", lambda did: _draft_row())
    monkeypatch.setattr(social_publish, "_assert_account_allowed", lambda *a, **k: None)
    monkeypatch.setattr(social_publish, "_platform_spec", lambda p: {"requires_image": False})
    monkeypatch.setattr(social_publish, "validate_post", lambda *a, **k: {"hard": []})
    monkeypatch.setattr(social_publish, "_pinterest_board_id", lambda m: None)
    monkeypatch.setattr(social_publish, "build_media", lambda *a, **k: [{"type": "image", "url": "u"}])
    monkeypatch.setattr(qa, "qa_gate_enabled", lambda c: True)
    monkeypatch.setattr(qa, "review_draft", lambda **k: {"verdict": "fail", "critical": ["On brand voice — forbidden: cheapest"], "rubric": "social_post"})
    monkeypatch.setattr(qa, "persist_verdict", lambda *a, **k: None)
    with pytest.raises(HTTPException) as e:
        fanout.publish_existing_draft("d1", "acct-1")
    assert e.value.status_code == 409 and str(e.value.detail).startswith("social_qa_violation")


def test_publish_force_qa_overrides_critical(monkeypatch):
    from services.social import publish as social_publish
    from types import SimpleNamespace as NS
    store = {"posts": []}
    monkeypatch.setattr(fanout, "get_draft", lambda did: _draft_row())
    monkeypatch.setattr(social_publish, "_assert_account_allowed", lambda *a, **k: None)
    monkeypatch.setattr(social_publish, "_platform_spec", lambda p: {"requires_image": False})
    monkeypatch.setattr(social_publish, "validate_post", lambda *a, **k: {"hard": []})
    monkeypatch.setattr(social_publish, "_pinterest_board_id", lambda m: None)
    monkeypatch.setattr(social_publish, "build_media", lambda *a, **k: [{"type": "image", "url": "u"}])
    monkeypatch.setattr(social_publish, "_ensure_future_iso", lambda x: None)
    monkeypatch.setattr(social_publish, "_insert_publish_job", lambda *a, **k: None)
    # QA would fail critically — but force_qa must skip the gate entirely (review not called).
    called = {"review": False}
    monkeypatch.setattr(qa, "qa_gate_enabled", lambda c: True)
    monkeypatch.setattr(qa, "review_draft", lambda **k: called.__setitem__("review", True) or {})

    class _T:
        def __init__(self, name):
            self.name = name

        def insert(self, row):
            self._row = row
            return self

        def update(self, *a, **k):
            return self

        def eq(self, *a, **k):
            return self

        def execute(self):
            return NS(data=[{"id": "post1", **getattr(self, "_row", {})}])

    monkeypatch.setattr(fanout, "_sb", lambda: NS(table=lambda t: _T(t)))
    post = fanout.publish_existing_draft("d1", "acct-1", force_qa=True)
    assert post["id"] == "post1"
    assert called["review"] is False        # force_qa short-circuits the QA gate
