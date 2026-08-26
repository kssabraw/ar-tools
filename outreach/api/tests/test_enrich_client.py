"""The enrichment client's ASYNC submit+poll contract (I-109).

Enrichments run asynchronously on Outscraper: a synchronous (`async=false`) call returns the base
Maps record BEFORE the enrichers finish, so it carries no emails/contacts/people — which is exactly
why the live Enrich only ever produced the business name. `enrich_client._enrich_one` must therefore
submit `async=true` and poll the archive to completion. These pin that behaviour without any real
transport: the submit carries `async=true` + the enrichment set, the archive is polled past
`Pending`, the parsed records are tagged by place_id, and the degenerate responses fail per-place
rather than silently vanishing.
"""

import asyncio

from api.services import enrich_client
from api.services.outscraper_client import (
    ENDPOINT_MAPS_SEARCH,
    ENDPOINT_SEARCH_V3,
    OutscraperClient,
)


class _Settings:
    outscraper_search_endpoint = ENDPOINT_SEARCH_V3
    outscraper_language = "en"
    outscraper_region = "US"
    outscraper_api_key = "k"
    outscraper_base_urls = ["https://api.example"]
    outscraper_poll_interval_seconds = 0.0  # no real sleep between polls
    outscraper_poll_timeout_seconds = 60.0
    outscraper_request_timeout_seconds = 60.0
    enrich_poll_timeout_seconds = 30.0
    enrich_request_timeout_seconds = 60.0
    enrich_chunk_size = 4


def _install(monkeypatch, script):
    """Drive OutscraperClient._request from `script(method, path, kwargs) -> body`. Returns the
    call log so a test can assert what went over the wire."""
    calls = []

    async def _request(self, method, path, **kwargs):  # noqa: ANN001
        calls.append((method, path, kwargs))
        return script(method, path, kwargs)

    monkeypatch.setattr(OutscraperClient, "_request", _request)
    return calls


def test_enrich_submits_async_and_polls_the_archive(monkeypatch):
    record = {
        "name": "Enhanced Hearing Center",
        "emails": [{"value": "rex@enhancedhearingcenter.com", "full_name": "Rex Mcgee",
                    "title": "owner"}],
    }
    polls = {"n": 0}

    def script(method, path, kwargs):
        if path == ENDPOINT_SEARCH_V3:                      # the submit
            assert method == "GET"
            assert kwargs["params"]["async"] == "true"     # NOT "false" — the whole fix
            assert kwargs["params"]["enrichment"] == "domains_service,emails_validator_service"
            assert kwargs["params"]["query"] == "place-1"
            return {"id": "req-1", "status": "Pending"}
        if path == "/requests/req-1":                       # the poll
            polls["n"] += 1
            if polls["n"] == 1:
                return {"status": "Pending"}                # still running → poll again
            return {"status": "Success", "data": [[record]]}
        raise AssertionError(f"unexpected path {path}")

    _install(monkeypatch, script)

    records, errors = asyncio.run(enrich_client.enrich_places(
        _Settings(), ["place-1"], enrichments=["domains_service", "emails_validator_service"]))

    assert errors == []
    assert len(records) == 1
    assert records[0]["name"] == "Enhanced Hearing Center"
    assert records[0]["emails"][0]["full_name"] == "Rex Mcgee"
    assert records[0][enrich_client.PLACE_TAG] == "place-1"   # tagged back to the prospect
    assert polls["n"] == 2                                    # polled PAST the first Pending


def test_the_post_endpoint_submits_async_true_as_a_bool(monkeypatch):
    settings = _Settings()
    settings.outscraper_search_endpoint = ENDPOINT_MAPS_SEARCH

    def script(method, path, kwargs):
        if path == ENDPOINT_MAPS_SEARCH:
            assert method == "POST"
            assert kwargs["json"]["async"] is True          # bool on the JSON body, not a string
            assert kwargs["json"]["enrichment"] == ["domains_service"]
            assert kwargs["json"]["query"] == ["place-1"]
            return {"id": "r2"}
        if path == "/requests/r2":
            return {"status": "Success", "data": [[{"name": "Y"}]]}
        raise AssertionError(f"unexpected path {path}")

    _install(monkeypatch, script)

    records, errors = asyncio.run(
        enrich_client.enrich_places(settings, ["place-1"], enrichments=["domains_service"]))
    assert errors == []
    assert records[0]["name"] == "Y"
    assert records[0][enrich_client.PLACE_TAG] == "place-1"


def test_a_submit_with_no_id_but_inline_data_is_used(monkeypatch):
    # Defensive fallback: a response that already carries data (no async id) is used as-is.
    def script(method, path, kwargs):
        if path == ENDPOINT_SEARCH_V3:
            return {"data": [[{"name": "Inline Co"}]]}
        raise AssertionError(f"unexpected path {path}")

    _install(monkeypatch, script)
    records, errors = asyncio.run(
        enrich_client.enrich_places(_Settings(), ["p1"], enrichments=["domains_service"]))
    assert errors == []
    assert len(records) == 1 and records[0][enrich_client.PLACE_TAG] == "p1"


def test_a_submit_with_no_id_and_no_data_is_a_per_place_error(monkeypatch):
    # No id AND no data is a real fault — surfaced as a per-place error, never swallowed.
    def script(method, path, kwargs):
        return {"status": "Pending"}

    _install(monkeypatch, script)
    records, errors = asyncio.run(
        enrich_client.enrich_places(_Settings(), ["p1"], enrichments=["domains_service"]))
    assert records == []
    assert len(errors) == 1 and errors[0].startswith("p1:")


def test_a_per_place_failure_is_isolated_not_fatal(monkeypatch):
    good = {"name": "Good Co"}

    def script(method, path, kwargs):
        # place-boom's submit errors; place-ok flows through submit → poll.
        if path == ENDPOINT_SEARCH_V3:
            if kwargs["params"]["query"] == "boom":
                raise enrich_client.OutscraperError("provider 500")
            return {"id": "ok-1"}
        if path == "/requests/ok-1":
            return {"status": "Success", "data": [[good]]}
        raise AssertionError(f"unexpected path {path}")

    _install(monkeypatch, script)
    records, errors = asyncio.run(
        enrich_client.enrich_places(_Settings(), ["ok", "boom"], enrichments=["domains_service"]))
    assert [r["name"] for r in records] == ["Good Co"]
    assert len(errors) == 1 and errors[0].startswith("boom:")
