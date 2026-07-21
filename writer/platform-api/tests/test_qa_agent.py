"""Unit tests for the QA chat persona's pure helpers (services/qa_agent.py) and
the bare-URL review path (services/qa_service.review_url / resolve_url_rubric).

The persona's LLM loop + DB reads are impure and covered by integration; here we
lock the pure pieces: URL extraction, the verdict formatter, the URL-rubric
resolver, and review_url's routing over a mocked page fetch.
"""

import asyncio
from unittest.mock import patch

from services import qa_agent
from services import qa_service
from services import qa_signals as sig


# ---------------------------------------------------------------------------
# first_url / qa_service_first_url
# ---------------------------------------------------------------------------
def test_first_url_extracts_and_trims():
    assert qa_agent.first_url("QA this: https://ex.com/a/b/.") == "https://ex.com/a/b/"
    assert qa_agent.first_url("no link here") is None
    assert qa_agent.first_url("(see https://ex.com/x)") == "https://ex.com/x"


def test_qa_service_first_url_prefers_tool_then_message():
    # A well-formed tool URL wins.
    assert qa_agent.qa_service_first_url("https://a.com/p", "look at https://b.com") == "https://a.com/p"
    # A paraphrased / empty tool value falls back to the message URL.
    assert qa_agent.qa_service_first_url("the coral springs page", "QA https://b.com/x") == "https://b.com/x"
    assert qa_agent.qa_service_first_url(None, "no url at all") is None


# ---------------------------------------------------------------------------
# resolve_url_rubric
# ---------------------------------------------------------------------------
def test_deliverable_urls_prepends_explicit_field():
    # The first-class 'Page URL to review' field wins over a description URL.
    task = {"deliverable_url": "https://client.com/posted-page/",
            "description": "old link https://other.com/x"}
    urls = qa_service._deliverable_urls(task, [], "")
    assert urls[0] == "https://client.com/posted-page/"
    assert "https://other.com/x" in urls


def test_resolve_url_rubric_defaults_and_words():
    assert qa_service.resolve_url_rubric(None) == sig.RUBRIC_PAGE  # config default
    assert qa_service.resolve_url_rubric("QA this page") == sig.RUBRIC_PAGE
    assert qa_service.resolve_url_rubric("check the guest post") == sig.RUBRIC_GUEST_POST
    assert qa_service.resolve_url_rubric("the niche edit") == sig.RUBRIC_NICHE_EDIT
    assert qa_service.resolve_url_rubric("press release") == sig.RUBRIC_PRESS_RELEASE
    assert qa_service.resolve_url_rubric("a citation listing") == sig.RUBRIC_CITATIONS
    assert qa_service.resolve_url_rubric("map embed") == sig.RUBRIC_MAP_EMBEDS
    # An explicit rubric key passes through verbatim.
    assert qa_service.resolve_url_rubric(sig.RUBRIC_MAP_EMBEDS) == sig.RUBRIC_MAP_EMBEDS


# ---------------------------------------------------------------------------
# format_review
# ---------------------------------------------------------------------------
def test_format_review_lists_blocking_issues():
    review = {
        "verdict": sig.FAIL,
        "checks": [
            {"key": "meta_title", "label": "Meta title present", "ok": True, "blocking": True},
            {"key": "internal_link", "label": "Internal link", "ok": False, "blocking": True, "note": "none found"},
            {"key": "client_name", "label": "Client name", "ok": False, "blocking": False},
        ],
        "narrative": "Fix the internal link.",
    }
    out = qa_agent.format_review(review, "https://ex.com/p")
    assert "Fail" in out
    assert "Internal link" in out and "none found" in out
    assert "Client name" in out          # advisory listed
    assert "Fix the internal link." in out


def test_format_review_pass_summarizes():
    review = {
        "verdict": sig.PASS,
        "composite": 88.0,
        "checks": [{"key": "meta_title", "label": "Meta title", "ok": True, "blocking": True}],
        "narrative": "",
    }
    out = qa_agent.format_review(review, "the page")
    assert "Pass" in out and "88/100" in out and "1 check" in out


# ---------------------------------------------------------------------------
# review_url routing (mocked fetch)
# ---------------------------------------------------------------------------
def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_review_url_unreachable_is_needs_human():
    async def fake_fetch(url):
        return None

    with patch.object(qa_service, "_fetch", fake_fetch):
        review = _run(qa_service.review_url("https://dead.example/x"))
    assert review["verdict"] == sig.NEEDS_HUMAN
    assert review["task_id"] is None
    assert review["urls"] == ["https://dead.example/x"]


def test_review_url_website_page_runs_checks():
    html = (
        "<html><head><title>Roof Repair Coral Springs</title>"
        "<meta name='description' content='We repair roofs.'></head>"
        "<body><a href='https://client.com/contact'>Contact</a>"
        "<img src='/a.jpg' alt='roof'></body></html>"
    )

    async def fake_fetch(url):
        return html

    async def no_broken(urls):
        return []

    client = {"website_url": "https://client.com", "name": "Client Co", "gbp": {}}
    with patch.object(qa_service, "_fetch", fake_fetch), \
         patch.object(qa_service, "_broken_assets", no_broken), \
         patch.object(qa_service.settings, "qa_visual_enabled", False):
        review = _run(qa_service.review_url("https://client.com/roof", client, sig.RUBRIC_PAGE))
    assert review["rubric"] == sig.RUBRIC_PAGE
    labels = {c["key"] for c in review["checks"]}
    assert "meta_title" in labels and "internal_link" in labels
    assert review["verdict"] in (sig.PASS, sig.NEEDS_HUMAN, sig.FAIL)


def test_review_url_threads_keyword_to_page_checks():
    # keyword present in <title> + an <h1> → the keyword-placement checks pass;
    # this proves review_url wires the keyword through to the website-page rubric.
    html = (
        "<html><head><title>Emergency Plumber Coral Springs</title>"
        "<meta name='description' content='24/7 emergency plumbing.'></head>"
        "<body><h1>Emergency Plumber Coral Springs</h1>"
        "<a href='https://client.com/contact'>Contact</a>"
        "<img src='/a.jpg' alt='plumber'></body></html>"
    )

    async def fake_fetch(url):
        return html

    async def no_broken(urls):
        return []

    client = {"website_url": "https://client.com", "name": "Client Co", "gbp": {}}
    with patch.object(qa_service, "_fetch", fake_fetch), \
         patch.object(qa_service, "_broken_assets", no_broken), \
         patch.object(qa_service.settings, "qa_visual_enabled", False):
        review = _run(qa_service.review_url(
            "https://client.com/plumber", client, sig.RUBRIC_PAGE,
            keyword="emergency plumber coral springs",
        ))
    kw_checks = [c for c in review["checks"] if "keyword" in c["key"]]
    assert kw_checks, "keyword was not threaded into the page checks"
    assert any(c["ok"] for c in kw_checks)


# ---------------------------------------------------------------------------
# resolve_client_by_url (mocked DB)
# ---------------------------------------------------------------------------
class _FakeTable:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *_a, **_k):
        return self

    def execute(self):
        class _R:
            pass
        r = _R()
        r.data = self._rows
        return r


class _FakeSupabase:
    def __init__(self, rows):
        self._rows = rows

    def table(self, _name):
        return _FakeTable(self._rows)


def test_resolve_client_by_url_matches_domain():
    rows = [
        {"id": "1", "name": "Other Co", "website_url": "https://other.com"},
        {"id": "2", "name": "Client Co", "website_url": "https://www.client.com"},
    ]
    with patch.object(qa_agent, "get_supabase", lambda: _FakeSupabase(rows)):
        got = qa_agent.resolve_client_by_url("https://client.com/some/posted-page/")
    assert got is not None and got["id"] == "2"


def test_resolve_client_by_url_no_match_returns_none():
    rows = [{"id": "1", "name": "Other Co", "website_url": "https://other.com"}]
    with patch.object(qa_agent, "get_supabase", lambda: _FakeSupabase(rows)):
        assert qa_agent.resolve_client_by_url("https://unknown.example/x") is None
    # A URL with no parseable domain never matches.
    with patch.object(qa_agent, "get_supabase", lambda: _FakeSupabase(rows)):
        assert qa_agent.resolve_client_by_url("not a url") is None
