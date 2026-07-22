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
    # A FRESH loop per call — asyncio.get_event_loop() can hand back a loop an
    # earlier async test in the full suite already closed (no pytest-asyncio in
    # this env), which would spuriously fail these otherwise-isolated tests.
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


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


def test_dead_image_is_advisory_dead_stylesheet_is_blocking():
    # A page with a 404'd IMAGE and a 404'd STYLESHEET: the image failure is
    # advisory (won't bounce), the stylesheet failure is blocking (does).
    html_img = (
        "<html><head><title>Roof Repair</title>"
        "<meta name='description' content='x'></head>"
        "<body><h1>Roof Repair</h1><a href='https://client.com/contact'>C</a>"
        "<p>Client Co here.</p><img src='https://client.com/dead.jpg' alt='r'></body></html>"
    )

    async def fake_fetch(url):
        return html_img

    async def dead_all(urls):
        return list(urls)  # everything 404s

    client = {"website_url": "https://client.com", "name": "Client Co", "gbp": {}}
    with patch.object(qa_service, "_fetch", fake_fetch), \
         patch.object(qa_service, "_broken_assets", dead_all), \
         patch.object(qa_service.settings, "qa_visual_enabled", False):
        review = _run(qa_service.review_url("https://client.com/roof", client, sig.RUBRIC_PAGE))
    by = {c["key"]: c for c in review["checks"]}
    assert "image_assets" in by and by["image_assets"]["blocking"] is False
    assert by["image_assets"]["ok"] is False  # flagged, but advisory
    # The dead image alone must not FAIL the page (no stylesheet in this HTML).
    assert review["verdict"] != sig.FAIL


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


# ---------------------------------------------------------------------------
# maybe_handle_web: external-page rubrics ask for the client up front
# ---------------------------------------------------------------------------
from services.pace_auth import ActionContext  # noqa: E402


def _handle(message, *, page_kind, scope_client=None, url_client=None, sticky_client=None):
    """Drive one maybe_handle_web turn with the LLM + DB reads mocked, returning
    (reply_dict, review_url_called)."""
    called = {"review": False}

    async def fake_interpret(*_a, **_k):
        return "url", {"url": "https://someblog.com/guest/post", "page_kind": page_kind}

    def fake_resolve_scope(_msg, _sticky):
        return ("client" if scope_client else "global"), (scope_client or {}), {}

    async def fake_review_url(*_a, **_k):
        called["review"] = True
        return {"verdict": sig.NEEDS_HUMAN, "rubric": sig.RUBRIC_GUEST_POST,
                "composite": None, "checks": [], "issues": [], "urls": [], "narrative": ""}

    actor = ActionContext(profile_id="p1", role="admin")
    with patch.object(qa_agent, "interpret_qa", fake_interpret), \
         patch.object(qa_agent, "_resolve_scope", fake_resolve_scope), \
         patch.object(qa_agent, "resolve_client_by_url", lambda _u: url_client), \
         patch.object(qa_agent, "_client_row", lambda _c: sticky_client), \
         patch.object(qa_service, "review_url", fake_review_url):
        out = _run(qa_agent.maybe_handle_web(message, [], None, None, actor))
    return out, called["review"]


def test_guest_post_with_no_client_asks_first():
    # No conversation client, URL is a third-party blog, no sticky client →
    # the bot asks which client and never runs the (meaningless) check.
    out, review_called = _handle("QA this guest post https://someblog.com/guest/post",
                                 page_kind="guest post")
    assert review_called is False
    assert "which client" in out["reply"].lower()


def test_guest_post_with_sticky_client_runs():
    # A known (sticky) client → the link-back check runs; no up-front question.
    sticky = {"id": "9", "name": "Acme", "website_url": "https://acme.com", "gbp": {}}
    out, review_called = _handle("QA this guest post https://someblog.com/guest/post",
                                 page_kind="guest post", sticky_client=sticky)
    assert review_called is True


def test_website_page_with_no_client_still_runs():
    # The website-page rubric is NOT client-required: it still runs client-less
    # (meta/keyword checks are useful) and appends the "which client" nudge.
    out, review_called = _handle("QA https://someblog.com/guest/post",
                                 page_kind="page")
    assert review_called is True
    assert "which client" in out["reply"].lower()


# ---------------------------------------------------------------------------
# Graceful no-match when the VA answers "which client?" with an unknown name
# ---------------------------------------------------------------------------
def test_just_asked_for_client_detects_the_prior_ask():
    asked = [
        {"role": "user", "content": "QA this niche edit https://x.com/p"},
        {"role": "assistant", "content": "Which client is this for? Just reply with the name."},
    ]
    assert qa_agent._just_asked_for_client(asked) is True
    # Last assistant turn was something else → not an answer-to-a-question turn.
    other = [{"role": "assistant", "content": "Pass — looks good."}]
    assert qa_agent._just_asked_for_client(other) is False
    assert qa_agent._just_asked_for_client([]) is False


def test_client_suggestions_finds_close_names():
    names = ["IHBS", "WheelHouse IT Fort Lauderdale", "First Class Roofing"]
    assert "WheelHouse IT Fort Lauderdale" in qa_agent._client_suggestions("wheelhouse", names)
    assert qa_agent._client_suggestions("", names) == []


def test_unknown_client_reply_lists_clients_instead_of_relooping():
    # The VA answered the which-client question with a name we don't have.
    # The bot must say so + show the real list, and NOT run the check or repeat
    # the identical "it's on another website" question.
    called = {"review": False}

    async def fake_interpret(*_a, **_k):
        return "url", {"url": "https://homoper.com/post", "page_kind": "niche edit"}

    def fake_resolve_scope(_msg, _sticky):
        return "global", {}, {}

    async def fake_review_url(*_a, **_k):
        called["review"] = True
        return {"verdict": sig.NEEDS_HUMAN, "rubric": sig.RUBRIC_NICHE_EDIT,
                "composite": None, "checks": [], "issues": [], "urls": [], "narrative": ""}

    history = [
        {"role": "user", "content": "Please QA this niche edit https://homoper.com/post"},
        {"role": "assistant", "content": "Which client is this for? Just reply with the name."},
    ]
    clients = [{"id": "1", "name": "IHBS"}, {"id": "2", "name": "First Class Roofing"}]
    actor = ActionContext(profile_id="p1", role="admin")
    with patch.object(qa_agent, "interpret_qa", fake_interpret), \
         patch.object(qa_agent, "_resolve_scope", fake_resolve_scope), \
         patch.object(qa_agent, "resolve_client_by_url", lambda _u: None), \
         patch.object(qa_agent, "_client_row", lambda _c: None), \
         patch.object(qa_agent, "_all_clients", lambda: clients), \
         patch.object(qa_service, "review_url", fake_review_url):
        out = _run(qa_agent.maybe_handle_web("UMH", history, None, None, actor))
    assert called["review"] is False
    low = out["reply"].lower()
    assert "umh" in low and "don't have" in low
    assert "IHBS" in out["reply"]  # the real client list is shown
    assert "on another website" not in low  # not the identical re-ask
