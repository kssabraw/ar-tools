"""Content Gap Analyzer — assembly / diff / presentation over surfaces the suite
already runs.

For a client's selected keywords × money pages, decide whether the client is
winning the SERP (top-10 organic AND — when an AI Overview exists — cited in it),
and where not, diff the competitors ranking above the client across authority,
traffic, entity, and on-page-content dimensions.

This module builds **no new scoring engine** (PRD §1). The net-new code is:
  * the pure win/gap verdict (§2.1, three-valued AIO axis),
  * the competitor-set resolution (§6, the "both" union),
  * the pure `build_onpage_diff` assembler (§4) over page signals the suite's
    existing `page_structure_eval` already extracts,
  * the read-an-existing-snapshot job skeleton (§8 — the cost-critical reuse),
  * metering, cadence, and persistence.

Phase 0 (this file, behind `content_gap_enabled=False`) ships the pure core +
a job that reads the client's latest `serp_snapshots` row and records the
verdict + competitor set per keyword. The deep dimensions (live-page scrapes,
nlp `/analyze` + `/score-page`, dataforseo_labs traffic, and calling
`build_onpage_diff` end-to-end) are wired in later phases.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from statistics import median
from typing import Any, Optional

import httpx
from bs4 import BeautifulSoup

from config import settings
from db.supabase_client import get_supabase
from services import dataforseo_labs, serp_snapshot
from services.dataforseo_rank import extract_domain
from services.forecasting import ctr_for_position
from services.page_structure_eval import (
    block_types_of,
    extract_outline_from_html,
)
from services.website_scraper import scrapeowl_fetch

logger = logging.getLogger(__name__)

# The locked top-N organic threshold (PRD §2 decision #2). A page ranked within
# this is "top-10 organic".
TOP_N = 10

# Human labels for the structural element flags page_structure_eval emits, for
# the on-page element-gap rows. `has_intro` is omitted — true for any non-empty
# page, so never a meaningful gap.
_ELEMENT_LABELS: dict[str, str] = {
    "has_faq": "FAQ section",
    "has_cta": "call-to-action",
    "has_table": "comparison/data table",
    "has_lists": "bulleted/numbered list",
    "has_key_takeaways": "key-takeaways block",
}


# ===========================================================================
# Pure: win/gap verdict (PRD §2.1)
# ===========================================================================
def compute_verdict(
    client_position: Optional[int],
    aio_present: bool,
    in_aio: bool,
    top_n: int = TOP_N,
) -> str:
    """The three-valued win/gap verdict for one keyword.

    Returns one of: 'win', 'aio_gap', 'organic_gap', 'full_gap'.

    Rules (PRD §2.1) — the AIO axis only ever produces a gap when an AIO is
    actually present on the SERP; a keyword with no AIO is judged on organic
    position alone, so a page the client ranks well for is never permanently
    flagged as an unfixable "AIO gap":

      top-10 organic  + no AIO                 → win
      top-10 organic  + AIO present + cited    → win
      top-10 organic  + AIO present + not cited→ aio_gap
      not top-10      + AIO present + not cited→ full_gap
      not top-10      + (no AIO OR in AIO only)→ organic_gap
    """
    top10 = client_position is not None and 1 <= client_position <= top_n
    if top10:
        if not aio_present:
            return "win"
        return "win" if in_aio else "aio_gap"
    # Not ranking in the top-N organic.
    if aio_present and not in_aio:
        return "full_gap"
    return "organic_gap"


def is_gap(verdict: str) -> bool:
    """True when a verdict is anything other than a win (needs the deep diff)."""
    return verdict != "win"


# ===========================================================================
# Pure: AIO citation helpers (PRD §3.2 AIO citation gap)
# ===========================================================================
def _norm_domain(value: Optional[str]) -> str:
    """Normalize a domain/URL to a bare host for comparison (no scheme/www)."""
    if not value:
        return ""
    host = extract_domain(value) or value
    host = str(host).strip().lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def client_cited_in_aio(aio_sources: list[dict], client_domain: str) -> bool:
    """Whether the client's domain appears among the AIO cited sources."""
    cd = _norm_domain(client_domain)
    if not cd:
        return False
    for src in aio_sources or []:
        if _norm_domain(src.get("domain") or src.get("url")) == cd:
            return True
    return False


def aio_gap_sources(aio_sources: list[dict], client_domain: str) -> list[dict]:
    """AIO cited sources that are NOT the client — 'who is cited that we aren't'.

    Deduped by domain, order preserved. Only meaningful when the AIO is present.
    """
    cd = _norm_domain(client_domain)
    out: list[dict] = []
    seen: set[str] = set()
    for src in aio_sources or []:
        d = _norm_domain(src.get("domain") or src.get("url"))
        if not d or d == cd or d in seen:
            continue
        seen.add(d)
        out.append({"domain": d, "url": src.get("url"), "title": src.get("title")})
    return out


# ===========================================================================
# Pure: competitor-set resolution (PRD §6, "both")
# ===========================================================================
def resolve_competitors(
    organic_rows: list[dict],
    client_position: Optional[int],
    registry_domains: set[str],
    client_domain: str,
    max_competitors: int = 5,
) -> list[dict]:
    """The competitor set for a gapped keyword — the union of:

      A. organic results ranking ABOVE the client (all top-10 when the client
         isn't ranking), and
      B. registered `client_competitors` whose domain appears in this SERP.

    Deduped by domain, the client excluded, sorted strongest-first (best organic
    position; a registry-only match with no position sorts last), and capped at
    `max_competitors` to bound the downstream scrape cost. Pure — no I/O.

    `organic_rows` are the snapshot's result rows ({position, url, domain, ...}).
    `registry_domains` are normalized bare hosts.
    """
    cd = _norm_domain(client_domain)
    reg = {_norm_domain(d) for d in registry_domains if d}
    # A page ranks "above" the client when its position is strictly better; when
    # the client isn't ranking, every top-N organic result is above it.
    ceiling = client_position if client_position is not None else (TOP_N + 1)

    best: dict[str, dict] = {}
    for row in organic_rows or []:
        d = _norm_domain(row.get("domain") or row.get("url"))
        # Exclude the client's own row — by domain, and by the snapshot's
        # `is_client` flag as a fallback (a client with no website_url yields an
        # empty `client_domain`, so domain matching alone can't identify it).
        if not d or d == cd or row.get("is_client"):
            continue
        pos = row.get("position")
        above = isinstance(pos, int) and pos < ceiling
        registered = d in reg
        if not (above or registered):
            continue
        cand = {
            "domain": d,
            "url": row.get("url"),
            "position": pos if isinstance(pos, int) else None,
            "registered": registered,
        }
        prev = best.get(d)
        if prev is None:
            best[d] = cand
        else:
            # Keep the best (lowest) position; carry a registered flag if either says so.
            prev["registered"] = prev["registered"] or registered
            if cand["position"] is not None and (
                prev["position"] is None or cand["position"] < prev["position"]
            ):
                prev["position"] = cand["position"]
                prev["url"] = cand["url"]

    def _sort_key(c: dict) -> tuple[int, int]:
        # Positioned competitors first (ascending position); registry-only last.
        return (0, c["position"]) if c["position"] is not None else (1, 0)

    ordered = sorted(best.values(), key=_sort_key)
    return ordered[: max_competitors if max_competitors and max_competitors > 0 else len(ordered)]


# ===========================================================================
# Pure: page-signal extraction (feeds build_onpage_diff)
# ===========================================================================
def _normalize_heading(text: str) -> str:
    return " ".join((text or "").lower().split())


def _extract_title(soup: BeautifulSoup) -> Optional[str]:
    t = soup.find("title")
    if t and t.get_text(strip=True):
        return t.get_text(strip=True)
    return None


def _extract_meta_description(soup: BeautifulSoup) -> Optional[str]:
    for attrs in ({"name": "description"}, {"property": "og:description"}):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            return tag["content"].strip() or None
    return None


def _extract_schema_types(soup: BeautifulSoup) -> list[str]:
    """The set of JSON-LD @type values on the page (FAQPage / Product / …)."""
    out: list[str] = []
    seen: set[str] = set()

    def _add(t: Any) -> None:
        if isinstance(t, str) and t and t not in seen:
            seen.add(t)
            out.append(t)

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            _add(node.get("@type"))
            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for v in node:
                if isinstance(v, str):
                    _add(v)
                else:
                    _walk(v)

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text() or ""
        if not raw.strip():
            continue
        try:
            _walk(json.loads(raw))
        except (ValueError, TypeError):
            continue
    return out


# --- Freshness (PRD §3.2 freshness gap, [free] — parses HTML already scraped) --
_MODIFIED_META_ATTRS = (
    {"property": "article:modified_time"},
    {"property": "og:updated_time"},
    {"itemprop": "dateModified"},
    {"name": "last-modified"},
)
_PUBLISHED_META_ATTRS = (
    {"property": "article:published_time"},
    {"itemprop": "datePublished"},
    {"name": "date"},
)


def _parse_date(value: Any) -> Optional[date]:
    """Parse a JSON-LD / meta date value to a `date`, leniently. Handles ISO
    date-only, full ISO with offset, and a trailing `Z`. Returns None on junk."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    iso = (s[:-1] + "+00:00") if s.endswith("Z") else s
    for candidate in (iso, s[:10]):
        try:
            return datetime.fromisoformat(candidate).date()
        except ValueError:
            continue
    return None


def _jsonld_dates(soup: BeautifulSoup) -> tuple[list[str], list[str]]:
    """Collect raw (modified, published) date strings from every JSON-LD node."""
    modified: list[str] = []
    published: list[str] = []

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            for key in ("dateModified", "lastReviewed"):
                v = node.get(key)
                if isinstance(v, str):
                    modified.append(v)
            v = node.get("datePublished")
            if isinstance(v, str):
                published.append(v)
            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for v in node:
                _walk(v)

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text() or ""
        if not raw.strip():
            continue
        try:
            _walk(json.loads(raw))
        except (ValueError, TypeError):
            continue
    return modified, published


def _extract_freshness(soup: BeautifulSoup) -> tuple[Optional[str], Optional[str]]:
    """Return `(iso_date | None, basis)` for a page's last-updated date.

    Prefers a *modified* signal (JSON-LD `dateModified`/`lastReviewed`,
    `article:modified_time`, `og:updated_time`, itemprop `dateModified`,
    `<meta name=last-modified>`); falls back to a *published* signal. `basis` is
    `'modified' | 'published' | None` so the diff can say which it used. When a
    page carries several, the most recent wins. Reuses only already-scraped HTML
    — no new call (PRD §3.2 freshness gap, [free])."""
    mod_raw, pub_raw = _jsonld_dates(soup)
    for attrs in _MODIFIED_META_ATTRS:
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            mod_raw.append(tag["content"])
    for attrs in _PUBLISHED_META_ATTRS:
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            pub_raw.append(tag["content"])

    mod_dates = [d for d in (_parse_date(v) for v in mod_raw) if d is not None]
    if mod_dates:
        return max(mod_dates).isoformat(), "modified"
    pub_dates = [d for d in (_parse_date(v) for v in pub_raw) if d is not None]
    if pub_dates:
        return max(pub_dates).isoformat(), "published"
    return None, None


def page_signals_from_html(html: str, url: Optional[str] = None) -> dict[str, Any]:
    """Extract the on-page signals `build_onpage_diff` compares, from page HTML.

    Deterministic, reuses `page_structure_eval` for the outline/word-count/blocks
    so the same measurement drives generation, the fidelity eval, and this diff.
    Returns `available: True` for real content; call sites mark a failed
    scrape as `{"available": False}` instead (PRD §4.1).
    """
    soup = BeautifulSoup(html or "", "html.parser")
    analysis = extract_outline_from_html(html or "")
    outline = analysis.get("outline") or []
    elements = analysis.get("elements") or {}

    headings: list[str] = []
    seen_h: set[str] = set()
    block_types: set[str] = set()
    for item in outline:
        level = str(item.get("level") or "").upper()
        block_types |= block_types_of(item)
        if level in ("H2", "H3"):
            norm = _normalize_heading(item.get("heading", ""))
            if norm and norm not in seen_h:
                seen_h.add(norm)
                headings.append(norm)

    last_modified, freshness_basis = _extract_freshness(soup)
    return {
        "available": True,
        "url": url,
        "title": _extract_title(soup),
        "meta_description": _extract_meta_description(soup),
        "word_count": int(elements.get("approx_total_words") or 0),
        "headings": headings,
        "heading_count": len(headings),
        "block_types": sorted(block_types),
        "schema_types": _extract_schema_types(soup),
        "elements": {k: bool(elements.get(k)) for k in _ELEMENT_LABELS},
        "last_modified": last_modified,
        "freshness_basis": freshness_basis,
    }


# ===========================================================================
# Pure: the on-page diff assembler (PRD §4)
# ===========================================================================
def _label(domain: Optional[str], url: Optional[str]) -> str:
    return domain or _norm_domain(url) or "competitor"


# Days behind the competitor median beyond which the client page is flagged stale.
FRESHNESS_STALE_DAYS = 180


def _median_date(dates: list[date]) -> Optional[str]:
    """Median of a list of `date`s as an ISO string (via day-ordinals)."""
    if not dates:
        return None
    ords = sorted(d.toordinal() for d in dates)
    return date.fromordinal(int(median(ords))).isoformat()


def build_freshness(
    client_signals: dict[str, Any],
    comps: list[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    """Freshness gap (PRD §3.2): the client's last-updated date vs competitors'.

    Pure. Dates come from `page_signals_from_html`'s `last_modified` (JSON-LD /
    meta, [free]). Only pages that carried a parseable date contribute. Returns
    None when NO page (client or competitor) had a date, so the dimension is
    omitted rather than rendered empty (PRD §4.1). `client_days_behind_median`
    is positive when the client is staler than the competitor median; `stale`
    flags a client more than `FRESHNESS_STALE_DAYS` behind it.

    `comps` is the available-filtered competitor list (from `build_onpage_diff`);
    a competitor with no parseable date simply doesn't contribute.
    """
    client_ok = bool(client_signals.get("available"))
    client_date = _parse_date(client_signals.get("last_modified")) if client_ok else None

    comp_rows: list[dict[str, Any]] = []
    comp_dates: list[date] = []
    for c in comps:
        d = _parse_date(c.get("last_modified"))
        if d is None:
            continue
        comp_dates.append(d)
        comp_rows.append(
            {
                "domain": _label(c.get("domain"), c.get("url")),
                "last_modified": d.isoformat(),
                "basis": c.get("freshness_basis"),
            }
        )

    if client_date is None and not comp_dates:
        return None

    comp_rows.sort(key=lambda r: r["last_modified"], reverse=True)
    most_recent = max(comp_dates).isoformat() if comp_dates else None
    median_iso = _median_date(comp_dates)

    days_behind: Optional[int] = None
    stale: Optional[bool] = None
    if client_date is not None and median_iso is not None:
        days_behind = (date.fromisoformat(median_iso) - client_date).days
        stale = days_behind > FRESHNESS_STALE_DAYS

    return {
        "client": client_date.isoformat() if client_date else None,
        "client_basis": client_signals.get("freshness_basis") if client_ok else None,
        "client_available": client_date is not None,
        "competitors": comp_rows,
        "competitors_with_date": len(comp_dates),
        "competitor_most_recent": most_recent,
        "competitor_median": median_iso,
        "client_days_behind_median": days_behind,
        "stale": stale,
    }


def build_onpage_diff(
    client_signals: dict[str, Any],
    competitor_signals: list[dict[str, Any]],
) -> dict[str, Any]:
    """Assemble the competitor-anchored on-page diff for one gapped keyword.

    Pure — no I/O, no scoring. Answers "how does our content stack up?" across
    the dimensions the suite already extracts: subtopic (heading) coverage,
    word count, structural elements, JSON-LD schema, and title/meta presence.

    `client_signals` is one `page_signals_from_html` dict (or `{"available":
    False}` when the client page couldn't be scraped, PRD §4.1). Each competitor
    dict is the same shape plus `domain`/`url`/`position`. Only competitors whose
    `available` is truthy contribute to the "competitors have X" side; an
    unavailable client marks its column `unavailable` rather than "has zero of
    everything".
    """
    client_ok = bool(client_signals.get("available"))
    comps = [c for c in competitor_signals if c.get("available")]
    unavailable = len(competitor_signals) - len(comps)

    client_headings = set(client_signals.get("headings") or []) if client_ok else set()
    client_elements = client_signals.get("elements") or {}
    client_schema = set(client_signals.get("schema_types") or []) if client_ok else set()

    # --- Subtopic (heading) gap: headings competitors cover, the client doesn't.
    heading_cover: dict[str, list[str]] = {}
    heading_display: dict[str, str] = {}
    for c in comps:
        label = _label(c.get("domain"), c.get("url"))
        for h in c.get("headings") or []:
            if client_ok and h in client_headings:
                continue
            heading_cover.setdefault(h, [])
            if label not in heading_cover[h]:
                heading_cover[h].append(label)
            heading_display.setdefault(h, h)
    subtopic_gap = sorted(
        (
            {"heading": heading_display[h], "covered_by": cov, "count": len(cov)}
            for h, cov in heading_cover.items()
        ),
        key=lambda r: (-r["count"], r["heading"]),
    )

    # --- Word-count gap vs the competitor median.
    comp_words = [int(c.get("word_count") or 0) for c in comps if c.get("word_count")]
    comp_median = int(median(comp_words)) if comp_words else 0
    client_words = int(client_signals.get("word_count") or 0) if client_ok else None
    word_delta = (client_words - comp_median) if client_words is not None else None

    # --- Structural element gap: elements a competitor has that the client lacks.
    element_gap: list[dict[str, Any]] = []
    for flag, flabel in _ELEMENT_LABELS.items():
        if client_ok and client_elements.get(flag):
            continue
        cover = [
            _label(c.get("domain"), c.get("url"))
            for c in comps
            if (c.get("elements") or {}).get(flag)
        ]
        if cover:
            element_gap.append({"element": flag, "label": flabel, "covered_by": cover, "count": len(cover)})
    element_gap.sort(key=lambda r: (-r["count"], r["element"]))

    # --- Schema (JSON-LD) gap.
    schema_cover: dict[str, list[str]] = {}
    for c in comps:
        label = _label(c.get("domain"), c.get("url"))
        for s in c.get("schema_types") or []:
            if client_ok and s in client_schema:
                continue
            schema_cover.setdefault(s, [])
            if label not in schema_cover[s]:
                schema_cover[s].append(label)
    schema_gap = sorted(
        ({"schema": s, "covered_by": cov, "count": len(cov)} for s, cov in schema_cover.items()),
        key=lambda r: (-r["count"], r["schema"]),
    )

    # --- Title + meta presence.
    title = {
        "client": client_signals.get("title") if client_ok else None,
        "competitors": [
            {"domain": _label(c.get("domain"), c.get("url")), "title": c.get("title")}
            for c in comps
            if c.get("title")
        ],
    }
    meta = {
        "client": client_signals.get("meta_description") if client_ok else None,
        "client_present": bool(client_signals.get("meta_description")) if client_ok else None,
        "competitors_with_meta": sum(1 for c in comps if c.get("meta_description")),
    }

    return {
        "client_available": client_ok,
        "competitors_compared": len(comps),
        "competitors_unavailable": unavailable,
        "subtopic_gap": subtopic_gap,
        "word_count": {"client": client_words, "competitor_median": comp_median, "delta": word_delta},
        "element_gap": element_gap,
        "schema_gap": schema_gap,
        "title": title,
        "meta_description": meta,
        "freshness": build_freshness(client_signals, comps),
    }


# ===========================================================================
# Pure: Phase 1 deep-dimension builders (authority / traffic / entities)
# ===========================================================================
# The score-page deficiency engines whose findings ARE the client side of the
# entity/signal gap (PRD §3.1 #1 — there is no endpoint for a raw client entity
# list, so /score-page's engines carry the client-vs-SERP entity coverage).
_ENTITY_DEFICIENCY_ENGINES = {"entity_establishment", "serp_signal_coverage"}


def estimate_deep_calls(competitor_count: int, page_traffic: bool = True) -> int:
    """The number of paid external calls one gapped keyword's deep pass makes —
    reserved against the meter BEFORE spending (PRD §8). Pure.

    Per keyword: 1 nlp /analyze + 1 nlp /score-page + 1 batched bulk_traffic +
    (page_traffic → one ranked_keywords per competitor + one for the client) +
    (one scrape per competitor + one for the client). An upper bound — a
    sub-call skipped because a URL is missing simply under-spends the
    reservation (fail-closed errs high, which is the safe direction)."""
    n = max(0, int(competitor_count))
    calls = 2  # /analyze + /score-page
    calls += 1  # bulk_traffic (batched over client + competitor domains)
    if page_traffic:
        calls += n + 1  # ranked_keywords: one per competitor + the client
    calls += n + 1  # scrapes: competitors + client
    return calls


def _norm_url(url: Optional[str]) -> str:
    """Normalize a URL for page matching: drop scheme/www/fragment/trailing
    slash (query kept — some pages differ only by query). Pure."""
    if not url:
        return ""
    u = str(url).strip().lower()
    if "://" in u:
        u = u.split("://", 1)[1]
    if u.startswith("www."):
        u = u[4:]
    u = u.split("#", 1)[0]
    if len(u) > 1 and u.endswith("/"):
        u = u[:-1]
    return u


def estimate_page_traffic(rows: list[dict], target_url: Optional[str]) -> Optional[float]:
    """Modeled monthly organic traffic for ONE page = Σ(volume × CTR(position))
    over the domain's ranked-keyword rows that rank with this exact URL. Pure.

    `rows` are `dataforseo_labs.fetch_ranked_keywords` rows ({url, position,
    volume, ...}); a domain-scoped call returns rows for many URLs, so we filter
    to the target page. Returns None when no row matches the URL (no signal —
    NOT zero, which would misreport a page the labs pull just didn't surface),
    else a float. This is the §3.1 #6 labelled modeled estimate — ranked_keywords
    carries volume, not ETV, so per-page ETV can't be summed directly."""
    tnorm = _norm_url(target_url)
    if not tnorm:
        return None
    matched = [r for r in (rows or []) if _norm_url(r.get("url")) == tnorm]
    if not matched:
        return None
    total = 0.0
    for r in matched:
        vol = r.get("volume")
        if not vol:
            continue
        total += float(vol) * ctr_for_position(r.get("position"))
    return round(total, 1)


def _median_of(values: list) -> Optional[float]:
    nums = [v for v in values if isinstance(v, (int, float))]
    return round(median(nums), 1) if nums else None


def _gap_delta(client_val: Optional[float], comp_median: Optional[float]) -> Optional[float]:
    """A positive delta = competitors are AHEAD (the client must gain this much
    to reach the competitor median). None when either side is unknown. Pure."""
    if client_val is None or comp_median is None:
        return None
    return round(comp_median - client_val, 1)


def build_authority_gap(
    client_auth: Optional[dict], competitor_auths: list[dict]
) -> dict:
    """Assemble the referring-domain / domain-rating gap for one keyword. Pure.

    `client_auth`/each `competitor_auth`: {page_rd, page_ur, domain_rd, dr}
    (page-level from the snapshot's result rows, domain-level from its domain
    rows — already captured, no new calls). Deltas are competitor-median minus
    client (positive = competitors ahead)."""
    ca = client_auth or {}
    page_rd_med = _median_of([c.get("page_rd") for c in competitor_auths])
    domain_rd_med = _median_of([c.get("domain_rd") for c in competitor_auths])
    dr_med = _median_of([c.get("dr") for c in competitor_auths])
    return {
        "client": client_auth,
        "competitors": competitor_auths,
        "competitor_page_rd_median": page_rd_med,
        "competitor_domain_rd_median": domain_rd_med,
        "competitor_dr_median": dr_med,
        "page_rd_gap": _gap_delta(ca.get("page_rd"), page_rd_med),
        "domain_rd_gap": _gap_delta(ca.get("domain_rd"), domain_rd_med),
        "dr_gap": _gap_delta(ca.get("dr"), dr_med),
        # The suite-standard caveat: these are DataForSEO tool reads (0–1000),
        # roughly ×10 a Moz-style DA, not Moz DA itself.
        "caveat": "RD/DR are DataForSEO tool reads (0–1000), ~×10 of a Moz-style DA — not Moz DA.",
    }


def build_site_traffic_gap(
    traffic_by_domain: dict[str, Optional[float]],
    client_domain: str,
    competitor_domains: list[str],
) -> dict:
    """Domain-level estimated organic traffic gap (§3.1 #5), from one batched
    `bulk_traffic` call. Pure. Deltas: competitor-median minus client."""
    client_t = traffic_by_domain.get(_norm_domain(client_domain)) if client_domain else None
    comps = [
        {"domain": d, "organic_traffic_est": traffic_by_domain.get(_norm_domain(d))}
        for d in competitor_domains
    ]
    comp_median = _median_of([c["organic_traffic_est"] for c in comps])
    return {
        "basis": "estimated (DataForSEO)",
        "client": client_t,
        "competitors": comps,
        "competitor_median": comp_median,
        "delta": _gap_delta(client_t, comp_median),
    }


def build_page_traffic_gap(
    client_est: Optional[float], competitor_ests: list[dict]
) -> dict:
    """Page-level MODELED traffic gap (§3.1 #6). Pure. `competitor_ests`:
    [{domain, url, estimate}]. Explicitly labelled 'estimated (modeled)' — this
    is Σ(volume × position-CTR), not a measured ETV."""
    comp_median = _median_of([c.get("estimate") for c in competitor_ests])
    return {
        "basis": "estimated (modeled)",
        "method": "sum(search_volume × position-CTR) over the page's ranked keywords",
        "client": client_est,
        "competitors": competitor_ests,
        "competitor_median": comp_median,
        "delta": _gap_delta(client_est, comp_median),
    }


def build_entity_gap(
    serp_entities: list[dict], score_deficiencies: list[dict], top_n: int = 25
) -> dict:
    """The entity gap (§3.1 #1). Pure. SERP side = the aggregated entities from
    nlp `/analyze` (already grouped with a `page_spread` count across
    competitors — the right shape for a gap). Client side = the entity/signal
    deficiencies from nlp `/score-page` (no endpoint returns a raw client entity
    list, so the score engines carry client-vs-SERP coverage)."""
    ents = [
        {
            "name": e.get("name"),
            "type": e.get("entity_type"),
            "page_spread": e.get("page_spread"),
            "page_spread_pct": e.get("page_spread_pct"),
            "recommended_mentions": e.get("recommended_mentions"),
            "wiki_link": e.get("wiki_link") or None,
        }
        for e in (serp_entities or [])[: max(0, top_n)]
    ]
    client_defs = [
        d
        for d in (score_deficiencies or [])
        if (d.get("engine_key") or d.get("engine")) in _ENTITY_DEFICIENCY_ENGINES
    ]
    return {
        "serp_entities": ents,
        "serp_entity_count": len(serp_entities or []),
        "client_deficiencies": client_defs,
    }


def assemble_authority(
    client_domain: str,
    competitors: list[dict],
    result_rows: list[dict],
    domain_rows: list[dict],
) -> dict:
    """Build the authority gap from the snapshot's already-captured page rows
    (RD/UR) and domain rows (RD/DR) — no new calls (§3.1 #2/#3). Pure.

    `result_rows` are `serp_snapshot_results` (page-level referring_domains /
    url_rating); `domain_rows` are `serp_snapshot_domains` (domain_rating +
    domain-level referring_domains). Matches competitor page rows by URL and
    domain rows by domain; the client's own row is found via `is_client`."""
    by_url = {_norm_url(r.get("url")): r for r in result_rows if r.get("url")}
    by_domain = {_norm_domain(r.get("domain")): r for r in domain_rows if r.get("domain")}

    client_page = next((r for r in result_rows if r.get("is_client")), None)
    client_domain_row = by_domain.get(_norm_domain(client_domain)) or next(
        (r for r in domain_rows if r.get("is_client")), None
    )
    client_auth: Optional[dict] = None
    if client_page or client_domain_row:
        client_auth = {
            "page_rd": (client_page or {}).get("referring_domains"),
            "page_ur": (client_page or {}).get("url_rating"),
            "domain_rd": (client_domain_row or {}).get("referring_domains"),
            "dr": (client_domain_row or {}).get("domain_rating"),
        }

    competitor_auths: list[dict] = []
    for c in competitors or []:
        page = by_url.get(_norm_url(c.get("url"))) or {}
        drow = by_domain.get(_norm_domain(c.get("domain"))) or {}
        competitor_auths.append(
            {
                "domain": c.get("domain"),
                "position": c.get("position"),
                "page_rd": page.get("referring_domains"),
                "page_ur": page.get("url_rating"),
                "domain_rd": drow.get("referring_domains"),
                "dr": drow.get("domain_rating"),
            }
        )
    return build_authority_gap(client_auth, competitor_auths)


# ===========================================================================
# Snapshot read (the cost-critical reuse, PRD §8)
# ===========================================================================
def _snapshot_fresh(captured_at: Optional[str], max_age_days: int, now: Optional[datetime] = None) -> bool:
    """Whether a snapshot's captured_at is within the reuse window."""
    if not captured_at:
        return False
    now = now or datetime.now(timezone.utc)
    try:
        ts = datetime.fromisoformat(str(captured_at).replace("Z", "+00:00"))
    except ValueError:
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (now - ts) <= timedelta(days=max_age_days)


def latest_reusable_snapshot(
    supabase, client_id: str, keyword: str, max_age_days: int
) -> Optional[dict]:
    """The client's newest complete/partial `serp_snapshots` row for a keyword
    within the reuse window, or None (→ a fresh capture is needed). Reads only;
    a failed-status snapshot is skipped."""
    res = (
        supabase.table("serp_snapshots")
        .select("*")
        .eq("client_id", client_id)
        .eq("keyword", keyword)
        .in_("status", ["complete", "partial"])
        .order("captured_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    if not rows:
        return None
    snap = rows[0]
    if not _snapshot_fresh(snap.get("captured_at"), max_age_days):
        return None
    return snap


def _snapshot_result_rows(supabase, snapshot_id: str) -> list[dict]:
    res = (
        supabase.table("serp_snapshot_results")
        .select("position, url, domain, is_client, referring_domains, url_rating")
        .eq("snapshot_id", snapshot_id)
        .order("position")
        .execute()
    )
    return res.data or []


def _snapshot_domain_rows(supabase, snapshot_id: str) -> list[dict]:
    """Per-domain backlink rows for a snapshot (domain-level RD + DR)."""
    res = (
        supabase.table("serp_snapshot_domains")
        .select("domain, is_client, domain_rating, referring_domains")
        .eq("snapshot_id", snapshot_id)
        .execute()
    )
    return res.data or []


# ===========================================================================
# Budget meter (fail-closed, PRD §7)
# ===========================================================================
def _today() -> str:
    return date.today().isoformat()


def _reserve(n: int) -> bool:
    """Reserve `n` paid calls against today's content-gap budget. Returns True
    only when the reservation is CONFIRMED within the cap — fail-CLOSED (PRD §7):
    an accounting error blocks the spend rather than proceeding, so no paid call
    ever runs without a confirmed reservation. (Deliberately stricter than
    domain_intel's fail-open reserve_budget.) A cap of 0 disables the guard."""
    cap = settings.content_gap_daily_call_budget
    if cap <= 0 or n <= 0:
        return True
    try:
        res = get_supabase().rpc(
            "reserve_content_gap_calls", {"p_day": _today(), "p_n": int(n), "p_cap": cap}
        ).execute()
        return res.data is True
    except Exception as exc:  # noqa: BLE001 — fail-closed: no confirmed reservation → no spend
        logger.warning("content_gap.budget_accounting_failed", extra={"error": str(exc), "n": n})
        return False


# ===========================================================================
# nlp + scrape helpers (job-friendly: best-effort, return None/unavailable)
# ===========================================================================
async def _post_nlp(path: str, payload: dict, timeout: float = 90.0) -> Optional[dict]:
    """POST to a plain-JSON nlp endpoint; return the parsed body or None.

    Job-friendly (unlike local_seo_service._post_nlp, which raises
    HTTPException): a dimension degrades to 'unavailable' on any failure (§4.1),
    it never aborts the scan. platform-api → nlp over HTTP — nlp is never
    imported (separate Railway service)."""
    url = f"{settings.nlp_api_url}{path}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload)
        if resp.status_code != 200:
            logger.warning(
                "content_gap.nlp_http_error",
                extra={"path": path, "status_code": resp.status_code, "body": resp.text[:300]},
            )
            return None
        return resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("content_gap.nlp_request_error", extra={"path": path, "error": str(exc)[:200]})
        return None


async def _scrape_signals(url: Optional[str]) -> dict:
    """Scrape a page and extract its on-page signals, or {"available": False}
    on any failure (404 / bot-block / empty) — PRD §4.1."""
    if not url:
        return {"available": False}
    try:
        html = await scrapeowl_fetch(url)
    except Exception as exc:  # noqa: BLE001 — a scrape failure degrades the column, never fatal
        logger.warning("content_gap.scrape_failed", extra={"url": url, "error": str(exc)[:200]})
        return {"available": False}
    if not html or not html.strip():
        return {"available": False}
    try:
        return page_signals_from_html(html, url=url)
    except Exception as exc:  # noqa: BLE001
        logger.warning("content_gap.signals_failed", extra={"url": url, "error": str(exc)[:200]})
        return {"available": False}


# ===========================================================================
# Scope resolution (§7 — money pages from tracked_keywords.canonical_url)
# ===========================================================================
def resolve_scope(supabase, client_id: str) -> list[dict]:
    """The client's active tracked keywords + their canonical (money-page) URL —
    the monthly auto-scope (owner ruling 2026-09-15). Keyed on the keyword, which
    is how `serp_snapshots` are stored. Returns [{keyword, page_url, keyword_id}]
    — `keyword_id` drives the fresh-capture enqueue when no snapshot is reusable."""
    props = (
        supabase.table("gsc_properties").select("id").eq("client_id", client_id).execute()
    ).data or []
    prop_ids = [p["id"] for p in props]
    if not prop_ids:
        return []
    kws = (
        supabase.table("tracked_keywords")
        .select("id, keyword, canonical_url")
        .in_("property_id", prop_ids)
        .eq("active", True)
        .execute()
    ).data or []
    scope: list[dict] = []
    seen: set[str] = set()
    for k in kws:
        kw = (k.get("keyword") or "").strip()
        if not kw or kw.lower() in seen:
            continue
        seen.add(kw.lower())
        scope.append(
            {"keyword": kw, "page_url": k.get("canonical_url"), "keyword_id": k.get("id")}
        )
    return scope


def _registry_domains(supabase, client_id: str) -> set[str]:
    rows = (
        supabase.table("client_competitors")
        .select("domain")
        .eq("client_id", client_id)
        .eq("active", True)
        .execute()
    ).data or []
    return {_norm_domain(r.get("domain")) for r in rows if r.get("domain")}


# ===========================================================================
# Enqueue + job skeleton (Phase 0: read an existing snapshot, record verdicts)
# ===========================================================================
def enqueue_content_gap_scan(client_id: str, trigger: str = "manual") -> Optional[str]:
    """Create a `content_gap_runs` row + enqueue a `content_gap_scan` job.

    Returns the run id, or None when the module is disabled. Deduped against a
    pending/running run for the same client.
    """
    if not settings.content_gap_enabled:
        return None
    supabase = get_supabase()
    existing = (
        supabase.table("content_gap_runs")
        .select("id")
        .eq("client_id", client_id)
        .in_("status", ["pending", "running"])
        .limit(1)
        .execute()
    ).data or []
    if existing:
        return existing[0]["id"]
    run = (
        supabase.table("content_gap_runs")
        .insert({"client_id": client_id, "trigger": trigger, "status": "pending"})
        .execute()
    ).data[0]
    supabase.table("async_jobs").insert(
        {
            "job_type": "content_gap_scan",
            "entity_id": client_id,
            "payload": {"client_id": client_id, "run_id": run["id"]},
        }
    ).execute()
    return run["id"]


# ===========================================================================
# Budget read + free estimate preflight (§8 — the "estimate" API, no spend)
# ===========================================================================
def budget_remaining() -> int:
    """Paid content-gap calls left in today's budget (a large number when the
    cap is disabled). Mirrors domain_intel.budget_remaining."""
    cap = settings.content_gap_daily_call_budget
    if cap <= 0:
        return 10**9
    try:
        rows = (
            get_supabase()
            .table("content_gap_usage")
            .select("calls")
            .eq("day", _today())
            .limit(1)
            .execute()
        ).data
    except Exception:  # noqa: BLE001 — a read failure shouldn't zero the estimate
        return cap
    used = rows[0]["calls"] if rows else 0
    return max(0, cap - used)


def estimate_max_calls(
    keyword_count: int, max_competitors: int, page_traffic: bool = True
) -> int:
    """Upper-bound paid calls a full scan could make (§8). Pure.

    Worst case is every keyword being a gap and hitting the competitor cap, so
    each keyword makes `estimate_deep_calls(max_competitors, page_traffic)`.
    Wins short-circuit and thin competitor sets under-spend this, so it is a
    ceiling — the free preflight number, never a promise."""
    kw = max(0, int(keyword_count))
    comp = max(0, int(max_competitors))
    return kw * estimate_deep_calls(comp, page_traffic)


def estimate_scan(supabase, client_id: str) -> dict:
    """Free preflight (§8): the client's keyword × money-page scope, the
    worst-case call ceiling, and today's remaining budget. Reads only — no paid
    call, no enqueue. Powers the run-now scope preview."""
    scope = resolve_scope(supabase, client_id)
    with_page = sum(1 for s in scope if (s.get("page_url") or "").strip())
    max_calls = estimate_max_calls(
        len(scope),
        settings.content_gap_max_competitors,
        settings.content_gap_page_traffic_enabled,
    )
    return {
        "keyword_count": len(scope),
        "money_page_count": with_page,
        "scope": scope,
        "estimated_max_calls": max_calls,
        "budget_remaining": budget_remaining(),
        "max_competitors": settings.content_gap_max_competitors,
        "snapshot_max_age_days": settings.content_gap_snapshot_max_age_days,
    }


# ===========================================================================
# Reads for the API (runs list + detail)
# ===========================================================================
def list_runs(client_id: str, limit: int = 50) -> list[dict]:
    """The client's content-gap runs, newest first (summary rows)."""
    return (
        get_supabase()
        .table("content_gap_runs")
        .select(
            "id, trigger, status, keywords_analyzed, wins, gaps, error, "
            "created_at, completed_at"
        )
        .eq("client_id", client_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    ).data or []


def get_run_detail(client_id: str, run_id: str) -> Optional[dict]:
    """One run + its per-keyword rows (verdict + competitor set + per-dimension
    gap + on-page diff). Returns None when the run isn't the client's. The nested
    `gap`/`onpage_diff`/`competitors` jsonb is returned verbatim (never through a
    strict response_model that would strip dimension fields — the Phase-1
    ReoptAction lesson)."""
    supabase = get_supabase()
    runs = (
        supabase.table("content_gap_runs")
        .select("*")
        .eq("id", run_id)
        .eq("client_id", client_id)
        .limit(1)
        .execute()
    ).data or []
    if not runs:
        return None
    keywords = (
        supabase.table("content_gap_keywords")
        .select("*")
        .eq("run_id", run_id)
        .order("created_at")
        .execute()
    ).data or []
    # Verdict order: gaps first (full → organic → aio), wins last — the drill-in
    # leads with what needs work.
    order = {"full_gap": 0, "organic_gap": 1, "aio_gap": 2, "win": 3}
    keywords.sort(key=lambda k: (order.get(k.get("verdict"), 9), k.get("keyword") or ""))
    return {"run": runs[0], "keywords": keywords}


# ===========================================================================
# Pure: CSV export rows (§8, §9)
# ===========================================================================
CSV_HEADERS = [
    "keyword",
    "page_url",
    "verdict",
    "client_position",
    "aio_present",
    "in_aio",
    "competitor_count",
    "top_competitor",
    "page_rd_gap",
    "domain_rd_gap",
    "dr_gap",
    "word_count_delta",
    "freshness_days_behind",
    "dimensions_unavailable",
]


def build_run_csv_rows(keywords: list[dict]) -> list[list]:
    """Flatten a run's keyword rows into a CSV table (the verdict table + the
    headline authority/on-page deltas). Pure — pulls defensively from the nested
    `gap`/`onpage_diff` jsonb so a partially-measured row still exports."""
    rows: list[list] = []
    for k in keywords or []:
        gap = k.get("gap") if isinstance(k.get("gap"), dict) else {}
        auth = gap.get("authority") if isinstance(gap.get("authority"), dict) else {}
        diff = k.get("onpage_diff") if isinstance(k.get("onpage_diff"), dict) else {}
        comps = k.get("competitors") if isinstance(k.get("competitors"), list) else []
        top = comps[0] if comps else {}
        word = diff.get("word_count") if isinstance(diff.get("word_count"), dict) else {}
        fresh = diff.get("freshness") if isinstance(diff.get("freshness"), dict) else {}
        rows.append(
            [
                k.get("keyword") or "",
                k.get("page_url") or "",
                k.get("verdict") or "",
                k.get("client_position"),
                k.get("aio_present"),
                k.get("in_aio"),
                len(comps),
                (top or {}).get("domain") or "",
                auth.get("page_rd_gap"),
                auth.get("domain_rd_gap"),
                auth.get("dr_gap"),
                word.get("delta"),
                fresh.get("client_days_behind_median"),
                "; ".join(gap.get("dimensions_unavailable") or []),
            ]
        )
    return rows


# ===========================================================================
# Monthly scheduler hook (§8 — enqueue_due_content_gap_scans)
# ===========================================================================
def enqueue_due_content_gap_scans() -> int:
    """Enqueue a monthly scan for each eligible client whose last COMPLETED
    content-gap scan is older than `content_gap_interval_days`. Daily due-check
    on the shared scheduler; self-gated + budget-guarded + fully
    exception-guarded (it runs in the scheduler's single daily try-block, so
    raising here would starve every hook after it). Returns the enqueued count.

    Eligibility mirrors the monthly auto-scope (owner ruling): a client with at
    least one active tracked keyword carrying a `canonical_url` (a money page).
    The last-run signal is the async_jobs history (latest completed
    content_gap_scan per client), NOT the run rows — a run that legitimately
    finds only wins still counts as "run", and a row read is subject to the
    PostgREST cap.
    """
    try:
        return _enqueue_due_content_gap_scans()
    except Exception as exc:  # noqa: BLE001
        logger.error("content_gap.due_check_failed", extra={"error": str(exc)})
        return 0


def _enqueue_due_content_gap_scans() -> int:
    if not (settings.content_gap_enabled and settings.content_gap_auto_enabled):
        return 0
    # Fresh captures + the deep pass draw on DataForSEO; without creds a scheduled
    # scan can only degrade, so don't burn the daily due-check on it.
    if not (settings.dataforseo_login and settings.dataforseo_password):
        return 0
    if budget_remaining() <= 0:
        return 0
    supabase = get_supabase()

    # Money-page owners: clients with an active tracked keyword carrying a
    # canonical_url, resolved property → client via gsc_properties.
    kw_rows = (
        supabase.table("tracked_keywords")
        .select("property_id, canonical_url, active")
        .eq("active", True)
        .execute()
    ).data or []
    prop_ids = {r["property_id"] for r in kw_rows if r.get("canonical_url") and r.get("property_id")}
    if not prop_ids:
        return 0
    prop_rows = (
        supabase.table("gsc_properties")
        .select("id, client_id")
        .in_("id", sorted(prop_ids))
        .execute()
    ).data or []
    eligible = {r["client_id"] for r in prop_rows if r.get("client_id")}
    if not eligible:
        return 0

    cutoff_iso = (
        datetime.now(timezone.utc) - timedelta(days=settings.content_gap_interval_days)
    ).isoformat()
    recent: set[str] = set()
    try:
        recent = {
            r["entity_id"]
            for r in (
                supabase.table("async_jobs")
                .select("entity_id")
                .eq("job_type", "content_gap_scan")
                .eq("status", "complete")
                .gte("completed_at", cutoff_iso)
                .execute()
            ).data or []
            if r.get("entity_id")
        }
    except Exception:  # noqa: BLE001
        recent = set()
    pending: set[str] = set()
    try:
        pending = {
            r["entity_id"]
            for r in (
                supabase.table("async_jobs")
                .select("entity_id")
                .eq("job_type", "content_gap_scan")
                .in_("status", ["pending", "running"])
                .execute()
            ).data or []
            if r.get("entity_id")
        }
    except Exception:  # noqa: BLE001
        pending = set()

    count = 0
    for cid in eligible - recent - pending:
        try:
            if enqueue_content_gap_scan(cid, trigger="scheduled"):
                count += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("content_gap.enqueue_failed", extra={"client_id": cid, "error": str(exc)})
    if count:
        logger.info("content_gap.enqueued", extra={"count": count})
    return count


# ===========================================================================
# Deep-dimension pass (Phase 1) — assumes the budget is already reserved
# ===========================================================================
async def _page_traffic_gap(
    client_domain: str,
    client_url: Optional[str],
    competitors: list[dict],
    location_code: Optional[int],
) -> dict:
    """Modeled page-traffic gap (§3.1 #6): one `fetch_ranked_keywords` call per
    competitor domain (filtered to the ranking URL) + one for the client."""
    competitor_ests: list[dict] = []
    for c in competitors:
        dom, url = c.get("domain"), c.get("url")
        est: Optional[float] = None
        if dom and url:
            try:
                rows, _ = await dataforseo_labs.fetch_ranked_keywords(dom, location_code)
                est = estimate_page_traffic(rows, url)
            except Exception as exc:  # noqa: BLE001 — one competitor degrading is not fatal
                logger.warning("content_gap.page_traffic_failed", extra={"domain": dom, "error": str(exc)[:200]})
        competitor_ests.append({"domain": dom, "url": url, "estimate": est})

    client_est: Optional[float] = None
    if client_url and client_domain:
        try:
            rows, _ = await dataforseo_labs.fetch_ranked_keywords(client_domain, location_code)
            client_est = estimate_page_traffic(rows, client_url)
        except Exception as exc:  # noqa: BLE001
            logger.warning("content_gap.page_traffic_failed", extra={"domain": client_domain, "error": str(exc)[:200]})
    return build_page_traffic_gap(client_est, competitor_ests)


async def _deep_dimensions(
    *,
    keyword: str,
    client_url: Optional[str],
    client_domain: str,
    business: dict,
    competitors: list[dict],
    result_rows: list[dict],
    domain_rows: list[dict],
    aio_present: bool,
    aio_sources: list[dict],
    location_code: Optional[int],
    entity_provider: Optional[str],
    page_traffic_enabled: bool,
) -> tuple[dict, Optional[dict]]:
    """Run the deep-dimension pass for one gapped keyword. Best-effort per
    dimension (PRD §4.1): a failed dimension is recorded in
    `dimensions_unavailable`, the rest still assemble. Returns
    `(gap, onpage_diff)`. Assumes the caller already reserved the budget."""
    gap: dict[str, Any] = {}
    unavailable: list[str] = []

    # --- Authority (free — the snapshot rows are already in hand) ---
    try:
        gap["authority"] = assemble_authority(client_domain, competitors, result_rows, domain_rows)
    except Exception as exc:  # noqa: BLE001
        logger.warning("content_gap.authority_failed", extra={"keyword": keyword, "error": str(exc)[:200]})
        unavailable.append("authority")

    # --- AIO citation gap (free) — who's cited in the AIO that the client isn't ---
    if aio_present:
        gap["aio_citation"] = {"cited_sources_not_client": aio_gap_sources(aio_sources, client_domain)}

    # --- SERP entities (nlp /analyze) — also reused as /score-page's serp_analysis ---
    analyze_result = await _post_nlp(
        "/analyze",
        {"keyword": keyword, "location": "", "location_code": location_code, "entity_provider": entity_provider},
    )
    if analyze_result is None:
        unavailable.append("serp_entities")

    # --- Client entity/structure/signal deficiencies (nlp /score-page on the client URL) ---
    score_result: Optional[dict] = None
    if client_url:
        score_result = await _post_nlp(
            "/score-page",
            {
                "keyword": keyword,
                "location": "",
                "location_code": location_code,
                "page_url": client_url,
                "page_content": None,
                "business_name": business.get("business_name") or "",
                "gbp_category": business.get("gbp_category") or "",
                "address": business.get("address") or "",
                "serp_analysis": analyze_result,
                "entity_provider": entity_provider,
            },
        )
        if score_result is None:
            unavailable.append("onpage_score")
    else:
        unavailable.append("onpage_score_no_client_url")

    if analyze_result is not None or score_result is not None:
        gap["entities"] = build_entity_gap(
            (analyze_result or {}).get("google_entities") or [],
            (score_result or {}).get("deficiencies") or [],
        )
    if score_result is not None:
        gap["onpage_score"] = {
            "composite_score": score_result.get("composite_score"),
            "composite_status": score_result.get("composite_status"),
            "engine_scores": score_result.get("engine_scores"),
            "deficiencies": score_result.get("deficiencies"),
        }

    # --- Site traffic (one batched bulk_traffic call) ---
    comp_domains = [c["domain"] for c in competitors if c.get("domain")]
    try:
        targets = [d for d in dict.fromkeys([client_domain, *comp_domains]) if d]
        traffic_by_domain, _ = await dataforseo_labs.fetch_bulk_traffic(targets, location_code)
        gap["site_traffic"] = build_site_traffic_gap(traffic_by_domain, client_domain, comp_domains)
    except Exception as exc:  # noqa: BLE001
        logger.warning("content_gap.site_traffic_failed", extra={"keyword": keyword, "error": str(exc)[:200]})
        unavailable.append("site_traffic")

    # --- Page traffic (modeled; the priciest sub-dimension, config-gated) ---
    if page_traffic_enabled:
        try:
            gap["page_traffic"] = await _page_traffic_gap(client_domain, client_url, competitors, location_code)
        except Exception as exc:  # noqa: BLE001
            logger.warning("content_gap.page_traffic_dim_failed", extra={"keyword": keyword, "error": str(exc)[:200]})
            unavailable.append("page_traffic")

    # --- On-page diff (scrape client + capped competitors) ---
    onpage_diff: Optional[dict] = None
    try:
        client_signals = await _scrape_signals(client_url)
        competitor_signals: list[dict] = []
        for c in competitors:
            sig = await _scrape_signals(c.get("url"))
            sig["domain"] = c.get("domain")
            sig["url"] = c.get("url")
            sig["position"] = c.get("position")
            competitor_signals.append(sig)
        onpage_diff = build_onpage_diff(client_signals, competitor_signals)
    except Exception as exc:  # noqa: BLE001
        logger.warning("content_gap.onpage_diff_failed", extra={"keyword": keyword, "error": str(exc)[:200]})
        unavailable.append("onpage_diff")

    gap["dimensions_unavailable"] = unavailable
    return gap, onpage_diff


async def run_content_gap_scan_job(job: dict) -> None:
    """async_jobs handler for `content_gap_scan`.

    Resolve the client's keyword × money-page scope; per keyword read the latest
    reusable `serp_snapshots` row (the cost-critical reuse, PRD §8), compute the
    win/gap verdict + competitor set, and — for a GAP (wins short-circuit, PRD
    §8) — reserve the deep-pass budget then run the deep dimensions (authority /
    site + modeled page traffic / SERP + client entities via nlp /analyze +
    /score-page / the competitor-anchored on-page diff), writing `gap` +
    `onpage_diff`. A keyword with no reusable snapshot enqueues a fresh
    `serp_snapshot` capture (budget-reserved + count-bounded) and defers to the
    next run rather than fabricating a verdict.
    """
    payload = job.get("payload") or {}
    client_id = payload.get("client_id")
    run_id = payload.get("run_id")
    job_id = job["id"]
    supabase = get_supabase()

    def _fail(msg: str) -> None:
        if run_id:
            supabase.table("content_gap_runs").update(
                {"status": "failed", "error": msg[:500], "completed_at": "now()"}
            ).eq("id", run_id).execute()
        supabase.table("async_jobs").update(
            {"status": "failed", "error": msg[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()

    if not settings.content_gap_enabled:
        _fail("content_gap_disabled")
        return
    if not client_id or not run_id:
        _fail("missing client_id or run_id")
        return

    supabase.table("content_gap_runs").update({"status": "running"}).eq("id", run_id).execute()

    # The worker loop only LOGS an unhandled handler exception (job_worker.py) —
    # it does not settle — so a transient DB error mid-scan would leave the run +
    # job stuck 'running' until the reaper requeues and RE-RUNS the whole scan,
    # double-inserting content_gap_keywords rows (no idempotency guard). Settle
    # 'failed' on any error so a re-run never duplicates; on-demand re-run is the
    # recovery path for a genuinely transient failure.
    try:
        client = (
            supabase.table("clients")
            .select("id, name, website_url, gbp, business_location")
            .eq("id", client_id)
            .limit(1)
            .execute()
        ).data or []
        if not client:
            _fail("client_not_found")
            return
        client_row = client[0]
        client_domain = _norm_domain(client_row.get("website_url"))
        gbp = client_row.get("gbp") if isinstance(client_row.get("gbp"), dict) else {}
        business = {
            "business_name": (gbp or {}).get("business_name") or client_row.get("name") or "",
            "gbp_category": (gbp or {}).get("gbp_category") or "",
            "address": (gbp or {}).get("address") or client_row.get("business_location") or "",
        }

        scope = resolve_scope(supabase, client_id)
        registry = _registry_domains(supabase, client_id)
        max_age = settings.content_gap_snapshot_max_age_days
        max_comp = settings.content_gap_max_competitors
        page_traffic_enabled = settings.content_gap_page_traffic_enabled
        max_fresh = settings.content_gap_max_fresh_captures
        snap_estimate = settings.content_gap_snapshot_call_estimate
        entity_provider = None  # nlp defaults to textrazor; a per-run choice is a later phase

        analyzed = wins = gaps = 0
        no_snapshot = pending_capture = budget_limited = deep_analyzed = 0
        fresh_enqueued = 0
        rows: list[dict] = []
        for item in scope:
            keyword = item["keyword"]
            snap = latest_reusable_snapshot(supabase, client_id, keyword, max_age)
            if snap is None:
                # No reusable snapshot → enqueue a fresh capture (budget-reserved +
                # count-bounded) and defer this keyword to the NEXT run: a
                # freshly-enqueued serp_snapshot job hasn't run yet, and the scan
                # never blocks on another job. A keyword with no keyword_id, or once
                # the per-run capture cap is hit, is left as no_snapshot.
                kid = item.get("keyword_id")
                if kid and fresh_enqueued < max_fresh:
                    if _reserve(snap_estimate):
                        serp_snapshot.enqueue_serp_snapshot(client_id, kid)
                        fresh_enqueued += 1
                        pending_capture += 1
                    else:
                        budget_limited += 1
                else:
                    no_snapshot += 1
                continue

            aio_present = bool(snap.get("aio_present"))
            aio_sources = snap.get("aio_sources") or []
            client_position = snap.get("client_rank")
            in_aio = client_cited_in_aio(aio_sources, client_domain) if aio_present else False
            verdict = compute_verdict(client_position, aio_present, in_aio)
            page_url = item.get("page_url") or snap.get("client_url")

            competitors: Optional[list[dict]] = None
            gap: Optional[dict] = None
            onpage_diff: Optional[dict] = None
            if is_gap(verdict):
                result_rows = _snapshot_result_rows(supabase, snap["id"])
                competitors = resolve_competitors(
                    result_rows, client_position, registry, client_domain, max_comp
                )
                # Wins short-circuit (no deep spend, PRD §8); a gap reserves its
                # whole deep-pass budget BEFORE any paid call (fail-closed §7). A
                # refused reservation keeps the shallow verdict row and marks the
                # keyword budget_limited — a re-run recovers it once budget frees.
                n = estimate_deep_calls(len(competitors), page_traffic_enabled)
                if _reserve(n):
                    domain_rows = _snapshot_domain_rows(supabase, snap["id"])
                    gap, onpage_diff = await _deep_dimensions(
                        keyword=keyword,
                        client_url=page_url,
                        client_domain=client_domain,
                        business=business,
                        competitors=competitors,
                        result_rows=result_rows,
                        domain_rows=domain_rows,
                        aio_present=aio_present,
                        aio_sources=aio_sources,
                        location_code=snap.get("location_code"),
                        entity_provider=entity_provider,
                        page_traffic_enabled=page_traffic_enabled,
                    )
                    deep_analyzed += 1
                else:
                    budget_limited += 1

            rows.append(
                {
                    "run_id": run_id,
                    "client_id": client_id,
                    "keyword": keyword,
                    "page_url": page_url,
                    "client_position": client_position,
                    "aio_present": aio_present,
                    "in_aio": in_aio,
                    "verdict": verdict,
                    "competitors": competitors,
                    "gap": gap,
                    "onpage_diff": onpage_diff,
                    "serp_snapshot_id": snap["id"],
                    "captured_fresh": False,
                }
            )
            analyzed += 1
            if verdict == "win":
                wins += 1
            else:
                gaps += 1

        if rows:
            supabase.table("content_gap_keywords").insert(rows).execute()

        # 'partial' when any keyword was deferred (pending a fresh capture, budget
        # limited, or left unmeasured) — an honest signal a re-run has work left.
        deferred = pending_capture + budget_limited + no_snapshot
        run_status = "partial" if deferred else "complete"
        supabase.table("content_gap_runs").update(
            {
                "status": run_status,
                "keywords_analyzed": analyzed,
                "wins": wins,
                "gaps": gaps,
                "completed_at": "now()",
            }
        ).eq("id", run_id).execute()
        result = {
            "analyzed": analyzed,
            "wins": wins,
            "gaps": gaps,
            "deep_analyzed": deep_analyzed,
            "no_snapshot": no_snapshot,
            "pending_capture": pending_capture,
            "budget_limited": budget_limited,
        }
        supabase.table("async_jobs").update(
            {"status": "complete", "result": result, "completed_at": "now()"}
        ).eq("id", job_id).execute()
        logger.info("content_gap_scan_complete", extra={"client_id": client_id, "run_id": run_id, **result})
    except Exception as exc:  # noqa: BLE001 — settle failed so the reaper can't re-run + duplicate
        logger.exception("content_gap_scan_failed", extra={"client_id": client_id, "run_id": run_id})
        _fail(f"content_gap_error: {str(exc)[:400]}")
