"""SIE Module 4: page scraping via ScrapeOwl (new service, key provisioned
2026-06-15). JS rendering on; retries; per-page scrape_status + failure reason.

Follows the DataForSEO client shape: structured external_call log (§16.3), cost
metered via `record_cost` (estimate until first invoices), cooperative
cancellation between scrapes.

A standard scrape is tried first. A 5xx (server-side render/proxy failure — usually
target-side bot protection) escalates that one URL to premium/residential proxies
once (costs more), so we only pay for premium on pages that actually need it.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ScrapeResult:
    url: str
    html: str | None
    text: str | None
    markdown: str | None
    scrape_status: str           # "success" | "failed"
    failure_reason: str | None = None


class ScrapeOwlError(Exception):
    pass


# PRD M4 failure reasons, mapped from HTTP/transport conditions.
def _failure_reason(status: int | None, exc: Exception | None) -> str:
    import httpx

    if isinstance(exc, httpx.TimeoutException):
        return "Timeout"
    if isinstance(exc, httpx.HTTPError):
        return "Scrape API error"
    if status in (403, 401):
        return "Blocked by robots or firewall"
    if status and status >= 400:
        return "HTTP error"
    return "Scrape API error"


def _note(mode: str | None, detail: str | None = None) -> str | None:
    return " ".join(p for p in (mode, detail) if p) or None


class ScrapeOwlClient:
    def __init__(
        self, api_key: str, base_url: str, *, cost_per_scrape: float = 0.0008,
        cost_per_scrape_premium: float = 0.005, premium_on_5xx: bool = True,
        timeout_s: float = 35.0, max_attempts: int = 3,
    ):
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._cost = cost_per_scrape
        self._cost_premium = cost_per_scrape_premium
        self._premium_on_5xx = premium_on_5xx
        self._timeout = timeout_s
        self._max_attempts = max(1, max_attempts)

    def scrape(self, url: str) -> ScrapeResult:
        """Scrape one URL (JS-rendered). Never raises for a single page — returns a
        failed ScrapeResult so the pipeline degrades per-page (PRD M4). A 5xx
        escalates to premium proxies once."""
        from fanout.cancellation import raise_if_cancelled

        raise_if_cancelled()
        result, status = self._scrape_once(url, premium=False)
        if (
            self._premium_on_5xx
            and result.scrape_status != "success"
            and status is not None
            and status >= 500
        ):
            # Server-side 5xx is usually target bot-protection; premium/residential
            # proxies get through most of it. Retry just this URL, once.
            result, _ = self._scrape_once(url, premium=True)
        return result

    def _scrape_once(self, url: str, *, premium: bool) -> tuple[ScrapeResult, int | None]:
        """One scrape mode (standard or premium). Returns (result, last_http_status)
        so the caller can decide whether to escalate."""
        import httpx  # lazy: keeps ScrapeResult importable without httpx

        from fanout.cost_meter import record_cost

        payload = {
            "api_key": self._api_key, "url": url, "render_js": True, "html": True,
        }
        if premium:
            payload["premium_proxies"] = True
        cost = self._cost_premium if premium else self._cost
        mode = "premium" if premium else None
        started = time.perf_counter()
        last_status: int | None = None
        last_exc: Exception | None = None
        for _attempt in range(self._max_attempts):
            try:
                resp = httpx.post(
                    f"{self._base_url}/scrape", json=payload, timeout=self._timeout
                )
                last_status = resp.status_code
                if resp.status_code >= 400:
                    # 4xx is persistent; a 5xx is handled by the caller's premium
                    # escalation rather than an in-mode retry. Either way, stop here.
                    last_exc = None
                    break
                try:
                    body = resp.json()
                except ValueError:
                    last_exc = None
                    break
                if not isinstance(body, dict):
                    self._log(url, resp.status_code, started, "failed", cost=cost,
                              note=_note(mode, f"non-dict body: {type(body).__name__}"))
                    return ScrapeResult(
                        url, None, None, None, "failed", "Unexpected scrape response shape"
                    ), resp.status_code
                html = body.get("html") or body.get("data")
                if not html or not isinstance(html, str):
                    # Log the keys so the real ScrapeOwl shape is visible on a miss.
                    self._log(url, resp.status_code, started, "failed", cost=cost,
                              note=_note(mode, f"no html; keys={sorted(body)[:8]}"))
                    return ScrapeResult(url, None, None, None, "failed", "Empty page"), resp.status_code
                record_cost(cost)
                self._log(url, resp.status_code, started, "success", cost=cost, note=mode)
                return ScrapeResult(
                    url=url, html=html,
                    text=body.get("text") if isinstance(body.get("text"), str) else None,
                    markdown=body.get("markdown") if isinstance(body.get("markdown"), str) else None,
                    scrape_status="success",
                ), resp.status_code
            except httpx.HTTPError as exc:
                last_exc = exc
        self._log(url, last_status, started, "failed", cost=cost, note=mode)
        return ScrapeResult(
            url, None, None, None, "failed", _failure_reason(last_status, last_exc)
        ), last_status

    def _log(
        self, url: str, status: int | None, started: float, outcome: str,
        *, cost: float | None = None, note: str | None = None,
    ) -> None:
        extra = {
            "event": "external_call", "service": "scrapeowl", "endpoint": "/scrape",
            "url": url, "status": status, "outcome": outcome,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "cost_usd": (cost if cost is not None else self._cost) if outcome == "success" else 0.0,
        }
        if note:
            extra["note"] = note
        logger.info("external_call", extra=extra)
