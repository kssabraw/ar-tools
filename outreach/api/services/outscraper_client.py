"""Outscraper API client — Google Maps base pull only.

Endpoint paths and parameter names were verified against the official outscraper-python SDK
v6.0.4 (commit 2026-06-11), which is the authoritative live client. THE PHASE 1 BRIEF IS STALE
HERE and the differences are not cosmetic:

  * The endpoint is POST /google-maps-search. It is not /maps/search-v3, and /maps/search is the
    deprecated v1.
  * Body parameters are camelCase: organizationsPerQueryLimit, skipPlaces, dropDuplicates.
  * Errors are returned as HTTP 2xx with {"error": true, "errorMessage": ...} in the body.
    Checking the status code alone silently swallows them.
  * A completed async response is retained for TWO HOURS. Persist raw on arrival.

Base tier only. `enrichment` is never sent — enrichments are billed separately and belong to
Phase 5 (brief §2).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..config import Settings

logger = logging.getLogger(__name__)

MAPS_SEARCH_PATH = "/google-maps-search"
REQUEST_ARCHIVE_PATH = "/requests/{request_id}"

# Outscraper reports a still-running request with this status. Anything else is terminal.
PENDING_STATUS = "Pending"


class OutscraperError(RuntimeError):
    """Any failure talking to Outscraper, including body-level errors returned with a 2xx."""


class OutscraperTimeout(OutscraperError):
    """An async request did not leave Pending inside the poll timeout."""


@dataclass
class TileRequest:
    """One query in the category x geography fan-out.

    `coordinates` biases the search centre. Note there is NO radius parameter in the API — the
    brief's "overlapping radii" is not expressible (ISSUES I-017). Overlap between adjacent tiles
    is real but implicit, and is resolved downstream by place_id dedup.
    """

    query: str
    coordinates: str | None = None
    submarket_id: str | None = None
    label: str = ""


@dataclass
class TileResult:
    tile: TileRequest
    places: list[dict[str, Any]] = field(default_factory=list)
    request_id: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


class OutscraperClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> "OutscraperClient":
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._settings.outscraper_request_timeout_seconds
            )
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    # -- transport ------------------------------------------------------------------------

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "X-API-KEY": self._settings.outscraper_api_key,
            "client": "ar-outreach-pipeline",
        }

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        """Issue a request, falling back across hosts on transport failure only.

        A 4xx/5xx is a real answer from a reachable host and must not trigger failover — retrying
        an authentication failure against two more hosts just produces three identical errors.
        """
        if self._client is None:
            raise OutscraperError("client used outside its async context manager")

        last_transport_error: Exception | None = None

        for base_url in self._settings.outscraper_base_urls:
            try:
                response = await self._client.request(
                    method, f"{base_url}{path}", headers=self._headers, **kwargs
                )
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                last_transport_error = exc
                logger.warning("outscraper host unreachable, failing over", extra={"host": base_url})
                continue

            return self._parse(response)

        raise OutscraperError(
            f"all Outscraper hosts unreachable: {last_transport_error!r}"
        ) from last_transport_error

    @staticmethod
    def _parse(response: httpx.Response) -> dict[str, Any]:
        if not (200 <= response.status_code < 300):
            raise OutscraperError(
                f"Outscraper returned HTTP {response.status_code}: {response.text[:500]}"
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise OutscraperError("Outscraper returned a non-JSON body") from exc

        if not isinstance(body, dict):
            raise OutscraperError(f"expected a JSON object, got {type(body).__name__}")

        # 2xx does not mean success. This is the trap the brief did not mention.
        if body.get("error"):
            raise OutscraperError(f"Outscraper error: {body.get('errorMessage')!r}")

        return body

    # -- maps search ----------------------------------------------------------------------

    async def submit_maps_search(self, tile: TileRequest, limit: int | None = None) -> str:
        """Submit one tile as an async request and return its request id.

        Synchronous calls time out at market scale (brief §2), so `async` is always true.
        """
        payload: dict[str, Any] = {
            "query": [tile.query],
            "organizationsPerQueryLimit": limit or self._settings.outscraper_places_per_query_limit,
            "language": self._settings.outscraper_language,
            "region": self._settings.outscraper_region,
            "async": True,
            # Dedup happens in our own code across ALL tiles, keyed on place_id. Outscraper's
            # dropDuplicates only spans queries inside one request, so it would not catch the
            # overlap between separately submitted tiles.
            "dropDuplicates": False,
            # Base tier only. Enrichments are billed separately and belong to Phase 5.
            # Do not populate this, and do not add a config flag that would let someone else.
            "enrichment": "",
        }
        if tile.coordinates:
            payload["coordinates"] = tile.coordinates

        body = await self._request("POST", MAPS_SEARCH_PATH, json=payload)

        request_id = body.get("id")
        if not request_id:
            raise OutscraperError(f"async submission returned no request id: {body!r}")

        logger.info(
            "outscraper tile submitted",
            extra={"request_id": request_id, "query": tile.query, "label": tile.label},
        )
        return str(request_id)

    async def fetch_result(self, request_id: str) -> dict[str, Any]:
        """Poll GET /requests/{id} until the request leaves Pending.

        Returns the full archive body. The caller persists it before parsing anything —
        re-parsing stored raw is free, re-pulling is not, and the archive expires in 2 hours.
        """
        deadline = time.monotonic() + self._settings.outscraper_poll_timeout_seconds
        path = REQUEST_ARCHIVE_PATH.format(request_id=request_id)

        while True:
            body = await self._request("GET", path)

            if body.get("status") != PENDING_STATUS:
                return body

            if time.monotonic() >= deadline:
                raise OutscraperTimeout(
                    f"request {request_id} still Pending after "
                    f"{self._settings.outscraper_poll_timeout_seconds}s"
                )

            await asyncio.sleep(self._settings.outscraper_poll_interval_seconds)


def extract_places(archive_body: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull the place dicts out of an archive response.

    The maps search nests results one level per query — `data` is a list of per-query lists. We
    submit one query per tile, but tolerate both shapes rather than assuming.
    """
    data = archive_body.get("data")
    if not isinstance(data, list):
        return []

    places: list[dict[str, Any]] = []
    for entry in data:
        if isinstance(entry, list):
            places.extend(item for item in entry if isinstance(item, dict))
        elif isinstance(entry, dict):
            places.append(entry)

    return places
