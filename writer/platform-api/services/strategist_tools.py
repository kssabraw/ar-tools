"""SerMaStr drill-down tools — Phase 3 (spec §2 "Drill-down tools").

The strategist's tool belt: bounded, read-only contexts it can pull when the
digest isn't enough. Four are deterministic data assemblers (cheap, no extra
LLM); ``serp_deep_dive`` and ``geogrid_history`` are the two true LLM
subagents (they summarize corpora too large to inline). ``audit_page`` is the
one PAID tool (an nlp-api scoring run) and carries its own tighter cap.

Every tool description is **self-documenting** (spec §2b mechanism 5): it
restates the instrument's semantics and traps so the strategist can't misread
what comes back. Every tool returns a *string* (the LLM reads it), truncated
to ``settings.strategist_tool_result_chars``; failures return a readable
error string, never raise into the tool-use loop.
"""

from __future__ import annotations

import json
import logging
from typing import Awaitable, Callable, Optional

from config import settings
from db.supabase_client import get_supabase
from services import sop_library

logger = logging.getLogger(__name__)

_LLM_TIMEOUT = 90.0


def _clip(text: str) -> str:
    limit = settings.strategist_tool_result_chars
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n…[truncated]"


def _dump(obj) -> str:
    return json.dumps(obj, default=str, ensure_ascii=False)


def _keyword_id(supabase, client_id: str, keyword: str) -> Optional[str]:
    rows = (
        supabase.table("tracked_keywords")
        .select("id").eq("client_id", client_id).ilike("keyword", keyword.strip())
        .limit(1).execute()
    ).data or []
    return rows[0]["id"] if rows else None


async def _subagent(system: str, user: str) -> str:
    """One bounded Sonnet call for the two summarizing subagents. Transient
    failures (429/5xx/connection) retry with backoff so a saturated account
    degrades the tool result only after the budget exhausts."""
    import anthropic

    from services.report_llm import retry_transient

    api = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, timeout=_LLM_TIMEOUT)
    resp = await retry_transient(
        lambda: api.messages.create(
            model=settings.strategist_subagent_model,
            max_tokens=settings.strategist_subagent_max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        ),
        max_retries=2,
        log_tag="strategist_subagent",
    )
    return "\n".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()


# ─────────────────────────────────────────────────────────────────────────────
# Deterministic tools
# ─────────────────────────────────────────────────────────────────────────────
async def _run_episode_timeline(client_id: str, args: dict) -> str:
    keyword = (args.get("keyword") or "").strip()
    if not keyword:
        return "episode_timeline needs a keyword."
    rows = (
        get_supabase().table("response_episodes")
        .select("channel, status, classification, baseline, checks, opened_at, "
                "recovered_at, escalated_at, last_checked_at")
        .eq("client_id", client_id).ilike("keyword", keyword)
        .order("opened_at", desc=True).limit(5).execute()
    ).data or []
    if not rows:
        return f"No response episodes recorded for '{keyword}'."
    return _clip(_dump(rows))


async def _run_read_sop(client_id: str, args: dict) -> str:
    return _clip(sop_library.read_sop(args.get("doc") or "", args.get("section")))


async def _run_competitor_profile(client_id: str, args: dict) -> str:
    """Full assembled profile for ONE registered competitor (the digest carries
    only the summary row). Deterministic read over stored captures."""
    from services import competitor_intel

    wanted = (args.get("competitor") or "").strip().casefold()
    if not wanted:
        return "competitor_profile needs a competitor (name or domain)."
    assembled = competitor_intel.build_profiles(client_id)
    profiles = assembled.get("competitors") or []
    if not profiles:
        return "No competitors are registered for this client yet."
    match = next(
        (p for p in profiles
         if wanted in (p.get("name") or "").casefold()
         or wanted == (p.get("domain") or "").casefold()),
        None,
    )
    if not match:
        names = ", ".join(p.get("name") or "?" for p in profiles[:10])
        return f"No registered competitor matches '{args.get('competitor')}'. Registered: {names}."
    return _clip(_dump({"client_comparison": assembled.get("client"), "competitor": match}))


async def _run_backlink_profile(client_id: str, args: dict) -> str:
    """The client's tracked backlink authority from the Backlink Explorer —
    beyond the digest's summary: per tracked domain (own + tracked competitors)
    the latest DR / RD / backlinks / linked-pages, own-domain link velocity with
    the actual gained/lost domain names, and the top pages by referring domains.
    Deterministic read over stored snapshots — free."""
    from services import backlink_explorer

    tracked = backlink_explorer.list_tracked(client_id)
    if not tracked:
        return ("No tracked backlink targets for this client yet (auto-track runs daily "
                "for clients with a website; the first snapshot may still be pending).")
    out: dict = {
        "tracked_domains": [
            {"domain": t.get("label") or t.get("target"), "latest": t.get("latest")}
            for t in tracked[:8]
        ],
    }
    velocity = backlink_explorer.client_own_domain_change(client_id)
    if velocity:
        out["own_domain_velocity"] = velocity
        # Top pages by RD from the own domain's latest snapshot — where the
        # authority actually lives.
        own = backlink_explorer.match_own_domain_target(tracked, velocity.get("domain"))
        if own:
            snap = backlink_explorer._latest_snapshot(own["id"])
            if snap:
                pages = backlink_explorer._read_pages(snap["id"])
                out["top_pages_by_rd"] = [
                    {k: p.get(k) for k in ("url", "page_rating", "referring_domains", "backlinks")}
                    for p in pages[:10]
                ]
    return _clip(_dump(out))


async def _run_client_capacity(client_id: str, args: dict) -> str:
    """Team capacity + current cross-client plan load. The roles matrix lives
    in _ORCHESTRATOR §6; the load read sums this month's stored task plans."""
    supabase = get_supabase()
    out: dict = {}
    try:
        plans = (
            supabase.table("monthly_task_plans")
            .select("client_id, month, spent, remaining, flags, plan, created_at")
            .order("created_at", desc=True).limit(60).execute()
        ).data or []
        # Latest plan per client only.
        latest: dict[str, dict] = {}
        for p in plans:
            latest.setdefault(p["client_id"], p)
        by_assignee: dict[str, dict] = {}
        for p in latest.values():
            for t in ((p.get("plan") or {}).get("tasks") or []):
                a = t.get("assignee") or "UNSTAFFED"
                slot = by_assignee.setdefault(a, {"tasks": 0, "cost": 0.0})
                slot["tasks"] += int(t.get("quantity") or 1)
                slot["cost"] += float(t.get("line_cost") or 0)
        out["open_plan_load_by_assignee"] = {
            k: {"tasks": v["tasks"], "cost": round(v["cost"], 2)} for k, v in by_assignee.items()
        }
        out["clients_with_plans"] = len(latest)
    except Exception as exc:
        out["plan_load_error"] = str(exc)
    roles = sop_library.read_sop("_ORCHESTRATOR", "Roles / Skills Matrix", max_chars=4000)
    return _clip(_dump(out) + "\n\nROLES MATRIX (_ORCHESTRATOR §6):\n" + roles)


async def _run_audit_page(client_id: str, args: dict) -> str:
    """PAID: one nlp-api /score-page run (8-engine on-page verdict)."""
    from services import local_seo_service

    url = (args.get("url") or "").strip()
    keyword = (args.get("keyword") or "").strip()
    if not (url and keyword):
        return "audit_page needs both url and keyword."
    location = (args.get("location") or "").strip()
    if not location:
        try:
            rows = (
                get_supabase().table("clients").select("gbp, target_cities")
                .eq("id", client_id).limit(1).execute()
            ).data or []
            c = rows[0] if rows else {}
            location = (
                ((c.get("gbp") or {}).get("address") or "")
                or ((c.get("target_cities") or [None])[0] or "")
            )
        except Exception:
            location = ""
    try:
        result = await local_seo_service.score_page(
            client_id, keyword, location, None, url, None, None
        )
    except Exception as exc:
        return f"audit_page failed: {exc}"
    compact = {
        "composite_score": result.get("composite_score"),
        "composite_status": result.get("composite_status"),
        "engine_scores": result.get("engine_scores"),
        "deficiencies": (result.get("deficiencies") or result.get("content_gaps") or [])[:12],
    }
    return _clip(_dump(compact))


# ─────────────────────────────────────────────────────────────────────────────
# LLM subagents
# ─────────────────────────────────────────────────────────────────────────────
async def _run_serp_deep_dive(client_id: str, args: dict) -> str:
    from services import rankability, serp_trends

    keyword = (args.get("keyword") or "").strip()
    if not keyword:
        return "serp_deep_dive needs a keyword."
    supabase = get_supabase()
    kw_id = _keyword_id(supabase, client_id, keyword)
    if not kw_id:
        return f"'{keyword}' is not a tracked keyword for this client."

    timeline = serp_trends.get_keyword_timeline(kw_id)
    if not timeline or not timeline.get("points"):
        return f"No SERP snapshots captured yet for '{keyword}' — nothing to deep-dive."

    snaps = (
        supabase.table("serp_snapshots")
        .select("id, captured_at, query_intent, intent_signals, aio_present, aio_sources, "
                "local_intent, client_rank, client_url, keyword_topic, client_topical_focus, "
                "generalist_count")
        .eq("keyword_id", kw_id).eq("status", "complete")
        .order("captured_at", desc=True).limit(1).execute()
    ).data or []
    top_results: list[dict] = []
    if snaps:
        top_results = (
            supabase.table("serp_snapshot_results")
            .select("position, domain, title, is_client, referring_domains, url_rating, topical_focus")
            .eq("snapshot_id", snaps[0]["id"]).order("position").limit(10).execute()
        ).data or []
    rb_item = None
    try:
        items = rankability.get_client_rankability(client_id).get("items", [])
        rb_item = next((i for i in items if (i.get("keyword") or "").lower() == keyword.lower()), None)
    except Exception:
        pass

    payload = {
        "keyword": keyword,
        "timeline_points": timeline["points"][-8:],
        "latest_snapshot": snaps[0] if snaps else None,
        "latest_top10": top_results,
        "rankability": {
            k: rb_item.get(k) for k in ("score", "band", "client_rank", "priority", "factors")
        } if rb_item else None,
    }
    system = (
        "You are a SERP analyst. From dated SERP snapshots + a change timeline, explain "
        "what this SERP rewards NOW versus earlier captures, and what changed. Facts to "
        "respect: per-result referring_domains are the tool's read of competitor pages "
        "(the agency scales competitor RD ×10 for true RD); aio_present means an AI "
        "Overview sits above the organic results; signals_added/removed track SERP "
        "features between captures; client_rank null means not in the captured depth. "
        "Be concrete and ≤300 words: 1) what the top of this SERP looks like now, "
        "2) what changed across captures, 3) what that implies the ranking levers are "
        "(intent match, RD, topical specialism, AIO presence). No invented numbers."
    )
    try:
        narrative = await _subagent(system, _dump(payload))
    except Exception as exc:
        return f"serp_deep_dive summarizer failed ({exc}); raw data:\n" + _clip(_dump(payload))
    return _clip(narrative)


async def _run_geogrid_history(client_id: str, args: dict) -> str:
    keyword = (args.get("keyword") or "").strip()
    if not keyword:
        return "geogrid_history needs a keyword."
    supabase = get_supabase()
    results = (
        supabase.table("maps_scan_results")
        .select("scan_id, average_rank, found_pins, total_pins, top3_pins, created_at")
        .eq("client_id", client_id).ilike("keyword", keyword)
        .order("created_at", desc=True).limit(8).execute()
    ).data or []
    if not results:
        return f"No geo-grid scans recorded for '{keyword}'."
    scan_ids = [r["scan_id"] for r in results if r.get("scan_id")]
    scan_meta: dict[str, dict] = {}
    if scan_ids:
        for s in (
            supabase.table("maps_scans").select("id, completed_at, trigger")
            .in_("id", scan_ids).execute()
        ).data or []:
            scan_meta[s["id"]] = s
    series = []
    for r in reversed(results):  # oldest → newest
        meta = scan_meta.get(r.get("scan_id"), {})
        total = r.get("total_pins") or 0
        series.append({
            "scanned_at": meta.get("completed_at") or r.get("created_at"),
            "average_rank_over_found_pins": r.get("average_rank"),
            "found_pins": r.get("found_pins"),
            "total_pins": total,
            "top3_pins": r.get("top3_pins"),
            "pack_presence_pct": round(100.0 * (r.get("top3_pins") or 0) / total, 1) if total else None,
        })
    alerts = (
        supabase.table("maps_alerts")
        .select("alert_type, sector, message, created_at, resolved_at")
        .eq("client_id", client_id).ilike("keyword", keyword)
        .order("created_at", desc=True).limit(6).execute()
    ).data or []

    payload = {"keyword": keyword, "scan_series_oldest_first": series, "recent_alerts": alerts}
    system = (
        "You are a local-pack (Google Maps geo-grid) analyst. Narrate the trend across "
        "these weekly grid scans. CRITICAL reading rules: average_rank is computed over "
        "FOUND pins only — always read it against found_pins/total_pins (3/25 pins at "
        "average 2.0 = barely present, not 'ranking #2'); pack_presence_pct (top-3 pins / "
        "total) is the honest coverage number — coverage first, average second; ±1 wobble "
        "on a few pins is noise, the alerts encode the real drops. Be concrete and ≤250 "
        "words: 1) trajectory of pack presence, 2) whether average-rank moves are real or "
        "coverage artifacts, 3) what the alerts say, 4) the one-line strategic read."
    )
    try:
        narrative = await _subagent(system, _dump(payload))
    except Exception as exc:
        return f"geogrid_history summarizer failed ({exc}); raw data:\n" + _clip(_dump(payload))
    return _clip(narrative)


# ─────────────────────────────────────────────────────────────────────────────
# Registry (name → spec). All read-only; `paid` marks tools that spend API
# budget beyond our own LLM tokens (capped tighter in the run loop).
# ─────────────────────────────────────────────────────────────────────────────
ToolRunner = Callable[[str, dict], Awaitable[str]]

TOOLS: dict[str, dict] = {
    "serp_deep_dive": {
        "description": (
            "LLM subagent: what this keyword's Google SERP rewards now vs earlier captures "
            "(dated snapshots + feature timeline + rankability). Use when a drop/opportunity "
            "needs a 'what changed on the SERP' answer. Trap notes: competitor referring-domain "
            "reads are tool reads (true RD ≈ ×10); a null client_rank means below captured depth, "
            "not necessarily deindexed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"keyword": {"type": "string", "description": "A tracked keyword (exact text)."}},
            "required": ["keyword"],
        },
        "paid": False,
        "run": _run_serp_deep_dive,
    },
    "geogrid_history": {
        "description": (
            "LLM subagent: trend narrative over the full Maps geo-grid scan series for one "
            "keyword (pack presence, found-pin coverage, alerts). Trap notes: average_rank is "
            "over FOUND pins only — check found_pins before comparing across scans; top3/total "
            "is the honest presence number."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"keyword": {"type": "string", "description": "The geo-grid keyword (exact text)."}},
            "required": ["keyword"],
        },
        "paid": False,
        "run": _run_geogrid_history,
    },
    "audit_page": {
        "description": (
            "PAID (counted against a tighter per-run cap): run the nlp-api 8-engine on-page "
            "audit for one URL against a keyword. Returns composite score (pass line 90, "
            "deficiency bar: engine < 80), per-engine scores, deficiencies. Only call when a "
            "proposal hinges on whether a specific page is on-page deficient."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "keyword": {"type": "string"},
                "location": {"type": "string", "description": "Optional 'City, ST' context; defaults to the client's own."},
            },
            "required": ["url", "keyword"],
        },
        "paid": True,
        "run": _run_audit_page,
    },
    "competitor_profile": {
        "description": (
            "Full assembled profile for ONE registered competitor across every module — "
            "local-pack pins, GBP rating/review count, DR/referring domains, organic top-10 "
            "keyword overlap, review velocity, recent new pages — plus the client's own "
            "comparison values. Deterministic read. Trap notes: competitor DR/RD are tool "
            "reads (true RD ≈ ×10 per the SOP shared definition); a null module means no "
            "capture yet, not competitor absence."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"competitor": {"type": "string", "description": "Competitor name (or domain) from the digest's competitors section."}},
            "required": ["competitor"],
        },
        "paid": False,
        "run": _run_competitor_profile,
    },
    "backlink_profile": {
        "description": (
            "The client's tracked backlink authority from the Backlink Explorer, beyond the "
            "digest summary: per tracked domain (own + tracked competitors) the latest DR / "
            "referring domains / total backlinks / linked-pages count; the own-domain link "
            "velocity with the ACTUAL gained/lost domain names since the previous weekly "
            "snapshot; and the top pages by referring domains (where the authority lives). "
            "Deterministic read of stored snapshots — free. Trap notes: DR/RD are tool reads "
            "(true RD ≈ ×10 per the SOP shared definition); velocity needs ≥2 tracked "
            "snapshots — a missing velocity block means the baseline was just captured, not "
            "zero movement."
        ),
        "input_schema": {"type": "object", "properties": {}},
        "paid": False,
        "run": _run_backlink_profile,
    },
    "episode_timeline": {
        "description": (
            "Full check history for a keyword's response episodes (the SOP verify loop: "
            "baseline at open, 2-week rechecks, 6-week escalation). Deterministic read."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"keyword": {"type": "string"}},
            "required": ["keyword"],
        },
        "paid": False,
        "run": _run_episode_timeline,
    },
    "read_sop": {
        "description": (
            "Fetch an SOP doc (or one section) beyond what the digest included. "
            "Docs: _ORCHESTRATOR, Link_Building_SOP, Link_Building_Recipe_Engine, "
            "Rank_Drop_Mitigation_SOP_Organic, Rank_Drop_Mitigation_SOP_Maps, "
            "How_To_Rank_In_Google_Maps_SOP, On_Page_Criteria_and_Coverage, AIO_AEO_SOP, "
            "Seed_Keyword_SOP, Site_Architecture_and_Internal_Linking_SOP."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "doc": {"type": "string"},
                "section": {"type": "string", "description": "Optional heading substring."},
            },
            "required": ["doc"],
        },
        "paid": False,
        "run": _run_read_sop,
    },
    "client_capacity": {
        "description": (
            "Team capacity + current plan load: the roles matrix (_ORCHESTRATOR §6) and the "
            "task/cost load per assignee summed across every client's latest monthly task plan. "
            "Use before proposing work that needs a specific person."
        ),
        "input_schema": {"type": "object", "properties": {}},
        "paid": False,
        "run": _run_client_capacity,
    },
}


def anthropic_tool_defs() -> list[dict]:
    """The registry rendered as Anthropic tool definitions."""
    return [
        {"name": name, "description": spec["description"], "input_schema": spec["input_schema"]}
        for name, spec in TOOLS.items()
    ]
