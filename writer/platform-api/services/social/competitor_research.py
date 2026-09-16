"""Social Media P1 — competitor research engine (analyze-in-place; ADR-0002).

One ``social_competitor_research`` job per client scrapes each competitor's public
per-platform handle (``social_competitor_handles``) via Apify, then rolls the
public post/engagement/caption data up into a ``social_competitor_signals`` row per
``(client, competitor, platform)``:

  - **formats / cadence / top_performers** — deterministic from post metadata.
    ``top_performers`` keeps LINKS + numbers only (url, engagement, published_at,
    media_type) — never media, never author/commenter identity (ADR-0002 + minimise
    personal data).
  - **themes / hook_patterns / whats_working** — one LLM rollup over CAPTIONS ONLY
    (never video, owner c1). Our own Anthropic key — NOT metered against the social
    budget; only the Apify calls are metered (fail-closed, reserved before spending).

Research/observation keeps running under freeze (PRD §3) — this job is deliberately
NOT freeze-gated (matches ``competitor_intel``). The signals feed Angle proposals
(``creator.propose_angles``) and future generator prompts.

Pure helpers are unit-tested; the Apify/LLM/DB work is the thin impure layer.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException

from config import settings
from services.social import apify, budget

logger = logging.getLogger(__name__)


def _sb():
    from db.supabase_client import get_supabase

    return get_supabase()


def research_gate_open() -> bool:
    """The module + P1 feature are on AND an Apify token is present. Pure over
    settings — the single gate for the scheduler sweep + on-demand trigger."""
    return bool(
        settings.social_enabled
        and settings.social_competitor_research_enabled
        and (settings.apify_api_token or "").strip()
    )


# ── pure aggregation helpers (unit-tested) ────────────────────────────────────

def engagement_of(post: dict) -> int:
    """Total public engagement for a post: likes + comments + shares. Views are
    kept separately (they inflate video-heavy feeds and aren't comparable across
    formats). Pure."""
    return int(post.get("likes", 0)) + int(post.get("comments", 0)) + int(post.get("shares", 0))


def aggregate_formats(posts: list[dict]) -> dict:
    """Format mix + the dominant format across a competitor's posts. Pure."""
    counts = {"image": 0, "video": 0, "carousel": 0, "unknown": 0}
    for p in posts or []:
        mt = str(p.get("media_type") or "unknown")
        counts[mt if mt in counts else "unknown"] += 1
    ranked = {k: v for k, v in counts.items() if k != "unknown" and v}
    dominant = max(ranked, key=ranked.get) if ranked else None
    return {**counts, "dominant": dominant}


def aggregate_cadence(posts: list[dict], now: Optional[datetime] = None) -> dict:
    """Posting cadence from the posts' timestamps: how many carried a parseable
    date, the span they cover, and posts-per-week over that span. Pure. Returns
    per_week=None when fewer than two dated posts (can't infer a rate)."""
    dates: list[datetime] = []
    for p in posts or []:
        ts = p.get("published_at")
        if not ts:
            continue
        try:
            dates.append(datetime.fromisoformat(str(ts).replace("Z", "+00:00")))
        except (TypeError, ValueError):
            continue
    dated = len(dates)
    if dated < 2:
        return {"posts": len(posts or []), "dated_posts": dated, "span_days": None, "per_week": None}
    dates.sort()
    span_days = (dates[-1] - dates[0]).days
    if span_days <= 0:
        # All within a day — report the burst rather than dividing by zero.
        return {"posts": len(posts or []), "dated_posts": dated, "span_days": 0, "per_week": None}
    per_week = round(dated / (span_days / 7.0), 2)
    return {"posts": len(posts or []), "dated_posts": dated, "span_days": span_days, "per_week": per_week}


def top_performers(posts: list[dict], n: int) -> list[dict]:
    """Top-N posts by engagement, as LINKS + numbers only — no caption text, no
    author/commenter identity (ADR-0002 + minimise personal data). Pure."""
    # Drop url-less rows BEFORE ranking so a link-less row can't consume a slot
    # (top_performers keeps links — a row with no url is useless here).
    ranked = sorted((p for p in (posts or []) if p.get("url")), key=engagement_of, reverse=True)
    out: list[dict] = []
    for p in ranked[: max(0, int(n))]:
        out.append({
            "url": p["url"],
            "engagement": engagement_of(p),
            "likes": int(p.get("likes", 0)),
            "comments": int(p.get("comments", 0)),
            "shares": int(p.get("shares", 0)),
            "views": int(p.get("views", 0)),
            "published_at": p.get("published_at"),
            "media_type": p.get("media_type"),
        })
    return out


def captions_for_rollup(posts: list[dict], cap: int, per_caption_chars: int = 400) -> list[str]:
    """Non-empty captions (bounded count + per-caption length) for the LLM rollup.
    Ordered by engagement so the strongest posts lead. Pure."""
    ranked = sorted(posts or [], key=engagement_of, reverse=True)
    out: list[str] = []
    for p in ranked:
        c = (p.get("caption") or "").strip()
        if not c:
            continue
        out.append(c[: max(1, per_caption_chars)])
        if len(out) >= max(1, int(cap)):
            break
    return out


def _str_list(raw, cap: int = 6, item_chars: int = 60) -> list[str]:
    out: list[str] = []
    for x in raw or []:
        s = (str(x) if x is not None else "").strip()
        if s:
            out.append(s[:item_chars])
        if len(out) >= cap:
            break
    return out


def sanitize_rollup(raw: Optional[dict]) -> dict:
    """Clean the LLM rollup into {themes, hook_patterns, whats_working}. Pure —
    tolerates a missing/partial/garbage response (→ empties)."""
    raw = raw or {}
    return {
        "themes": _str_list(raw.get("themes")),
        "hook_patterns": _str_list(raw.get("hook_patterns")),
        "whats_working": (str(raw.get("whats_working") or "").strip()[:1200]),
    }


def build_signal_row(
    client_id: str,
    competitor_id: Optional[str],
    platform: str,
    posts: list[dict],
    rollup: Optional[dict] = None,
    now: Optional[datetime] = None,
) -> dict:
    """Assemble a ``social_competitor_signals`` insert row from normalized posts +
    the (best-effort) LLM rollup. status='insufficient_data' when no posts. Pure."""
    r = sanitize_rollup(rollup)
    has_posts = bool(posts)
    ts = (now or datetime.now(timezone.utc)).isoformat()
    return {
        "client_id": client_id,
        "competitor_id": competitor_id,
        "platform": (platform or "").lower(),
        "themes": r["themes"],
        "formats": aggregate_formats(posts),
        "hook_patterns": r["hook_patterns"],
        "cadence": aggregate_cadence(posts, now),
        "top_performers": top_performers(posts, settings.social_competitor_top_performers),
        "whats_working": r["whats_working"] or None,
        "status": "ok" if has_posts else "insufficient_data",
        "captured_at": ts,
    }


def select_signals_for_angles(signals: list[dict], cap: int) -> list[dict]:
    """Latest signal per (competitor, platform), most-recent first, capped. Drops
    insufficient_data rows (nothing to ground on). Pure."""
    best: dict[tuple, dict] = {}
    for s in signals or []:
        if s.get("status") == "insufficient_data":
            continue
        key = (s.get("competitor_id"), (s.get("platform") or "").lower())
        prev = best.get(key)
        if prev is None or (s.get("captured_at") or "") > (prev.get("captured_at") or ""):
            best[key] = s
    ordered = sorted(best.values(), key=lambda s: s.get("captured_at") or "", reverse=True)
    return ordered[: max(0, int(cap))]


def render_competitor_signals_block(signals: list[dict], cap: Optional[int] = None) -> str:
    """A compact grounding block for the angle-proposal prompt. Empty string when
    there are no usable signals (→ prompt is byte-identical to today). Pure."""
    cap = int(cap if cap is not None else settings.social_competitor_angle_signal_cap)
    chosen = select_signals_for_angles(signals, cap)
    if not chosen:
        return ""
    lines = [
        "RELEVANT COMPETITOR SIGNALS (public research — for inspiration only; "
        "transform, never copy a competitor's post):"
    ]
    for s in chosen:
        name = s.get("competitor_name") or "A competitor"
        platform = (s.get("platform") or "").lower()
        themes = ", ".join(s.get("themes") or []) or "—"
        hooks = ", ".join(s.get("hook_patterns") or []) or "—"
        parts = [f"- {name} on {platform}: themes: {themes}; hooks: {hooks}."]
        ww = (s.get("whats_working") or "").strip()
        if ww:
            parts.append(f" What's working: {ww[:280]}")
        lines.append("".join(parts))
    return "\n".join(lines)


# ── LLM rollup (impure, best-effort, NOT budget-metered) ──────────────────────

_ROLLUP_SYSTEM = (
    "You are a social media competitive analyst. Given a competitor's recent PUBLIC "
    "post captions/titles on one platform plus aggregate stats, identify: the dominant "
    "content THEMES, the recurring HOOK/opening patterns, and a short 'what's working' "
    "summary. Base everything ONLY on the text provided — you have NOT seen any image "
    "or video content, so never describe visuals or invent metrics. Themes and "
    "hook_patterns are concise phrases (2–6 words), at most 6 of each. whats_working "
    "is 1–3 plain sentences about the patterns behind the higher-engagement posts."
)

_ROLLUP_SCHEMA = {
    "type": "object",
    "properties": {
        "themes": {"type": "array", "items": {"type": "string"},
                   "description": "Dominant content themes (2–6 words each)."},
        "hook_patterns": {"type": "array", "items": {"type": "string"},
                          "description": "Recurring opening/hook patterns (2–6 words each)."},
        "whats_working": {"type": "string", "description": "1–3 sentences on what's working."},
    },
    "required": ["themes", "hook_patterns", "whats_working"],
}


def build_rollup_prompt(platform: str, captions: list[str], formats: dict, cadence: dict) -> str:
    """Assemble the rollup user prompt from captions + deterministic aggregates. Pure."""
    lines = [
        f"Platform: {platform}.",
        f"Format mix: {formats}.",
        f"Posting cadence: {cadence}.",
        "",
        "Recent post captions/titles (highest-engagement first):",
    ]
    for i, c in enumerate(captions, 1):
        lines.append(f"{i}. {c}")
    return "\n".join(lines)


async def run_signal_rollup(platform: str, captions: list[str], formats: dict, cadence: dict) -> dict:
    """One caption-only LLM rollup → {themes, hook_patterns, whats_working}.
    Best-effort: any failure (or no captions) returns empties, so the signal still
    stores its deterministic aggregates. Uses our own Anthropic key — NOT metered."""
    if not captions:
        return sanitize_rollup(None)
    from services import report_llm

    try:
        out = await report_llm.run_forced_tool(
            provider="anthropic", model=settings.social_competitor_signal_model,
            system=_ROLLUP_SYSTEM,
            user=build_rollup_prompt(platform, captions, formats, cadence),
            tool_name="emit_signal", tool_description="Return the competitor content signal.",
            input_schema=_ROLLUP_SCHEMA, max_tokens=int(settings.social_competitor_signal_max_tokens),
            log_tag="social_competitor_signal",
        )
    except Exception as exc:  # noqa: BLE001 — rollup is best-effort
        logger.info("social.signal_rollup_failed",
                    extra={"platform": platform, "error": str(getattr(exc, "detail", exc))[:200]})
        return sanitize_rollup(None)
    return sanitize_rollup(out)


# ── handle + signal CRUD (impure) ─────────────────────────────────────────────

def _assert_enabled() -> None:
    if not settings.social_enabled:
        raise HTTPException(status_code=503, detail="social_not_enabled")


def _competitor_for_client(competitor_id: str, client_id: str) -> dict:
    rows = (
        _sb().table("client_competitors").select("id, client_id, name")
        .eq("id", competitor_id).limit(1).execute()
    ).data or []
    if not rows or str(rows[0]["client_id"]) != str(client_id):
        raise HTTPException(status_code=404, detail="social_competitor_not_found")
    return rows[0]


def list_competitors_with_handles(client_id: str) -> list[dict]:
    """Active competitors for a client, each with its per-platform social handles.
    Drives the Competitors tab."""
    _assert_enabled()
    sb = _sb()
    comps = (
        sb.table("client_competitors").select("id, name, domain, active")
        .eq("client_id", client_id).eq("active", True).order("name").execute()
    ).data or []
    if not comps:
        return []
    ids = [c["id"] for c in comps]
    handles = (
        sb.table("social_competitor_handles").select("id, competitor_id, platform, handle")
        .in_("competitor_id", ids).execute()
    ).data or []
    by_comp: dict[str, list[dict]] = {}
    for h in handles:
        by_comp.setdefault(h["competitor_id"], []).append(h)
    for c in comps:
        c["handles"] = by_comp.get(c["id"], [])
    return comps


def add_handle(client_id: str, competitor_id: str, platform: str, handle: str) -> dict:
    """Add a per-platform handle to one of the client's competitors (idempotent on
    the (competitor, platform, handle) unique index)."""
    _assert_enabled()
    pl = (platform or "").lower().strip()
    if pl not in apify.SUPPORTED_PLATFORMS:
        raise HTTPException(status_code=422, detail="social_platform_unsupported:" + (pl or "?"))
    h = apify.normalize_handle(handle)
    if not h:
        raise HTTPException(status_code=422, detail="social_handle_required")
    _competitor_for_client(competitor_id, client_id)
    try:
        row = (
            _sb().table("social_competitor_handles")
            .upsert({"competitor_id": competitor_id, "platform": pl, "handle": h},
                    on_conflict="competitor_id,platform,handle")
            .execute()
        ).data
    except Exception as exc:  # noqa: BLE001
        logger.warning("social.add_handle_failed", extra={"error": str(exc)[:200]})
        raise HTTPException(status_code=502, detail="social_handle_add_failed") from exc
    return (row[0] if row else {"competitor_id": competitor_id, "platform": pl, "handle": h})


def delete_handle(client_id: str, handle_id: str) -> dict:
    """Remove a competitor handle (verifying it belongs to the client's competitor)."""
    _assert_enabled()
    sb = _sb()
    rows = (
        sb.table("social_competitor_handles").select("id, competitor_id")
        .eq("id", handle_id).limit(1).execute()
    ).data or []
    if not rows:
        raise HTTPException(status_code=404, detail="social_handle_not_found")
    _competitor_for_client(rows[0]["competitor_id"], client_id)
    sb.table("social_competitor_handles").delete().eq("id", handle_id).execute()
    return {"ok": True}


def list_signals(client_id: str, limit: int = 100) -> list[dict]:
    """Stored competitor signals for a client, most-recent first, enriched with the
    competitor name."""
    _assert_enabled()
    return _signals_with_names(client_id, limit)


def _signals_with_names(client_id: str, limit: int) -> list[dict]:
    sb = _sb()
    signals = (
        sb.table("social_competitor_signals").select("*")
        .eq("client_id", client_id).order("captured_at", desc=True).limit(limit).execute()
    ).data or []
    if not signals:
        return []
    comp_ids = [s["competitor_id"] for s in signals if s.get("competitor_id")]
    names: dict[str, str] = {}
    if comp_ids:
        for c in (
            sb.table("client_competitors").select("id, name")
            .in_("id", list(set(comp_ids))).execute()
        ).data or []:
            names[c["id"]] = c.get("name")
    for s in signals:
        s["competitor_name"] = names.get(s.get("competitor_id"))
    return signals


def latest_signals_for_client(client_id: str, cap: Optional[int] = None) -> list[dict]:
    """The most recent usable signals for angle grounding (best-effort — never
    raises; an empty list means no grounding). Enriched with competitor names."""
    try:
        cap_n = int(cap if cap is not None else settings.social_competitor_angle_signal_cap)
        # Pull a few per (competitor, platform) then let select_signals_for_angles
        # pick the latest of each; 4x the cap is a generous read bound.
        return select_signals_for_angles(_signals_with_names(client_id, max(cap_n * 4, 20)), cap_n)
    except Exception as exc:  # noqa: BLE001 — grounding is best-effort
        logger.info("social.latest_signals_failed", extra={"client_id": client_id, "error": str(exc)[:160]})
        return []


# ── enqueue + job + scheduler (impure) ────────────────────────────────────────

def enqueue_social_competitor_research(client_id: str, user_id: Optional[str] = None) -> dict:
    """Enqueue one research job for a client. Requires the P1 gate open. Deduped
    against an in-flight job for the same client."""
    if not research_gate_open():
        raise HTTPException(status_code=503, detail="social_competitor_research_disabled")
    sb = _sb()
    existing = (
        sb.table("async_jobs").select("id")
        .eq("job_type", "social_competitor_research").eq("entity_id", client_id)
        .in_("status", ["pending", "running"]).limit(1).execute()
    ).data or []
    if existing:
        return {"job_id": existing[0]["id"], "already_running": True}
    job = (
        sb.table("async_jobs").insert({
            "job_type": "social_competitor_research", "entity_id": client_id,
            "payload": {"client_id": client_id, "user_id": user_id},
        }).execute()
    ).data[0]
    return {"job_id": job["id"], "already_running": False}


def get_research_job(job_id: str) -> dict:
    rows = (
        _sb().table("async_jobs").select("id, status, result, error")
        .eq("id", job_id).limit(1).execute()
    ).data or []
    if not rows:
        raise HTTPException(status_code=404, detail="social_job_not_found")
    return rows[0]


async def run_competitor_research_job(job: dict) -> None:
    """Handler for job_type='social_competitor_research'. For each competitor
    handle: reserve budget (fail-closed) → scrape via Apify → aggregate + caption
    rollup → upsert one signal row. Best-effort per handle (one failure never aborts
    the run). NOT freeze-gated — research keeps running under freeze (PRD §3).
    Settles its own job row."""
    import asyncio

    from services import notifications

    payload = job.get("payload") or {}
    client_id = payload.get("client_id")
    sb = _sb()

    def _settle(status: str, **fields) -> None:
        sb.table("async_jobs").update(
            {"status": status, "completed_at": "now()", **fields}
        ).eq("id", job["id"]).execute()

    if not client_id:
        _settle("failed", error="missing_client_id")
        return

    try:
        competitors = list_competitors_with_handles(client_id)
    except Exception as exc:  # noqa: BLE001
        _settle("failed", error=str(getattr(exc, "detail", exc))[:500])
        return

    # Flatten to (competitor, platform, handle) targets.
    targets = [
        (c, h["platform"], h["handle"])
        for c in competitors for h in (c.get("handles") or [])
    ]
    if not targets:
        _settle("complete", result={"signals": 0, "note": "no_handles"})
        return

    cap = budget.ceiling_for_client(client_id)
    run_cost = float(settings.social_apify_run_cost_usd)
    signals_written = 0
    skipped: list[str] = []
    budget_hit = False

    for comp, platform, handle in targets:
        pl = (platform or "").lower()
        if not apify.actor_for_platform(pl):
            skipped.append(f"{pl}:no_actor")
            continue
        # Fail-closed reserve BEFORE the paid Apify run. A refused reservation means
        # the monthly ceiling is reached — stop (further reserves would also fail).
        # Not refunded on Apify failure: a partial run can still incur compute cost,
        # so leaving the estimate charged errs toward the cap (never over it).
        if not budget.reserve(client_id, run_cost, cap=cap):
            budget_hit = True
            break
        try:
            posts = await asyncio.to_thread(apify.scrape_handle, pl, handle)
        except apify.ApifyError as exc:
            logger.info("social.research_scrape_failed",
                        extra={"platform": pl, "error": str(exc)[:160]})
            _upsert_signal(build_signal_row(client_id, comp["id"], pl, [], None))
            skipped.append(f"{pl}:scrape_failed")
            continue
        except Exception as exc:  # noqa: BLE001 — one handle never aborts the run
            logger.warning("social.research_handle_error",
                           extra={"platform": pl, "error": str(exc)[:200]})
            skipped.append(f"{pl}:error")
            continue

        rollup = {}
        if posts:
            rollup = await run_signal_rollup(
                pl,
                captions_for_rollup(posts, settings.social_competitor_signal_caption_cap),
                aggregate_formats(posts), aggregate_cadence(posts),
            )
        _upsert_signal(build_signal_row(client_id, comp["id"], pl, posts, rollup))
        signals_written += 1

    result = {"signals": signals_written}
    if skipped:
        result["skipped"] = skipped
    if budget_hit:
        result["budget_exceeded"] = True
    _settle("complete", result=result)

    if signals_written:
        notifications.emit(
            client_id, "social_competitor_signals_ready", "Competitor signals refreshed",
            summary=f"{signals_written} competitor signal(s) captured for angle ideas.",
            severity="info",
            dedupe_key=f"social_competitor_signals:{client_id}:{datetime.now(timezone.utc):%Y-%m-%d}",
        )


def _upsert_signal(row: dict) -> None:
    """Write one signal row (best-effort — a write failure logs, never aborts the run)."""
    try:
        _sb().table("social_competitor_signals").insert(row).execute()
    except Exception as exc:  # noqa: BLE001
        logger.warning("social.signal_write_failed",
                       extra={"platform": row.get("platform"), "error": str(exc)[:200]})


def enqueue_due_social_competitor_research() -> int:
    """Weekly due-check (daily tick): enqueue one job per client that has ≥1
    competitor handle and whose latest signal is older than the interval (or none).
    No-op unless the P1 gate is open."""
    if not research_gate_open():
        return 0
    sb = _sb()
    cutoff = datetime.now(timezone.utc) - timedelta(
        days=settings.social_competitor_research_interval_days
    )
    try:
        handles = (
            sb.table("social_competitor_handles").select("competitor_id").execute()
        ).data or []
        comp_ids = list({h["competitor_id"] for h in handles})
        if not comp_ids:
            return 0
        # competitor_id → client_id (only active competitors).
        client_of: dict[str, str] = {}
        for c in (
            sb.table("client_competitors").select("id, client_id, active")
            .in_("id", comp_ids).execute()
        ).data or []:
            if c.get("active", True):
                client_of[c["id"]] = c["client_id"]
        clients_with_handles = set(client_of.values())
        if not clients_with_handles:
            return 0
        # Latest signal captured_at per client.
        latest: dict[str, str] = {}
        for s in (
            sb.table("social_competitor_signals").select("client_id, captured_at")
            .in_("client_id", list(clients_with_handles))
            .order("captured_at", desc=True).execute()
        ).data or []:
            cid = s["client_id"]
            if cid not in latest:  # first seen == most recent (ordered desc)
                latest[cid] = s.get("captured_at")
        due = {
            cid for cid in clients_with_handles
            if cid not in latest or not latest[cid]
            or datetime.fromisoformat(latest[cid].replace("Z", "+00:00")) <= cutoff
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("social.research_due_check_failed", extra={"error": str(exc)})
        return 0
    if not due:
        return 0
    try:
        pending = {
            r["entity_id"] for r in (
                sb.table("async_jobs").select("entity_id")
                .eq("job_type", "social_competitor_research")
                .in_("status", ["pending", "running"]).execute()
            ).data or []
        }
    except Exception:  # noqa: BLE001
        pending = set()
    count = 0
    for cid in due - pending:
        try:
            enqueue_social_competitor_research(cid)
            count += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("social.research_enqueue_failed",
                           extra={"client_id": cid, "error": str(exc)[:160]})
    if count:
        logger.info("social.research_enqueued", extra={"count": count})
    return count
