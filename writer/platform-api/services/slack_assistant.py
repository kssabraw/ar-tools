"""Slack conversational assistant — "SerMastr".

Two-way Slack, **channel mode**: SerMastr lives in a dedicated channel, so Slack
POSTs a `message` event to `/slack/events` for *every* message there (no @mention
needed). We answer each plain human message — resolve which client it's about,
assemble a cross-module context (rank tracker, Maps geo-grid, AI visibility,
content, keyword research, setup), fold in the thread's prior turns for
continuity, ask Claude, and post the answer back **in-thread**. The bot's own
posts (rank-drop alerts etc.) and other bots are ignored, so it never loops.

Q&A plus an action registry (_ACTIONS): the assistant has admin-level write
access — it can trigger work (scans, research, a strategist review, client
reports, an Asana task-plan push), manage the client's Asana board, edit the
client profile (Setup-page scalars + target cities), and manage campaign state
(tracked keywords, AI-visibility keywords/competitors, campaign goals). Every
paid or side-effecting action is staged behind an explicit reply-*yes* confirm
that names the exact change. Anyone in the workspace can ask (per the product
decision); inbound requests are verified by Slack's request signature so the
public endpoint can't be spoofed.

Split: pure helpers (signature verify, mention stripping, client resolution,
history formatting) are import-light and unit-tested; the context build + thread
fetch + Claude call + Slack post do I/O.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
from datetime import date
from typing import Optional

import httpx

from config import settings
from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

_SLACK_POST_URL = "https://slack.com/api/chat.postMessage"
_SLACK_REPLIES_URL = "https://slack.com/api/conversations.replies"
_TIMEOUT = 20.0
_LLM_TIMEOUT = 60.0  # bound the Claude call so a hung request can't pin the task
_THREAD_HISTORY_LIMIT = 12  # prior thread messages folded into context for continuity
_MENTION_RE = re.compile(r"<@[A-Z0-9]+>")
_SIG_MAX_SKEW_SECONDS = 60 * 5  # reject events older than 5 min (replay guard)

_SYSTEM = (
    "You are SerMastr, an in-house SEO strategist for an agency, answering a "
    "teammate in Slack. You are given a JSON object describing ONE client across "
    "the agency's SEO modules, keyed by module:\n"
    "- campaign_goals: the client's success targets (rank, traffic, AI-visibility, "
    "local-pack goals) with a deterministic status each — achieved/on_track/behind/"
    "overdue.\n"
    "- competitors: named competitors profiled across every module — local-pack pins, "
    "GBP rating/reviews, DR/referring domains (tool reads — true RD ≈ ×10), organic "
    "top-10 keyword overlap, review velocity, and new pages they published in the last "
    "30 days. A null module inside a competitor = no capture yet.\n"
    "- forecast: deterministic projections — portfolio clicks/value now vs 90 days at "
    "the current trend, the GSC clicks trajectory, the quick-win scenario (what moving "
    "striking-distance keywords to top 3 is worth), and per-goal trajectory reads. "
    "CITE these numbers verbatim; never compute your own projections. Always carry the "
    "caveat that projections are linear trend extrapolations, and prefer 'gsc'-sourced "
    "click numbers (actuals) over 'ctr_model' ones (estimates) when both exist.\n"
    "- trends: cross-client algorithm-update detections (several of the agency's "
    "clients opened rank drops in the same window = a Google update, not this client's "
    "emergency — factor this into any drop explanation) + the client's seasonal demand "
    "outlook from 12-month volume history (falling seasonal demand explains falling "
    "impressions without a ranking problem).\n"
    "- organic_rank: tracked keywords with current rank + trend, open ranking-drop "
    "alerts, the latest reoptimization Action Plan, and Search Console opportunities.\n"
    "- maps_geogrid: local-pack / Google Maps geo-grid scan results (average rank, "
    "top-3/top-10 pin counts, weak coverage areas).\n"
    "- ai_visibility: whether the brand appears in AI-assistant answers across "
    "engines (per-engine visibility, invisible keywords).\n"
    "- content: what content has been produced (blog posts, service/location pages, "
    "Local SEO pages).\n"
    "- keyword_research: Topic Fanout research sessions.\n"
    "- setup: the client's configured context (GBP, brand voice, ICP, target cities).\n"
    "A module is OMITTED when there's no data for it — if a module key is absent, "
    "that work simply hasn't been set up or run for this client; say so rather than "
    "guessing. Answer using ONLY this data. Be concise and direct — a few sentences "
    "or a short list, Slack-friendly (you may use *bold* and bullets). Lead with the "
    "answer. As a strategist, you may connect signals across modules when relevant "
    "(e.g. a ranking drop + a content gap). Never invent numbers or modules.\n\n"
    "You can also TAKE ACTIONS via the provided tools — you have admin-level write "
    "access to the client's campaign, so NEVER claim you can't make a change that a "
    "tool covers. Your action groups:\n"
    "- Run work: rebuild the Action Plan, run a Maps geo-grid scan, GSC Research, an "
    "AI Visibility scan, or a strategist review; generate a client report "
    "(generate_client_report — optionally delivered to the client per their report "
    "settings); push the latest monthly task plan to Asana.\n"
    "- Asana board: add_asana_task (extract the task name, assignee and any detail "
    "from the message), remove_asana_task / complete_asana_task (pass the task name "
    "the teammate used).\n"
    "- Client profile (the Setup page): update_client_profile (website URL, GSC "
    "property, business location, monthly retainer, client type, SAB flag) and "
    "add_target_cities / remove_target_cities for the Local SEO target-city list.\n"
    "- Campaign management: add_tracked_keywords / remove_tracked_keyword (organic "
    "rank tracker), add_ai_keywords / remove_ai_keyword and add_ai_competitor / "
    "remove_ai_competitor (AI Visibility), add_campaign_goal / remove_campaign_goal "
    "(Campaign Goals).\n"
    "If the teammate is clearly asking you to run/start/trigger/rebuild/create/"
    "change/assign/delete/finish one of these for the client, call the matching tool "
    "instead of answering — every change is confirmed with them before it's applied, "
    "so prefer calling the tool over asking permission in prose. Only things with no "
    "tool (creating or archiving clients, freezing/unfreezing, WordPress/Drive "
    "credentials, brand-voice or ICP text, reference page structures, GBP connection) "
    "are dashboard-only — say so and name the page. If they're only asking about "
    "results or anything else, answer normally — do NOT call a tool for a question.\n\n"
    "STRATEGIST BEHAVIOURS:\n"
    "- 'How is the campaign going?' → a short cross-module health read: when "
    "campaign_goals exist, LEAD with progress against them (their status field — "
    "achieved/on_track/behind/overdue — is computed deterministically; report it, "
    "never re-derive it), then the 2-3 biggest wins and the 2-3 biggest concerns, "
    "each with its number (rank moves, pack presence, AI visibility, open alerts). "
    "Note any module with no data as not-yet-set-up rather than silently skipping "
    "it. No goals set → say so and suggest adding them on the Campaign Goals page.\n"
    "- 'What should we improve/tweak?' → concrete, prioritized recommendations "
    "grounded ONLY in the data (e.g. striking-distance keywords to reoptimize, weak "
    "geo-grid areas needing location pages, invisible AI keywords, open drop alerts "
    "to diagnose, unstaffed plan lines). Name the tool/page that does each. Offer to "
    "run a full strategist review for a deeper pass — don't trigger it unasked.\n\n"
    "HOW TO READ THE INSTRUMENTS (module-card rules — never misread these):\n"
    "- Rank tracker: position is lower=better. A null GSC position means NO DATA that "
    "day (no impressions / not connected), never 'dropped out'; read positions with "
    "their impressions; don't splice GSC and DataForSEO reads into one trend.\n"
    "- Maps geo-grid: average_rank is computed over FOUND pins only — always read it "
    "with found/total pin coverage (3/25 pins at average 2.0 = barely present, not "
    "'ranking #2'); top-3 pins / total pins is the honest pack-presence number.\n"
    "- GBP levers: local-pack rank is relevance (categories, business name) + "
    "distance + prominence (reviews, links). The GBP business DESCRIPTION is NOT a "
    "local-pack ranking factor — never present it as one. A complete description / "
    "profile matters for AI VISIBILITY instead (per the agency's AIO/AEO SOP, AIO and "
    "AI-Mode lean heavily on GBP) — attribute description advice there.\n"
    "- AI visibility: single results are noisy by design — one engine flipping on one "
    "keyword is NOT a trend; read batch rollups and cross-batch trends; engines are "
    "not interchangeable (AIO/AI-Mode lean on GBP + top organic, ChatGPT leans Bing)."
)

# Appended to the system prompt when the assistant speaks through the dashboard
# chatbox (routers/assistant.py) instead of Slack — same brain, different room.
_WEB_STYLE = (
    "\n\nSURFACE: you are answering in the AR Tools dashboard chat (a web app), NOT "
    "Slack. Format with standard Markdown — **bold**, `-` bullets — and never mention "
    "Slack, threads, or channels. When you name a tool/page (Action Plan, Campaign "
    "Goals, Maps geo-grid, …) the teammate can open it from the client's workspace."
)


# ---------------------------------------------------------------------------
# Pure helpers (no I/O) — unit-tested.
# ---------------------------------------------------------------------------
def verify_slack_signature(
    signing_secret: str, timestamp: str, raw_body: str, signature: str, now_ts: int
) -> bool:
    """True iff the Slack request signature is valid and recent. Pure.

    Slack signs `v0:{timestamp}:{body}` with HMAC-SHA256 over the signing secret.
    Fail-closed: a missing secret/signature/timestamp, a stale timestamp (replay),
    or any parse error returns False.
    """
    if not (signing_secret and timestamp and signature):
        return False
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs(now_ts - ts) > _SIG_MAX_SKEW_SECONDS:
        return False
    basestring = f"v0:{timestamp}:{raw_body}".encode()
    expected = "v0=" + hmac.new(signing_secret.encode(), basestring, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def strip_mention(text: str) -> str:
    """Remove Slack user mentions (`<@U123>`) and collapse whitespace. Pure."""
    return _MENTION_RE.sub("", text or "").strip()


def resolve_client(message: str, clients: list[dict]) -> Optional[dict]:
    """Pick the client a message is about by matching client names. Pure.

    Prefers the longest client name that appears as a whole-word substring of the
    message (so "Acme Plumbing" wins over "Acme" when both exist). Falls back to a
    token-overlap match (any distinctive name word present). Returns None when
    nothing matches — the caller then asks the user to name the client.
    """
    msg = (message or "").lower()
    if not msg:
        return None
    # 1) Whole-name substring, longest name first.
    named = sorted(
        (c for c in clients if (c.get("name") or "").strip()),
        key=lambda c: len(c["name"]),
        reverse=True,
    )
    for c in named:
        name = c["name"].lower()
        if re.search(rf"\b{re.escape(name)}\b", msg):
            return c
    # 2) Distinctive-token overlap (ignore generic words).
    stop = {"the", "and", "of", "for", "co", "inc", "llc", "ltd", "group", "services", "service"}
    best, best_hits = None, 0
    for c in named:
        tokens = {t for t in re.split(r"\W+", c["name"].lower()) if len(t) > 2 and t not in stop}
        hits = sum(1 for t in tokens if re.search(rf"\b{re.escape(t)}\b", msg))
        if hits > best_hits:
            best, best_hits = c, hits
    return best if best_hits else None


def format_context(client: dict, context: dict) -> str:
    """Compact JSON-ish context block for the LLM prompt. Pure."""
    payload = {
        "client": {"name": client.get("name"), "website": client.get("website_url")},
        **context,
    }
    return json.dumps(payload, default=str, ensure_ascii=False)


def weak_cities(report_weak_locations) -> list[str]:
    """City names from a Maps result's `report_weak_locations`. Pure, shape-tolerant.

    The stored value is the geocoder's object — `{geocoded, capped, weak_areas:[...]}`
    — but tolerate a bare list of area dicts or None/other too (so a shape change
    never throws and drops the whole module)."""
    rwl = report_weak_locations
    if isinstance(rwl, dict):
        areas = rwl.get("weak_areas") or []
    elif isinstance(rwl, list):
        areas = rwl
    else:
        areas = []
    out: list[str] = []
    for area in areas[:5]:
        city = area.get("city") if isinstance(area, dict) else None
        if city:
            out.append(city)
    return out


def format_history(history: list[dict]) -> str:
    """Render prior thread turns as a plain transcript for the prompt. Pure.

    Folded into the user message (not structured messages) so multi-person threads
    with no strict user/assistant alternation don't violate the LLM's role rules.
    Each item is {"role": "assistant"|"user", "content": str}.
    """
    lines = []
    for h in history:
        who = "SerMastr" if h.get("role") == "assistant" else "Teammate"
        text = (h.get("content") or "").strip()
        if text:
            lines.append(f"{who}: {text}")
    return "\n".join(lines)


def is_affirmative(text: str) -> bool:
    """Whether a reply confirms a pending action (a 'yes'). Pure."""
    t = (text or "").strip().lower().rstrip("!.")
    return t in {
        "yes", "y", "yep", "yeah", "yup", "confirm", "confirmed", "do it",
        "go", "go ahead", "proceed", "ok", "okay", "sure", "please do",
    } or t.startswith(("yes ", "yes,", "go ahead", "do it"))


# ---------------------------------------------------------------------------
# Context assembly (DB reads).
# ---------------------------------------------------------------------------
def build_context(client_id: str, today: Optional[date] = None) -> dict:
    """Assemble a per-client, cross-module context for the assistant.

    Runs every registered module provider (see `_CONTEXT_PROVIDERS`), each isolated
    so one module's failure or empty result never breaks the answer. A provider
    returning a falsy value is omitted entirely, so the LLM can tell "no data for
    this module" from real data.

    **To give SerMastr a new module:** write a `_ctx_<module>(supabase, client_id,
    today)` provider returning a compact dict (or None), and append it to
    `_CONTEXT_PROVIDERS`. It flows into every answer automatically — no other change.
    """
    supabase = get_supabase()
    today = today or date.today()
    ctx: dict = {}
    for key, provider in _CONTEXT_PROVIDERS:
        try:
            section = provider(supabase, client_id, today)
            if section:
                ctx[key] = section
        except Exception as exc:
            logger.warning(
                "slack_ctx_provider_failed",
                extra={"client_id": client_id, "ctx_module": key, "error": str(exc)},
            )
    return ctx


# --- Module context providers (each: (supabase, client_id, today) -> dict|None) ---
def _ctx_organic_rank(supabase, client_id: str, today: date) -> Optional[dict]:
    """Organic rank tracker: keywords + rank/trend, open drops, Action Plan, GSC."""
    from services import rank_status

    out: dict = {}
    kws = (
        supabase.table("tracked_keywords")
        .select("id, keyword, status")
        .eq("client_id", client_id)
        .eq("active", True)
        .order("keyword")
        .limit(settings.slack_assistant_max_keywords)
        .execute()
    ).data or []
    if kws:
        kw_ids = [k["id"] for k in kws]
        metrics: dict[str, list[dict]] = {}
        cutoff = date.fromordinal(today.toordinal() - 90).isoformat()
        for r in (
            supabase.table("rank_keyword_metrics")
            .select("keyword_id, date, gsc_position, tracked_rank")
            .in_("keyword_id", kw_ids)
            .gte("date", cutoff)
            .execute()
        ).data or []:
            metrics.setdefault(r["keyword_id"], []).append(r)
        out["keywords"] = [
            {
                "keyword": k["keyword"],
                "status": k.get("status"),
                "current_rank": (s := rank_status.compute_keyword_summary(
                    metrics.get(k["id"], []), today, settings.rank_gsc_coverage_days
                )).get("today_rank"),
                "avg_30d": s.get("avg_30"),
                "direction": s.get("direction"),
            }
            for k in kws
        ]
        out["keyword_count"] = len(kws)

    alerts = (
        supabase.table("rank_alerts")
        .select("keyword, alert_type, message")
        .eq("client_id", client_id)
        .is_("resolved_at", "null")
        .execute()
    ).data or []
    if alerts:
        out["open_drop_alerts"] = alerts

    plan = (
        supabase.table("reopt_plans")
        .select("summary, items, action_count, created_at")
        .eq("client_id", client_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    ).data
    if plan:
        p = plan[0]
        out["action_plan"] = {
            "summary": p.get("summary"),
            "action_count": p.get("action_count"),
            "top_actions": [
                {"keyword": a.get("keyword"), "recommendation": a.get("recommendation")}
                for a in (p.get("items") or [])[:8]
            ],
        }

    gsc = (
        supabase.table("gsc_research_runs")
        .select("cannibalization, hidden_wins, quick_wins, created_at")
        .eq("client_id", client_id)
        .eq("status", "complete")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    ).data
    if gsc:
        g = gsc[0]
        out["gsc_opportunities"] = {
            "cannibalization": len(g.get("cannibalization") or []),
            "quick_wins": len(g.get("quick_wins") or []),
            "hidden_wins": len(g.get("hidden_wins") or []),
        }
    return out or None


def _ctx_maps(supabase, client_id: str, today: date) -> Optional[dict]:
    """Maps geo-grid: latest scan status + per-keyword average rank / pin coverage."""
    scan = (
        supabase.table("maps_scans")
        .select("id, status, created_at")
        .eq("client_id", client_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    ).data
    if not scan:
        return None
    s = scan[0]
    out: dict = {"latest_scan_status": s.get("status"), "latest_scan_at": s.get("created_at")}
    results = (
        supabase.table("maps_scan_results")
        .select("keyword, average_rank, top3_pins, top10_pins, report_weak_locations")
        .eq("scan_id", s["id"])
        .limit(15)
        .execute()
    ).data or []
    if results:
        out["keywords"] = [
            {
                "keyword": r.get("keyword"),
                "average_rank": r.get("average_rank"),
                "top3_pins": r.get("top3_pins"),
                "top10_pins": r.get("top10_pins"),
            }
            for r in results
        ]
        weak: list[str] = []
        for r in results:
            for city in weak_cities(r.get("report_weak_locations")):
                if city not in weak:
                    weak.append(city)
        if weak:
            out["weak_coverage_areas"] = weak[:10]
    return out


def _ctx_ai_visibility(supabase, client_id: str, today: date) -> Optional[dict]:
    """AI Visibility: tracked-keyword count + latest scan's per-engine visibility."""
    kw_count = (
        supabase.table("brand_tracked_keywords")
        .select("id", count="exact")
        .eq("client_id", client_id)
        .eq("is_active", True)
        .execute()
    ).count or 0
    # Pin the latest batch id first, then fetch that whole batch — a batch is
    # (keywords × engines) rows, so a single capped query could truncate it and
    # undercount visibility for clients with many tracked keywords.
    newest = (
        supabase.table("brand_mention_history")
        .select("scan_batch_id, created_at")
        .eq("client_id", client_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    ).data
    if not (kw_count or newest):
        return None
    out: dict = {"keywords_tracked": kw_count}
    if newest:
        latest_batch = newest[0]["scan_batch_id"]
        batch = (
            supabase.table("brand_mention_history")
            .select("keyword_id, engine, mention_found")
            .eq("client_id", client_id)
            .eq("scan_batch_id", latest_batch)
            .execute()
        ).data or []
        out["latest_scan_at"] = newest[0].get("created_at")
        per_engine: dict[str, dict] = {}
        for r in batch:
            e = per_engine.setdefault(r.get("engine") or "?", {"found": 0, "total": 0})
            e["total"] += 1
            if r.get("mention_found"):
                e["found"] += 1
        out["per_engine_visibility"] = {k: f"{v['found']}/{v['total']}" for k, v in per_engine.items()}
        seen, visible = set(), set()
        for r in batch:
            seen.add(r.get("keyword_id"))
            if r.get("mention_found"):
                visible.add(r.get("keyword_id"))
        out["invisible_keyword_count"] = len(seen - visible)
    return out


def _ctx_content(supabase, client_id: str, today: date) -> Optional[dict]:
    """Content produced: completed blog/service/location runs + Local SEO pages.

    Uses head-only `count="exact"` queries (no row transfer) — these counts can
    grow large for an active client and we only need the totals.
    """
    out: dict = {}
    by_type: dict[str, int] = {}
    for t in ("blog_post", "service_page", "location_page"):
        n = (
            supabase.table("runs")
            .select("id", count="exact", head=True)
            .eq("client_id", client_id)
            .eq("status", "complete")
            .eq("content_type", t)
            .execute()
        ).count or 0
        if n:
            by_type[t] = n
    if by_type:
        out["completed_runs_by_type"] = by_type

    saved = (
        supabase.table("local_seo_pages")
        .select("id", count="exact", head=True)
        .eq("client_id", client_id)
        .is_("deleted_at", "null")
        .execute()
    ).count or 0
    if saved:
        published = (
            supabase.table("local_seo_pages")
            .select("id", count="exact", head=True)
            .eq("client_id", client_id)
            .is_("deleted_at", "null")
            .not_.is_("published_doc_id", "null")
            .execute()
        ).count or 0
        out["local_seo_pages_saved"] = saved
        out["local_seo_pages_published"] = published
    return out or None


def _ctx_keyword_research(supabase, client_id: str, today: date) -> Optional[dict]:
    """Topic Fanout keyword-research sessions (vendored fanout schema)."""
    from fanout.storage.supabase_client import get_service_client

    rows = (
        get_service_client()
        .table("sessions")
        .select("seed_keyword, status, created_at")
        .eq("client_id", client_id)
        .eq("archived", False)
        .order("created_at", desc=True)
        .limit(10)
        .execute()
    ).data or []
    if not rows:
        return None
    return {
        "session_count": len(rows),
        "recent_seeds": [r.get("seed_keyword") for r in rows[:5] if r.get("seed_keyword")],
    }


def _ctx_setup(supabase, client_id: str, today: date) -> Optional[dict]:
    """Client setup context the strategist should be aware of."""
    rows = (
        supabase.table("clients")
        .select("website_url, gbp, brand_voice, detected_icp, differentiators, target_cities")
        .eq("id", client_id)
        .limit(1)
        .execute()
    ).data
    if not rows:
        return None
    c = rows[0]
    gbp = c.get("gbp") or {}
    return {
        "website": c.get("website_url"),
        "has_gbp": bool(gbp.get("business_name") or gbp.get("place_id")),
        "gbp_name": gbp.get("business_name"),
        "has_brand_voice": bool(c.get("brand_voice")),
        "has_icp": bool(c.get("detected_icp") or c.get("differentiators")),
        "target_city_count": len(c.get("target_cities") or []),
    }


def _ctx_campaign_goals(supabase, client_id: str, today: date) -> Optional[dict]:
    """The client's success targets with deterministic status — lets 'how is
    the campaign going' lead with progress vs what was promised."""
    from services import campaign_goals

    assessed = campaign_goals.assess_goals(client_id, today=today)
    if not assessed:
        return None
    return {
        "goals": [
            {
                "label": g.get("label"),
                "status": g.get("status"),
                "current_value": g.get("current_value"),
                "target_value": g.get("target_value"),
                "progress_pct": g.get("progress_pct"),
                "due_date": g.get("due_date"),
                "note": g.get("note"),
            }
            for g in assessed
        ],
    }


def _ctx_competitors(supabase, client_id: str, today: date) -> Optional[dict]:
    """Assembled competitor profiles so competitive questions get real data."""
    from services import competitor_intel

    assembled = competitor_intel.build_profiles(client_id, today=today)
    profiles = assembled.get("competitors") or []
    if not profiles:
        return None
    return {
        "client_comparison": assembled.get("client"),
        "competitors": [
            {
                "name": p.get("name"),
                "domain": p.get("domain"),
                "local_pack": p.get("local_pack"),
                "gbp": p.get("gbp"),
                "backlinks": p.get("backlinks"),
                "organic": p.get("organic"),
                "review_velocity_30d": p.get("review_velocity_30d"),
                "new_pages_30d": p.get("new_pages_30d"),
            }
            for p in profiles[:6]
        ],
    }


def _ctx_forecast(supabase, client_id: str, today: date) -> Optional[dict]:
    """Deterministic projections so 'where is this heading / what's it worth'
    questions get computed numbers, never invented ones."""
    from services import forecasting

    fc = forecasting.build_forecast(client_id, today=today)
    if not fc.get("keyword_count"):
        return None
    return {
        "note": fc.get("note"),
        "portfolio": fc.get("portfolio"),
        "gsc_clicks_trajectory": fc.get("gsc_clicks_trajectory"),
        "quick_wins_summary": {
            k: v for k, v in (fc.get("quick_wins") or {}).items() if k != "keywords"
        },
        "quick_wins_top": (fc.get("quick_wins") or {}).get("keywords", [])[:6],
        "goal_projections": fc.get("goal_projections"),
    }


def _ctx_trends(supabase, client_id: str, today: date) -> Optional[dict]:
    """Cross-client algo-update events + this client's seasonal demand read."""
    from services import trend_watch

    events = trend_watch.recent_algo_events()
    outlook = None
    try:
        outlook = trend_watch.build_demand_outlook(client_id, today=today)
    except Exception:
        pass
    if not events and not outlook:
        return None
    return {
        "algo_events": [
            {
                "window_start": e.get("window_start"),
                "window_end": e.get("window_end"),
                "clients_affected": e.get("clients_affected"),
                "clients_total": e.get("clients_total"),
            }
            for e in events[:3]
        ],
        "demand_outlook": outlook,
    }


# Registry — append a provider here to give SerMastr a new module (see build_context).
_CONTEXT_PROVIDERS = [
    ("campaign_goals", _ctx_campaign_goals),
    ("competitors", _ctx_competitors),
    ("forecast", _ctx_forecast),
    ("trends", _ctx_trends),
    ("organic_rank", _ctx_organic_rank),
    ("maps_geogrid", _ctx_maps),
    ("ai_visibility", _ctx_ai_visibility),
    ("content", _ctx_content),
    ("keyword_research", _ctx_keyword_research),
    ("setup", _ctx_setup),
]


# ---------------------------------------------------------------------------
# Actions — SerMastr can trigger work (not just report). Anyone in the channel
# may trigger (product decision); paid/side-effecting actions are gated behind
# an explicit confirmation. Runners take (client_id, args) and return a reply
# string; they may be sync or async.
# ---------------------------------------------------------------------------
def match_named(items: list[dict], query: str, key: str = "name") -> list[dict]:
    """Items whose `key` matches the query. Pure.

    Case-insensitive; an exact match wins outright (so "citations" can't be
    ambiguous with "citations — batch 2" when the user names one exactly),
    else substring matches."""
    q = (query or "").strip().casefold()
    if not q:
        return []
    exact = [i for i in items if (i.get(key) or "").strip().casefold() == q]
    if exact:
        return exact
    return [i for i in items if q in (i.get(key) or "").casefold()]


def match_open_tasks(tasks: list[dict], query: str) -> list[dict]:
    """Open tasks whose name matches the query. Pure.

    Completed tasks are never candidates; matching per `match_named`."""
    return match_named([t for t in tasks if not t.get("completed")], query)


def merge_cities(existing, additions) -> tuple[list[str], list[str], list[str]]:
    """Append cities to a target-city list, case-insensitively deduped. Pure.

    Returns (merged, added, already_present) — `already_present` in the
    teammate's casing so the reply can name what was skipped."""
    merged = [str(c).strip() for c in (existing or []) if str(c).strip()]
    was_existing = {c.casefold() for c in merged}
    have = set(was_existing)
    added, already = [], []
    for c in additions or []:
        name = str(c).strip()
        if not name:
            continue
        key = name.casefold()
        if key in have:
            if key in was_existing:  # intra-request dupes skip silently
                already.append(name)
            continue
        have.add(key)
        merged.append(name)
        added.append(name)
    return merged, added, already


def drop_cities(existing, removals) -> tuple[list[str], list[str], list[str]]:
    """Remove cities from a target-city list, case-insensitively. Pure.

    Returns (remaining, removed, missing) — `removed` in the STORED casing
    (what actually leaves the list), `missing` in the teammate's casing."""
    current = [str(c).strip() for c in (existing or []) if str(c).strip()]
    wanted = {str(c).strip().casefold() for c in (removals or []) if str(c).strip()}
    remaining = [c for c in current if c.casefold() not in wanted]
    removed = [c for c in current if c.casefold() in wanted]
    hit = {c.casefold() for c in removed}
    missing = [str(c).strip() for c in (removals or []) if str(c).strip() and str(c).strip().casefold() not in hit]
    return remaining, removed, missing


# Client-profile fields SerMastr may edit (the Setup page's simple scalars).
# Deliberately excluded: name (used for chat client-resolution + dup-checked),
# brand guide / ICP text (long-form authored assets), GBP + page structures
# (complex objects with their own capture flows), WP/Drive credentials.
_PROFILE_FIELDS = {
    "website_url": "the website URL",
    "gsc_property": "the Search Console property",
    "business_location": "the business location",
    "retainer_monthly": "the monthly retainer",
    "client_type": "the client type",
    "is_sab": "the service-area-business (SAB) flag",
}


def coerce_profile_value(field: str, value) -> tuple[object, Optional[str]]:
    """Validate + coerce a profile edit's value. Pure. Returns (coerced, error).

    Mirrors the clients API's typing: retainer → float, client_type →
    local|enterprise, is_sab → bool, website_url → scheme-prefixed."""
    if field not in _PROFILE_FIELDS:
        editable = ", ".join(_PROFILE_FIELDS)
        return None, f"I can't edit “{field}” — I can change: {editable}."
    raw = ("" if value is None else str(value)).strip()
    if not raw:
        return None, f"What should {_PROFILE_FIELDS[field]} be set to?"
    if field == "retainer_monthly":
        try:
            return float(raw.replace("$", "").replace(",", "")), None
        except ValueError:
            return None, f"“{raw}” isn't a number — give me the monthly retainer in dollars."
    if field == "client_type":
        v = raw.lower()
        if v not in ("local", "enterprise"):
            return None, "Client type must be *local* or *enterprise*."
        return v, None
    if field == "is_sab":
        v = raw.lower()
        if v in ("true", "yes", "y", "1", "on", "sab"):
            return True, None
        if v in ("false", "no", "n", "0", "off"):
            return False, None
        return None, "Should the SAB flag be *yes* or *no*?"
    if field == "website_url":
        return (raw if raw.startswith(("http://", "https://")) else f"https://{raw}"), None
    return raw, None


def _act_rebuild_plan(client_id: str, args: Optional[dict] = None) -> str:
    from services import reopt_planner

    res = reopt_planner.build_plan(client_id, trigger="manual")
    return f"✅ Rebuilt the Action Plan — {res.get('summary')}."


def _act_maps_scan(client_id: str, args: Optional[dict] = None) -> str:
    from services import local_dominator

    started = local_dominator.enqueue_maps_scan(client_id, trigger="manual")
    return (
        "✅ Started a Maps geo-grid scan — results land in a few minutes."
        if started
        else "A Maps scan is already running for this client."
    )


def _act_gsc_research(client_id: str, args: Optional[dict] = None) -> str:
    from services import gsc_research

    job_id = gsc_research.enqueue_gsc_research(client_id, trigger="manual")
    return (
        "✅ Started a GSC Research analysis."
        if job_id
        else "A GSC Research run is already in progress for this client."
    )


def _act_strategy_review(client_id: str, args: Optional[dict] = None) -> str:
    from services import strategist

    if not settings.strategist_enabled:
        return (
            "The strategist is currently disabled (`strategist_enabled` is off) — "
            "it activates once the smoke gate is passed."
        )
    review_id = strategist.enqueue_strategy_review(client_id, trigger="on_demand", notify=True)
    return (
        "🧠 Strategist review started — the digest will post to the alerts channel "
        "when it's done; the full review (with Approve/Dismiss) lands on the client's "
        "Action Plan page."
        if review_id
        else "A strategist review is already running for this client."
    )


def _act_ai_scan(client_id: str, args: Optional[dict] = None) -> str:
    from fastapi import HTTPException

    from services import brand_service

    try:
        brand_service.start_scan(client_id, None, None, False, None)
        return "✅ Started an AI Visibility scan across the engines."
    except HTTPException as exc:
        if exc.detail == "no_keywords_to_scan":
            return "No AI-visibility keywords are set up for this client yet — add some first."
        raise


def _act_push_task_plan(client_id: str, args: Optional[dict] = None) -> str:
    from services import asana_monthly, asana_push, asana_service

    if not asana_service.is_configured():
        return "Asana isn't connected yet (ASANA_TOKEN + workspace) — set that up on the platform first."
    if not asana_monthly.get_project_gid(client_id):
        return "This client has no Asana project mapped yet — set it on their Asana Tasks page first."
    rows = (
        get_supabase()
        .table("monthly_task_plans")
        .select("id, month, plan")
        .eq("client_id", client_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    ).data
    if not rows:
        return "No monthly task plan exists for this client yet — generate one on the Task Plan page first."
    plan_row = rows[0]
    if not ((plan_row.get("plan") or {}).get("tasks")):
        return "The latest task plan has no task lines to push (empty or frozen plan)."
    asana_push.enqueue_asana_push(client_id, str(plan_row["id"]))
    return (
        f"✅ Pushing the latest task plan ({plan_row.get('month') or 'current month'}) to Asana — "
        "tasks land on the board in a moment. Already-pushed lines are skipped."
    )


def _asana_ready(client_id: str) -> tuple[Optional[str], Optional[str]]:
    """(project_gid, None) when the client's Asana board is usable, else
    (None, guidance string)."""
    from services import asana_monthly, asana_service

    if not asana_service.is_configured():
        return None, "Asana isn't connected yet (ASANA_TOKEN + workspace) — set that up on the platform first."
    project_gid = asana_monthly.get_project_gid(client_id)
    if not project_gid:
        return None, "This client has no Asana project mapped yet — set it on their Asana Tasks page first."
    return project_gid, None


async def _stage_add_task(client_id: str, args: dict) -> tuple[str, dict | str]:
    """Resolve the assignee and build the exact confirm text for add_asana_task."""
    from services.asana_push import match_member_gid

    name = (args.get("task_name") or "").strip()
    if not name:
        return "reply", "What should the task be called?"
    _, problem = _asana_ready(client_id)
    if problem:
        return "reply", problem

    assignee_note = "unassigned"
    assignee_gid = None
    wanted = (args.get("assignee") or "").strip()
    if wanted:
        members = (
            get_supabase().table("asana_team_members").select("gid, name")
            .eq("active", True).execute()
        ).data or []
        assignee_gid = match_member_gid(wanted, members)
        if assignee_gid:
            full = next((m.get("name") for m in members if m["gid"] == assignee_gid), wanted)
            assignee_note = f"assigned to *{full}*"
        else:
            assignee_note = (
                f"unassigned — I couldn't match “{wanted}” to a tracked team member "
                "(check the Workload page)"
            )
    staged = {**args, "task_name": name, "assignee_gid": assignee_gid}
    staged["_confirm"] = f"create the Asana task *“{name}”* ({assignee_note})"
    return "confirm", staged


async def _act_add_task(client_id: str, args: Optional[dict] = None) -> str:
    from services import asana_push, asana_service

    args = args or {}
    project_gid, problem = _asana_ready(client_id)
    if problem:
        return problem
    section_gid = await asana_push._ensure_month_section(project_gid, date.today())
    fields = await asana_service.resolve_project_fields(project_gid)
    payload = asana_service.build_task_payload(
        (args.get("task_name") or "Task")[:250],
        project_gid,
        section_gid or "",
        assignee_gid=args.get("assignee_gid"),
        status_field_gid=fields.get("status_field_gid") or "",
        not_started_option_gid=fields.get("not_started_option_gid") or "",
    )
    if not section_gid:  # section create failed → land in the project top-level
        payload.pop("memberships", None)
    notes = ["AR Tools · created via SerMastr"]
    if args.get("notes"):
        notes.append(str(args["notes"]))
    payload["notes"] = "\n".join(notes)
    result = await asana_service.create_task(payload)
    gid = (result or {}).get("gid")
    if not gid:
        return "Asana didn't return the new task — check the board."
    who = "" if args.get("assignee_gid") else " (unassigned)"
    return f"✅ Created *“{payload['name']}”*{who} — {asana_push.task_url(gid)}"


async def _stage_pick_task(client_id: str, args: dict, verb: str) -> tuple[str, dict | str]:
    """Shared resolver for remove/complete: find exactly one open task by name.

    Resolution happens BEFORE the confirm so the reply-*yes* names the exact
    task (never 'yes' to a fuzzy match)."""
    from services import asana_service

    query = (args.get("task_name") or "").strip()
    if not query:
        return "reply", f"Which task should I {verb}? Give me (part of) its name."
    project_gid, problem = _asana_ready(client_id)
    if problem:
        return "reply", problem
    tasks = await asana_service.list_project_tasks(project_gid)
    matches = match_open_tasks(tasks, query)
    if not matches:
        open_names = [t.get("name") for t in tasks if not t.get("completed") and t.get("name")]
        listing = "; ".join(open_names[:8]) or "none"
        return "reply", (
            f"I couldn't find an open task matching “{query}” on this board. "
            f"Open tasks: {listing}."
        )
    if len(matches) > 1:
        listing = "\n".join(f"• {t.get('name')}" for t in matches[:8])
        return "reply", (
            f"“{query}” matches {len(matches)} open tasks — which one?\n{listing}"
        )
    task = matches[0]
    who = (task.get("assignee") or {}).get("name")
    staged = {**args, "task_gid": task.get("gid"), "task_name": task.get("name")}
    staged["_confirm"] = (
        f"{verb} the Asana task *“{task.get('name')}”*"
        + (f" (assigned to {who})" if who else " (unassigned)")
    )
    return "confirm", staged


async def _stage_remove_task(client_id: str, args: dict) -> tuple[str, dict | str]:
    return await _stage_pick_task(client_id, args, "permanently delete")


async def _stage_complete_task(client_id: str, args: dict) -> tuple[str, dict | str]:
    return await _stage_pick_task(client_id, args, "mark complete")


async def _act_remove_task(client_id: str, args: Optional[dict] = None) -> str:
    from services import asana_service

    args = args or {}
    if not args.get("task_gid"):
        return "I lost track of which task to delete — ask again naming the task."
    await asana_service.delete_task(args["task_gid"])
    return f"🗑️ Deleted *“{args.get('task_name')}”* from the board."


async def _act_complete_task(client_id: str, args: Optional[dict] = None) -> str:
    from services import asana_service

    args = args or {}
    if not args.get("task_gid"):
        return "I lost track of which task to complete — ask again naming the task."
    await asana_service.complete_task(args["task_gid"])
    return f"✅ Marked *“{args.get('task_name')}”* complete."


# ---------------------------------------------------------------------------
# Admin actions — client profile, target cities, tracked keywords, AI-visibility
# keywords/competitors, campaign goals, client reports. All confirm-gated
# (writes to campaign state / paid follow-on work), all staged so the confirm
# names the exact change before anything is written.
# ---------------------------------------------------------------------------
def _clean_list(values) -> list[str]:
    """Trim + case-insensitively dedupe a Claude-supplied string list."""
    seen: dict[str, str] = {}
    for v in values or []:
        name = str(v).strip() if v is not None else ""
        if name:
            seen.setdefault(name.casefold(), name)
    return list(seen.values())


def _client_row(client_id: str, columns: str) -> dict:
    rows = (
        get_supabase().table("clients").select(columns).eq("id", client_id).limit(1).execute()
    ).data
    return rows[0] if rows else {}


def _fmt_profile_value(field: str, value) -> str:
    if field == "is_sab":
        return "yes" if value else "no"
    if field == "retainer_monthly" and value is not None:
        return f"${value:,.0f}"
    return str(value) if value not in (None, "") else "(not set)"


async def _stage_update_profile(client_id: str, args: dict) -> tuple[str, dict | str]:
    field = (args.get("field") or "").strip()
    coerced, error = coerce_profile_value(field, args.get("value"))
    if error:
        return "reply", error
    current = _client_row(client_id, field).get(field)
    if current == coerced:
        return "reply", f"{_PROFILE_FIELDS[field].capitalize()} is already *{_fmt_profile_value(field, coerced)}* — nothing to change."
    staged = {**args, "field": field, "coerced_value": coerced}
    staged["_confirm"] = (
        f"set {_PROFILE_FIELDS[field]} to *{_fmt_profile_value(field, coerced)}* "
        f"(currently *{_fmt_profile_value(field, current)}*)"
    )
    return "confirm", staged


def _act_update_profile(client_id: str, args: Optional[dict] = None) -> str:
    args = args or {}
    field = args.get("field")
    if field not in _PROFILE_FIELDS or "coerced_value" not in args:
        return "I lost track of which field to change — ask again naming the field and value."
    value = args["coerced_value"]
    supabase = get_supabase()
    updates: dict = {field: value, "updated_at": "now()"}
    if field == "website_url":
        # Mirror the clients API: a website change re-runs the site analysis.
        updates.update(
            {"website_analysis_status": "pending", "website_analysis": None, "website_analysis_error": None}
        )
    supabase.table("clients").update(updates).eq("id", client_id).execute()
    if field == "website_url":
        supabase.table("async_jobs").insert(
            {
                "job_type": "website_scrape",
                "entity_id": client_id,
                "payload": {"website_url": value, "client_id": client_id},
            }
        ).execute()
        return f"✅ Website set to *{value}* — re-running the site analysis in the background."
    return f"✅ Set {_PROFILE_FIELDS[field]} to *{_fmt_profile_value(field, value)}*."


async def _stage_add_cities(client_id: str, args: dict) -> tuple[str, dict | str]:
    cities = _clean_list(args.get("cities"))
    if not cities:
        return "reply", "Which cities should I add to the target list?"
    existing = _client_row(client_id, "target_cities").get("target_cities") or []
    merged, added, already = merge_cities(existing, cities)
    if not added:
        return "reply", f"Already on the target list: {', '.join(already)} — nothing to add."
    staged = {**args, "merged": merged, "added": added, "already": already}
    note = f" ({', '.join(already)} already on the list)" if already else ""
    staged["_confirm"] = f"add *{', '.join(added)}* to the target-city list{note}"
    return "confirm", staged


def _act_add_cities(client_id: str, args: Optional[dict] = None) -> str:
    args = args or {}
    if not args.get("merged"):
        return "I lost track of which cities to add — ask again naming them."
    get_supabase().table("clients").update(
        {"target_cities": args["merged"], "updated_at": "now()"}
    ).eq("id", client_id).execute()
    return (
        f"✅ Added *{', '.join(args.get('added') or [])}* to the target cities "
        f"({len(args['merged'])} total). The Local SEO silo planner picks them up on its next run."
    )


async def _stage_remove_cities(client_id: str, args: dict) -> tuple[str, dict | str]:
    cities = _clean_list(args.get("cities"))
    if not cities:
        return "reply", "Which cities should I remove from the target list?"
    existing = _client_row(client_id, "target_cities").get("target_cities") or []
    remaining, removed, missing = drop_cities(existing, cities)
    if not removed:
        listing = ", ".join(existing[:12]) or "none"
        return "reply", (
            f"None of those are on the target list. Current target cities: {listing}."
        )
    staged = {**args, "remaining": remaining, "removed": removed}
    note = f" ({', '.join(missing)} not on the list)" if missing else ""
    staged["_confirm"] = f"remove *{', '.join(removed)}* from the target-city list{note}"
    return "confirm", staged


def _act_remove_cities(client_id: str, args: Optional[dict] = None) -> str:
    args = args or {}
    if not args.get("removed"):
        return "I lost track of which cities to remove — ask again naming them."
    get_supabase().table("clients").update(
        {"target_cities": args.get("remaining") or [], "updated_at": "now()"}
    ).eq("id", client_id).execute()
    return f"🗑️ Removed *{', '.join(args['removed'])}* from the target cities ({len(args.get('remaining') or [])} remain)."


async def _stage_add_tracked_keywords(client_id: str, args: dict) -> tuple[str, dict | str]:
    keywords = _clean_list(args.get("keywords"))
    if not keywords:
        return "reply", "Which keywords should I start tracking?"
    existing = {
        (r.get("keyword") or "").casefold()
        for r in (
            get_supabase().table("tracked_keywords").select("keyword")
            .eq("client_id", client_id).execute()
        ).data or []
    }
    new = [k for k in keywords if k.casefold() not in existing]
    dupes = [k for k in keywords if k.casefold() in existing]
    if not new:
        return "reply", f"Already tracked: {', '.join(dupes)} — nothing to add."
    staged = {**args, "new": new}
    note = f" ({', '.join(dupes)} already tracked)" if dupes else ""
    staged["_confirm"] = f"start rank-tracking *{', '.join(new)}*{note}"
    return "confirm", staged


def _act_add_tracked_keywords(client_id: str, args: Optional[dict] = None) -> str:
    from services import keyword_market, rank_materialize

    args = args or {}
    new = args.get("new") or []
    if not new:
        return "I lost track of which keywords to add — ask again naming them."
    supabase = get_supabase()
    supabase.table("tracked_keywords").upsert(
        [{"client_id": client_id, "keyword": kw, "source": "gsc"} for kw in new],
        on_conflict="client_id,keyword",
        ignore_duplicates=True,
    ).execute()
    # Same follow-on as the Rankings page: backfill the rank axis + market data.
    rank_materialize.enqueue_materialize(client_id)
    keyword_market.enqueue_keyword_market(client_id)
    return (
        f"✅ Now tracking *{', '.join(new)}* — backfilling rank history and market "
        "data in the background; they appear on the Rankings page shortly."
    )


async def _stage_remove_tracked_keyword(client_id: str, args: dict) -> tuple[str, dict | str]:
    query = (args.get("keyword") or "").strip()
    if not query:
        return "reply", "Which keyword should I stop tracking?"
    rows = (
        get_supabase().table("tracked_keywords").select("id, keyword")
        .eq("client_id", client_id).execute()
    ).data or []
    matches = match_named(rows, query, key="keyword")
    if not matches:
        listing = "; ".join(r["keyword"] for r in rows[:10]) or "none"
        return "reply", f"“{query}” isn't tracked for this client. Tracked keywords: {listing}."
    if len(matches) > 1:
        listing = "\n".join(f"• {r['keyword']}" for r in matches[:8])
        return "reply", f"“{query}” matches {len(matches)} tracked keywords — which one?\n{listing}"
    staged = {**args, "keyword_id": matches[0]["id"], "keyword": matches[0]["keyword"]}
    staged["_confirm"] = (
        f"stop tracking *“{matches[0]['keyword']}”* and delete its rank history"
    )
    return "confirm", staged


def _act_remove_tracked_keyword(client_id: str, args: Optional[dict] = None) -> str:
    args = args or {}
    if not args.get("keyword_id"):
        return "I lost track of which keyword to remove — ask again naming it."
    get_supabase().table("tracked_keywords").delete().eq("id", args["keyword_id"]).execute()
    return f"🗑️ Stopped tracking *“{args.get('keyword')}”*."


async def _stage_add_ai_keywords(client_id: str, args: dict) -> tuple[str, dict | str]:
    from services import brand_service

    keywords = _clean_list(args.get("keywords"))
    if not keywords:
        return "reply", "Which keywords should I add to AI Visibility tracking?"
    existing = {
        (r.get("keyword") or "").casefold() for r in brand_service.list_keywords(client_id)
    }
    new = [k for k in keywords if k.casefold() not in existing]
    dupes = [k for k in keywords if k.casefold() in existing]
    if not new:
        return "reply", f"Already tracked in AI Visibility: {', '.join(dupes)} — nothing to add."
    staged = {**args, "new": new}
    note = f" ({', '.join(dupes)} already tracked)" if dupes else ""
    staged["_confirm"] = f"add *{', '.join(new)}* to AI Visibility tracking{note}"
    return "confirm", staged


def _act_add_ai_keywords(client_id: str, args: Optional[dict] = None) -> str:
    from fastapi import HTTPException

    from services import brand_service

    args = args or {}
    new = args.get("new") or []
    if not new:
        return "I lost track of which keywords to add — ask again naming them."
    added = []
    for kw in new:
        try:
            brand_service.add_keyword(client_id, kw, None)
            added.append(kw)
        except HTTPException as exc:
            if exc.detail != "keyword_exists":
                raise
    return (
        f"✅ Added *{', '.join(added)}* to AI Visibility — they're included in the next scan."
        if added
        else "Those keywords were already tracked — nothing added."
    )


async def _stage_remove_ai_keyword(client_id: str, args: dict) -> tuple[str, dict | str]:
    from services import brand_service

    query = (args.get("keyword") or "").strip()
    if not query:
        return "reply", "Which AI-visibility keyword should I remove?"
    rows = brand_service.list_keywords(client_id)
    matches = match_named(rows, query, key="keyword")
    if not matches:
        listing = "; ".join(r["keyword"] for r in rows[:10]) or "none"
        return "reply", f"“{query}” isn't an AI-visibility keyword here. Tracked: {listing}."
    if len(matches) > 1:
        listing = "\n".join(f"• {r['keyword']}" for r in matches[:8])
        return "reply", f"“{query}” matches {len(matches)} keywords — which one?\n{listing}"
    staged = {**args, "keyword_id": matches[0]["id"], "keyword": matches[0]["keyword"]}
    staged["_confirm"] = f"remove *“{matches[0]['keyword']}”* from AI Visibility tracking"
    return "confirm", staged


def _act_remove_ai_keyword(client_id: str, args: Optional[dict] = None) -> str:
    from services import brand_service

    args = args or {}
    if not args.get("keyword_id"):
        return "I lost track of which keyword to remove — ask again naming it."
    brand_service.delete_keyword(client_id, args["keyword_id"])
    return f"🗑️ Removed *“{args.get('keyword')}”* from AI Visibility tracking."


async def _stage_add_ai_competitor(client_id: str, args: dict) -> tuple[str, dict | str]:
    from services import brand_service

    name = (args.get("name") or "").strip()
    if not name:
        return "reply", "Which competitor should I add to AI Visibility tracking?"
    existing = brand_service.list_competitors(client_id)
    if any((c.get("competitor_name") or "").casefold() == name.casefold() for c in existing):
        return "reply", f"*{name}* is already a tracked AI-visibility competitor."
    staged = {**args, "name": name}
    site = (args.get("website") or "").strip()
    staged["_confirm"] = (
        f"add *{name}*{f' ({site})' if site else ''} as an AI Visibility competitor"
    )
    return "confirm", staged


def _act_add_ai_competitor(client_id: str, args: Optional[dict] = None) -> str:
    from fastapi import HTTPException

    from services import brand_service

    args = args or {}
    name = (args.get("name") or "").strip()
    if not name:
        return "I lost track of which competitor to add — ask again naming them."
    try:
        brand_service.add_competitor(client_id, name, (args.get("website") or "").strip() or None, None)
    except HTTPException as exc:
        if exc.detail == "competitor_exists":
            return f"*{name}* is already a tracked AI-visibility competitor."
        raise
    return f"✅ Added *{name}* as an AI Visibility competitor — they're classified against the next scan."


async def _stage_remove_ai_competitor(client_id: str, args: dict) -> tuple[str, dict | str]:
    from services import brand_service

    query = (args.get("name") or "").strip()
    if not query:
        return "reply", "Which AI-visibility competitor should I remove?"
    rows = brand_service.list_competitors(client_id)
    matches = match_named(rows, query, key="competitor_name")
    if not matches:
        listing = "; ".join(r["competitor_name"] for r in rows[:10]) or "none"
        return "reply", f"“{query}” isn't a tracked competitor here. Tracked: {listing}."
    if len(matches) > 1:
        listing = "\n".join(f"• {r['competitor_name']}" for r in matches[:8])
        return "reply", f"“{query}” matches {len(matches)} competitors — which one?\n{listing}"
    staged = {**args, "competitor_id": matches[0]["id"], "name": matches[0]["competitor_name"]}
    staged["_confirm"] = f"remove *{matches[0]['competitor_name']}* from AI Visibility competitors"
    return "confirm", staged


def _act_remove_ai_competitor(client_id: str, args: Optional[dict] = None) -> str:
    from services import brand_service

    args = args or {}
    if not args.get("competitor_id"):
        return "I lost track of which competitor to remove — ask again naming them."
    brand_service.delete_competitor(client_id, args["competitor_id"])
    return f"🗑️ Removed *{args.get('name')}* from AI Visibility competitors."


async def _stage_add_goal(client_id: str, args: dict) -> tuple[str, dict | str]:
    from services.campaign_goals import GOAL_TYPES

    goal_type = (args.get("goal_type") or "").strip()
    if goal_type not in GOAL_TYPES:
        return "reply", f"Goal type must be one of: {', '.join(GOAL_TYPES)}."
    label = (args.get("label") or "").strip()
    if not label:
        return "reply", "What should the goal be called? Give me a short label."
    # Tolerate Claude passing numbers as strings.
    for num_field, caster in (("target_value", float), ("target_position", int)):
        if args.get(num_field) is not None:
            try:
                args[num_field] = caster(args[num_field])
            except (TypeError, ValueError):
                return "reply", f"“{args[num_field]}” isn't a number — what's the {num_field.replace('_', ' ')}?"
    # Mirror the Campaign Goals API's validation rules.
    if goal_type != "custom" and args.get("target_value") is None:
        return "reply", "What's the target value for this goal (a number)?"
    if goal_type == "keyword_position" and not (args.get("keyword") or "").strip():
        return "reply", "Which keyword is this position goal for?"
    if goal_type == "keywords_in_top" and not args.get("target_position"):
        return "reply", "Top what? Give me the position band (e.g. top 3 → 3)."
    due = (args.get("due_date") or "").strip()
    if due:
        try:
            date.fromisoformat(due)
        except ValueError:
            return "reply", "The due date must be YYYY-MM-DD (e.g. 2026-12-31)."
    staged = {**args, "label": label, "goal_type": goal_type}
    bits = [goal_type.replace("_", " ")]
    if args.get("keyword"):
        bits.append(f"keyword “{args['keyword']}”")
    if args.get("target_value") is not None:
        bits.append(f"target {args['target_value']:g}")
    if args.get("target_position"):
        bits.append(f"top {args['target_position']}")
    if due:
        bits.append(f"due {due}")
    staged["_confirm"] = f"create the campaign goal *“{label}”* ({', '.join(bits)})"
    return "confirm", staged


def _act_add_goal(client_id: str, args: Optional[dict] = None) -> str:
    from services import campaign_goals

    args = args or {}
    if not (args.get("label") and args.get("goal_type")):
        return "I lost track of the goal's details — ask again with the label and target."
    fields = {
        k: args.get(k)
        for k in ("goal_type", "label", "keyword", "target_value", "target_position", "due_date", "notes")
    }
    if isinstance(fields.get("due_date"), str) and not fields["due_date"].strip():
        fields["due_date"] = None
    row = campaign_goals.create_goal(client_id, fields, created_by=None)
    baseline = row.get("baseline_value")
    note = f" Baseline captured: {baseline:g}." if isinstance(baseline, (int, float)) else ""
    return (
        f"🎯 Created the campaign goal *“{row.get('label')}”*.{note} "
        "Progress is assessed on every read — see the Campaign Goals page."
    )


async def _stage_remove_goal(client_id: str, args: dict) -> tuple[str, dict | str]:
    query = (args.get("label") or "").strip()
    if not query:
        return "reply", "Which goal should I remove? Give me (part of) its label."
    rows = (
        get_supabase().table("campaign_goals").select("id, label, goal_type")
        .eq("client_id", client_id).execute()
    ).data or []
    matches = match_named(rows, query, key="label")
    if not matches:
        listing = "; ".join(r["label"] for r in rows[:10] if r.get("label")) or "none"
        return "reply", f"I couldn't find a goal matching “{query}”. Goals: {listing}."
    if len(matches) > 1:
        listing = "\n".join(f"• {r['label']}" for r in matches[:8])
        return "reply", f"“{query}” matches {len(matches)} goals — which one?\n{listing}"
    staged = {**args, "goal_id": matches[0]["id"], "label": matches[0]["label"]}
    staged["_confirm"] = f"permanently delete the campaign goal *“{matches[0]['label']}”*"
    return "confirm", staged


def _act_remove_goal(client_id: str, args: Optional[dict] = None) -> str:
    args = args or {}
    if not args.get("goal_id"):
        return "I lost track of which goal to delete — ask again naming it."
    get_supabase().table("campaign_goals").delete().eq("id", args["goal_id"]).eq(
        "client_id", client_id
    ).execute()
    return f"🗑️ Deleted the campaign goal *“{args.get('label')}”*."


_REPORT_TYPES = ("monthly", "weekly", "ai_visibility")


async def _stage_generate_report(client_id: str, args: dict) -> tuple[str, dict | str]:
    report_type = (args.get("report_type") or "monthly").strip()
    if report_type not in _REPORT_TYPES:
        return "reply", f"Report type must be one of: {', '.join(_REPORT_TYPES)}."
    deliver = bool(args.get("deliver"))
    staged = {**args, "report_type": report_type, "deliver": deliver}
    staged["_confirm"] = (
        f"generate a {report_type.replace('_', ' ')} client report"
        + (
            " and DELIVER it to the client per their report settings (email/Drive)"
            if deliver
            else " (internal — not delivered to the client)"
        )
    )
    return "confirm", staged


def _act_generate_report(client_id: str, args: Optional[dict] = None) -> str:
    from services import client_report

    args = args or {}
    report_type = args.get("report_type") or "monthly"
    deliver = bool(args.get("deliver"))
    client_report.enqueue_client_report(client_id, report_type, deliver=deliver)
    return (
        f"📄 Generating the {report_type.replace('_', ' ')} report — it lands on the "
        "Client Reports page in a minute or two"
        + (" and is delivered per the client's report settings." if deliver else ".")
    )


# (tool name) → {label, paid, run} + optional:
#   note   — the parenthetical in the reply-*yes* confirm (default: API-budget
#            wording). `paid` really means "confirm-gated": paid API spend OR
#            side effects on an external system (Asana writes).
#   params — JSON-schema properties/required for the tool (Claude fills them
#            from the conversation; args flow stage → confirm → run).
#   stage  — async (client_id, args) -> ("confirm", staged_args) to proceed
#            (staged_args["_confirm"] overrides the confirm verb-phrase) or
#            ("reply", text) to answer immediately (guards / disambiguation).
_ACTIONS: dict[str, dict] = {
    "rebuild_action_plan": {"label": "rebuild the Action Plan", "paid": False, "run": _act_rebuild_plan},
    "run_maps_scan": {"label": "run a Maps geo-grid scan", "paid": True, "run": _act_maps_scan},
    "run_gsc_research": {"label": "run a GSC Research analysis", "paid": True, "run": _act_gsc_research},
    "run_ai_visibility_scan": {"label": "run an AI Visibility scan", "paid": True, "run": _act_ai_scan},
    # SerMaStr strategist mode: "strategy review for <client>". Paid gating =
    # the reply-*yes* confirm (an LLM run + up to one paid nlp audit call).
    "run_strategy_review": {"label": "run a strategist review", "paid": True, "run": _act_strategy_review},
    # Not paid-API spend, but it creates real tasks on the client's board — same
    # reply-*yes* confirm gate (the `note` swaps the budget wording).
    "push_task_plan": {
        "label": "push the latest monthly task plan to Asana",
        "paid": True,
        "note": "creates real tasks on the client's Asana board",
        "run": _act_push_task_plan,
    },
    # Conversational task management — parameterized (Claude extracts the task
    # name / assignee from the message), staged so the confirm names the exact
    # resolved task before anything is written or deleted.
    "add_asana_task": {
        "label": "create an Asana task",
        "paid": True,
        "note": "creates a real task on the client's Asana board",
        "run": _act_add_task,
        "stage": _stage_add_task,
        "params": {
            "properties": {
                "task_name": {"type": "string", "description": "The task's name, verbatim from the teammate."},
                "assignee": {"type": "string", "description": "Person to assign it to (first or full name), if the teammate named one."},
                "notes": {"type": "string", "description": "Any extra detail the teammate gave, for the task description."},
            },
            "required": ["task_name"],
        },
    },
    "remove_asana_task": {
        "label": "delete an Asana task",
        "paid": True,
        "note": "permanently deletes a task from the client's Asana board",
        "run": _act_remove_task,
        "stage": _stage_remove_task,
        "params": {
            "properties": {
                "task_name": {"type": "string", "description": "Name (or distinctive part of the name) of the task to delete."},
            },
            "required": ["task_name"],
        },
    },
    "complete_asana_task": {
        "label": "mark an Asana task complete",
        "paid": True,
        "note": "marks a task complete on the client's Asana board",
        "run": _act_complete_task,
        "stage": _stage_complete_task,
        "params": {
            "properties": {
                "task_name": {"type": "string", "description": "Name (or distinctive part of the name) of the task to mark complete."},
            },
            "required": ["task_name"],
        },
    },
    # ── Admin actions: client profile / setup ──────────────────────────────
    "update_client_profile": {
        "label": "edit the client's profile",
        "paid": True,
        "note": "changes the client's Setup-page configuration",
        "run": _act_update_profile,
        "stage": _stage_update_profile,
        "params": {
            "properties": {
                "field": {
                    "type": "string",
                    "enum": list(_PROFILE_FIELDS),
                    "description": "Which profile field to change.",
                },
                "value": {
                    "type": "string",
                    "description": "The new value, verbatim from the teammate (retainer as a dollar amount; client_type local|enterprise; is_sab yes|no).",
                },
            },
            "required": ["field", "value"],
        },
    },
    "add_target_cities": {
        "label": "add target cities",
        "paid": True,
        "note": "adds cities to the client's Local SEO target-city list",
        "run": _act_add_cities,
        "stage": _stage_add_cities,
        "params": {
            "properties": {
                "cities": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "City names to add to the target list, verbatim from the teammate.",
                },
            },
            "required": ["cities"],
        },
    },
    "remove_target_cities": {
        "label": "remove target cities",
        "paid": True,
        "note": "removes cities from the client's Local SEO target-city list",
        "run": _act_remove_cities,
        "stage": _stage_remove_cities,
        "params": {
            "properties": {
                "cities": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "City names to remove from the target list.",
                },
            },
            "required": ["cities"],
        },
    },
    # ── Admin actions: organic rank tracker keywords ───────────────────────
    "add_tracked_keywords": {
        "label": "add tracked keywords",
        "paid": True,
        "note": "starts rank-tracking new keywords (backfills rank + market data via DataForSEO)",
        "run": _act_add_tracked_keywords,
        "stage": _stage_add_tracked_keywords,
        "params": {
            "properties": {
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Keywords to start rank-tracking, verbatim from the teammate.",
                },
            },
            "required": ["keywords"],
        },
    },
    "remove_tracked_keyword": {
        "label": "remove a tracked keyword",
        "paid": True,
        "note": "stops tracking a keyword and deletes its rank history",
        "run": _act_remove_tracked_keyword,
        "stage": _stage_remove_tracked_keyword,
        "params": {
            "properties": {
                "keyword": {"type": "string", "description": "The keyword (or a distinctive part of it) to stop tracking."},
            },
            "required": ["keyword"],
        },
    },
    # ── Admin actions: AI Visibility keywords + competitors ────────────────
    "add_ai_keywords": {
        "label": "add AI Visibility keywords",
        "paid": True,
        "note": "adds keywords to AI Visibility tracking (scanned on the next run)",
        "run": _act_add_ai_keywords,
        "stage": _stage_add_ai_keywords,
        "params": {
            "properties": {
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Keywords to add to AI Visibility tracking.",
                },
            },
            "required": ["keywords"],
        },
    },
    "remove_ai_keyword": {
        "label": "remove an AI Visibility keyword",
        "paid": True,
        "note": "removes a keyword from AI Visibility tracking",
        "run": _act_remove_ai_keyword,
        "stage": _stage_remove_ai_keyword,
        "params": {
            "properties": {
                "keyword": {"type": "string", "description": "The AI-visibility keyword (or a distinctive part of it) to remove."},
            },
            "required": ["keyword"],
        },
    },
    "add_ai_competitor": {
        "label": "add an AI Visibility competitor",
        "paid": True,
        "note": "adds a competitor to AI Visibility tracking",
        "run": _act_add_ai_competitor,
        "stage": _stage_add_ai_competitor,
        "params": {
            "properties": {
                "name": {"type": "string", "description": "The competitor's business name."},
                "website": {"type": "string", "description": "The competitor's website, if the teammate gave one."},
            },
            "required": ["name"],
        },
    },
    "remove_ai_competitor": {
        "label": "remove an AI Visibility competitor",
        "paid": True,
        "note": "removes a competitor from AI Visibility tracking",
        "run": _act_remove_ai_competitor,
        "stage": _stage_remove_ai_competitor,
        "params": {
            "properties": {
                "name": {"type": "string", "description": "The competitor's name (or a distinctive part of it) to remove."},
            },
            "required": ["name"],
        },
    },
    # ── Admin actions: campaign goals ──────────────────────────────────────
    "add_campaign_goal": {
        "label": "add a campaign goal",
        "paid": True,
        "note": "creates a success target the strategist judges progress against",
        "run": _act_add_goal,
        "stage": _stage_add_goal,
        "params": {
            "properties": {
                "goal_type": {
                    "type": "string",
                    "enum": ["keyword_position", "keywords_in_top", "organic_clicks", "organic_impressions", "ai_visibility", "maps_pack_presence", "custom"],
                    "description": "The goal's metric. keyword_position = one keyword to position N (needs keyword); keywords_in_top = N keywords inside top X (needs target_position); organic_clicks/impressions = 30-day GSC sums; ai_visibility = visibility %; maps_pack_presence = top-3 pin share %; custom = manual.",
                },
                "label": {"type": "string", "description": "Short human label, e.g. \"'roof repair' to top 3\"."},
                "target_value": {"type": "number", "description": "The numeric target (position for keyword_position — lower is better; count/percentage otherwise)."},
                "keyword": {"type": "string", "description": "The keyword, for keyword_position goals."},
                "target_position": {"type": "integer", "description": "The top-X band, for keywords_in_top goals (top 3 → 3)."},
                "due_date": {"type": "string", "description": "Due date YYYY-MM-DD, if the teammate gave one (e.g. \"by Q4\" → 2026-12-31)."},
                "notes": {"type": "string", "description": "Any extra context the teammate gave."},
            },
            "required": ["goal_type", "label"],
        },
    },
    "remove_campaign_goal": {
        "label": "remove a campaign goal",
        "paid": True,
        "note": "permanently deletes a campaign goal",
        "run": _act_remove_goal,
        "stage": _stage_remove_goal,
        "params": {
            "properties": {
                "label": {"type": "string", "description": "The goal's label (or a distinctive part of it)."},
            },
            "required": ["label"],
        },
    },
    # ── Admin actions: client reports ──────────────────────────────────────
    "generate_client_report": {
        "label": "generate a client report",
        "paid": True,
        "note": "renders a client PDF report (uses API budget)",
        "run": _act_generate_report,
        "stage": _stage_generate_report,
        "params": {
            "properties": {
                "report_type": {
                    "type": "string",
                    "enum": ["monthly", "weekly", "ai_visibility"],
                    "description": "Which report to generate (default monthly).",
                },
                "deliver": {
                    "type": "boolean",
                    "description": "True ONLY when the teammate explicitly asks to send/deliver it to the client — delivery emails the client's recipients + saves to their Drive.",
                },
            },
            "required": [],
        },
    },
}
_ACTION_TOOLS = [
    {"name": name, "description": meta["label"].capitalize() + " for the client.",
     "input_schema": {"type": "object", **(meta.get("params") or {"properties": {}})}}
    for name, meta in _ACTIONS.items()
]

# Pending paid actions awaiting a "yes", keyed by (channel, thread_ts). In-memory
# / single-process (PLATFORM is one replica) + best-effort: a redeploy drops
# pending confirmations, which just means the user re-asks. Never executes a paid
# action without an explicit confirm.
_pending: dict[tuple, dict] = {}


# ---------------------------------------------------------------------------
# Claude + Slack I/O.
# ---------------------------------------------------------------------------
async def interpret(
    question: str, client: dict, context: dict, history: Optional[list[dict]] = None,
    style: str = "slack",
) -> tuple[str, object]:
    """Decide whether the message is a question or an action request.

    Returns ("action", {"name": tool_name, "args": tool_input}) when the
    teammate is asking to trigger one of the available actions, else
    ("text", answer). Claude sees the cross-module context + thread history and
    the action tools; a tool call ⇒ action, otherwise a normal grounded answer.
    `style="web"` swaps the Slack-mrkdwn voice for dashboard-chat Markdown.
    """
    import anthropic

    blocks = []
    if history:
        blocks.append("Conversation so far (oldest first):\n" + format_history(history))
    blocks.append(f"Latest message: {question}")
    blocks.append(f"Client data (JSON):\n{format_context(client, context)}")
    user = "\n\n".join(blocks)
    api = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, timeout=_LLM_TIMEOUT)
    resp = await api.messages.create(
        model=settings.slack_assistant_model,
        max_tokens=settings.slack_assistant_max_tokens,
        system=_SYSTEM + (_WEB_STYLE if style == "web" else ""),
        tools=_ACTION_TOOLS,
        messages=[{"role": "user", "content": user}],
    )
    for b in resp.content:
        if getattr(b, "type", None) == "tool_use" and b.name in _ACTIONS:
            return ("action", {"name": b.name, "args": dict(b.input or {})})
    parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
    return ("text", "\n".join(parts).strip() or "I couldn't generate an answer just now — try rephrasing.")


async def _run_action(name: str, client_id: str, args: Optional[dict]) -> str:
    """Invoke an action runner, awaiting it when async."""
    import inspect

    out = _ACTIONS[name]["run"](client_id, args or {})
    if inspect.isawaitable(out):
        out = await out
    return out


async def post_message(channel: str, text: str, thread_ts: Optional[str] = None) -> None:
    """Post a message to a channel (optionally threaded) via chat.postMessage."""
    body: dict = {"channel": channel, "text": text, "mrkdwn": True}
    if thread_ts:
        body["thread_ts"] = thread_ts
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            _SLACK_POST_URL,
            headers={"Authorization": f"Bearer {settings.slack_bot_token}"},
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"slack_error: {data.get('error')}")


async def fetch_thread_history(channel: str, thread_ts: str, skip_ts: Optional[str]) -> list[dict]:
    """Recent prior messages of a thread as [{role, content}], oldest first.

    `role` is "assistant" for SerMastr's own posts (any bot message) and "user"
    otherwise. The triggering message (`skip_ts`) is excluded. Best-effort — any
    failure returns []."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            _SLACK_REPLIES_URL,
            headers={"Authorization": f"Bearer {settings.slack_bot_token}"},
            params={"channel": channel, "ts": thread_ts, "limit": _THREAD_HISTORY_LIMIT},
        )
        resp.raise_for_status()
        data = resp.json()
    if not data.get("ok"):
        return []
    out: list[dict] = []
    for m in data.get("messages", []):
        if skip_ts and m.get("ts") == skip_ts:
            continue
        text = strip_mention(m.get("text", ""))
        if not text:
            continue
        out.append({"role": "assistant" if m.get("bot_id") else "user", "content": text})
    return out


async def handle_message(event: dict) -> None:
    """Process one channel message end-to-end (channel mode: no @mention needed).

    The router has already filtered to plain human messages. We answer every one:
    resolve the client, build cross-module context, fold in thread history for
    continuity, ask Claude, and reply in-thread. Best-effort; logs and bails on error.
    """
    channel = event.get("channel")
    thread_ts = event.get("thread_ts") or event.get("ts")
    question = strip_mention(event.get("text", ""))
    if not (channel and question):
        return
    try:
        # 1) Confirmation of a pending paid action ("yes") — runs the stored action
        # (which carries its own client_id, so the "yes" needn't name a client).
        pend_key = (channel, thread_ts)
        pending = _pending.get(pend_key)
        if pending and is_affirmative(question):
            _pending.pop(pend_key, None)
            reply = await _run_action(pending["action"], pending["client_id"], pending.get("args"))
            await post_message(channel, reply, thread_ts)
            return
        if pending:  # a different message supersedes the pending confirmation
            _pending.pop(pend_key, None)

        supabase = get_supabase()
        clients = (
            supabase.table("clients").select("id, name, website_url").execute()
        ).data or []
        client = resolve_client(question, clients)
        if not client:
            names = ", ".join(c["name"] for c in clients[:8] if c.get("name"))
            await post_message(
                channel,
                "Which client do you mean? Name them in your message"
                + (f" — e.g. {names}." if names else "."),
                thread_ts,
            )
            return

        history: list[dict] = []
        if event.get("thread_ts") and event.get("thread_ts") != event.get("ts"):
            try:
                history = await fetch_thread_history(channel, event["thread_ts"], event.get("ts"))
            except Exception as exc:  # memory is best-effort
                logger.warning("slack_thread_history_failed", extra={"channel": channel, "error": str(exc)})

        context = build_context(client["id"])
        kind, payload = await interpret(question, client, context, history)
        if kind == "action":
            name, args = payload["name"], payload["args"]
            meta = _ACTIONS[name]
            confirm_phrase = None
            if meta.get("stage"):
                # Resolve the target BEFORE the confirm (exact task, matched
                # assignee) — guards / ambiguity answer immediately instead.
                outcome, staged = await meta["stage"](client["id"], args)
                if outcome == "reply":
                    await post_message(channel, staged, thread_ts)
                    return
                args = staged
                confirm_phrase = args.pop("_confirm", None)
            if meta["paid"]:
                # 2) Stage confirm-gated actions behind an explicit reply-*yes*
                # (guards spend + external side effects).
                _pending[pend_key] = {"action": name, "client_id": client["id"], "args": args}
                # A staged confirm phrase already names the exact target (and
                # carries its own severity wording), so the generic note only
                # accompanies the generic label.
                phrase = confirm_phrase or f"{meta['label']} ({meta.get('note', 'uses API budget')})"
                await post_message(
                    channel,
                    f"This will {phrase} for *{client['name']}*. Reply *yes* to proceed.",
                    thread_ts,
                )
            else:
                await post_message(channel, await _run_action(name, client["id"], args), thread_ts)
            return
        await post_message(channel, payload, thread_ts)
    except Exception as exc:
        logger.warning("slack_assistant_failed", extra={"channel": channel, "error": str(exc)})
        try:
            await post_message(channel, "Sorry — I hit an error answering that.", thread_ts)
        except Exception:
            pass
