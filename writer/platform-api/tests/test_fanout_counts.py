"""Regression test for the fanout `_count` helper (storage/silo.py).

The pinned postgrest (0.17.x via supabase 2.9.1) discards the Content-Range
total on HEAD responses: an empty body raises JSONDecodeError inside
`APIResponse.from_http_request_response`, which short-circuits to `count=0`
before the header is parsed. So every `head=True` count silently read 0 —
in the fanout pipeline summary that made the post-clustering settling guard
report a *finished* session as `running` forever (the UI span "still
running" until a manual DB check).

`_count` must therefore issue a GET (body present -> count parsed from
Content-Range) with limit(1) so only one row is transferred. This test wires
the real supabase/postgrest client to an httpx.MockTransport and asserts
both halves.
"""

from unittest.mock import patch

import httpx
import pytest

pytest.importorskip("supabase")

from fanout.storage import silo  # noqa: E402


def _client_with_transport(handler):
    """A real supabase client whose PostgREST session runs on a mock transport."""
    from supabase import create_client

    # create_client validates the key is JWT-shaped; any three-segment token works.
    fake_jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.c2ln"
    client = create_client("http://mock.local", fake_jwt)
    client.postgrest.session._transport = httpx.MockTransport(handler)
    return client


def test_count_issues_get_and_parses_content_range_total():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["prefer"] = request.headers.get("prefer", "")
        # PostgREST: limit(1) caps the body at one row; Content-Range still
        # carries the exact total (206 = partial range, the >1-row case).
        return httpx.Response(
            206,
            headers={"Content-Range": "0-0/27537", "Content-Type": "application/json"},
            content=b'[{"id":"x"}]',
        )

    with patch.object(silo, "get_service_client", return_value=_client_with_transport(handler)):
        assert silo._count("keywords", session_id="s1", status="active") == 27537

    # A HEAD request would lose the count under the pinned postgrest — the
    # helper must fetch with a body.
    assert seen["method"] == "GET"
    assert "count=exact" in seen["prefer"]


def test_count_zero_rows_reads_zero():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Range": "*/0", "Content-Type": "application/json"},
            content=b"[]",
        )

    with patch.object(silo, "get_service_client", return_value=_client_with_transport(handler)):
        assert silo._count("keywords", session_id="none") == 0


def test_count_transfers_at_most_one_row():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["range"] = request.headers.get("range", "")
        seen["url"] = str(request.url)
        return httpx.Response(
            206,
            headers={"Content-Range": "0-0/1919", "Content-Type": "application/json"},
            content=b'[{"id":"x"}]',
        )

    with patch.object(silo, "get_service_client", return_value=_client_with_transport(handler)):
        assert silo._count("keywords", session_id="s1") == 1919

    # limit(1) rides either the Range header or a limit=1 query param depending
    # on the client version — accept both, but one must be present.
    assert seen["range"] == "0-0" or "limit=1" in seen["url"]
