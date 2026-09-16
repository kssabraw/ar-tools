"""Per-client SITE CLAIM INDEX — the grounding corpus for Information Gain (P1).

Topic-Vector Centering + Information Gain, P1
(``docs/modules/topic-vector-information-gain-plan-v1_0.md`` §6/§7).

The scored Information Gain dimension credits a page claim only when it is
(a) on-vector, (b) rare in the top-10, and (c) **site-grounded** — corroborated
by a structured fact the client's OWN site actually asserts. Guard (c) is the
anti-fabrication mechanism: gain must be SOURCED, never generated. This module
is guard (c)'s corpus.

Cross-service by necessity (§7): the scorer lives in nlp-api, which has no
database and no crawl of the client site. So the index is built + cached HERE
(platform-api) and passed to nlp in the score/reopt request body, exactly like
``serp_analysis`` and ``researched_facts`` already are. nlp never crawls; it
just grounds the scored page's claims against this index.

Design mirrors ``ecommerce_facts_cache``:
  - Pure helpers (``extract_page_claims`` / ``merge_index`` / ``is_fresh`` /
    ``cache_row``) are unit-tested; the Supabase + scrape round-trips are
    best-effort and never raise.
  - Keyed on ``client_id`` (the corpus is the client's whole site). TTL is a
    re-crawl cadence, not an expiry.
  - Empty/thin is never a hard failure: the gain measure SUPPRESSES rather than
    scoring 0, so a new / sitemap-less client degrades gracefully.

Extraction is DETERMINISTIC (regex + sentence selection) — no LLM, no
fabrication risk in the corpus itself. The two shapes it stores:
  - ``facts``  — typed number-entity facts (price / purity / CAS / molecular
    weight / formula / storage / sizes / COA) for the exact-value grounding
    path.
  - ``claims`` — substantive claim phrases for the fuzzy embedding-grounding
    path (embedded on the nlp side, where the Gemini key lives — this keeps the
    module name-agnostic: a coded-name claim grounds against the coded-name
    phrase on the client's own site).
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from config import settings
from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

_TABLE = "site_claim_index"

# Single-flight registry: coalesces concurrent cache-miss BUILDS for the same
# client onto one crawl. platform-api runs the worker on one event loop with
# several lanes (interactive + bulk), so a bulk reoptimize of N pages for one
# client can miss the cache on N lanes at once; without this each would crawl the
# site independently. Keyed by client_id; process-local (PLATFORM is one replica).
_inflight_builds: dict[str, "asyncio.Future[dict]"] = {}

# ── Deterministic typed-fact extraction ─────────────────────────────────────
# Conservative number-entity patterns — the "verifiable number-entity" facts
# the MCS/AEO methodology rewards and the ones a page claim can be grounded to
# by typed value agreement. Each returns (type, value, unit).

_PRICE_RE = re.compile(r"\$\s?(\d{1,5}(?:\.\d{2})?)\b")
_PURITY_RE = re.compile(r"(?:≥|>=|>|~)?\s?(\d{2,3}(?:\.\d+)?)\s?%\s*(?:purity|pure)?",
                        re.IGNORECASE)
_CAS_RE = re.compile(r"\b(\d{2,7}-\d{2}-\d)\b")
_MW_RE = re.compile(r"\b(\d{2,5}(?:\.\d+)?)\s?(da|kda|g\/mol)\b", re.IGNORECASE)
_FORMULA_RE = re.compile(r"\b(C\d{1,3}H\d{1,3}(?:[A-Z][a-z]?\d{0,3})+)\b")
_STORAGE_RE = re.compile(r"(-?\d{1,2})\s?°?\s?C\b")
_SIZE_RE = re.compile(r"\b(\d{1,4})\s?(mg|mcg|iu|ml)\b", re.IGNORECASE)

_PURITY_CONTEXT = ("purity", "pure", "hplc", "≥98", "≥99")
_STORAGE_CONTEXT = ("store", "storage", "freeze", "frozen", "refriger")
_COA_HINTS = ("certificate of analysis", " coa ", "(coa)", "coa ", "hplc", "mass spec")

_WS_RE = re.compile(r"\s+")
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
# A claim phrase is substantive when it carries a factual signal — a number,
# unit, percentage, degree sign, or a currency amount. Bleached marketing prose
# ("we care about quality") carries none and is dropped.
_FACT_SIGNAL_RE = re.compile(r"\d|%|°|\$")
# Site-chrome/boilerplate sentences that carry a stray number (an age-gate, a
# cart/discount popup, a blog-index "N min read" blurb) pass the fact-signal
# gate but are NOT product claims. Left in the SITE index they self-ground a
# matching page claim: a live Nova run credited "I acknowledge that I am age 21
# or older." as a realized Information Gain (site_cosine 1.0 against the same
# chrome here). html_to_text strips nav/footer/header/form TAGS; this catches
# the modal/popup chrome that lives in ordinary <div>s. Kept narrow so a real
# product claim can never match. Must stay in sync with the nlp-api page-claim
# extractor (nlp-api/topic_vector.py::_CHROME_CLAIM_RE).
_CHROME_CLAIM_RE = re.compile(
    r"(?:"
    r"add(?:ed)?\s+to\s+cart|your\s+cart\s+is\s+empty|cart\s+total|check\s+out\s+our\s+shop|"
    r"close\s+cart|view\s+cart|"
    r"i\s+acknowledge\s+that\s+i\s+am|are\s+you\s+(?:18|21)|age\s+verification|"
    r"\d+\s*%\s*off|off\s+your\s+first\s+order|discount\s+code|"
    r"\d+\s*min\s+read|read\s+article|"
    r"uncategorized"
    r")",
    re.IGNORECASE,
)


def _norm(text: object) -> str:
    return _WS_RE.sub(" ", str(text or "")).strip()


def _lower(text: object) -> str:
    return _norm(text).lower()


def html_to_text(html: str) -> str:
    """Strip a page to visible text (lazy bs4 so the pure regex helpers import
    without bs4). Drops script/style/nav/footer chrome so a claim never comes
    from the site's boilerplate menu."""
    try:
        from bs4 import BeautifulSoup
    except Exception:  # pragma: no cover - bs4 always present in the service image
        return _norm(re.sub(r"<[^>]+>", " ", html or ""))
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "form"]):
        tag.decompose()
    return _norm(soup.get_text(" ", strip=True))


def extract_facts(text: str, url: str = "") -> list[dict]:
    """Pull typed number-entity facts from page text. Deterministic + de-duped
    within the page. Each fact: {type, value, unit, raw, url}."""
    low = _lower(text)
    out: list[dict] = []
    seen: set = set()

    def _add(ftype: str, value: str, unit: str = "", raw: str = "") -> None:
        value = _norm(value)
        if not value:
            return
        key = (ftype, value.lower(), unit.lower())
        if key in seen:
            return
        seen.add(key)
        out.append({"type": ftype, "value": value, "unit": unit, "raw": _norm(raw)[:120], "url": url})

    for m in _PRICE_RE.finditer(text):
        # A $0 / $0.00 is an empty-cart / discount-widget / chrome artifact, never
        # a real product price. Leaving it in the corpus polluted reopt coaching
        # ("state price: 0.00 USD" — a live Nova run) and could false-ground a
        # "0.00" page claim via _site_fact_values. Drop it at the source.
        try:
            if float(m.group(1)) == 0:
                continue
        except ValueError:  # pragma: no cover - regex guarantees a number
            pass
        _add("price", m.group(1), "USD", m.group(0))
    # Purity only when a purity/HPLC context word is nearby (a bare "50%" is not).
    for m in _PURITY_RE.finditer(text):
        window = low[max(0, m.start() - 40): m.end() + 40]
        if any(h in window for h in _PURITY_CONTEXT):
            _add("purity", m.group(1), "%", m.group(0))
    for m in _CAS_RE.finditer(text):
        _add("cas", m.group(1), "", m.group(0))
    for m in _MW_RE.finditer(text):
        _add("molecular_weight", m.group(1), m.group(2), m.group(0))
    for m in _FORMULA_RE.finditer(text):
        _add("molecular_formula", m.group(1), "", m.group(0))
    for m in _STORAGE_RE.finditer(text):
        window = low[max(0, m.start() - 40): m.end() + 20]
        if any(h in window for h in _STORAGE_CONTEXT):
            _add("storage_temp", m.group(1), "°C", m.group(0))
    for m in _SIZE_RE.finditer(text):
        _add("size", m.group(1), m.group(2).lower(), m.group(0))
    if any(h in low for h in _COA_HINTS):
        _add("coa", "present", "", "certificate of analysis")
    return out


def extract_claims(text: str, url: str = "", *, max_words: int = 45,
                   min_words: int = 6) -> list[dict]:
    """Pull substantive claim phrases (fact-bearing sentences) from page text.
    A claim survives only when it has a factual signal (number / unit / % / °),
    so bleached marketing prose is dropped. Each claim: {text, url}."""
    out: list[dict] = []
    seen: set = set()
    for raw in _SENT_SPLIT_RE.split(text or ""):
        sent = _norm(raw)
        words = sent.split()
        if not (min_words <= len(words) <= max_words):
            continue
        if not _FACT_SIGNAL_RE.search(sent):
            continue
        if _CHROME_CLAIM_RE.search(sent):  # drop age-gate/cart/popup chrome
            continue
        key = re.sub(r"[^a-z0-9]+", " ", sent.lower()).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append({"text": sent, "url": url})
    return out


def extract_page(html: str, url: str = "") -> dict:
    """Extract one page's facts + claims from its HTML."""
    text = html_to_text(html)
    return {"facts": extract_facts(text, url), "claims": extract_claims(text, url)}


def merge_index(pages: list[dict], *, max_facts: int, max_claims: int) -> dict:
    """Merge per-page extractions into one deduped index. Facts deduped by
    (type, value, unit); claims by normalized text. Order preserved (first-seen)
    so the cap keeps the earliest (usually the money/spec pages, crawled first)."""
    facts: list[dict] = []
    claims: list[dict] = []
    fseen: set = set()
    cseen: set = set()
    for page in pages or []:
        for f in (page or {}).get("facts", []) or []:
            key = (f.get("type"), _lower(f.get("value")), _lower(f.get("unit")))
            if key in fseen:
                continue
            fseen.add(key)
            facts.append(f)
        for c in (page or {}).get("claims", []) or []:
            key = re.sub(r"[^a-z0-9]+", " ", _lower(c.get("text"))).strip()
            if not key or key in cseen:
                continue
            cseen.add(key)
            claims.append(c)
    return {"facts": facts[:max_facts], "claims": claims[:max_claims]}


# ── Cache freshness + row (pure) ────────────────────────────────────────────

def is_fresh(fetched_at: Optional[str], ttl_days: int, now: Optional[datetime] = None) -> bool:
    """Whether a cached row is within its TTL. Missing/unparseable = STALE (safe
    direction: re-crawl). ``ttl_days <= 0`` disables freshness (always stale)."""
    if ttl_days <= 0 or not fetched_at:
        return False
    now = now or datetime.now(timezone.utc)
    try:
        stamp = datetime.fromisoformat(str(fetched_at).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp > now - timedelta(days=ttl_days)


def cache_row(client_id: str, website_url: str, index: dict, source: str,
              url_count: int, note: str = "") -> dict:
    """Build the upsert row for a cache fill (pure — unit-testable)."""
    return {
        "client_id": client_id,
        "website_url": (website_url or "").strip() or None,
        "facts": index.get("facts", []),
        "claims": index.get("claims", []),
        "url_count": int(url_count or 0),
        "source": source or "none",
        "note": (note or "").strip() or None,
        "fetched_at": "now()",
        "updated_at": "now()",
    }


def index_is_thin(index: Optional[dict], min_claims: int) -> bool:
    """Thin/absent → the caller SUPPRESSES the gain score ('not measured'),
    never reports a misleading 0 (§6). Thin = fewer than ``min_claims`` claims
    AND no typed facts."""
    if not index:
        return True
    claims = index.get("claims") or []
    facts = index.get("facts") or []
    return len(claims) < max(1, min_claims) and not facts


# ── Supabase + scrape round-trips (best-effort — never fail a page) ─────────

def get_cached_index(client_id: str) -> Optional[dict]:
    """Return the fresh cached index for this client, or None on any miss
    (expired / empty / disabled / error). None means "(re)build it"."""
    if not settings.topic_vector_gain_enabled:
        return None
    try:
        res = (
            get_supabase().table(_TABLE)
            .select("facts, claims, url_count, source, fetched_at")
            .eq("client_id", client_id).limit(1).execute()
        )
    except Exception:  # noqa: BLE001 — a cache read must never break scoring
        logger.warning("site_claim_index.read_failed", extra={"client_id": client_id})
        return None
    row = (res.data or [None])[0]
    if not row or not is_fresh(row.get("fetched_at"), settings.site_claim_index_days):
        return None
    return {
        "facts": row.get("facts") or [],
        "claims": row.get("claims") or [],
        "url_count": row.get("url_count") or 0,
        "source": row.get("source") or "none",
    }


def store_index(client_id: str, website_url: str, index: dict, source: str,
                url_count: int, note: str = "") -> None:
    """Upsert the built index. Best-effort. An EMPTY build IS stored (with its
    note) so a sitemap-less site isn't re-crawled every score — the read side
    treats a thin index as 'suppress', not 'retry'; the TTL re-crawls later."""
    try:
        get_supabase().table(_TABLE).upsert(
            cache_row(client_id, website_url, index, source, url_count, note),
            on_conflict="client_id",
        ).execute()
        logger.info(
            "site_claim_index.stored",
            extra={"client_id": client_id, "facts": len(index.get("facts", [])),
                   "claims": len(index.get("claims", [])), "source": source},
        )
    except Exception:  # noqa: BLE001 — a cache write must never break scoring
        logger.warning("site_claim_index.write_failed", extra={"client_id": client_id})


async def build_site_claim_index(client_id: str, website_url: str) -> dict:
    """Discover + scrape + extract the client's site into a claim index. Best-
    effort throughout: a dead site / unreadable sitemap / scrape failures yield a
    thin-or-empty index (never raises). Returns the built index dict (also stored)."""
    from services import site_page_index
    from services.website_scraper import scrapeowl_fetch

    max_pages = max(1, settings.site_claim_index_max_pages)
    urls: list[str] = []
    source = "none"
    note = ""
    if (website_url or "").strip():
        try:
            urls, source = await site_page_index.discover_site_urls(
                website_url, settings.dataforseo_default_location_code,
                max_urls=max_pages * 4,
            )
        except Exception:  # noqa: BLE001
            logger.warning("site_claim_index.discover_failed", extra={"client_id": client_id})
            urls, source = [], "none"
    else:
        note = "no_website"

    urls = urls[:max_pages]
    if not urls and not note:
        note = "no_urls"

    # Scrape concurrently under a bounded semaphore (was serial — up to
    # max_pages × scrape_timeout of blocking wall-clock; parallel cuts it to
    # roughly one timeout). One dead/slow page never aborts the crawl; order is
    # not load-bearing (merge_index dedupes first-seen, and gather preserves it).
    sem = asyncio.Semaphore(max(1, settings.site_claim_index_scrape_concurrency))

    async def _scrape_one(url: str) -> Optional[dict]:
        async with sem:
            try:
                html = await scrapeowl_fetch(url, timeout=settings.site_claim_index_scrape_timeout)
            except Exception:  # noqa: BLE001 — one dead page never aborts the crawl
                logger.info("site_claim_index.scrape_failed", extra={"client_id": client_id, "url": url})
                return None
            return extract_page(html, url) if html else None

    results = await asyncio.gather(*(_scrape_one(u) for u in urls))
    pages: list[dict] = [p for p in results if p]

    index = merge_index(
        pages,
        max_facts=settings.site_claim_index_max_facts,
        max_claims=settings.site_claim_index_max_claims,
    )
    store_index(client_id, website_url, index, source, len(pages), note)
    index["url_count"] = len(pages)
    index["source"] = source
    return index


async def _build_coalesced(client_id: str, website_url: str) -> dict:
    """Run at most one build per client at a time: a concurrent caller awaits the
    in-flight build instead of starting its own. The dict get/create is atomic
    under asyncio (no await between them), so two simultaneous misses share one
    crawl. The starter clears its own entry in `finally`; awaiters never touch the
    registry, so there is no leak and no cross-clearing."""
    existing = _inflight_builds.get(client_id)
    if existing is not None and not existing.done():
        return await existing
    fut = asyncio.ensure_future(build_site_claim_index(client_id, website_url))
    _inflight_builds[client_id] = fut
    try:
        return await fut
    finally:
        if _inflight_builds.get(client_id) is fut:
            del _inflight_builds[client_id]


async def resolve_index_for_request(client: dict) -> Optional[dict]:
    """The single entry point the ecommerce score/reopt paths call. Cache-first;
    on a miss it builds inline (capped, best-effort, single-flight per client) and
    caches for next time. Returns the index dict, or None when the gain measure is
    disabled / the client has no id. NEVER raises — a failure degrades to None
    (gain suppressed downstream)."""
    if not settings.topic_vector_gain_enabled:
        return None
    client_id = (client or {}).get("id")
    if not client_id:
        return None
    try:
        cached = get_cached_index(client_id)
        if cached is not None:
            return cached
        return await _build_coalesced(client_id, (client or {}).get("website_url") or "")
    except Exception:  # noqa: BLE001 — grounding is best-effort, never a page failure
        logger.warning("site_claim_index.resolve_failed", extra={"client_id": client_id})
        return None
