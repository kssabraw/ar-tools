"""Regression tests for `persist_article_plan`'s write phase (storage/silo.py).

The keyword->cluster linkage used to be one PostgREST UPDATE *per cluster* —
every cluster has a distinct cluster_id, so `.in_()` couldn't fold them together.
At small plan sizes that was merely chatty. On 2026-07-31 the "tirzepatide" run
for Nova Life Peptides planned 4,043 clusters over 4,423 active keywords, so the
write phase fired ~4,100 sequential requests down a single HTTP/2 connection and
died partway through:

    RemoteProtocolError: <ConnectionTerminated error_code:1, last_stream_id:8201>

(stream 8201 == request #4,101). That left a half-written plan — clusters and
linkage present, primary flags/drops/coverage-gaps missing — and the session
stuck at status=error after $9.33 of upstream spend.

The linkage now goes through the `bulk_link_keywords_to_clusters` RPC in batches,
so request count scales with keyword count / _LINK_BATCH rather than with cluster
count. These tests pin both halves: the request count stays bounded at the scale
that broke, and the per-keyword payload keeps the old loop's exact semantics.
"""

from unittest.mock import patch

import httpx
import pytest

pytest.importorskip("supabase")

from fanout.pipeline.article_planning.models import (  # noqa: E402
    ArticleRecord,
    PlanResult,
    TopicPlan,
)
from fanout.storage import silo  # noqa: E402


def _client_with_transport(handler):
    """A real supabase client whose PostgREST session runs on a mock transport."""
    from supabase import create_client

    fake_jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.c2ln"
    client = create_client("http://mock.local", fake_jwt)
    client.postgrest.session._transport = httpx.MockTransport(handler)
    return client


def _article(primary: str, supporting: list[str], serp: list[str] | None = None):
    return ArticleRecord(
        topic_id="t1",
        primary_keyword=primary,
        supporting_keywords=supporting,
        intent="informational",
        suggested_h2s=["h2"],
        source_statistical_grouping_id=None,
        orchestrator_notes="",
        serp_top_urls=serp or [],
    )


def _run_persist(articles, kw_index):
    """Persist a one-topic plan against a mock transport; return the captured
    requests as (method, path, parsed json body) triples."""
    result = PlanResult(per_topic=[TopicPlan(topic_id="t1", articles=articles)])
    calls: list[tuple[str, str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = None
        if request.content:
            import json

            body = json.loads(request.content)
        calls.append((request.method, request.url.path, body))
        return httpx.Response(
            200, headers={"Content-Type": "application/json"}, content=b"[]"
        )

    with (
        patch.object(silo, "get_service_client", return_value=_client_with_transport(handler)),
        patch.object(silo, "get_active_keyword_index", return_value=kw_index),
    ):
        silo.persist_article_plan("sess-1", result, embed_fn=lambda texts: [])
    return calls


def _link_payloads(calls):
    """Flatten every row sent to the bulk-linkage RPC, in order."""
    rows = []
    for _method, path, body in calls:
        if path.endswith("/rpc/bulk_link_keywords_to_clusters"):
            rows.extend(body["p_rows"])
    return rows


def test_linkage_request_count_is_bounded_at_the_scale_that_broke():
    """4,043 single-keyword clusters used to mean ~4,100 requests on one
    connection. It must now be a couple of dozen."""
    n = 4043
    articles = [_article(f"kw {i}", []) for i in range(n)]
    kw_index = {f"kw {i}": f"kid-{i}" for i in range(n)}

    calls = _run_persist(articles, kw_index)

    rpc_calls = [c for c in calls if c[1].endswith("/rpc/bulk_link_keywords_to_clusters")]
    # 4,043 keywords / 500 per batch == 9 linkage requests.
    assert len(rpc_calls) == 9
    # Total write phase: cluster inserts (batches of 200) + linkage. Comfortably
    # under the ~4,100 that exhausted the connection.
    assert len(calls) < 50, f"write phase issued {len(calls)} requests"

    # Every keyword still gets linked exactly once.
    rows = _link_payloads(calls)
    assert len(rows) == n
    assert len({r["keyword_id"] for r in rows}) == n
    assert all(r["is_primary"] for r in rows)


def test_primary_and_supporting_rows_carry_the_old_semantics():
    articles = [_article("head kw", ["supp a", "supp b"], serp=["https://x.test"])]
    kw_index = {"head kw": "kid-h", "supp a": "kid-a", "supp b": "kid-b"}

    rows = _link_payloads(_run_persist(articles, kw_index))
    by_id = {r["keyword_id"]: r for r in rows}

    assert len(rows) == 3
    # One cluster, so everything shares its id.
    assert len({r["cluster_id"] for r in rows}) == 1

    assert by_id["kid-h"]["is_primary"] is True
    assert by_id["kid-h"]["serp_top_urls"] == ["https://x.test"]

    for kid in ("kid-a", "kid-b"):
        assert by_id[kid]["is_primary"] is False
        # A supporting keyword must never clobber a captured SERP with null —
        # the RPC coalesces, and the payload says "don't touch".
        assert by_id[kid]["serp_top_urls"] is None


def test_keyword_in_two_clusters_is_sent_once_and_keeps_primary():
    """`UPDATE ... FROM` picks an arbitrary match when a target row is named
    twice, so the payload must fold to one row per keyword. The old loop applied
    primary flags in a final pass, so primary-anywhere wins; cluster linkage was
    last-write-wins."""
    articles = [
        _article("shared kw", [], serp=["https://x.test"]),  # primary of cluster 0
        _article("other kw", ["shared kw"]),  # supporting in cluster 1
    ]
    kw_index = {"shared kw": "kid-s", "other kw": "kid-o"}

    rows = _link_payloads(_run_persist(articles, kw_index))
    shared = [r for r in rows if r["keyword_id"] == "kid-s"]

    assert len(shared) == 1, "a keyword must appear at most once per payload"
    assert shared[0]["is_primary"] is True
    assert shared[0]["serp_top_urls"] == ["https://x.test"]


def test_keyword_missing_from_the_index_is_skipped():
    """A primary the orchestrator named but that has no keyword row must not
    produce a linkage row (the old code guarded on `if pkid`)."""
    articles = [_article("ghost kw", ["supp a"])]
    kw_index = {"supp a": "kid-a"}

    rows = _link_payloads(_run_persist(articles, kw_index))

    assert [r["keyword_id"] for r in rows] == ["kid-a"]
    assert rows[0]["is_primary"] is False


def test_empty_plan_sends_no_linkage_requests():
    calls = _run_persist([], {})
    assert not [c for c in calls if c[1].endswith("/rpc/bulk_link_keywords_to_clusters")]


# --- reset_article_planning ------------------------------------------------
#
# Six foreign keys point at `clusters` (keywords, coverage_gaps, briefs,
# keyword_analyses, article_outputs, scheduled_article_runs), so every deleted
# row fires six trigger checks. Deleting a whole session's clusters in one
# statement measured ~3.6s warm at 4,043 clusters — inside the 8s
# statement_timeout, but not by enough. The 2026-07-31 tirzepatide re-plan blew
# it cold and died with `57014: canceling statement due to statement timeout`,
# and because reset runs *between* planning and persistence it threw away the
# orchestrator spend that had already completed.


def _run_reset(cluster_ids):
    calls: list[tuple[str, str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, str(request.url.query)))
        return httpx.Response(
            200, headers={"Content-Type": "application/json"}, content=b"[]"
        )

    with (
        patch.object(silo, "get_service_client", return_value=_client_with_transport(handler)),
        patch.object(silo, "list_topics", return_value=[{"id": "t1"}]),
        patch.object(silo, "_session_cluster_ids", return_value=cluster_ids),
    ):
        silo.reset_article_planning("sess-1")
    return calls


def test_cluster_delete_is_batched():
    ids = [f"cid-{i}" for i in range(4043)]

    calls = _run_reset(ids)
    deletes = [c for c in calls if c[0] == "DELETE" and c[1].endswith("/clusters")]

    # 4,043 clusters / 500 per statement == 9 DELETEs, none of them unbounded.
    assert len(deletes) == 9
    # Every batch filters on explicit ids, never on topic_id (the old whole-session
    # statement, which is the one that timed out).
    for _method, _path, query in deletes:
        assert "id=in." in query
        assert "topic_id" not in query


def test_reset_with_no_clusters_issues_no_delete():
    calls = _run_reset([])
    assert not [c for c in calls if c[0] == "DELETE" and c[1].endswith("/clusters")]


def test_session_cluster_ids_pages_past_the_postgrest_default():
    """A large plan runs to several thousand clusters; PostgREST caps a plain
    select at 1000 rows, so a single unpaged read would silently under-delete."""
    pages = [
        [{"id": f"cid-{i}"} for i in range(1000)],
        [{"id": f"cid-{1000 + i}"} for i in range(1000)],
        [{"id": f"cid-{2000 + i}"} for i in range(43)],
    ]
    seen_ranges: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen_ranges.append(request.headers.get("range", "") or str(request.url.query))
        body = pages[len(seen_ranges) - 1]
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            content=json.dumps(body).encode(),
        )

    with patch.object(silo, "get_service_client", return_value=_client_with_transport(handler)):
        ids = silo._session_cluster_ids(["t1"])

    assert len(ids) == 2043
    assert ids[0] == "cid-0" and ids[-1] == "cid-2042"
    # Stopped on the short page rather than looping forever.
    assert len(seen_ranges) == 3
