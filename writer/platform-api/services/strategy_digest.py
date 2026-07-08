"""Strategy digest assembler — SerMaStr Phase 0 (docs/modules/
seo-strategist-agent-plan-v1_0.md §2/§2b).

``build_strategy_digest(client_id)`` produces the token-budgeted, pre-digested
context ONE strategist run reasons over. The strategist never reads raw tables;
this module normalizes everything the deterministic layer already produces into
three legibility mechanisms (spec §2b):

  1. **Standard signal envelope** — every module's headline metric becomes
     ``{module, keyword, metric, value, baseline, delta, direction, status,
     coverage, measured_at, cadence_days, stale}``. ``status`` is computed
     HERE, deterministically — the LLM never does trend arithmetic.
  2. **The keyword passport** — signals grouped by keyword, not module, so the
     cross-channel join (organic × maps × AI answers × episodes) is free.
  3. **Explicit staleness** — each envelope carries ``measured_at`` + the
     expected cadence; violations are flagged so the strategist can't reason
     confidently over dead data.

Split, per repo convention: envelope/status/staleness/passport/trim helpers are
pure (unit-tested, no DB); ``build_strategy_digest`` does the reads through an
isolated provider registry (one failing module never breaks the digest —
the slack_assistant pattern).
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from config import settings
from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

# A signal is stale when its age exceeds cadence × this grace factor
# (spec example: a 19-day-old grid scan on a weekly cadence → stale).
STALE_GRACE = 2.0

# Direction constants (envelope field values — spelled out, never inferred).
LOWER_IS_BETTER = "lower_is_better"    # rank positions
HIGHER_IS_BETTER = "higher_is_better"  # visibility %, coverage %

# Bounds that keep the digest inside the token budget before trimming.
MAX_PASSPORT_KEYWORDS = 40
MAX_PLAN_ITEMS = 15
MAX_EPISODES = 15
MAX_ALERTS = 15
MAX_TASKS = 20
# Review-count threshold from the Recipe Engine SOP (reviews funded to 25 first).
REVIEW_THRESHOLD = 25


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Pure helpers (unit-tested)
# ─────────────────────────────────────────────────────────────────────────────
def compute_status(
    value: Optional[float],
    baseline: Optional[float],
    direction: str,
    min_delta: float,
) -> str:
    """Deterministic trend status for an envelope. Pure.

    ``improving`` / ``declining`` only when the move clears ``min_delta`` in the
    metric's own units (noise floor); otherwise ``stable``. Either side missing
    → ``insufficient_data`` — never guessed.
    """
    if value is None or baseline is None:
        return "insufficient_data"
    delta = float(value) - float(baseline)
    if abs(delta) < min_delta:
        return "stable"
    better = delta < 0 if direction == LOWER_IS_BETTER else delta > 0
    return "improving" if better else "declining"


def staleness(measured_at, cadence_days: Optional[float], now: datetime) -> tuple[bool, Optional[int]]:
    """(stale?, age_days) for a signal. Pure. Unknown timestamp → stale with
    unknown age (can't be trusted); no cadence → never stale."""
    ts = _parse_ts(measured_at)
    if ts is None:
        return True, None
    age_days = (now - ts).days
    if not cadence_days:
        return False, age_days
    return age_days > cadence_days * STALE_GRACE, age_days


def make_envelope(
    *,
    module: str,
    keyword: Optional[str],
    metric: str,
    value,
    baseline=None,
    direction: str,
    coverage: Optional[str] = None,
    measured_at=None,
    cadence_days: Optional[float] = None,
    min_delta: float = 0.0,
    now: Optional[datetime] = None,
    status: Optional[str] = None,
) -> dict:
    """One standard signal envelope. Pure. ``status`` may be passed pre-computed
    (when a module already has deterministic trend logic — e.g. the rank
    tracker's direction) — otherwise it's derived from value vs baseline."""
    now = now or _now()
    stale, age_days = staleness(measured_at, cadence_days, now)
    delta = None
    if isinstance(value, (int, float)) and isinstance(baseline, (int, float)):
        delta = round(float(value) - float(baseline), 2)
    return {
        "module": module,
        "keyword": keyword,
        "metric": metric,
        "value": value,
        "baseline": baseline,
        "delta": delta,
        "direction": direction,
        "status": status or compute_status(
            value if isinstance(value, (int, float)) else None,
            baseline if isinstance(baseline, (int, float)) else None,
            direction, min_delta,
        ),
        "coverage": coverage,
        "measured_at": str(measured_at) if measured_at else None,
        "age_days": age_days,
        "cadence_days": cadence_days,
        "stale": stale,
    }


def staleness_flags(envelopes: list[dict]) -> list[str]:
    """Human-readable staleness violations for the digest header. Pure."""
    flags: list[str] = []
    for e in envelopes:
        if not e.get("stale"):
            continue
        kw = f" '{e['keyword']}'" if e.get("keyword") else ""
        if e.get("age_days") is None:
            flags.append(f"{e['module']}{kw}: no timestamp on the last measurement — treat as unmeasured.")
        else:
            flags.append(
                f"{e['module']}{kw}: last measured {e['age_days']} days ago on a "
                f"~{int(e['cadence_days'] or 0)}-day cadence — STALE, do not treat as current."
            )
    return flags


def _norm_kw(keyword: Optional[str]) -> str:
    return (keyword or "").strip().lower()


def build_keyword_passports(
    envelopes: list[dict],
    episodes: list[dict],
    alerts: list[dict],
    max_keywords: int = MAX_PASSPORT_KEYWORDS,
) -> list[dict]:
    """Group per-keyword signals across channels into passports. Pure.

    One entry per keyword: every module's envelope side by side, plus its open
    episodes and alerts. Keywords with an open alert/episode or any non-stable
    status sort first (they're what the strategist is for)."""
    by_kw: dict[str, dict] = {}

    def _entry(keyword: str) -> dict:
        key = _norm_kw(keyword)
        if key not in by_kw:
            by_kw[key] = {"keyword": keyword, "signals": [], "episodes": [], "alerts": []}
        return by_kw[key]

    for e in envelopes:
        if e.get("keyword"):
            _entry(e["keyword"])["signals"].append(e)
    for ep in episodes:
        if ep.get("keyword"):
            _entry(ep["keyword"])["episodes"].append(ep)
    for a in alerts:
        if a.get("keyword"):
            _entry(a["keyword"])["alerts"].append(a)

    def _urgency(p: dict) -> tuple:
        has_alert = bool(p["alerts"]) or bool(p["episodes"])
        declining = sum(1 for s in p["signals"] if s.get("status") == "declining")
        return (has_alert, declining, len(p["signals"]))

    passports = sorted(by_kw.values(), key=_urgency, reverse=True)
    return passports[:max_keywords]


def active_signal_domains(digest: dict) -> set[str]:
    """Which signal domains are 'active' for this client — drives both the SOP
    selection (sop_library.select_sops_text) and the weekly scheduler's
    'active-signal clients only' gate. Pure."""
    domains: set[str] = set()
    alerts = digest.get("open_alerts") or {}
    if alerts.get("rank") or any(
        (e.get("channel") == "organic") for e in digest.get("episodes") or []
    ):
        domains.add("organic_drop")
    if alerts.get("maps") or any(
        (e.get("channel") == "maps") for e in digest.get("episodes") or []
    ):
        domains.add("maps")
    if alerts.get("offpage"):
        domains.add("offpage")
    labs = digest.get("ai_visibility") or {}
    if labs.get("invisible_keywords") or any(
        s.get("status") == "declining" for s in labs.get("envelopes") or []
    ):
        domains.add("ai_visibility")
    plan = digest.get("action_plan") or {}
    if any(
        i.get("kind") in ("quick_win", "opportunity", "content_gap", "cannibalization")
        for i in plan.get("items") or []
    ):
        domains.add("content")
    task_plan = digest.get("task_plan") or {}
    if task_plan.get("flags") or (digest.get("client") or {}).get("retainer_monthly"):
        domains.add("budget")
    return domains


def has_active_signals(digest: dict) -> bool:
    """The weekly gate: schedule a strategist run only when something is
    actually open (alerts / episodes / task-plan flags). Pure."""
    alerts = digest.get("open_alerts") or {}
    return bool(
        alerts.get("rank")
        or alerts.get("maps")
        or alerts.get("offpage")
        or digest.get("episodes")
        or (digest.get("task_plan") or {}).get("flags")
    )


def render_digest(digest: dict, budget_chars: int) -> str:
    """Compact JSON for the strategist prompt, trimmed to a character budget.
    Pure. Trims the biggest repeated lists first (passports, then plan items),
    and only hard-truncates as a last resort (flagged in the output)."""
    def _dump(d: dict) -> str:
        return json.dumps(d, default=str, ensure_ascii=False)

    out = _dump(digest)
    if len(out) <= budget_chars:
        return out
    for kw_cap, item_cap in ((25, 10), (15, 8), (8, 5)):
        d = dict(digest)
        if d.get("keyword_passports"):
            d["keyword_passports"] = d["keyword_passports"][:kw_cap]
        if (d.get("action_plan") or {}).get("items"):
            plan = dict(d["action_plan"])
            plan["items"] = plan["items"][:item_cap]
            d["action_plan"] = plan
        d["trimmed_to_fit_budget"] = True
        out = _dump(d)
        if len(out) <= budget_chars:
            return out
    return out[:budget_chars] + '… TRUNCATED_TO_BUDGET"}'


# ─────────────────────────────────────────────────────────────────────────────
# Providers (DB reads — each isolated; a failure yields None for that section)
# ─────────────────────────────────────────────────────────────────────────────
def _prov_client(supabase, client_id: str, today: date, now: datetime) -> Optional[dict]:
    from services import freeze, icp_service
    from services.slack_assistant import is_local_client

    rows = (
        supabase.table("clients")
        .select(
            "name, website_url, gbp, brand_voice, detected_icp, differentiators, "
            "icp_text, target_cities, retainer_monthly, is_sab, client_type, "
            "business_location"
        )
        .eq("id", client_id).limit(1).execute()
    ).data
    if not rows:
        return None
    c = rows[0]
    gbp = c.get("gbp") or {}
    review_count = gbp.get("gbp_review_count")
    icp = icp_service.resolve_icp_text(c) or ""
    # Local-only settings (target cities) read "n/a" for a non-local client so
    # the strategist never proposes fixing an empty list that is correct.
    local = is_local_client(c)
    if not local:
        # NOT head=True: the pinned postgrest discards the count on HEAD
        # responses (always reads 0); limit(1) keeps the transfer to one row.
        pages = (
            supabase.table("local_seo_pages")
            .select("id", count="exact")
            .eq("client_id", client_id)
            .is_("deleted_at", "null")
            .limit(1)
            .execute()
        ).count or 0
        scans = (
            supabase.table("maps_scans")
            .select("id", count="exact")
            .eq("client_id", client_id)
            .limit(1)
            .execute()
        ).count or 0
        local = is_local_client(c, pages, scans)
    out = {
        "name": c.get("name"),
        "website": c.get("website_url"),
        "client_type": c.get("client_type") or "local",
        "is_sab": bool(c.get("is_sab")),
        "retainer_monthly": c.get("retainer_monthly"),
        "local_campaign": local,
        "target_cities": (c.get("target_cities") or [])[:12]
        if local
        else "n/a — no local campaign; suburb-level targeting does not apply",
        "gbp": {
            "business_name": gbp.get("business_name"),
            "address": gbp.get("address"),
            "latitude": gbp.get("latitude"),
            "longitude": gbp.get("longitude"),
            "phone": gbp.get("phone"),
            "google_maps_uri": gbp.get("google_maps_uri"),
            "category": gbp.get("gbp_category"),
            "categories": (gbp.get("gbp_categories") or [])[:6],
            "rating": gbp.get("gbp_rating"),
            "review_count": review_count,
            "reviews_vs_threshold": (
                f"{review_count}/{REVIEW_THRESHOLD} (below the funding threshold)"
                if isinstance(review_count, (int, float)) and review_count < REVIEW_THRESHOLD
                else f"{review_count} (threshold {REVIEW_THRESHOLD} met)"
                if isinstance(review_count, (int, float))
                else "unknown"
            ),
            "service_area_places": (gbp.get("service_area_places") or [])[:10],
            "address_hidden": gbp.get("address_hidden"),
        } if gbp else None,
        "icp_summary": icp[:1500] or None,
        "frozen": False,
    }
    try:
        fr = freeze.active_freeze(client_id)
        if fr:
            out["frozen"] = True
            out["freeze"] = {"reason": fr.get("reason"), "since": fr.get("created_at"), "note": fr.get("note")}
    except Exception:
        pass
    return out


def _prov_organic(supabase, client_id: str, today: date, now: datetime) -> Optional[dict]:
    from services import rank_status

    kws = (
        supabase.table("tracked_keywords")
        .select("id, keyword")
        .eq("client_id", client_id).eq("active", True)
        .order("keyword").limit(MAX_PASSPORT_KEYWORDS)
        .execute()
    ).data or []
    if not kws:
        return None
    kw_ids = [k["id"] for k in kws]
    cutoff = date.fromordinal(today.toordinal() - 90).isoformat()
    metrics: dict[str, list[dict]] = {}
    for r in (
        supabase.table("rank_keyword_metrics")
        .select("keyword_id, date, gsc_position, tracked_rank, clicks, impressions")
        .in_("keyword_id", kw_ids).gte("date", cutoff).execute()
    ).data or []:
        metrics.setdefault(r["keyword_id"], []).append(r)

    envelopes: list[dict] = []
    for k in kws:
        rows = metrics.get(k["id"], [])
        s = rank_status.compute_keyword_summary(rows, today, settings.rank_gsc_coverage_days)
        source = s.get("primary_source")
        # The rank tracker's own deterministic trend read ("up" = improving).
        status_map = {"up": "improving", "down": "declining", "flat": "stable"}
        value = s.get("avg_7") if source == "gsc" else s.get("today_rank")
        latest_date = max((r.get("date") for r in rows if r.get("date")), default=None)
        envelopes.append(
            make_envelope(
                module="organic_rank",
                keyword=k["keyword"],
                metric="position",
                value=value,
                baseline=s.get("avg_30"),
                direction=LOWER_IS_BETTER,
                coverage=(
                    f"GSC impressions-weighted, {s.get('impressions_30d', 0)} impressions/30d"
                    if source == "gsc"
                    else "DataForSEO point sample (weekly live SERP check)"
                    if source == "dataforseo"
                    else "no rank data yet"
                ),
                measured_at=latest_date,
                cadence_days=7,
                min_delta=1.0,
                now=now,
                status=status_map.get(s.get("direction")) if s.get("direction") else None,
            )
        )
    return {"keyword_count": len(kws), "envelopes": envelopes}


def _prov_open_alerts(supabase, client_id: str, today: date, now: datetime) -> Optional[dict]:
    from services.offpage_agent import open_offpage_alerts

    rank = (
        supabase.table("rank_alerts")
        .select("keyword, alert_type, message, created_at")
        .eq("client_id", client_id).is_("resolved_at", "null")
        .limit(MAX_ALERTS).execute()
    ).data or []
    maps = (
        supabase.table("maps_alerts")
        .select("keyword, alert_type, sector, message, created_at")
        .eq("client_id", client_id).is_("resolved_at", "null")
        .limit(MAX_ALERTS).execute()
    ).data or []
    offpage = [
        {
            "alert_type": a.get("alert_type"),
            "message": a.get("message"),
            "delta_pct": a.get("delta_pct"),
            "triggered_on": a.get("triggered_on"),
        }
        for a in open_offpage_alerts(client_id)[:MAX_ALERTS]
    ]
    if not (rank or maps or offpage):
        return None
    return {"rank": rank, "maps": maps, "offpage": offpage}


def _prov_action_plan(supabase, client_id: str, today: date, now: datetime) -> Optional[dict]:
    rows = (
        supabase.table("reopt_plans")
        .select("summary, items, action_count, trigger, created_at")
        .eq("client_id", client_id).order("created_at", desc=True).limit(1).execute()
    ).data
    if not rows:
        return None
    p = rows[0]
    items = [
        {
            "kind": a.get("kind"),
            "source": a.get("source"),
            "keyword": a.get("keyword"),
            "classification": a.get("classification"),
            "diagnosis": a.get("diagnosis"),
            "recommendation": (a.get("recommendation") or "")[:400],
            "severity": a.get("severity"),
            "episode_note": a.get("episode_note"),
        }
        for a in (p.get("items") or [])[:MAX_PLAN_ITEMS]
    ]
    return {
        "summary": p.get("summary"),
        "action_count": p.get("action_count"),
        "built_at": p.get("created_at"),
        "items": items,
    }


def _prov_episodes(supabase, client_id: str, today: date, now: datetime) -> Optional[list[dict]]:
    from services.response_episodes import episode_note

    rows = (
        supabase.table("response_episodes")
        .select("keyword, channel, status, classification, baseline, checks, opened_at")
        .eq("client_id", client_id).in_("status", ["open", "escalated"])
        .order("opened_at", desc=True).limit(MAX_EPISODES).execute()
    ).data or []
    if not rows:
        return None
    out = []
    for ep in rows:
        checks = ep.get("checks") or []
        out.append(
            {
                "keyword": ep.get("keyword"),
                "channel": ep.get("channel"),
                "status": ep.get("status"),
                "classification": ep.get("classification"),
                "baseline_position": (ep.get("baseline") or {}).get("position"),
                "last_check": checks[-1] if checks else None,
                "opened_at": ep.get("opened_at"),
                "age_weeks": max(((now - (_parse_ts(ep.get("opened_at")) or now)).days) // 7, 0),
                "clock_note": episode_note(ep, now),
            }
        )
    return out


def _prov_maps(supabase, client_id: str, today: date, now: datetime) -> Optional[dict]:
    scans = (
        supabase.table("maps_scans")
        .select("id, completed_at")
        .eq("client_id", client_id).eq("status", "complete")
        .order("completed_at", desc=True).limit(2).execute()
    ).data or []
    if not scans:
        return None
    latest = (
        supabase.table("maps_scan_results")
        .select("keyword, average_rank, found_pins, total_pins, top3_pins")
        .eq("scan_id", scans[0]["id"]).execute()
    ).data or []
    prev_by_kw: dict[str, dict] = {}
    if len(scans) > 1:
        for r in (
            supabase.table("maps_scan_results")
            .select("keyword, total_pins, top3_pins")
            .eq("scan_id", scans[1]["id"]).execute()
        ).data or []:
            prev_by_kw[_norm_kw(r.get("keyword"))] = r

    envelopes = []
    for r in latest:
        total = r.get("total_pins") or 0
        top3 = r.get("top3_pins") or 0
        pct = round(100.0 * top3 / total, 1) if total else None
        prev = prev_by_kw.get(_norm_kw(r.get("keyword")))
        prev_total = (prev or {}).get("total_pins") or 0
        prev_pct = (
            round(100.0 * (prev.get("top3_pins") or 0) / prev_total, 1)
            if prev and prev_total else None
        )
        envelopes.append(
            make_envelope(
                module="maps_geogrid",
                keyword=r.get("keyword"),
                metric="local_pack_presence_pct",  # top-3 pins / total pins — the honest read
                value=pct,
                baseline=prev_pct,
                direction=HIGHER_IS_BETTER,
                coverage=(
                    f"found {r.get('found_pins') or 0}/{total} pins, "
                    f"{top3} in the pack; average_rank {r.get('average_rank')} "
                    "(over FOUND pins only — read with coverage)"
                ),
                measured_at=scans[0].get("completed_at"),
                cadence_days=7,
                min_delta=5.0,
                now=now,
            )
        )
    return {"scan_completed_at": scans[0].get("completed_at"), "envelopes": envelopes}


def _prov_ai_visibility(supabase, client_id: str, today: date, now: datetime) -> Optional[dict]:
    from services import brand_service

    trends = brand_service.get_trends(client_id)
    if not trends:
        return None
    latest = trends[-1]
    prev = trends[-2] if len(trends) > 1 else {}
    envelopes = [
        make_envelope(
            module="ai_visibility",
            keyword=None,
            metric="visibility_pct",
            value=latest.get("visibility_pct"),
            baseline=prev.get("visibility_pct"),
            direction=HIGHER_IS_BETTER,
            coverage=(
                f"{latest.get('found', 0)}/{latest.get('total', 0)} keyword×engine cells "
                f"across {len(latest.get('engines') or {})} engines (batch rollup — "
                "single-cell flips are noise by design)"
            ),
            measured_at=latest.get("created_at"),
            cadence_days=30,
            min_delta=10.0,
            now=now,
        )
    ]
    # Invisible keywords in the latest batch (keyword-level, for the passport).
    invisible: list[str] = []
    try:
        newest_batch = latest.get("scan_batch_id")
        if newest_batch:
            batch = (
                supabase.table("brand_mention_history")
                .select("keyword_id, engine, mention_found")
                .eq("client_id", client_id).eq("scan_batch_id", newest_batch)
                .eq("is_competitor_scan", False).execute()
            ).data or []
            kw_rows = (
                supabase.table("brand_tracked_keywords")
                .select("id, keyword").eq("client_id", client_id).execute()
            ).data or []
            names = {k["id"]: k["keyword"] for k in kw_rows}
            seen: dict[str, int] = {}
            found: dict[str, int] = {}
            for r in batch:
                kid = r.get("keyword_id")
                seen[kid] = seen.get(kid, 0) + 1
                if r.get("mention_found"):
                    found[kid] = found.get(kid, 0) + 1
            invisible = sorted(
                names.get(kid, "?") for kid in seen if not found.get(kid)
            )[:20]
    except Exception as exc:
        logger.warning("strategy_digest.labs_invisible_failed", extra={"client_id": client_id, "error": str(exc)})
    return {
        "envelopes": envelopes,
        "per_engine": latest.get("engines"),
        "invisible_keywords": invisible,
    }


def _prov_task_plan(supabase, client_id: str, today: date, now: datetime) -> Optional[dict]:
    rows = (
        supabase.table("monthly_task_plans")
        .select("month, margin_used, deployable, spent, remaining, flags, plan, created_at")
        .eq("client_id", client_id).order("created_at", desc=True).limit(1).execute()
    ).data
    if not rows:
        return None
    p = rows[0]
    plan = p.get("plan") or {}
    tasks = [
        {
            "label": t.get("label"),
            "quantity": t.get("quantity"),
            "line_cost": t.get("line_cost"),
            "assignee": t.get("assignee"),
            "rationale": (t.get("rationale") or "")[:200],
        }
        for t in (plan.get("tasks") or [])[:MAX_TASKS]
    ]
    return {
        "month": p.get("month"),
        "margin_used": p.get("margin_used"),
        "deployable": p.get("deployable"),
        "spent": p.get("spent"),
        "remaining": p.get("remaining"),
        "flags": p.get("flags") or [],
        "diagnosis": (plan.get("diagnosis") or {}),
        "tasks": tasks,
        "built_at": p.get("created_at"),
    }


def _prov_gsc_research(supabase, client_id: str, today: date, now: datetime) -> Optional[dict]:
    rows = (
        supabase.table("gsc_research_runs")
        .select("cannibalization_count, quick_wins_count, hidden_wins_count, cannibalization, created_at")
        .eq("client_id", client_id).eq("status", "complete")
        .order("created_at", desc=True).limit(1).execute()
    ).data
    if not rows:
        return None
    g = rows[0]
    return {
        "cannibalization_count": g.get("cannibalization_count"),
        "quick_wins_count": g.get("quick_wins_count"),
        "hidden_wins_count": g.get("hidden_wins_count"),
        "top_cannibalizations": [
            {"query": c.get("query"), "page_count": c.get("page_count"), "impressions": c.get("total_impressions")}
            for c in (g.get("cannibalization") or [])[:5]
        ],
        "run_at": g.get("created_at"),
    }


def _prov_backlinks(supabase, client_id: str, today: date, now: datetime) -> Optional[dict]:
    from services import backlink_intel

    intel = backlink_intel.get_backlink_intel(client_id)
    client = intel.get("client") or {}
    if not client:
        return None
    comparison = intel.get("comparison") or {}
    return {
        "client_dr": client.get("domain_rating"),
        "client_referring_domains": client.get("referring_domains"),
        "competitor_median_dr": comparison.get("competitor_median_dr"),
        "competitor_median_referring_domains": comparison.get("competitor_median_referring_domains"),
        "note": "competitor RD reads are tool-visibility discounted ×10 per the SOP shared definition",
        "captured_at": client.get("captured_at"),
    }


def _prov_campaign_goals(supabase, client_id: str, today: date, now: datetime) -> Optional[dict]:
    """The client's success targets with deterministic on-track reads —
    the yardstick the strategist judges every other section against."""
    from services import campaign_goals

    assessed = campaign_goals.assess_goals(client_id, today=today)
    if not assessed:
        return None
    return {
        "goals": [
            {
                "label": g.get("label"),
                "goal_type": g.get("goal_type"),
                "keyword": g.get("keyword"),
                "target_value": g.get("target_value"),
                "target_position": g.get("target_position"),
                "baseline_value": g.get("baseline_value"),
                "current_value": g.get("current_value"),
                "status": g.get("status"),  # computed deterministically — trust it
                "progress_pct": g.get("progress_pct"),
                "elapsed_pct": g.get("elapsed_pct"),
                "due_date": g.get("due_date"),
                "note": g.get("note"),
            }
            for g in assessed
        ],
        "counts": {
            s: sum(1 for g in assessed if g.get("status") == s)
            for s in ("achieved", "on_track", "behind", "overdue", "no_data", "manual")
            if any(g.get("status") == s for g in assessed)
        },
    }


def _prov_competitors(supabase, client_id: str, today: date, now: datetime) -> Optional[dict]:
    """Assembled competitor profiles (registry × every module) — gaps the
    strategist can aim proposals at, plus fresh competitor content."""
    from services import competitor_intel

    assembled = competitor_intel.build_profiles(client_id, today=today)
    profiles = assembled.get("competitors") or []
    if not profiles:
        return None
    return {
        "client": assembled.get("client"),
        "note": (
            "profiles join maps/GBP/backlinks/organic/reviews per competitor; a null "
            "module means no capture yet, not absence of the competitor. Competitor "
            "RD/DR are tool reads (true RD ≈ ×10, SOP shared definition). "
            "new_pages_30d counts non-baseline URLs first seen in the last 30 days."
        ),
        "competitors": [
            {
                "name": p.get("name"),
                "domain": p.get("domain"),
                "sources": p.get("sources"),
                "local_pack": p.get("local_pack"),
                "gbp": p.get("gbp"),
                "backlinks": p.get("backlinks"),
                "organic": p.get("organic"),
                "review_velocity_30d": p.get("review_velocity_30d"),
                "new_pages_30d": p.get("new_pages_30d"),
                "recent_pages": (p.get("recent_pages") or [])[:5],
            }
            for p in profiles[:8]
        ],
    }


def _prov_forecast(supabase, client_id: str, today: date, now: datetime) -> Optional[dict]:
    """Deterministic trajectory/value projections — the strategist cites these
    numbers, never derives its own."""
    from services import forecasting

    fc = forecasting.build_forecast(client_id, today=today)
    if not fc.get("keyword_count"):
        return None
    keywords = fc.get("keywords") or []
    return {
        "note": fc.get("note"),
        "portfolio": fc.get("portfolio"),
        "gsc_clicks_trajectory": fc.get("gsc_clicks_trajectory"),
        "quick_wins": {
            **{k: v for k, v in (fc.get("quick_wins") or {}).items() if k != "keywords"},
            "top_keywords": (fc.get("quick_wins") or {}).get("keywords", [])[:8],
        },
        "goal_projections": fc.get("goal_projections"),
        # The biggest movers only — full per-keyword table lives in the API/UI.
        "top_keyword_forecasts": [
            {k: f.get(k) for k in (
                "keyword", "current_position", "trend_per_week",
                "projected_position_90d", "confidence",
                "clicks_per_month_now", "clicks_per_month_90d", "clicks_source",
            )}
            for f in keywords[:10]
        ],
    }


def _prov_trends(supabase, client_id: str, today: date, now: datetime) -> Optional[dict]:
    """Portfolio-level trend context: suspected Google algorithm updates
    (cross-client co-drops) + the client's seasonal demand outlook."""
    from services import trend_watch

    events = trend_watch.recent_algo_events()
    outlook = None
    try:
        outlook = trend_watch.build_demand_outlook(client_id, today=today)
    except Exception as exc:
        logger.warning("strategy_digest.demand_outlook_failed", extra={"client_id": client_id, "error": str(exc)})
    if not events and not outlook:
        return None
    return {
        "note": (
            "algo_events are CROSS-CLIENT detections (several clients opened drops in "
            "the same window = a Google update, not this client's emergency) — drops "
            "inside a window carry an algo_note on the Action Plan; don't propose "
            "reoptimizing into a rolling update. demand_outlook is seasonality from "
            "12-month volume history: falling demand explains falling impressions "
            "without a ranking problem."
        ),
        "algo_events": [
            {
                "window_start": e.get("window_start"),
                "window_end": e.get("window_end"),
                "clients_affected": e.get("clients_affected"),
                "clients_total": e.get("clients_total"),
                "drop_count": e.get("drop_count"),
            }
            for e in events[:3]
        ],
        "demand_outlook": outlook,
    }


def review_snippets(gbp, limit: int = 10, clip: int = 240) -> list[dict]:
    """Recent GBP review texts, clipped for the prompt. Pure, shape-tolerant.

    The stored set (`clients.gbp.reviews`) is what GBP enrichment kept —
    high-rating reviews only — so this is positive-theme raw material, not a
    sentiment sample."""
    out: list[dict] = []
    for r in (gbp or {}).get("reviews") or []:
        if not isinstance(r, dict):
            continue
        text = (r.get("text") or "").strip()
        if not text:
            continue
        out.append({"rating": r.get("rating"), "date": r.get("date") or None, "text": text[:clip]})
        if len(out) >= limit:
            break
    return out


def competitor_review_sets(
    rows: list[dict], max_competitors: int = 4, per_competitor: int = 5, clip: int = 200
) -> list[dict]:
    """Per-competitor review snippets from raw competitor_gbp_profiles rows. Pure.

    Rows arrive newest-capture-first; the first occurrence per place_id is the
    latest capture. Competitors are ordered by local-pack presence (top3 then
    found pins — the ones that matter most first), competitors with no review
    text are skipped."""
    seen: set = set()
    latest: list[dict] = []
    for r in rows or []:
        pid = r.get("place_id")
        if not pid or pid in seen:
            continue
        seen.add(pid)
        latest.append(r)
    latest.sort(key=lambda r: (-(r.get("top3_pins") or 0), -(r.get("found_pins") or 0)))
    out: list[dict] = []
    for r in latest:
        snippets = review_snippets(r.get("profile") or {}, limit=per_competitor, clip=clip)
        if not snippets:
            continue
        out.append({"competitor": r.get("name"), "reviews": snippets})
        if len(out) >= max_competitors:
            break
    return out


def _prov_reviews(supabase, client_id: str, today: date, now: datetime) -> Optional[dict]:
    """Customer voice, verbatim — the client's GBP reviews AND the top local-pack
    competitors' reviews (from the competitor_gbp captures).

    Lets the strategist notice recurring themes ("every review mentions the
    free parking") and positioning gaps (what competitors' customers praise
    that the client doesn't market) instead of a human having to spot them."""
    rows = (
        supabase.table("clients").select("gbp").eq("id", client_id).limit(1).execute()
    ).data
    snippets = review_snippets((rows[0].get("gbp") if rows else None) or {})

    comp_rows = (
        supabase.table("competitor_gbp_profiles")
        .select("place_id, name, found_pins, top3_pins, profile, captured_at")
        .eq("client_id", client_id)
        .order("captured_at", desc=True)
        .limit(60)
        .execute()
    ).data or []
    competitor_sets = competitor_review_sets(comp_rows)

    if not snippets and not competitor_sets:
        return None
    out: dict = {
        "note": (
            "What customers say in their own words — recent Google reviews for the "
            "client and (when captured) its top local-pack competitors. A theme "
            "recurring across the CLIENT's reviews (a praised amenity, speed, a "
            "differentiator) is marketing raw material the campaign may be under-using. "
            "A theme recurring in a COMPETITOR's reviews is either a positioning gap "
            "(they have it, the client can't match it) or an unmatched weapon (the "
            "client has it too but doesn't market it — check the client's own reviews "
            "and ICP). TRAP: all sets are filtered to high ratings at capture, so use "
            "them to find what customers PRAISE — never to assess overall sentiment or "
            "detect complaints (absence of complaints here means nothing)."
        ),
    }
    if snippets:
        out["client_reviews"] = snippets
    if competitor_sets:
        out["competitor_reviews"] = competitor_sets
    return out


def _prov_gbp_audit(supabase, client_id: str, today: date, now: datetime) -> Optional[dict]:
    """Deterministic GBP audit vs captured competitor profiles — profile-
    completeness gaps, category gaps (categories most competitors carry that the
    client doesn't), and the review deficit vs the competitor median. Pure gap
    data the strategist can aim proposals at."""
    from services import competitor_gbp, gbp_audit

    rows = supabase.table("clients").select("gbp").eq("id", client_id).limit(1).execute().data
    gbp = (rows[0].get("gbp") if rows else None) or {}
    if not gbp:
        return None
    audit = gbp_audit.audit(gbp, competitor_gbp.latest_profiles(client_id))
    return {
        "note": (
            "Deterministic audit of the client's GBP vs its captured local-pack "
            "competitors. category_gaps = categories on at least half the competitors "
            "but missing from the client (usually worth adding). review_gap = deficit "
            "vs the competitor median (the Recipe Engine funds reviews first when "
            "gating). gaps = failed profile-completeness checks. Remember the module "
            "card: the GBP description is an AI-visibility factor, not a local-pack "
            "ranking factor."
        ),
        "score": audit.get("score"),
        "gaps": audit.get("gaps"),
        "category_gaps": audit.get("category_gaps"),
        "review_gap": audit.get("review_gap"),
        "competitor_count": audit.get("competitor_count"),
    }


def _prov_content(supabase, client_id: str, today: date, now: datetime) -> Optional[dict]:
    """What the campaign has actually produced — the coverage map to hold
    against ICP/differentiators, review themes, and competitor content when
    hunting gaps."""
    out: dict = {}
    by_type: dict[str, int] = {}
    for t in ("blog_post", "service_page", "location_page"):
        n = (
            supabase.table("runs")
            .select("id", count="exact")
            .eq("client_id", client_id).eq("status", "complete").eq("content_type", t)
            .limit(1)
            .execute()
        ).count or 0
        if n:
            by_type[t] = n
    if by_type:
        out["completed_runs_by_type"] = by_type
        out["recent_runs"] = [
            {"keyword": r.get("keyword"), "content_type": r.get("content_type")}
            for r in (
                supabase.table("runs").select("keyword, content_type")
                .eq("client_id", client_id).eq("status", "complete")
                .order("created_at", desc=True).limit(8).execute()
            ).data or []
        ]

    pages = (
        supabase.table("local_seo_pages").select("keyword, page_title, published_doc_id")
        .eq("client_id", client_id).is_("deleted_at", "null")
        .order("created_at", desc=True).limit(200).execute()
    ).data or []
    if pages:
        out["local_seo_pages_saved"] = len(pages)
        out["local_seo_pages_published"] = sum(1 for p in pages if p.get("published_doc_id"))
        out["recent_local_seo_keywords"] = [p.get("keyword") for p in pages[:8] if p.get("keyword")]

    if not out:
        return None
    out["note"] = (
        "The campaign's content inventory (counts + most recent targets). Hold it "
        "against the ICP/differentiators, review themes, and competitors' recent_pages: "
        "a service the ICP names with no page, a praised theme with no content, or a "
        "competitor content push with no answer is a coverage gap worth a proposal."
    )
    return out


# Registry — append a provider to feed the strategist a new module.
_PROVIDERS: list[tuple[str, object]] = [
    ("client", _prov_client),
    ("reviews", _prov_reviews),
    ("gbp_audit", _prov_gbp_audit),
    ("content", _prov_content),
    ("campaign_goals", _prov_campaign_goals),
    ("competitors", _prov_competitors),
    ("forecast", _prov_forecast),
    ("trends", _prov_trends),
    ("organic_rank", _prov_organic),
    ("open_alerts", _prov_open_alerts),
    ("action_plan", _prov_action_plan),
    ("episodes", _prov_episodes),
    ("maps_geogrid", _prov_maps),
    ("ai_visibility", _prov_ai_visibility),
    ("task_plan", _prov_task_plan),
    ("gsc_research", _prov_gsc_research),
    ("backlinks", _prov_backlinks),
]


def build_strategy_digest(client_id: str, today: Optional[date] = None) -> dict:
    """Assemble the full strategist digest for one client. Each provider is
    isolated (a failing module is omitted, never fatal). Returns the digest
    dict; render with ``render_digest`` for the prompt."""
    supabase = get_supabase()
    today = today or date.today()
    now = _now()
    digest: dict = {}
    for key, provider in _PROVIDERS:
        try:
            section = provider(supabase, client_id, today, now)
            if section:
                digest[key] = section
        except Exception as exc:
            logger.warning(
                "strategy_digest.provider_failed",
                extra={"client_id": client_id, "provider": key, "error": str(exc)},
            )

    # Cross-module assembly: envelopes → passports + staleness flags.
    envelopes: list[dict] = []
    for section_key in ("organic_rank", "maps_geogrid"):
        envelopes.extend((digest.get(section_key) or {}).get("envelopes") or [])
    labs_envs = (digest.get("ai_visibility") or {}).get("envelopes") or []
    envelopes.extend(labs_envs)

    alerts = digest.get("open_alerts") or {}
    keyword_alerts = (alerts.get("rank") or []) + (alerts.get("maps") or [])
    digest["keyword_passports"] = build_keyword_passports(
        [e for e in envelopes if e.get("keyword")],
        digest.get("episodes") or [],
        keyword_alerts,
    )
    # The per-keyword envelopes now live in the passports — drop the per-module
    # duplicates so the digest doesn't carry every signal twice.
    for section_key in ("organic_rank", "maps_geogrid"):
        if section_key in digest and "envelopes" in digest[section_key]:
            digest[section_key] = {
                k: v for k, v in digest[section_key].items() if k != "envelopes"
            }

    digest["staleness_flags"] = staleness_flags(envelopes)
    digest["active_domains"] = sorted(active_signal_domains(digest))
    digest["generated_at"] = now.isoformat()
    return digest
