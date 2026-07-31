"""Regression tests for paged cluster reads + batched slug writes (storage/silo.py).

PostgREST truncates an unpaged select at 1000 rows *silently* — no error, and the
client surfaces no partial-content signal. Several whole-session cluster reads
were unpaged, so everything past the first 1000 clusters was invisible to the
callers that matter. That is not hypothetical; it was already in the data:

    session       clusters   slugged   scheduled
    semaglutide      1,594     1,000       1,000
    retatrutide      1,413     1,000       1,000

Exactly 1000 both times. `list_clusters_link_info` fed slug assignment and
`list_clusters` fed the schedule's target list, so ~1,000 planned articles across
those two sessions were never slugged and never scheduled. At the tirzepatide
session's 3,896 clusters it would have hidden ~74% of the plan.

Paging alone would have made things worse in a different way: `ensure_session_slugs`
writes one UPDATE per cluster, and the 1000-row truncation was the only thing
keeping that under the ~4,100-request HTTP/2 ceiling that killed the article-plan
linkage. So the write is batched through `bulk_set_cluster_slugs` at the same time.
"""

import json
from unittest.mock import patch

import httpx
import pytest

pytest.importorskip("supabase")

from fanout.storage import silo  # noqa: E402


def _client_with_transport(handler):
    from supabase import create_client

    fake_jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.c2ln"
    client = create_client("http://mock.local", fake_jwt)
    client.postgrest.session._transport = httpx.MockTransport(handler)
    return client


def _paging_handler(total: int, rows_for):
    """Serve `total` rows across 1000-row pages, recording each request."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        start = (len(calls) - 1) * 1000
        body = rows_for(start, min(start + 1000, total))
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            content=json.dumps(body).encode(),
        )

    return handler, calls


def test_paged_cluster_rows_fetches_past_1000():
    total = 3896  # the real tirzepatide plan size

    handler, calls = _paging_handler(
        total, lambda a, b: [{"id": f"cid-{i}"} for i in range(a, b)]
    )
    with patch.object(silo, "get_service_client", return_value=_client_with_transport(handler)):
        rows = silo.paged_cluster_rows(["t1"], "id")

    assert len(rows) == total, "unpaged read would have stopped at 1000"
    assert rows[0]["id"] == "cid-0"
    assert rows[-1]["id"] == f"cid-{total - 1}"
    # 3,896 rows -> 4 requests (1000, 1000, 1000, 896 short page ends it).
    assert len(calls) == 4


def test_paged_cluster_rows_stops_on_exact_multiple():
    """A final page that is exactly full must trigger one more read, and that
    empty read must terminate the loop rather than spin."""
    total = 2000

    handler, calls = _paging_handler(
        total, lambda a, b: [{"id": f"cid-{i}"} for i in range(a, b)]
    )
    with patch.object(silo, "get_service_client", return_value=_client_with_transport(handler)):
        rows = silo.paged_cluster_rows(["t1"], "id")

    assert len(rows) == total
    assert len(calls) == 3  # 1000, 1000, then an empty page


def test_paged_cluster_rows_always_orders_by_id():
    """Clusters are bulk-inserted, so created_at ties across a whole batch. Paging
    on an unstable sort would overlap pages and silently drop rows, so `id` must
    always be present as a tiebreak."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url.query))
        return httpx.Response(200, headers={"Content-Type": "application/json"}, content=b"[]")

    with patch.object(silo, "get_service_client", return_value=_client_with_transport(handler)):
        silo.paged_cluster_rows(["t1"], "id, name", order="created_at")

    assert "order=" in seen[0]
    assert "created_at" in seen[0] and "id" in seen[0]


def test_ensure_session_slugs_batches_writes():
    """One RPC per 500 changed clusters, not one UPDATE per cluster."""
    total = 3896
    clusters = [
        {"id": f"cid-{i}", "topic_id": "t1", "name": f"keyword {i}",
         "primary_keyword_id": None, "slug": None}
        for i in range(total)
    ]
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        return httpx.Response(200, headers={"Content-Type": "application/json"}, content=b"[]")

    with (
        patch.object(silo, "get_service_client", return_value=_client_with_transport(handler)),
        patch.object(silo, "list_clusters_link_info", return_value=clusters),
        patch.object(silo, "get_keyword_texts", return_value={}),
    ):
        result = silo.ensure_session_slugs("sess-1")

    assert len(result) == total, "every cluster must get a slug, not just the first 1000"

    rpc = [c for c in calls if c[1].endswith("/rpc/bulk_set_cluster_slugs")]
    assert len(rpc) == 8, f"expected ceil(3896/500)=8 batched writes, got {len(rpc)}"
    # The per-cluster PATCH is exactly what blew the HTTP/2 connection.
    assert not [c for c in calls if c[0] == "PATCH"]


def test_ensure_session_slugs_skips_unchanged():
    """Idempotent: a second run writes nothing (drip-safe — a target's URL is
    fixed before it's generated)."""
    clusters = [
        {"id": "cid-1", "topic_id": "t1", "name": "tirzepatide dosage",
         "primary_keyword_id": None, "slug": "tirzepatide-dosage"},
    ]
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, headers={"Content-Type": "application/json"}, content=b"[]")

    with (
        patch.object(silo, "get_service_client", return_value=_client_with_transport(handler)),
        patch.object(silo, "list_clusters_link_info", return_value=clusters),
        patch.object(silo, "get_keyword_texts", return_value={}),
    ):
        result = silo.ensure_session_slugs("sess-1")

    assert result == {"cid-1": "tirzepatide-dosage"}
    assert not [c for c in calls if c.endswith("/rpc/bulk_set_cluster_slugs")]
