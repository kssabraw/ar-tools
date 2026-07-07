"""Slack conversational assistant — "SerMastr".

Two-way Slack, **channel mode**: SerMastr lives in a dedicated channel, so Slack
POSTs a `message` event to `/slack/events` for *every* message there (no @mention
needed). We answer each plain human message — resolve which client it's about,
assemble a cross-module context covering every workspace module (rank trackers,
Maps geo-grid, AI visibility, content, keyword research, task plan, citations,
syndication, reports, SOPs, Asana, health guards, strategist reviews, setup),
fold in the thread's prior turns for
continuity, ask Claude, and post the answer back **in-thread**. The bot's own
posts (rank-drop alerts etc.) and other bots are ignored, so it never loops.

Q&A plus a small action registry (_ACTIONS): the assistant can trigger existing
jobs — scans, research, a strategist review, an Asana task-plan push — with paid
or side-effecting actions staged behind an explicit reply-*yes* confirm. Anyone
in the workspace can ask (per the product decision); inbound requests are
verified by Slack's request signature so the public endpoint can't be spoofed.

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
from datetime import date, timedelta
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
    "- task_plan: the latest Recipe Engine monthly task plan — deployable budget, "
    "spend, flags, diagnosis, and the assigned task lines.\n"
    "- citations: citation-liveness tracking — status counts + currently-dead URLs.\n"
    "- syndication: content-syndication config + discovered/published item counts.\n"
    "- reports: recently generated client reports + the delivery schedule.\n"
    "- sops: which SOPs are loaded for this client (titles; agency-wide + "
    "client-specific).\n"
    "- asana: whether an Asana project is mapped + the monthly task templates.\n"
    "- health: campaign guards — an active FREEZE (all content/link output paused; "
    "mention it prominently if present), open response episodes (each drop's "
    "response clock), and offpage alerts (referring-domain loss/spike, citation "
    "loss).\n"
    "- strategist_review: the latest completed strategist review — assessment, "
    "proposals with approval status, open questions.\n"
    "- setup: the client's full business profile — the GBP listing (address, "
    "coordinates, phone, categories, rating, review count, hours, service-area "
    "places, Maps link), target cities, campaign settings (client type, SAB, "
    "retainer), brand-voice summary, and ICP summary.\n"
    "A module is OMITTED when there's no data for it — if a module key is absent, "
    "that work simply hasn't been set up or run for this client; say so rather than "
    "guessing. Answer using ONLY this data (plus live tool results). Be concise and "
    "direct — a few sentences "
    "or a short list, Slack-friendly (you may use *bold* and bullets). Lead with the "
    "answer. As a strategist, you may connect signals across modules when relevant "
    "(e.g. a ranking drop + a content gap). Never invent numbers or modules.\n\n"
    "LIVE DATA: the stored context above is refreshed on a schedule (GSC daily, "
    "DataForSEO weekly). Two tools get you fresher reads:\n"
    "- fetch_live_gsc (free, use directly): pulls LIVE Search Console rows for the "
    "client's verified property. Use it when the teammate asks for current/live/"
    "latest search performance, top queries or pages, clicks/impressions — or when "
    "the stored context can't answer a performance question. Then answer from the "
    "result, saying the numbers are a live Search Console pull.\n"
    "- check_live_serp (paid, confirm-gated): a live Google SERP check for one "
    "keyword. Call it when the teammate explicitly wants a right-now SERP/position "
    "check; the teammate will be asked to confirm before it runs.\n\n"
    "You can also TAKE ACTIONS via the provided tools: run work (rebuild the Action "
    "Plan, run a Maps geo-grid scan, run GSC Research, run an AI Visibility scan, run "
    "a strategist review, push the latest monthly task plan to Asana) and manage the "
    "client's Asana board (add_asana_task — extract the task name, assignee and any "
    "detail from the message; remove_asana_task / complete_asana_task — pass the task "
    "name the teammate used). If the teammate is clearly asking you to run/start/"
    "trigger/rebuild/create/assign/delete/finish one of these for the client, call the "
    "matching tool instead of answering. If they're only asking about results or "
    "anything else, answer normally — do NOT call an action tool for a question "
    "(fetch_live_gsc is the one tool that IS for questions).\n\n"
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
        cann = g.get("cannibalization") or []
        quick = g.get("quick_wins") or []
        hidden = g.get("hidden_wins") or []
        out["gsc_opportunities"] = {
            "counts": {
                "cannibalization": len(cann),
                "quick_wins": len(quick),
                "hidden_wins": len(hidden),
            },
            "cannibalization": [
                {"query": c.get("query"), "competing_pages": len(c.get("pages") or [])}
                for c in cann[:5]
            ],
            "quick_wins": [
                {"keyword": w.get("keyword"), "position": w.get("position"),
                 "impressions": w.get("impressions"), "page": w.get("page")}
                for w in quick[:8]
            ],
            "hidden_wins": [
                {"keyword": w.get("keyword"), "position": w.get("position"),
                 "impressions": w.get("impressions"), "page": w.get("page")}
                for w in hidden[:8]
            ],
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
    alerts = (
        supabase.table("maps_alerts")
        .select("keyword, alert_type, message, triggered_on")
        .eq("client_id", client_id)
        .is_("resolved_at", "null")
        .order("created_at", desc=True)
        .limit(10)
        .execute()
    ).data or []
    if alerts:
        out["open_alerts"] = alerts
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

    recent_runs = (
        supabase.table("runs")
        .select("keyword, content_type, created_at")
        .eq("client_id", client_id)
        .eq("status", "complete")
        .order("created_at", desc=True)
        .limit(8)
        .execute()
    ).data or []
    if recent_runs:
        out["recent_completed_runs"] = recent_runs
    recent_pages = (
        supabase.table("local_seo_pages")
        .select("keyword, created_at")
        .eq("client_id", client_id)
        .is_("deleted_at", "null")
        .order("created_at", desc=True)
        .limit(8)
        .execute()
    ).data or []
    if recent_pages:
        out["recent_local_seo_pages"] = recent_pages
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
    """The client's full configured business profile.

    Everything captured on the client row goes in — the whole GBP profile
    (address, coordinates, phone, categories, rating, hours, service area…),
    target cities, campaign settings, ICP — except bulky raw assets (the GBP
    reviews array, the full brand guide), which stay presence flags so one
    client's context can't swamp the prompt.
    """
    rows = (
        supabase.table("clients")
        .select(
            "website_url, gbp, gbp_place_id, brand_voice, detected_icp, "
            "differentiators, icp_text, target_cities, retainer_monthly, "
            "is_sab, client_type"
        )
        .eq("id", client_id)
        .limit(1)
        .execute()
    ).data
    if not rows:
        return None
    c = rows[0]
    gbp = c.get("gbp") or {}
    out: dict = {
        "website": c.get("website_url"),
        "client_type": c.get("client_type"),
        "is_sab": bool(c.get("is_sab")),
        "retainer_monthly": c.get("retainer_monthly"),
        "target_cities": (c.get("target_cities") or [])[:12],
        "has_brand_voice": bool(c.get("brand_voice")),
        "has_icp": bool(c.get("detected_icp") or c.get("differentiators")),
    }
    try:
        from services import icp_service

        icp = icp_service.resolve_icp_text(c) or ""
        if icp:
            out["icp_summary"] = icp[:1500]
    except Exception:
        pass
    try:
        from services.brand_voice_service import render_brand_voice_text

        bv = render_brand_voice_text(c.get("brand_voice")) or ""
        if bv:
            out["brand_voice_summary"] = bv[:800]
    except Exception:
        pass
    if gbp:
        out["gbp"] = {
            "business_name": gbp.get("business_name"),
            "place_id": c.get("gbp_place_id") or gbp.get("place_id"),
            "address": gbp.get("address"),
            "address_hidden": gbp.get("address_hidden"),
            "latitude": gbp.get("latitude"),
            "longitude": gbp.get("longitude"),
            "phone": gbp.get("phone"),
            "website": gbp.get("website"),
            "category": gbp.get("gbp_category"),
            "categories": (gbp.get("gbp_categories") or [])[:8],
            "rating": gbp.get("gbp_rating"),
            "review_count": gbp.get("gbp_review_count"),
            "hours": gbp.get("hours"),
            "google_maps_uri": gbp.get("google_maps_uri"),
            "service_area_places": (gbp.get("service_area_places") or [])[:10],
            "description": (gbp.get("description") or "")[:500] or None,
        }
    else:
        out["has_gbp"] = False
    return out


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


def _ctx_task_plan(supabase, client_id: str, today: date) -> Optional[dict]:
    """Latest Recipe Engine monthly task plan — budget, flags, assigned lines."""
    rows = (
        supabase.table("monthly_task_plans")
        .select("month, margin_used, deployable, spent, remaining, flags, plan, created_at")
        .eq("client_id", client_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    ).data
    if not rows:
        return None
    p = rows[0]
    plan = p.get("plan") or {}
    return {
        "month": p.get("month"),
        "margin_used": p.get("margin_used"),
        "deployable": p.get("deployable"),
        "spent": p.get("spent"),
        "remaining": p.get("remaining"),
        "flags": p.get("flags") or [],
        "diagnosis": plan.get("diagnosis"),
        "tasks": [
            {
                "task": t.get("label"),
                "quantity": t.get("quantity"),
                "line_cost": t.get("line_cost"),
                "assignee": t.get("assignee"),
            }
            for t in (plan.get("tasks") or [])[:15]
        ],
    }


def _ctx_citations(supabase, client_id: str, today: date) -> Optional[dict]:
    """Citation liveness — status counts plus the currently-dead URLs."""
    rows = (
        supabase.table("client_citations")
        .select("url, status, last_checked_at")
        .eq("client_id", client_id)
        .execute()
    ).data or []
    if not rows:
        return None
    by_status: dict[str, int] = {}
    for r in rows:
        s = r.get("status") or "unknown"
        by_status[s] = by_status.get(s, 0) + 1
    out: dict = {"total": len(rows), "by_status": by_status}
    dead = [r["url"] for r in rows if r.get("status") == "dead"]
    if dead:
        out["dead_urls"] = dead[:8]
    return out


def _ctx_syndication(supabase, client_id: str, today: date) -> Optional[dict]:
    """Content syndication — config plus discovered/published item counts."""
    cfg = (
        supabase.table("syndication_config")
        .select("enabled, share_mode, last_scan_date")
        .eq("client_id", client_id)
        .limit(1)
        .execute()
    ).data
    by_status: dict[str, int] = {}
    for s in ("discovered", "rewriting", "published", "failed", "skipped"):
        n = (
            supabase.table("syndication_items")
            .select("id", count="exact", head=True)
            .eq("client_id", client_id)
            .eq("status", s)
            .execute()
        ).count or 0
        if n:
            by_status[s] = n
    if not (cfg or by_status):
        return None
    out: dict = {"items_by_status": by_status}
    if cfg:
        c = cfg[0]
        out["enabled"] = c.get("enabled")
        out["share_mode"] = c.get("share_mode")
        out["last_scan_date"] = c.get("last_scan_date")
    return out


def _ctx_reports(supabase, client_id: str, today: date) -> Optional[dict]:
    """Client reports — recent generated reports + the delivery schedule."""
    reports = (
        supabase.table("client_reports")
        .select("report_type, status, title, period_start, period_end, created_at")
        .eq("client_id", client_id)
        .order("created_at", desc=True)
        .limit(5)
        .execute()
    ).data or []
    cfg = (
        supabase.table("client_report_settings")
        .select("*")
        .eq("client_id", client_id)
        .limit(1)
        .execute()
    ).data
    if not (reports or cfg):
        return None
    out: dict = {}
    if reports:
        out["recent_reports"] = reports
    if cfg:
        c = cfg[0]
        out["schedule"] = {
            "cadence": c.get("cadence"),
            "recipient_count": len(c.get("recipients") or []),
            "email_enabled": c.get("email_enabled"),
            "drive_enabled": c.get("drive_enabled"),
            "coverage": c.get("coverage"),
            "next_run_at": c.get("next_run_at"),
        }
    return out


def _ctx_sops(supabase, client_id: str, today: date) -> Optional[dict]:
    """Loaded SOPs — titles only (the Action Plan/strategist consume the bodies)."""
    from services import sop_store

    rows = sop_store.list_sops(client_id)
    if not rows:
        return None
    return {
        "count": len(rows),
        "sops": [
            {
                "title": r.get("title"),
                "category": r.get("category"),
                "scope": "client" if r.get("client_id") else "agency",
            }
            for r in rows[:20]
        ],
    }


def _ctx_asana(supabase, client_id: str, today: date) -> Optional[dict]:
    """Asana setup — whether a project is mapped + the monthly task templates."""
    proj = (
        supabase.table("asana_client_projects")
        .select("project_gid")
        .eq("client_id", client_id)
        .limit(1)
        .execute()
    ).data
    templates = (
        supabase.table("asana_client_task_templates")
        .select("name, assignee_name, category_name")
        .eq("client_id", client_id)
        .eq("active", True)
        .order("sort_order")
        .limit(20)
        .execute()
    ).data or []
    if not (proj or templates):
        return None
    out: dict = {"project_mapped": bool(proj)}
    if templates:
        out["monthly_task_templates"] = templates
    return out


def _ctx_health(supabase, client_id: str, today: date) -> Optional[dict]:
    """Campaign health guards — freeze state, open response episodes, offpage alerts."""
    out: dict = {}
    try:
        from services import freeze

        fr = freeze.active_freeze(client_id)
        if fr:
            out["freeze"] = {
                "reason": fr.get("reason"),
                "since": fr.get("created_at"),
                "note": fr.get("note"),
            }
    except Exception:
        pass
    episodes = (
        supabase.table("response_episodes")
        .select("channel, keyword, classification, status, opened_at, last_checked_at")
        .eq("client_id", client_id)
        .in_("status", ["open", "escalated"])
        .order("opened_at", desc=True)
        .limit(10)
        .execute()
    ).data or []
    if episodes:
        out["response_episodes"] = episodes
    offpage = (
        supabase.table("offpage_alerts")
        .select("alert_type, message, from_rd, to_rd, delta_pct, triggered_on")
        .eq("client_id", client_id)
        .is_("resolved_at", "null")
        .execute()
    ).data or []
    if offpage:
        out["offpage_alerts"] = offpage
    return out or None


def _ctx_strategist(supabase, client_id: str, today: date) -> Optional[dict]:
    """Latest completed strategist review — assessment, proposals, open questions."""
    rows = (
        supabase.table("strategy_reviews")
        .select("assessment, proposals, questions, trigger, created_at")
        .eq("client_id", client_id)
        .eq("status", "complete")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    ).data
    if not rows:
        return None
    r = rows[0]
    return {
        "reviewed_at": r.get("created_at"),
        "trigger": r.get("trigger"),
        "assessment": (r.get("assessment") or "")[:1200] or None,
        "proposals": [
            {"title": p.get("title"), "status": p.get("status"), "requires": p.get("requires")}
            for p in (r.get("proposals") or [])[:8]
        ],
        "questions": (r.get("questions") or [])[:5],
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
    ("task_plan", _ctx_task_plan),
    ("citations", _ctx_citations),
    ("syndication", _ctx_syndication),
    ("reports", _ctx_reports),
    ("sops", _ctx_sops),
    ("asana", _ctx_asana),
    ("health", _ctx_health),
    ("strategist_review", _ctx_strategist),
    ("setup", _ctx_setup),
]


# ---------------------------------------------------------------------------
# Actions — SerMastr can trigger work (not just report). Anyone in the channel
# may trigger (product decision); paid/side-effecting actions are gated behind
# an explicit confirmation. Runners take (client_id, args) and return a reply
# string; they may be sync or async.
# ---------------------------------------------------------------------------
def match_open_tasks(tasks: list[dict], query: str) -> list[dict]:
    """Open tasks whose name matches the query. Pure.

    Case-insensitive; an exact name match wins outright (so "citations" can't
    be ambiguous with "citations — batch 2" when the user names one exactly),
    else substring matches. Completed tasks are never candidates."""
    q = (query or "").strip().casefold()
    if not q:
        return []
    open_tasks = [t for t in tasks if not t.get("completed")]
    exact = [t for t in open_tasks if (t.get("name") or "").strip().casefold() == q]
    if exact:
        return exact
    return [t for t in open_tasks if q in (t.get("name") or "").casefold()]


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


async def _stage_live_serp(client_id: str, args: dict) -> tuple[str, dict | str]:
    """Validate the keyword and name it in the confirm phrase."""
    keyword = (args.get("keyword") or "").strip()
    if not keyword:
        return (
            "reply",
            "Which keyword should I check? e.g. “check the live SERP for "
            "roof repair akron for Acme”.",
        )
    args["_confirm"] = f"run one live Google SERP check for *{keyword}*"
    return "confirm", args


async def _act_live_serp(client_id: str, args: Optional[dict] = None) -> str:
    """One live DataForSEO SERP pull: where the client's domain ranks right now."""
    from services import dataforseo_rank

    keyword = ((args or {}).get("keyword") or "").strip()
    supabase = get_supabase()
    rows = (
        supabase.table("clients")
        .select("website_url, gbp, rank_tracking_location_code")
        .eq("id", client_id)
        .limit(1)
        .execute()
    ).data
    if not rows:
        return "Client not found."
    c = rows[0]
    domain = dataforseo_rank.extract_domain(c.get("website_url") or "")
    if not domain:
        return "This client has no website URL on file — I can't identify their domain in the SERP."
    location_code = dataforseo_rank.location_code_for(c)
    try:
        urls = await dataforseo_rank.fetch_serp_rank_urls(keyword, domain, location_code)
    except Exception as exc:
        return f"Live SERP check failed: {exc}"
    if not urls:
        return (
            f"Live SERP for *{keyword}* (just checked): no page of {domain} in the "
            f"top {settings.dataforseo_serp_depth} organic results."
        )
    lines = "\n".join(f"  #{u['position']} — {u['url']}" for u in urls[:5])
    return f"Live SERP for *{keyword}* (just checked) — {domain} ranks:\n{lines}"


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
    # A right-now Google SERP read for one keyword — the on-demand freshness
    # escape hatch when the weekly tracked rank isn't recent enough.
    "check_live_serp": {
        "label": "run a live Google SERP check",
        "paid": True,
        "note": "one live DataForSEO SERP pull",
        "run": _act_live_serp,
        "stage": _stage_live_serp,
        "params": {
            "properties": {
                "keyword": {"type": "string", "description": "The exact search keyword to check the live Google results for."},
            },
            "required": ["keyword"],
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
# Live-data tools — answer-time reads, distinct from actions. fetch_live_gsc is
# free (Search Console API), so Claude may call it mid-answer with no confirm;
# paid live reads (DataForSEO) stay confirm-gated actions (`check_live_serp`).
# ---------------------------------------------------------------------------
_LIVE_GSC_ROUNDS = 2  # tool-use rounds before the answer is forced from what's fetched
_LIVE_GSC_TOP = 15  # rows surfaced per pull
_LIVE_GSC_RESULT_CHARS = 4000

_LIVE_GSC_TOOL = {
    "name": "fetch_live_gsc",
    "description": (
        "Pull LIVE Google Search Console data for this client's verified property "
        "(free — no confirmation needed). Use for current/latest search performance: "
        "top queries or pages by clicks/impressions, a specific keyword's or page's "
        "numbers, or daily totals. Fresher than the stored context (which is a daily "
        "ingest). Returns window totals plus the top rows."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "dimension": {
                "type": "string",
                "enum": ["query", "page", "date"],
                "description": "Group rows by search query, by page URL, or by day.",
            },
            "days": {
                "type": "integer",
                "description": "Lookback window in days (default 28, max 180).",
            },
            "search": {
                "type": "string",
                "description": "Optional case-insensitive substring filter on the dimension value (a keyword or URL fragment).",
            },
        },
        "required": ["dimension"],
    },
}


async def _run_live_gsc(client_id: str, args: dict) -> str:
    """Execute one live Search Console pull; returns a JSON summary string.

    Errors return an explanatory string (never raise) so Claude can tell the
    teammate why live data isn't available."""
    import asyncio

    from services import gsc_service, rank_materialize

    if not gsc_service.is_configured():
        return "Live GSC unavailable: the agency service-account key is not configured."
    prop = rank_materialize._verified_property(get_supabase(), client_id)
    if not prop:
        return (
            "Live GSC unavailable: no verified Search Console property for this "
            "client — connect one on the Rankings page."
        )
    dim = args.get("dimension") or "query"
    if dim not in ("query", "page", "date"):
        dim = "query"
    days = max(1, min(int(args.get("days") or 28), 180))
    end = date.today() - timedelta(days=2)  # GSC data lags ~2 days
    start = end - timedelta(days=days)
    try:
        rows = await asyncio.to_thread(
            gsc_service.fetch_search_analytics,
            prop["site_url"], [dim], start.isoformat(), end.isoformat(),
        )
    except Exception as exc:
        return f"Live GSC pull failed: {exc}"
    needle = (args.get("search") or "").strip().lower()
    if needle:
        rows = [r for r in rows if needle in str((r.get("keys") or [""])[0]).lower()]
    clicks = sum(int(r.get("clicks") or 0) for r in rows)
    impressions = sum(int(r.get("impressions") or 0) for r in rows)
    pos_num = sum(float(r.get("position") or 0) * int(r.get("impressions") or 0) for r in rows)
    top = sorted(rows, key=lambda r: (r.get("clicks") or 0, r.get("impressions") or 0), reverse=True)
    if dim == "date":
        top = sorted(rows, key=lambda r: (r.get("keys") or [""])[0])
    payload = {
        "property": prop["site_url"],
        "window": {"start": start.isoformat(), "end": end.isoformat(), "note": "GSC data lags ~2 days"},
        "dimension": dim,
        "filter": needle or None,
        "totals": {
            "rows": len(rows),
            "clicks": clicks,
            "impressions": impressions,
            "avg_position": round(pos_num / impressions, 1) if impressions else None,
        },
        "top_rows": [
            {
                dim: (r.get("keys") or [""])[0],
                "clicks": r.get("clicks"),
                "impressions": r.get("impressions"),
                "ctr": round(float(r.get("ctr") or 0), 4),
                "position": round(float(r.get("position") or 0), 1),
            }
            for r in top[:_LIVE_GSC_TOP]
        ],
    }
    return json.dumps(payload, default=str)[:_LIVE_GSC_RESULT_CHARS]


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
    ("text", answer). Claude sees the cross-module context + thread history, the
    action tools, and the free `fetch_live_gsc` tool — a live-GSC call is
    executed inline (bounded rounds) and folded back into the answer; an action
    call ⇒ ("action", …). `style="web"` swaps the Slack-mrkdwn voice for
    dashboard-chat Markdown.
    """
    import anthropic

    blocks = []
    if history:
        blocks.append("Conversation so far (oldest first):\n" + format_history(history))
    blocks.append(f"Latest message: {question}")
    blocks.append(f"Client data (JSON):\n{format_context(client, context)}")
    user = "\n\n".join(blocks)
    api = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, timeout=_LLM_TIMEOUT)
    messages: list[dict] = [{"role": "user", "content": user}]
    for round_no in range(_LIVE_GSC_ROUNDS + 1):
        # Last round withholds the live tool so the model must answer.
        tools = _ACTION_TOOLS + ([_LIVE_GSC_TOOL] if round_no < _LIVE_GSC_ROUNDS else [])
        resp = await api.messages.create(
            model=settings.slack_assistant_model,
            max_tokens=settings.slack_assistant_max_tokens,
            system=_SYSTEM + (_WEB_STYLE if style == "web" else ""),
            tools=tools,
            messages=messages,
        )
        for b in resp.content:
            if getattr(b, "type", None) == "tool_use" and b.name in _ACTIONS:
                return ("action", {"name": b.name, "args": dict(b.input or {})})
        live_calls = [
            b for b in resp.content
            if getattr(b, "type", None) == "tool_use" and b.name == _LIVE_GSC_TOOL["name"]
        ]
        if not live_calls:
            parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
            return ("text", "\n".join(parts).strip() or "I couldn't generate an answer just now — try rephrasing.")
        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for b in live_calls:
            out = await _run_live_gsc(client["id"], dict(b.input or {}))
            results.append({"type": "tool_result", "tool_use_id": b.id, "content": out})
        messages.append({"role": "user", "content": results})
    return ("text", "I couldn't generate an answer just now — try rephrasing.")


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
