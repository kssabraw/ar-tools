"""Response-episode tracking — the verify loop from the Rank Drop Mitigation
SOPs (docs/sops/Rank_Drop_Mitigation_SOP_{Organic,Maps}.md §Timelines).

The SOPs give every drop response a clock:
  * expect movement **~2 weeks** after the response lands → recheck cadence
  * no improvement and the response work done → **another link round** (Recipe
    Engine) — surfaced as a plan note, not auto-executed
  * **6 weeks** with no improvement → notify the Senior SEOs (Kyle/Ryan) for a
    strategy review — a critical notification through the notifications service

An *episode* is one drop response with that clock attached: opened when a
rank/maps alert opens, rechecked on the cadence against its baseline, marked
**recovered** when the alert auto-resolves (the trackers already resolve alerts
when the condition clears), and **escalated** exactly once at the 6-week mark.
Escalation is terminal for automation — humans own strategy reviews.

`run_episode_sync()` runs daily on the shared scheduler:
  1. open episodes for open alerts that lack one (baseline = current read)
  2. recover episodes whose alert resolved
  3. evaluate due episodes (improvement vs baseline; escalate at 6 weeks)

Pure helpers (`evaluate_episode`, `episode_note`) are unit-tested without a DB.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import notifications

logger = logging.getLogger(__name__)

CHECK_INTERVAL_DAYS = 14      # "expect movement ~2 weeks after indexing"
ESCALATE_DAYS = 42            # the 6-week rule
IMPROVE_MIN_POSITIONS = 2.0   # baseline→current position gain to count as "improving"


# ─────────────────────────────────────────────────────────────────────────────
# Pure helpers (unit-tested)
# ─────────────────────────────────────────────────────────────────────────────
def _parse_ts(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def evaluate_episode(
    episode: dict,
    *,
    alert_resolved: bool,
    current_position: Optional[float],
    now: datetime,
) -> dict:
    """Decide one due-check's outcome. Pure.

    Returns {verdict: 'recovered'|'escalate'|'improving'|'no_improvement',
             improved: bool} — the caller applies the state change.

    Recovery is the tracker's call (the alert auto-resolves when the condition
    clears), not a position heuristic. Improvement (position gained ≥
    IMPROVE_MIN_POSITIONS vs baseline) resets nothing but records progress —
    an improving episode is never escalated even past 6 weeks; the 6-week rule
    targets *stalled* responses."""
    if alert_resolved:
        return {"verdict": "recovered", "improved": True}

    baseline_pos = (episode.get("baseline") or {}).get("position")
    improved = (
        baseline_pos is not None
        and current_position is not None
        and (float(baseline_pos) - float(current_position)) >= IMPROVE_MIN_POSITIONS
    )

    opened = _parse_ts(episode.get("opened_at"))
    age_days = (now - opened).days if opened else 0
    if not improved and age_days >= ESCALATE_DAYS:
        return {"verdict": "escalate", "improved": False}
    return {"verdict": "improving" if improved else "no_improvement", "improved": improved}


def episode_note(episode: dict, now: datetime) -> Optional[str]:
    """One-line verify-loop note for the Action Plan's drop row. Pure."""
    opened = _parse_ts(episode.get("opened_at"))
    if not opened:
        return None
    weeks = max((now - opened).days // 7, 0)
    age = f"{weeks} week{'s' if weeks != 1 else ''}" if weeks else "under a week"
    if episode.get("status") == "escalated":
        return f"Response open {age} — escalated to the senior SEOs (6-week rule)."
    checks = episode.get("checks") or []
    last = checks[-1] if checks else None
    if last and last.get("verdict") == "improving":
        return f"Response open {age} — improving vs baseline; hold course."
    if last and last.get("verdict") == "no_improvement":
        return (
            f"Response open {age} with no movement — if the on-page work is done, "
            "fund another link round via the Recipe Engine."
        )
    return f"Response open {age} — first recheck at the 2-week mark."


# ─────────────────────────────────────────────────────────────────────────────
# Daily sync (shared scheduler)
# ─────────────────────────────────────────────────────────────────────────────
def _current_position(supabase, keyword_id: Optional[str]) -> Optional[float]:
    """Recent 7-day position read for an organic episode (best-effort)."""
    if not keyword_id:
        return None
    try:
        from services.drop_classifier import summarize_window

        since = (datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat()
        rows = (
            supabase.table("rank_keyword_metrics")
            .select("clicks, impressions, gsc_position, tracked_rank")
            .eq("keyword_id", keyword_id)
            .gte("date", since)
            .execute()
        ).data or []
        window = summarize_window(rows)
        return window.get("position") if window else None
    except Exception:
        return None


def _open_alerts(supabase, table: str) -> list[dict]:
    cols = "id, client_id, keyword, alert_type" + (", keyword_id" if table == "rank_alerts" else "")
    return (
        supabase.table(table).select(cols).is_("resolved_at", "null").execute()
    ).data or []


def _alert_resolved(supabase, table: str, alert_id: str) -> bool:
    try:
        rows = (
            supabase.table(table).select("resolved_at").eq("id", alert_id).limit(1).execute()
        ).data or []
        # A deleted alert row also ends the episode (e.g. Maps history cleared).
        return (not rows) or rows[0].get("resolved_at") is not None
    except Exception:
        return False


def _open_episodes_for(supabase, channel: str) -> dict[str, dict]:
    rows = (
        supabase.table("response_episodes")
        .select("*")
        .eq("channel", channel)
        .eq("status", "open")
        .execute()
    ).data or []
    return {r["alert_id"]: r for r in rows}


def run_episode_sync() -> dict:
    """Daily sweep: open / recover / evaluate episodes across all clients.
    Best-effort per episode — one bad row never stops the sweep."""
    if not settings.episode_tracking_enabled:
        return {"opened": 0, "recovered": 0, "escalated": 0, "checked": 0}
    supabase = get_supabase()
    now = datetime.now(timezone.utc)
    stats = {"opened": 0, "recovered": 0, "escalated": 0, "checked": 0}

    for channel, table in (("organic", "rank_alerts"), ("maps", "maps_alerts")):
        try:
            alerts = _open_alerts(supabase, table)
            episodes = _open_episodes_for(supabase, channel)
        except Exception as exc:
            logger.error("episodes.sync_read_failed", extra={"channel": channel, "error": str(exc)})
            continue

        # 1) Open an episode for every open alert that lacks one.
        for a in alerts:
            if a["id"] in episodes:
                continue
            try:
                keyword_id = a.get("keyword_id")
                baseline_pos = _current_position(supabase, keyword_id) if channel == "organic" else None
                supabase.table("response_episodes").insert(
                    {
                        "client_id": a["client_id"],
                        "channel": channel,
                        "alert_id": a["id"],
                        "keyword_id": keyword_id,
                        "keyword": a.get("keyword") or "",
                        "classification": a.get("alert_type"),
                        "baseline": {"position": baseline_pos},
                        "next_check_at": (now + timedelta(days=CHECK_INTERVAL_DAYS)).isoformat(),
                    }
                ).execute()
                stats["opened"] += 1
            except Exception as exc:
                logger.warning("episodes.open_failed", extra={"alert_id": a["id"], "error": str(exc)})

        # 2) + 3) Recover resolved episodes; evaluate the due ones.
        for ep in episodes.values():
            try:
                resolved = _alert_resolved(supabase, table, ep["alert_id"])
                due = (_parse_ts(ep.get("next_check_at")) or now) <= now
                if not resolved and not due:
                    continue
                current_pos = _current_position(supabase, ep.get("keyword_id")) if channel == "organic" else None
                result = evaluate_episode(
                    ep, alert_resolved=resolved, current_position=current_pos, now=now
                )
                _apply_result(supabase, ep, result, current_pos, now)
                stats["checked"] += 1
                if result["verdict"] == "recovered":
                    stats["recovered"] += 1
                elif result["verdict"] == "escalate":
                    stats["escalated"] += 1
            except Exception as exc:
                logger.warning("episodes.check_failed", extra={"episode_id": ep.get("id"), "error": str(exc)})

    if any(stats.values()):
        logger.info("episodes.sync_complete", extra=stats)
    return stats


def _apply_result(supabase, episode: dict, result: dict, current_pos: Optional[float], now: datetime) -> None:
    checks = list(episode.get("checks") or [])
    checks.append({"at": now.isoformat(), "verdict": result["verdict"], "position": current_pos})
    updates: dict = {"checks": checks, "last_checked_at": now.isoformat()}

    if result["verdict"] == "recovered":
        updates.update({"status": "recovered", "recovered_at": now.isoformat(), "next_check_at": None})
        notifications.emit(
            episode["client_id"],
            kind="episode_recovered",
            title=f"Recovered: {episode.get('keyword') or 'keyword'}",
            summary="The drop this response was tracking has cleared — episode closed "
            f"after {len(checks)} check{'s' if len(checks) != 1 else ''}.",
            severity="info",
            payload={"link": f"clients/{episode['client_id']}/action-plan", "episode_id": episode["id"]},
        )
    elif result["verdict"] == "escalate":
        updates.update({"status": "escalated", "escalated_at": now.isoformat(), "next_check_at": None})
        notifications.emit(
            episode["client_id"],
            kind="episode_escalated",
            title=f"6-week rule: {episode.get('keyword') or 'keyword'} still down",
            summary="Six weeks of correct-factor work with no improvement — the SOP "
            "hands this to the senior SEOs (Kyle/Ryan) for a strategy review. "
            f"Channel: {episode.get('channel')}; classification: {episode.get('classification') or '—'}.",
            severity="critical",
            payload={"link": f"clients/{episode['client_id']}/action-plan", "episode_id": episode["id"]},
        )
    else:
        # improving / no_improvement → schedule the next recheck.
        updates["next_check_at"] = (now + timedelta(days=CHECK_INTERVAL_DAYS)).isoformat()

    supabase.table("response_episodes").update(updates).eq("id", episode["id"]).execute()


# ─────────────────────────────────────────────────────────────────────────────
# Action Plan surfacing
# ─────────────────────────────────────────────────────────────────────────────
def open_episode_notes(client_id: str) -> dict[str, str]:
    """{keyword(lower): verify-loop note} for the client's open + escalated
    episodes — appended to the Action Plan's drop rows. Best-effort."""
    try:
        supabase = get_supabase()
        rows = (
            supabase.table("response_episodes")
            .select("keyword, status, opened_at, checks")
            .eq("client_id", client_id)
            .in_("status", ["open", "escalated"])
            .execute()
        ).data or []
        now = datetime.now(timezone.utc)
        notes: dict[str, str] = {}
        for ep in rows:
            note = episode_note(ep, now)
            kw = (ep.get("keyword") or "").lower()
            if kw and note:
                notes[kw] = note
        return notes
    except Exception as exc:
        logger.warning("episodes.notes_failed", extra={"client_id": client_id, "error": str(exc)})
        return {}
