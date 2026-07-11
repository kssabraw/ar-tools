"""DataForSEO Backlinks API client — the data layer for the backlink explorer
tool (Ahrefs Site Explorer analog).

Wraps the backlinks endpoint *family* (the rest of the suite only ever called
``/v3/backlinks/summary/live`` via ``serp_snapshot``):

  * summary            → the Overview card (RD, backlinks, dofollow, DR)
  * referring_domains  → the Referring Domains table (one row per domain)
  * anchors            → the anchor-text distribution
  * history            → the RD/backlinks trend series
  * backlinks          → the individual-link list (paginated, filterable)

Cost note: the ``backlinks`` endpoint bills per returned row, so callers default
to ``mode="one_per_domain"`` (collapses a domain's N links to 1). The other
endpoints are cheap. All ``rank`` values are 0–1000; the suite-wide convention
is DR/UR = rank ÷ 10 (0–100) — applied here at parse time so callers never see
the raw 0–1000 scale.

Parse helpers are pure (no I/O) and independently unit-tested; fetch helpers do
the HTTP with 429/5xx retry + backoff.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import secrets
from typing import Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.dataforseo.com"
_SUMMARY_PATH = "/v3/backlinks/summary/live"
_REFERRING_DOMAINS_PATH = "/v3/backlinks/referring_domains/live"
_ANCHORS_PATH = "/v3/backlinks/anchors/live"
_DOMAIN_PAGES_PATH = "/v3/backlinks/domain_pages/live"
_HISTORY_PATH = "/v3/backlinks/history/live"
_BACKLINKS_PATH = "/v3/backlinks/backlinks/live"
_TIMEOUT = 60.0

_DFS_MAX_RETRIES = 3
_DFS_RETRY_BASE_SECONDS = 2.0

# Valid link-list modes on the backlinks endpoint (one_per_subdomain is NOT a
# native mode — only these three). one_per_domain is the cheap default.
LINK_MODES = ("as_is", "one_per_domain", "one_per_anchor")


def _auth_header() -> dict[str, str]:
    creds = f"{settings.dataforseo_login}:{settings.dataforseo_password}"
    encoded = base64.b64encode(creds.encode()).decode()
    return {"Authorization": f"Basic {encoded}", "Content-Type": "application/json"}


def _rank_to_rating(rank) -> Optional[float]:
    """DataForSEO rank (0–1000) → the suite's DR/UR proxy (0–100)."""
    if rank is None:
        return None
    try:
        return round(float(rank) / 10.0, 1)
    except (TypeError, ValueError):
        return None


# ----------------------------------------------------------------------------
# Pure parse helpers (no I/O) — independently unit-tested.
# ----------------------------------------------------------------------------
def _first_result(body: dict, error_prefix: str) -> dict:
    """The single result object from a DataForSEO backlinks response, or raise."""
    tasks = body.get("tasks") or []
    if not tasks or (tasks[0].get("status_code") or 0) >= 40000:
        msg = tasks[0].get("status_message") if tasks else "no tasks"
        raise RuntimeError(f"{error_prefix}: {msg}")
    return (tasks[0].get("result") or [{}])[0] or {}


def _items(result: dict) -> list[dict]:
    return result.get("items") or []


def parse_summary(body: dict) -> dict:
    """Overview metrics for a target. dofollow is derived (total − nofollow)."""
    r = _first_result(body, "dataforseo_backlinks_summary_error")
    backlinks = r.get("backlinks")
    nofollow = r.get("backlinks_nofollow")
    dofollow = (backlinks - nofollow) if isinstance(backlinks, int) and isinstance(nofollow, int) else None
    return {
        "target": r.get("target"),
        "referring_domains": r.get("referring_domains"),
        "referring_main_domains": r.get("referring_main_domains"),
        "backlinks": backlinks,
        "dofollow": dofollow,
        "nofollow": nofollow,
        "broken_backlinks": r.get("broken_backlinks"),
        "referring_ips": r.get("referring_ips"),
        "referring_subnets": r.get("referring_subnets"),
        "domain_rating": _rank_to_rating(r.get("rank")),
        "first_seen": r.get("first_seen"),
        "lost_date": r.get("lost_date"),
    }


def parse_referring_domains(body: dict) -> list[dict]:
    """One row per referring domain (DR, links, dofollow, first/lost seen)."""
    out: list[dict] = []
    for it in _items(_first_result(body, "dataforseo_backlinks_referring_domains_error")):
        backlinks = it.get("backlinks")
        nofollow = it.get("backlinks_nofollow")
        dofollow = (backlinks - nofollow) if isinstance(backlinks, int) and isinstance(nofollow, int) else None
        lost = it.get("lost_date")
        out.append(
            {
                "domain": it.get("domain"),
                "domain_rating": _rank_to_rating(it.get("rank")),
                "backlinks": backlinks,
                "dofollow": dofollow,
                "first_seen": it.get("first_seen"),
                "last_seen": lost or it.get("last_seen"),
                "is_lost": bool(lost),
                "is_new": bool(it.get("is_new")),
            }
        )
    return out


def parse_anchors(body: dict) -> list[dict]:
    """Anchor-text distribution (anchor, links, referring domains)."""
    out: list[dict] = []
    for it in _items(_first_result(body, "dataforseo_backlinks_anchors_error")):
        backlinks = it.get("backlinks")
        nofollow = it.get("backlinks_nofollow")
        dofollow = (backlinks - nofollow) if isinstance(backlinks, int) and isinstance(nofollow, int) else None
        out.append(
            {
                "anchor": it.get("anchor"),
                "backlinks": backlinks,
                "referring_domains": it.get("referring_domains"),
                "dofollow": dofollow,
                "first_seen": it.get("first_seen"),
            }
        )
    return out


def parse_domain_pages(body: dict) -> list[dict]:
    """Per-page authority breakdown of a domain target ("Best by links"):
    one row per page — UR (rank ÷ 10), referring domains, backlinks."""
    out: list[dict] = []
    for it in _items(_first_result(body, "dataforseo_backlinks_domain_pages_error")):
        url = it.get("url") or it.get("page_address")
        if not url:
            continue
        out.append(
            {
                "url": url,
                "page_rating": _rank_to_rating(it.get("rank")),
                "referring_domains": it.get("referring_domains"),
                "backlinks": it.get("backlinks"),
                "first_seen": it.get("first_seen"),
            }
        )
    return out


def parse_history(body: dict) -> list[dict]:
    """Monthly RD/backlinks series for the trend chart."""
    out: list[dict] = []
    for it in _items(_first_result(body, "dataforseo_backlinks_history_error")):
        out.append(
            {
                "date": it.get("date"),
                "referring_domains": it.get("referring_domains"),
                "backlinks": it.get("backlinks"),
                "domain_rating": _rank_to_rating(it.get("rank")),
                "new_referring_domains": it.get("new_referring_domains"),
                "lost_referring_domains": it.get("lost_referring_domains"),
                "new_backlinks": it.get("new_backlinks"),
                "lost_backlinks": it.get("lost_backlinks"),
            }
        )
    return out


def parse_backlinks(body: dict) -> dict:
    """The individual-link list + the total_count for pagination."""
    r = _first_result(body, "dataforseo_backlinks_list_error")
    links: list[dict] = []
    for it in _items(r):
        links.append(
            {
                "url_from": it.get("url_from"),
                "domain_from": it.get("domain_from"),
                "url_to": it.get("url_to"),
                "anchor": it.get("anchor"),
                "dofollow": it.get("dofollow"),
                "domain_rating": _rank_to_rating(it.get("domain_from_rank")),
                "page_rating": _rank_to_rating(it.get("page_from_rank")),
                "first_seen": it.get("first_seen"),
                "last_seen": it.get("last_seen"),
                "is_new": bool(it.get("is_new")),
                "is_lost": bool(it.get("is_lost")),
                "is_broken": bool(it.get("is_broken")),
            }
        )
    return {"total_count": r.get("total_count"), "links": links}


# ----------------------------------------------------------------------------
# Fetch (I/O) — 429/5xx retry with jittered backoff.
# ----------------------------------------------------------------------------
async def _post(path: str, payload: list[dict]) -> dict:
    attempt = 0
    while True:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(f"{_BASE_URL}{path}", headers=_auth_header(), json=payload)
        if resp.status_code == 429 or resp.status_code >= 500:
            if attempt >= _DFS_MAX_RETRIES:
                resp.raise_for_status()
            try:
                retry_after = float(resp.headers.get("Retry-After") or 0)
            except ValueError:
                retry_after = 0.0
            delay = max(
                retry_after,
                _DFS_RETRY_BASE_SECONDS * (2 ** attempt) * (0.5 + secrets.randbelow(1000) / 1000.0),
            )
            logger.warning("backlinks_dfs_retry", extra={"path": path, "status": resp.status_code,
                                                          "attempt": attempt + 1, "delay_s": round(delay, 1)})
            await asyncio.sleep(delay)
            attempt += 1
            continue
        resp.raise_for_status()
        return resp.json()


def _include_subdomains(target_type: str) -> bool:
    # Whole-domain metrics include subdomains; a subdomain/url target does not.
    return target_type == "domain"


async def fetch_summary(target: str, target_type: str = "domain") -> dict:
    payload = [{"target": target, "internal_list_limit": 1, "backlinks_status_type": "live",
                "include_subdomains": _include_subdomains(target_type)}]
    return parse_summary(await _post(_SUMMARY_PATH, payload))


async def fetch_referring_domains(target: str, target_type: str = "domain", limit: int = 100) -> list[dict]:
    payload = [{"target": target, "limit": limit, "backlinks_status_type": "live",
                "include_subdomains": _include_subdomains(target_type),
                "order_by": ["rank,desc"]}]
    return parse_referring_domains(await _post(_REFERRING_DOMAINS_PATH, payload))


async def fetch_anchors(target: str, target_type: str = "domain", limit: int = 100) -> list[dict]:
    payload = [{"target": target, "limit": limit, "internal_list_limit": 1,
                "backlinks_status_type": "live", "include_subdomains": _include_subdomains(target_type),
                "order_by": ["backlinks,desc"]}]
    return parse_anchors(await _post(_ANCHORS_PATH, payload))


async def fetch_domain_pages(target: str, target_type: str = "domain", limit: int = 100) -> list[dict]:
    payload = [{"target": target, "limit": limit, "internal_list_limit": 1,
                "backlinks_status_type": "live",
                "include_subdomains": _include_subdomains(target_type),
                "order_by": ["referring_domains,desc"]}]
    return parse_domain_pages(await _post(_DOMAIN_PAGES_PATH, payload))


async def fetch_history(target: str, target_type: str = "domain", date_from: Optional[str] = None) -> list[dict]:
    payload: dict = {"target": target, "backlinks_status_type": "live"}
    if date_from:
        payload["date_from"] = date_from
    return parse_history(await _post(_HISTORY_PATH, [payload]))


async def fetch_backlinks(
    target: str,
    target_type: str = "domain",
    mode: str = "one_per_domain",
    limit: int = 100,
    offset: int = 0,
    filters: Optional[list] = None,
) -> dict:
    """Individual-link list. `filters` is a DataForSEO filter expression
    (e.g. [["dofollow", "=", True]] or [["is_broken", "=", True]])."""
    if mode not in LINK_MODES:
        mode = "one_per_domain"
    payload: dict = {
        "target": target,
        "mode": mode,
        "limit": limit,
        "offset": offset,
        "backlinks_status_type": "live",
        "include_subdomains": _include_subdomains(target_type),
        "order_by": ["domain_from_rank,desc"],
    }
    if filters:
        payload["filters"] = filters
    return parse_backlinks(await _post(_BACKLINKS_PATH, [payload]))
