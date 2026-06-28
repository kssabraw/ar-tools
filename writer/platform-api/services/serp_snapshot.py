"""Competitive SERP Snapshot — diagnostic capture for ranking-drop analysis.

Organic Rank Tracker (Module #4). Captures a dated, stored snapshot of the SERP
for a tracked keyword so a ranking drop can be diagnosed after the fact. It is
NOT a user-facing feature — there is no viewer; snapshots are retrieved on
request via the API. Captured WEEKLY alongside the DataForSEO rank refresh so a
pre-drop baseline always exists.

Each snapshot records, for a keyword at a point in time:
  - the AI Overview (presence, text, cited sources),
  - the SERP feature inventory ("enhancements": local pack/GBP, PAA, forums,
    featured snippet, …),
  - the query intent (informational/commercial/transactional/navigational),
  - the top organic results (url / domain / rendered title + description /
    position), each enriched with referring domains + URL Rating (DataForSEO
    Backlinks page rank, 0–1000) — including the client's own ranking page,
  - and, per unique domain in the SERP (competitors + the client), the
    Domain Rating (DataForSEO Backlinks domain rank, 0–1000) — the whole-domain
    authority signal (PRD §14).

Sources (all DataForSEO, reusing the Basic-auth pattern from dataforseo_rank):
  - SERP advanced  (/v3/serp/google/organic/live/advanced) — AIO + organic + features
  - Labs search-intent  (/v3/dataforseo_labs/google/search_intent/live)
  - Backlinks summary  (/v3/backlinks/summary/live) — per target URL (UR) AND
    per target domain (DR)

Per-URL / per-domain / per-keyword failures are isolated and recorded, never
fatal to the batch (the same resilience as refresh_client_ranks).
"""

from __future__ import annotations

import base64
import logging
from datetime import date
from typing import Optional

import httpx

from config import settings
from db.supabase_client import get_supabase
from services.dataforseo_rank import extract_domain, location_code_for

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.dataforseo.com"
_SERP_PATH = "/v3/serp/google/organic/live/advanced"
_INTENT_PATH = "/v3/dataforseo_labs/google/search_intent/live"
_BACKLINKS_PATH = "/v3/backlinks/summary/live"
_TIMEOUT = 60.0


def _auth_header() -> dict[str, str]:
    creds = f"{settings.dataforseo_login}:{settings.dataforseo_password}"
    encoded = base64.b64encode(creds.encode()).decode()
    return {"Authorization": f"Basic {encoded}", "Content-Type": "application/json"}


def _domain_matches(item_domain: Optional[str], domain: str) -> bool:
    d = (item_domain or "").lower()
    return bool(domain) and (d == domain or d.endswith("." + domain))


# ----------------------------------------------------------------------------
# Pure parse helpers (no I/O) — independently unit-tested.
# ----------------------------------------------------------------------------
def extract_organic_results(items: list[dict], top_n: int) -> list[dict]:
    """Top `top_n` organic results: position, url, domain, rendered title + desc."""
    out: list[dict] = []
    for item in items:
        if item.get("type") != "organic":
            continue
        rank = item.get("rank_absolute") or item.get("rank_group")
        out.append(
            {
                "position": int(rank) if rank is not None else None,
                "url": item.get("url"),
                "domain": (item.get("domain") or "").lower() or None,
                "title": item.get("title"),
                "description": item.get("description"),
            }
        )
        if len(out) >= top_n:
            break
    return out


def find_client_organic(items: list[dict], domain: str) -> Optional[dict]:
    """The client's own organic result anywhere in the fetched depth (or None)."""
    if not domain:
        return None
    for item in items:
        if item.get("type") != "organic":
            continue
        if _domain_matches(item.get("domain"), domain):
            rank = item.get("rank_absolute") or item.get("rank_group")
            return {
                "position": int(rank) if rank is not None else None,
                "url": item.get("url"),
                "domain": (item.get("domain") or "").lower() or None,
                "title": item.get("title"),
                "description": item.get("description"),
            }
    return None


def collect_snapshot_domains(result_rows: list[dict], client_domain: str) -> list[dict]:
    """Deduped, ordered ``[{domain, is_client}, ...]`` to fetch Domain Rating for.

    The whole-domain authority targets for a snapshot: every distinct competitor
    domain among the captured ranking pages, plus exactly one row for the client's
    own domain (always included, even when the client doesn't rank in the fetched
    depth). The client's ranking page may surface on a www/subdomain host (e.g.
    ``www.acme.com``) while the canonical client domain is the bare ``acme.com``
    (``extract_domain`` strips ``www``); such hosts are folded into the single
    canonical client row rather than emitted as a separate (mislabelled) target —
    using the same suffix match as the rest of the module (``_domain_matches``).
    Competitor order is SERP order; the client row is appended last. Case-insensitive.
    """
    out: list[dict] = []
    seen: set[str] = set()
    cd = (client_domain or "").lower()
    for row in result_rows:
        domain = (row.get("domain") or "").lower()
        if not domain or domain in seen:
            continue
        seen.add(domain)
        if cd and _domain_matches(domain, cd):
            continue  # the client's own (sub)domain — folded into the cd row below
        out.append({"domain": domain, "is_client": False})
    if cd:
        out.append({"domain": cd, "is_client": True})
    return out


def _dedup_sources(sources: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for s in sources:
        url = s.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        out.append({"url": url, "domain": s.get("domain"), "title": s.get("title")})
    return out


def extract_aio(items: list[dict]) -> dict:
    """AI Overview presence, concatenated text, and deduped cited sources."""
    for item in items:
        if item.get("type") != "ai_overview":
            continue
        text_parts: list[str] = []
        sources: list[dict] = []
        for ref in item.get("references") or []:
            sources.append({"url": ref.get("url"), "domain": ref.get("domain"), "title": ref.get("title")})
        for sub in item.get("items") or []:
            if sub.get("text"):
                text_parts.append(sub["text"])
            for ref in sub.get("references") or []:
                sources.append({"url": ref.get("url"), "domain": ref.get("domain"), "title": ref.get("title")})
        return {
            "present": True,
            "text": "\n\n".join(text_parts) or None,
            "sources": _dedup_sources(sources),
        }
    return {"present": False, "text": None, "sources": []}


def extract_serp_features(items: list[dict]) -> dict:
    """SERP feature inventory ("enhancements"): the item types present plus
    captured detail for the notable ones (local pack/GBP, PAA, forums, snippet)."""
    feature_types: list[str] = []
    seen: set[str] = set()
    local_pack: list[dict] = []
    paa: list[str] = []
    forums: list[dict] = []
    featured: Optional[dict] = None
    for item in items:
        t = item.get("type")
        if not t or t == "organic":
            continue
        if t not in seen:
            seen.add(t)
            feature_types.append(t)
        if t == "local_pack":
            rating = item.get("rating")
            local_pack.append(
                {
                    "title": item.get("title"),
                    "domain": (item.get("domain") or "").lower() or None,
                    "rating": rating.get("value") if isinstance(rating, dict) else rating,
                }
            )
        elif t == "people_also_ask":
            for sub in item.get("items") or []:
                if sub.get("title"):
                    paa.append(sub["title"])
        elif t == "discussions_and_forums":
            for sub in item.get("items") or []:
                forums.append(
                    {"title": sub.get("title"), "url": sub.get("url"), "domain": sub.get("domain")}
                )
        elif t == "featured_snippet" and featured is None:
            featured = {"title": item.get("title"), "url": item.get("url"), "domain": item.get("domain")}
    return {
        "feature_types": feature_types,
        "local_pack": local_pack,
        "people_also_ask": paa,
        "discussions_and_forums": forums,
        "featured_snippet": featured,
    }


# SERP item types that signal Google treats the query as locally-intented.
_LOCAL_FEATURE_TYPES = {"local_pack", "local_finder", "map"}


def detect_local_intent(features: dict) -> bool:
    """Whether the query carries **local intent**, derived from the SERP feature
    inventory (extract_serp_features output): a local pack / local finder / map
    means Google surfaced geographic results. Cheap + reliable — no extra API
    call — and independent of the Labs search-intent call (whose taxonomy has no
    'local' label), so it still works when that call fails.
    """
    if not features:
        return False
    types = set(features.get("feature_types") or [])
    if types & _LOCAL_FEATURE_TYPES:
        return True
    # Defensive: local_pack detail captured even if feature_types somehow missed it.
    return bool(features.get("local_pack"))


def classify_intent(result_items: list[dict]) -> tuple[Optional[str], dict]:
    """Primary intent label + a {label: probability} map from a Labs
    search-intent result's items."""
    if not result_items:
        return None, {}
    first = result_items[0] or {}
    ki = first.get("keyword_intent") or {}
    label = ki.get("label")
    probs: dict[str, float] = {}
    if label and ki.get("probability") is not None:
        probs[label] = ki["probability"]
    for sec in first.get("secondary_keyword_intents") or []:
        sec_label = sec.get("label")
        if sec_label and sec.get("probability") is not None:
            probs.setdefault(sec_label, sec["probability"])
    return label, probs


def parse_backlinks_summary(body: dict) -> dict:
    """referring_domains + URL Rating (page rank 0–1000) + total backlinks."""
    tasks = body.get("tasks") or []
    if not tasks or (tasks[0].get("status_code") or 0) >= 40000:
        msg = tasks[0].get("status_message") if tasks else "no tasks"
        raise RuntimeError(f"dataforseo_backlinks_error: {msg}")
    result = (tasks[0].get("result") or [{}])[0] or {}
    return {
        "referring_domains": result.get("referring_domains"),
        "url_rating": result.get("rank"),
        "backlinks": result.get("backlinks"),
    }


# ----------------------------------------------------------------------------
# Fetch (I/O)
# ----------------------------------------------------------------------------
async def fetch_serp(keyword: str, location_code: int, language_code: str, depth: int) -> list[dict]:
    """Full SERP item list (AIO + organic + features) for `keyword`."""
    payload = [
        {
            "keyword": keyword,
            "language_code": language_code,
            "location_code": location_code,
            "depth": depth,
            "calculate_rectangles": False,
        }
    ]
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(f"{_BASE_URL}{_SERP_PATH}", headers=_auth_header(), json=payload)
        resp.raise_for_status()
        body = resp.json()
    tasks = body.get("tasks") or []
    if not tasks or (tasks[0].get("status_code") or 0) >= 40000:
        msg = tasks[0].get("status_message") if tasks else "no tasks"
        raise RuntimeError(f"dataforseo_serp_error: {msg}")
    return (tasks[0].get("result") or [{}])[0].get("items") or []


async def fetch_intent(keyword: str, language_code: str) -> list[dict]:
    """Labs search-intent result items for `keyword`."""
    payload = [{"keywords": [keyword], "language_code": language_code}]
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(f"{_BASE_URL}{_INTENT_PATH}", headers=_auth_header(), json=payload)
        resp.raise_for_status()
        body = resp.json()
    tasks = body.get("tasks") or []
    if not tasks or (tasks[0].get("status_code") or 0) >= 40000:
        msg = tasks[0].get("status_message") if tasks else "no tasks"
        raise RuntimeError(f"dataforseo_intent_error: {msg}")
    return (tasks[0].get("result") or [{}])[0].get("items") or []


async def fetch_backlinks_summary(target_url: str) -> dict:
    """referring_domains + URL Rating for one page-level target URL."""
    payload = [
        {
            "target": target_url,
            "internal_list_limit": 1,
            "backlinks_status_type": "live",
            "include_subdomains": False,
        }
    ]
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(f"{_BASE_URL}{_BACKLINKS_PATH}", headers=_auth_header(), json=payload)
        resp.raise_for_status()
        body = resp.json()
    return parse_backlinks_summary(body)


async def fetch_domain_summary(domain: str) -> dict:
    """Domain Rating (DR) + domain-level referring domains for one domain target.

    Same Backlinks summary endpoint as :func:`fetch_backlinks_summary`, but with
    a bare-domain target and ``include_subdomains=True`` so DataForSEO returns
    whole-domain metrics. Its ``rank`` (0–1000) is the DR-equivalent. Reuses
    ``parse_backlinks_summary`` and relabels ``rank`` → ``domain_rating``.
    """
    payload = [
        {
            "target": domain,
            "internal_list_limit": 1,
            "backlinks_status_type": "live",
            "include_subdomains": True,
        }
    ]
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(f"{_BASE_URL}{_BACKLINKS_PATH}", headers=_auth_header(), json=payload)
        resp.raise_for_status()
        body = resp.json()
    summary = parse_backlinks_summary(body)
    return {
        "domain_rating": summary["url_rating"],
        "referring_domains": summary["referring_domains"],
        "backlinks": summary["backlinks"],
    }


# ----------------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------------
async def _capture_and_store(
    supabase, client: dict, kw: dict, domain: str, location_code: int, language_code: str
) -> str:
    """Capture one keyword's snapshot and persist it. Returns the stored status.

    SERP failure stores a 'failed' marker row (so diagnosis knows it was
    attempted) and returns 'failed' without raising. Backlinks failures are
    per-URL and degrade the snapshot to 'partial'.
    """
    keyword = kw["keyword"]
    keyword_id = kw["id"]
    client_id = client["id"]

    try:
        items = await fetch_serp(keyword, location_code, language_code, settings.serp_snapshot_depth)
    except Exception as exc:
        logger.warning("serp_snapshot_serp_failed", extra={"keyword": keyword, "error": str(exc)})
        supabase.table("serp_snapshots").insert(
            {
                "keyword_id": keyword_id,
                "client_id": client_id,
                "keyword": keyword,
                "status": "failed",
                "location_code": location_code,
                "language_code": language_code,
                "error": str(exc)[:500],
            }
        ).execute()
        return "failed"

    organic = extract_organic_results(items, settings.serp_snapshot_top_n)
    aio = extract_aio(items)
    features = extract_serp_features(items)
    local_intent = detect_local_intent(features)

    # Intent is best-effort — a failure here must not lose the SERP capture.
    try:
        intent_label, intent_probs = classify_intent(await fetch_intent(keyword, language_code))
    except Exception as exc:
        logger.warning("serp_snapshot_intent_failed", extra={"keyword": keyword, "error": str(exc)})
        intent_label, intent_probs = None, {}

    client_match = find_client_organic(items, domain)
    client_rank = client_match["position"] if client_match else None
    client_url = (client_match["url"] if client_match else None) or kw.get("canonical_url")

    # Build the ranking-page rows to enrich with backlinks: the top organic
    # results, plus the client's own page if it ranks below the captured depth.
    result_rows: list[dict] = []
    client_in_top = False
    for o in organic:
        is_client = _domain_matches(o["domain"], domain)
        client_in_top = client_in_top or is_client
        result_rows.append({**o, "is_client": is_client})
    if client_match and not client_in_top:
        result_rows.append({**client_match, "is_client": True})

    # Backlinks enrichment (the pricier per-URL calls), isolated per URL.
    any_backlinks_failed = False
    for row in result_rows:
        url = row.get("url")
        if not url:
            row["backlinks_status"] = "skipped"
            continue
        try:
            summary = await fetch_backlinks_summary(url)
            row["referring_domains"] = summary["referring_domains"]
            row["url_rating"] = summary["url_rating"]
            row["backlinks"] = summary["backlinks"]
            row["backlinks_status"] = "ok"
        except Exception as exc:
            any_backlinks_failed = True
            row["backlinks_status"] = "failed"
            logger.warning(
                "serp_snapshot_backlinks_failed", extra={"url": url, "error": str(exc)}
            )

    # Per-domain Domain Rating (DR): one Backlinks call per unique domain across
    # the captured pages plus the client's own domain (always included). Isolated
    # per domain — a failure degrades the snapshot to 'partial', never fatal.
    domain_rows = collect_snapshot_domains(result_rows, domain)
    any_domains_failed = False
    for d in domain_rows:
        try:
            summary = await fetch_domain_summary(d["domain"])
            d["domain_rating"] = summary["domain_rating"]
            d["referring_domains"] = summary["referring_domains"]
            d["backlinks"] = summary["backlinks"]
            d["backlinks_status"] = "ok"
        except Exception as exc:
            any_domains_failed = True
            d["backlinks_status"] = "failed"
            logger.warning(
                "serp_snapshot_domain_failed", extra={"domain": d["domain"], "error": str(exc)}
            )

    status = "partial" if (any_backlinks_failed or any_domains_failed) else "complete"
    snapshot_res = (
        supabase.table("serp_snapshots")
        .insert(
            {
                "keyword_id": keyword_id,
                "client_id": client_id,
                "keyword": keyword,
                "status": status,
                "location_code": location_code,
                "language_code": language_code,
                "query_intent": intent_label,
                "intent_probabilities": intent_probs or None,
                "local_intent": local_intent,
                "aio_present": aio["present"],
                "aio_text": aio["text"],
                "aio_sources": aio["sources"] or None,
                "serp_features": features,
                "client_rank": client_rank,
                "client_url": client_url,
            }
        )
        .execute()
    )
    snapshot_id = snapshot_res.data[0]["id"]

    if result_rows:
        supabase.table("serp_snapshot_results").insert(
            [
                {
                    "snapshot_id": snapshot_id,
                    "position": r.get("position"),
                    "url": r.get("url"),
                    "domain": r.get("domain"),
                    "title": r.get("title"),
                    "description": r.get("description"),
                    "is_client": r.get("is_client", False),
                    "referring_domains": r.get("referring_domains"),
                    "url_rating": r.get("url_rating"),
                    "backlinks": r.get("backlinks"),
                    "backlinks_status": r.get("backlinks_status", "pending"),
                }
                for r in result_rows
            ]
        ).execute()

    if domain_rows:
        try:
            supabase.table("serp_snapshot_domains").insert(
                [
                    {
                        "snapshot_id": snapshot_id,
                        "domain": d.get("domain"),
                        "is_client": d.get("is_client", False),
                        "domain_rating": d.get("domain_rating"),
                        "referring_domains": d.get("referring_domains"),
                        "backlinks": d.get("backlinks"),
                        "backlinks_status": d.get("backlinks_status", "pending"),
                    }
                    for d in domain_rows
                ]
            ).execute()
        except Exception as exc:
            # The snapshot + results already persisted; don't let a domains-insert
            # failure propagate (which would miscount this mostly-successful
            # capture as 'failed'). Degrade to 'partial' so the missing DR is
            # visible, best-effort.
            logger.warning(
                "serp_snapshot_domains_insert_failed",
                extra={"snapshot_id": snapshot_id, "error": str(exc)},
            )
            if status != "partial":
                status = "partial"
                try:
                    supabase.table("serp_snapshots").update({"status": "partial"}).eq(
                        "id", snapshot_id
                    ).execute()
                except Exception:
                    pass

    return status


async def capture_client_snapshots(
    client_id: str, keyword_id: Optional[str] = None, today: Optional[date] = None
) -> dict:
    """Capture SERP snapshots for a client's active keywords (or one keyword).

    Resilient: a single keyword's failure is logged + counted, never fatal.
    """
    supabase = get_supabase()
    client_res = (
        supabase.table("clients")
        .select("id, name, website_url, rank_tracking_location_code")
        .eq("id", client_id)
        .limit(1)
        .execute()
    )
    if not client_res.data:
        return {"status": "failed", "error": "client_not_found", "captured": 0}
    client = client_res.data[0]
    domain = extract_domain(client.get("website_url") or "")
    if not domain:
        return {"status": "failed", "error": "client_has_no_website", "captured": 0}
    location_code = location_code_for(client)
    language_code = settings.dataforseo_default_language_code

    query = (
        supabase.table("tracked_keywords")
        .select("id, keyword, canonical_url")
        .eq("client_id", client_id)
        .eq("active", True)
    )
    if keyword_id:
        query = query.eq("id", keyword_id)
    keywords = (query.execute()).data or []
    if not keywords:
        return {"status": "ok", "captured": 0, "failed": 0}

    captured = failed = 0
    for kw in keywords:
        try:
            result_status = await _capture_and_store(
                supabase, client, kw, domain, location_code, language_code
            )
            if result_status == "failed":
                failed += 1
            else:
                captured += 1
        except Exception as exc:  # defensive — _capture_and_store handles its own
            failed += 1
            logger.warning(
                "serp_snapshot_keyword_failed", extra={"keyword": kw.get("keyword"), "error": str(exc)}
            )

    logger.info(
        "serp_snapshot_complete",
        extra={"client_id": client_id, "captured": captured, "failed": failed},
    )
    return {"status": "ok", "captured": captured, "failed": failed}


def enqueue_serp_snapshot(client_id: str, keyword_id: Optional[str] = None) -> None:
    """Enqueue a serp_snapshot capture job (deduped against pending ones).

    With no keyword_id the job snapshots every active keyword for the client
    (the weekly pass); with one it captures just that keyword (on-demand).
    """
    supabase = get_supabase()
    existing = (
        supabase.table("async_jobs")
        .select("id, payload")
        .eq("job_type", "serp_snapshot")
        .eq("entity_id", client_id)
        .in_("status", ["pending", "running"])
        .execute()
    )
    for job in existing.data or []:
        if (job.get("payload") or {}).get("keyword_id") == keyword_id:
            return
    supabase.table("async_jobs").insert(
        {
            "job_type": "serp_snapshot",
            "entity_id": client_id,
            "payload": {"client_id": client_id, "keyword_id": keyword_id},
        }
    ).execute()


async def run_serp_snapshot_job(job: dict) -> None:
    """async_jobs handler for job_type='serp_snapshot'."""
    payload = job.get("payload") or {}
    client_id = payload.get("client_id")
    keyword_id = payload.get("keyword_id")
    job_id = job["id"]
    supabase = get_supabase()
    if not client_id:
        supabase.table("async_jobs").update(
            {"status": "failed", "error": "missing client_id", "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return

    result = await capture_client_snapshots(client_id, keyword_id=keyword_id)
    supabase.table("async_jobs").update(
        {
            "status": "complete" if result.get("status") == "ok" else "failed",
            "result": result,
            "error": result.get("error"),
            "completed_at": "now()",
        }
    ).eq("id", job_id).execute()
