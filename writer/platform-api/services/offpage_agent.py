"""Offpage agent — the detection layer for off-page signals
(_ORCHESTRATOR.md §Agents; consumed by the Organic Rank Drop SOP §A.5/§B5.6).

Detects, from the `backlink_profiles` time-series that backlink_intel already
captures (DataForSEO Backlinks summary, interval-gated):

  * **Lost referring domains** — the client's RD fell materially between
    captures → §A.5 response: build a replacement plan via the Recipe Engine.
  * **Unnatural RD spike** — the client's RD jumped far past anything we'd
    build in a month → negative-SEO / unintended-blast check; MC4 judgment
    call, senior SEO if unclear (per the SOP; we never disavow either way).

Citation status is **deferred**: the SOP routes citation consistency to the
external Citation Audit tool and the suite stores no citation data.

Alerts carry the same episode semantics as rank/maps alerts (one OPEN row per
client+type; `resolved_at` set when the condition clears), feed a notification
on open, an Action Plan action (reopt_planner.build_offpage_actions), and the
Recipe Engine's diagnosis (an open rd_loss marks referring_domains deficient).

`detect_rd_change` + `should_resolve` are pure (unit-tested);
`run_offpage_sweep` runs daily on the shared scheduler — cheap DB reads only
(the paid captures themselves stay on backlink_intel's interval gate).
"""

from __future__ import annotations

import logging
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import notifications

logger = logging.getLogger(__name__)

# Thresholds: both the relative and absolute bars must clear, so tiny profiles
# (5 → 3 RD) and rounding jitter on large ones don't fire.
RD_LOSS_MIN_PCT = 15.0
RD_LOSS_MIN_ABS = 10
RD_SPIKE_MIN_PCT = 50.0
RD_SPIKE_MIN_ABS = 20
# A loss episode resolves when RD recovers to ~the pre-loss level; a spike
# episode resolves when RD settles back toward the pre-spike level.
LOSS_RESOLVE_RATIO = 0.95
SPIKE_RESOLVE_RATIO = 1.20


# ─────────────────────────────────────────────────────────────────────────────
# Pure helpers (unit-tested)
# ─────────────────────────────────────────────────────────────────────────────
def detect_rd_change(prev_rd: Optional[int], cur_rd: Optional[int]) -> Optional[dict]:
    """Classify the client's capture-over-capture RD change. Pure.

    Returns {'type': 'rd_loss'|'rd_spike', 'delta_pct', 'from_rd', 'to_rd'} or
    None when the change is unremarkable / data is missing."""
    if prev_rd is None or cur_rd is None or prev_rd <= 0:
        return None
    delta = cur_rd - prev_rd
    delta_pct = delta / prev_rd * 100
    if delta <= -RD_LOSS_MIN_ABS and delta_pct <= -RD_LOSS_MIN_PCT:
        return {"type": "rd_loss", "delta_pct": round(delta_pct, 1), "from_rd": prev_rd, "to_rd": cur_rd}
    if delta >= RD_SPIKE_MIN_ABS and delta_pct >= RD_SPIKE_MIN_PCT:
        return {"type": "rd_spike", "delta_pct": round(delta_pct, 1), "from_rd": prev_rd, "to_rd": cur_rd}
    return None


def should_resolve(alert: dict, cur_rd: Optional[int]) -> bool:
    """Whether an open alert's condition has cleared. Pure.

    rd_loss resolves when RD recovers to ≥95% of the pre-loss level;
    rd_spike resolves when RD settles back to ≤120% of the pre-spike level
    (the extra domains dropped out — spam links churn — or were reabsorbed
    as the new, verified baseline by a human dismissing the alert)."""
    if cur_rd is None:
        return False
    from_rd = alert.get("from_rd")
    if from_rd is None or from_rd <= 0:
        return False
    if alert.get("alert_type") == "rd_loss":
        return cur_rd >= from_rd * LOSS_RESOLVE_RATIO
    if alert.get("alert_type") == "rd_spike":
        return cur_rd <= from_rd * SPIKE_RESOLVE_RATIO
    return False


def alert_message(change: dict) -> str:
    if change["type"] == "rd_loss":
        return (
            f"Referring domains fell {abs(change['delta_pct'])}% "
            f"({change['from_rd']:,} → {change['to_rd']:,}) between captures."
        )
    return (
        f"Referring domains jumped {change['delta_pct']}% "
        f"({change['from_rd']:,} → {change['to_rd']:,}) between captures — "
        "far past normal build volume."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Daily sweep (shared scheduler)
# ─────────────────────────────────────────────────────────────────────────────
def _client_rd_series(supabase, client_id: str, limit: int = 2) -> list[dict]:
    """Latest client-domain captures, newest first."""
    return (
        supabase.table("backlink_profiles")
        .select("referring_domains, captured_at")
        .eq("client_id", client_id)
        .eq("is_client", True)
        .not_.is_("referring_domains", "null")
        .order("captured_at", desc=True)
        .limit(limit)
        .execute()
    ).data or []


def _open_alerts(supabase, client_id: str) -> list[dict]:
    return (
        supabase.table("offpage_alerts")
        .select("*")
        .eq("client_id", client_id)
        .is_("resolved_at", "null")
        .execute()
    ).data or []


def analyze_client(client_id: str) -> dict:
    """Detect / resolve offpage alerts for one client from its capture series.
    Returns {opened: [...types], resolved: [...types]}."""
    supabase = get_supabase()
    series = _client_rd_series(supabase, client_id)
    cur_rd = series[0]["referring_domains"] if series else None
    prev_rd = series[1]["referring_domains"] if len(series) > 1 else None

    opened: list[str] = []
    resolved: list[str] = []

    # Resolve open alerts whose condition cleared.
    open_alerts = _open_alerts(supabase, client_id)
    for a in open_alerts:
        if should_resolve(a, cur_rd):
            supabase.table("offpage_alerts").update({"resolved_at": "now()"}).eq("id", a["id"]).execute()
            resolved.append(a["alert_type"])

    change = detect_rd_change(prev_rd, cur_rd)
    if not change:
        return {"opened": opened, "resolved": resolved}

    still_open = {a["alert_type"] for a in open_alerts if a["alert_type"] not in resolved}
    if change["type"] in still_open:
        return {"opened": opened, "resolved": resolved}  # episode dedup

    details = {"captured_at": series[0].get("captured_at") if series else None}
    # Enrich a loss with the *actual* referring domains that dropped, when the
    # client's own domain is tracked in the Backlink Explorer — turns "RD fell"
    # into a concrete replacement list. Best-effort; absent tracking, unchanged.
    if change["type"] == "rd_loss":
        try:
            from services import backlink_explorer

            velocity = backlink_explorer.client_own_domain_change(client_id)
            # Only attach the sample if the tracked snapshot is recent — a months-
            # old lost-domain list must not decorate a fresh RD-loss episode.
            max_age = settings.backlink_tracking_interval_days * 3
            if (velocity and velocity.get("lost_sample")
                    and backlink_explorer.is_recent(velocity.get("captured_at"), max_age)):
                details["lost_domains"] = velocity["lost_sample"]
        except Exception:
            logger.warning("offpage.lost_domain_enrich_failed", extra={"client_id": client_id})

    supabase.table("offpage_alerts").insert(
        {
            "client_id": client_id,
            "alert_type": change["type"],
            "from_rd": change["from_rd"],
            "to_rd": change["to_rd"],
            "delta_pct": change["delta_pct"],
            "message": alert_message(change),
            "details": details,
        }
    ).execute()
    opened.append(change["type"])

    # A new offpage alert refreshes the Action Plan silently (same pattern as
    # the rank/maps drop triggers — no week-long lag before the action shows).
    try:
        from services.reopt_planner import enqueue_reopt_plan

        enqueue_reopt_plan(client_id, trigger="offpage")
    except Exception:
        logger.warning("offpage.plan_refresh_enqueue_failed", extra={"client_id": client_id})

    if change["type"] == "rd_loss":
        notifications.emit(
            client_id,
            kind="offpage_rd_loss",
            title="Referring domains lost",
            summary=alert_message(change)
            + " SOP §A.5: build a replacement plan via the Recipe Engine.",
            severity="warning",
            payload={"link": f"clients/{client_id}/action-plan"},
        )
    else:
        notifications.emit(
            client_id,
            kind="offpage_rd_spike",
            title="Unnatural referring-domain spike",
            summary=alert_message(change)
            + " Check for negative SEO or an unintended blast (we never disavow — "
            "response levers are dilution/velocity/settling). MC4 judgment call — "
            "senior SEO if unclear.",
            severity="warning",
            payload={"link": f"clients/{client_id}/action-plan"},
        )
    return {"opened": opened, "resolved": resolved}


def run_offpage_sweep() -> dict:
    """Daily sweep over every client with ≥2 client-domain captures. Cheap —
    DB reads only; the paid captures stay on backlink_intel's interval gate."""
    supabase = get_supabase()
    stats = {"clients": 0, "opened": 0, "resolved": 0}
    try:
        # Clients that have client-domain capture history at all.
        rows = (
            supabase.table("backlink_profiles")
            .select("client_id")
            .eq("is_client", True)
            .execute()
        ).data or []
        client_ids = sorted({r["client_id"] for r in rows})
    except Exception as exc:
        logger.error("offpage.sweep_read_failed", extra={"error": str(exc)})
        return stats

    for cid in client_ids:
        try:
            result = analyze_client(cid)
            stats["clients"] += 1
            stats["opened"] += len(result["opened"])
            stats["resolved"] += len(result["resolved"])
        except Exception as exc:
            logger.warning("offpage.analyze_failed", extra={"client_id": cid, "error": str(exc)})
    if stats["opened"] or stats["resolved"]:
        logger.info("offpage.sweep_complete", extra=stats)
    return stats


def open_offpage_alerts(client_id: str) -> list[dict]:
    """The client's open offpage alerts (Action Plan + Recipe Engine input).
    Best-effort."""
    try:
        return _open_alerts(get_supabase(), client_id)
    except Exception as exc:
        logger.warning("offpage.read_failed", extra={"client_id": client_id, "error": str(exc)})
        return []
