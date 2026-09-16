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

from bs4 import BeautifulSoup

from config import settings
from db.supabase_client import get_supabase
from services.dataforseo_rank import extract_domain
from services.page_structure_eval import (
    block_types_of,
    extract_outline_from_html,
    word_count_of,
)

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
        if not d or d == cd:
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
    }


# ===========================================================================
# Pure: the on-page diff assembler (PRD §4)
# ===========================================================================
def _label(domain: Optional[str], url: Optional[str]) -> str:
    return domain or _norm_domain(url) or "competitor"


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
    }


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


# ===========================================================================
# Scope resolution (§7 — money pages from tracked_keywords.canonical_url)
# ===========================================================================
def resolve_scope(supabase, client_id: str) -> list[dict]:
    """The client's active tracked keywords + their canonical (money-page) URL —
    the monthly auto-scope (owner ruling 2026-09-15). Keyed on the keyword, which
    is how `serp_snapshots` are stored. Returns [{keyword, page_url}]."""
    props = (
        supabase.table("gsc_properties").select("id").eq("client_id", client_id).execute()
    ).data or []
    prop_ids = [p["id"] for p in props]
    if not prop_ids:
        return []
    kws = (
        supabase.table("tracked_keywords")
        .select("keyword, canonical_url")
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
        scope.append({"keyword": kw, "page_url": k.get("canonical_url")})
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


async def run_content_gap_scan_job(job: dict) -> None:
    """async_jobs handler for `content_gap_scan`.

    Phase 0 scope: resolve the client's keyword × money-page scope, read the
    latest reusable `serp_snapshots` row per keyword (the cost-critical reuse,
    PRD §8), compute the win/gap verdict + competitor set, and persist one
    `content_gap_keywords` row per keyword. The deep dimensions (live-page
    scrapes, nlp `/analyze` + `/score-page`, dataforseo_labs traffic, calling
    `build_onpage_diff` end-to-end) are added in later phases — those rows land
    with `gap`/`onpage_diff` null for now.
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

    client = (
        supabase.table("clients").select("id, website_url").eq("id", client_id).limit(1).execute()
    ).data or []
    if not client:
        _fail("client_not_found")
        return
    client_domain = _norm_domain(client[0].get("website_url"))

    scope = resolve_scope(supabase, client_id)
    registry = _registry_domains(supabase, client_id)
    max_age = settings.content_gap_snapshot_max_age_days
    max_comp = settings.content_gap_max_competitors

    analyzed = wins = gaps = 0
    rows: list[dict] = []
    for item in scope:
        keyword = item["keyword"]
        snap = latest_reusable_snapshot(supabase, client_id, keyword, max_age)
        if snap is None:
            # Phase 0 reads existing snapshots only; a stale/absent snapshot is
            # recorded so the run is honest about coverage (fresh capture: a
            # later phase enqueues serp_snapshot and re-reads).
            rows.append(
                {
                    "run_id": run_id,
                    "client_id": client_id,
                    "keyword": keyword,
                    "page_url": item.get("page_url"),
                    "verdict": "organic_gap",
                    "client_position": None,
                    "aio_present": None,
                    "in_aio": None,
                    "competitors": None,
                    "captured_fresh": False,
                }
            )
            analyzed += 1
            gaps += 1
            continue

        aio_present = bool(snap.get("aio_present"))
        aio_sources = snap.get("aio_sources") or []
        client_position = snap.get("client_rank")
        in_aio = client_cited_in_aio(aio_sources, client_domain) if aio_present else False
        verdict = compute_verdict(client_position, aio_present, in_aio)

        competitors = None
        if is_gap(verdict):
            organic = _snapshot_result_rows(supabase, snap["id"])
            competitors = resolve_competitors(
                organic, client_position, registry, client_domain, max_comp
            )

        rows.append(
            {
                "run_id": run_id,
                "client_id": client_id,
                "keyword": keyword,
                "page_url": item.get("page_url") or snap.get("client_url"),
                "client_position": client_position,
                "aio_present": aio_present,
                "in_aio": in_aio,
                "verdict": verdict,
                "competitors": competitors,
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

    supabase.table("content_gap_runs").update(
        {
            "status": "complete",
            "keywords_analyzed": analyzed,
            "wins": wins,
            "gaps": gaps,
            "location_code": None,
            "completed_at": "now()",
        }
    ).eq("id", run_id).execute()
    supabase.table("async_jobs").update(
        {"status": "complete", "result": {"analyzed": analyzed, "wins": wins, "gaps": gaps}, "completed_at": "now()"}
    ).eq("id", job_id).execute()
    logger.info(
        "content_gap_scan_complete",
        extra={"client_id": client_id, "run_id": run_id, "analyzed": analyzed, "wins": wins, "gaps": gaps},
    )
