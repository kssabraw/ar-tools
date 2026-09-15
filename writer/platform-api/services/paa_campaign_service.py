"""PAA → SEO Neo Phase 3 — the impure service layer (I/O) for the Service PAA
Campaign + the automated single-variable gate (PRD §12).

Orchestrates the campaign loop over reused suite seams — the campaign wraps the
EXISTING v1 paa_set (its content) + the EXISTING Phase-2 manifest (its asset
ledger); it does not duplicate either:

  * **create** — wrap a saved paa_set in a campaign (1:1), and **auto-add** the
    service keyword to the client's Maps tracker (``maps_keywords`` upsert) so the
    single-variable gate scan can measure it (PRD §12.2 fork 3).
  * **start** (human-confirmed) — create the PAA posts (reuses v1
    ``paa_sets_service.create_posts``) → the content state; capture the baseline
    geo-grid rank.
  * **sync** (``run_paa_campaign_sync``) — the inline scheduler sweep (like
    ``response_episodes.run_episode_sync``): advance settling → scan_ready, read a
    completed scan through the gate (moved / drill / HALT), schedule maintenance,
    and re-evaluate the rinse loop. Cheap/free steps only; best-effort per campaign.
  * **confirm_scan** (human-confirmed) — kick a single-keyword ``manual`` geo-grid
    scan for the service keyword (reuses ``local_dominator.enqueue_maps_scan``).
  * **propose_drill / confirm_drill** (human-confirmed) — pull sub-PAAs seeded from
    the current level's questions (reuses ``paa_sets_service.pull_paa``), preview
    them, and on confirm add them as drill_level+1 items + create their posts.

Autonomy (PRD §12.2 fork 1): **hybrid propose-confirm** — the two paid/content
steps (scan, drill) are human-confirmed; everything else auto-advances.

Guardrail (PRD §9): the campaign ORCHESTRATES + TRACKS the loop and hands off the
Phase-2 manifest (build/cost/QA) — it NEVER executes the SEO Neo authority layer.
The "moved" branch only refreshes the manifest; there is no code path here that
runs a link blast. HALT is a STOP (re-check on-page/entity), never "keep writing."

Baseline note (single-variable measurement): the gate compares a post-settle scan
against the campaign's ``baseline_rank`` — captured at start from the latest
existing completed geo-grid scan for the service keyword. A keyword the client has
never scanned has no baseline; the first post-settle scan then ADOPTS itself as the
baseline (``no_data`` branch) and the campaign re-arms one settle→scan cycle to
obtain the after-reading. Once the auto-added keyword accrues scheduled scans this
self-heals, and any keyword with scan history reads a clean before/after on cycle 1.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import paa_campaign, paa_seo, paa_sets_service

logger = logging.getLogger(__name__)

# Terminal-ish or human-gated states the sweep never auto-advances: scan_ready and
# drill_ready wait on a human confirm; halted waits on a human; moved is transient
# (the sweep moves it straight to maintenance). Draft waits on the start action.
_HUMAN_GATED = {"draft", "scan_ready", "drill_ready", "halted"}


def _sb():
    return get_supabase()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _client(client_id: str) -> dict:
    rows = (
        _sb().table("clients").select("id, name, business_location, gbp")
        .eq("id", client_id).limit(1).execute()
    ).data or []
    if not rows:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="client_not_found")
    return rows[0]


def _campaign(campaign_id: str) -> dict:
    rows = (
        _sb().table("paa_campaigns").select("*").eq("id", campaign_id).limit(1).execute()
    ).data or []
    if not rows:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="paa_campaign_not_found")
    return rows[0]


# ── Maps tracker auto-add (PRD §12.2 fork 3) ──────────────────────────────────


def _ensure_tracked_keyword(client_id: str, keyword: str) -> None:
    """Auto-add the service keyword to the client's Maps tracker so the gate scan
    can measure it. Idempotent (the maps router's own upsert pattern). Best-effort
    — a failure here never blocks campaign creation (the scan step will surface the
    missing keyword instead)."""
    kw = (keyword or "").strip()
    if not kw:
        return
    try:
        _sb().table("maps_keywords").upsert(
            {"client_id": client_id, "keyword": kw, "active": True},
            on_conflict="client_id,keyword",
            ignore_duplicates=True,
        ).execute()
    except Exception as exc:  # pragma: no cover - best-effort
        logger.warning("paa_campaign.track_keyword_failed",
                       extra={"client_id": client_id, "keyword": kw, "error": str(exc)})


# ── geo-grid scan reads (the gate's measurement source) ───────────────────────


def _latest_scan_result(
    client_id: str, keyword: str, *, trigger: Optional[str] = None,
    after: Optional[str] = None,
) -> Optional[dict]:
    """The most-recent completed geo-grid scan result for a keyword.

    Returns ``{scan_id, average_rank, top3_pins, created_at}`` or None. ``trigger``
    optionally restricts to 'manual' (a campaign's own scan) or 'scheduled' (the
    maintenance piggyback). ``after`` (ISO) keeps only scans created at/after that
    instant — used to match the scan the campaign just requested. Best-effort."""
    try:
        q = (
            _sb().table("maps_scans").select("id, created_at, trigger, status")
            .eq("client_id", client_id).eq("status", "complete")
            .order("created_at", desc=True).limit(25)
        )
        if trigger:
            q = q.eq("trigger", trigger)
        scans = q.execute().data or []
        if after:
            scans = [s for s in scans if (s.get("created_at") or "") >= after]
        if not scans:
            return None
        scan_ids = [s["id"] for s in scans]
        results = (
            _sb().table("maps_scan_results").select("scan_id, average_rank, top3_pins")
            .in_("scan_id", scan_ids).eq("keyword", keyword).execute()
        ).data or []
        by_scan = {r["scan_id"]: r for r in results}
        for s in scans:  # newest first
            r = by_scan.get(s["id"])
            if r:
                return {
                    "scan_id": s["id"],
                    "average_rank": r.get("average_rank"),
                    "top3_pins": r.get("top3_pins"),
                    "created_at": s.get("created_at"),
                }
        return None
    except Exception as exc:  # pragma: no cover - best-effort
        logger.warning("paa_campaign.scan_read_failed",
                       extra={"client_id": client_id, "keyword": keyword, "error": str(exc)})
        return None


# ── create + read ─────────────────────────────────────────────────────────────


def create_campaign(set_id: str, user_id: Optional[str] = None) -> dict:
    """Wrap a saved PAA set in a campaign (1:1). Auto-adds the service keyword to
    the Maps tracker and captures the starting baseline rank. Idempotent — a set
    that already has a campaign returns it."""
    from fastapi import HTTPException

    set_row = paa_sets_service.get_set(set_id)
    client_id = set_row["client_id"]
    service_keyword = (set_row.get("service_keyword") or "").strip()
    if not service_keyword:
        raise HTTPException(status_code=400, detail="service_keyword_required")

    existing = (
        _sb().table("paa_campaigns").select("*").eq("set_id", set_id).limit(1).execute()
    ).data or []
    if existing:
        return get_campaign(campaign_id=existing[0]["id"])

    _ensure_tracked_keyword(client_id, service_keyword)
    baseline = _latest_scan_result(client_id, service_keyword)
    now = _now()
    row = {
        "set_id": set_id,
        "client_id": client_id,
        "service_keyword": service_keyword,
        "location": set_row.get("location"),
        "state": "draft",
        "drill_level": 0,
        "baseline_rank": (baseline or {}).get("average_rank"),
        "history": paa_campaign.record_transition([], "new", "draft", now,
                                                  "campaign created"),
        "created_by": user_id,
    }
    try:
        _sb().table("paa_campaigns").insert(row).execute()
    except Exception:
        # Unique set_id race — adopt the winner.
        rows = (
            _sb().table("paa_campaigns").select("*").eq("set_id", set_id).limit(1).execute()
        ).data or []
        if not rows:
            raise
    campaign = (
        _sb().table("paa_campaigns").select("*").eq("set_id", set_id).limit(1).execute()
    ).data[0]
    return get_campaign(campaign_id=campaign["id"])


def get_campaign(*, campaign_id: Optional[str] = None, set_id: Optional[str] = None) -> dict:
    """The campaign view: the row + its current next-action descriptor. Returns
    ``{exists: False}`` when a set has no campaign yet."""
    from fastapi import HTTPException

    if campaign_id:
        rows = _sb().table("paa_campaigns").select("*").eq("id", campaign_id).limit(1).execute().data or []
    elif set_id:
        rows = _sb().table("paa_campaigns").select("*").eq("set_id", set_id).limit(1).execute().data or []
    else:
        raise HTTPException(status_code=400, detail="campaign_id_or_set_id_required")
    if not rows:
        return {"exists": False, "set_id": set_id}
    campaign = rows[0]
    return {
        "exists": True,
        "campaign": campaign,
        "next_action": paa_campaign.next_action(campaign),
        "enabled": settings.paa_campaign_enabled,
    }


def _apply(campaign_id: str, updates: dict, *, from_state: str, to_state: str,
           note: Optional[str] = None) -> None:
    """Persist a state transition, appending to the history log. Best-effort."""
    now = _now()
    campaign = _campaign(campaign_id)
    payload = dict(updates)
    payload["state"] = to_state
    payload["history"] = paa_campaign.record_transition(
        campaign.get("history"), from_state, to_state, now, note
    )
    payload["updated_at"] = "now()"
    _sb().table("paa_campaigns").update(payload).eq("id", campaign_id).execute()


# ── start (human-confirmed: draft → content) ──────────────────────────────────


async def start_campaign(campaign_id: str, user_id: str, acknowledge: bool = False) -> dict:
    """Create the PAA posts for the root level and enter the content state. Reuses
    v1 ``create_posts`` (cannibalization guard + one blog run per PAA + best-effort
    GBP/syndication). Returns ``{view, run_ids, blocked?, gates?}``; the router
    dispatches the returned run ids."""
    campaign = _campaign(campaign_id)
    if campaign["state"] != "draft":
        from fastapi import HTTPException

        raise HTTPException(status_code=409, detail="paa_campaign_not_draft")

    result = await paa_sets_service.create_posts(
        campaign["set_id"], user_id=user_id, acknowledge=acknowledge
    )
    if result.get("blocked"):
        return {"blocked": True, "gates": result.get("gates"), "run_ids": [],
                "view": get_campaign(campaign_id=campaign_id)}

    _apply(campaign_id, {}, from_state="draft", to_state="content",
           note=f"created {result.get('created', 0)} PAA post(s)")
    return {"blocked": False, "run_ids": result.get("run_ids", []),
            "created": result.get("created", 0),
            "view": get_campaign(campaign_id=campaign_id)}


# ── confirm scan (human-confirmed: scan_ready → scanning) ─────────────────────


def confirm_scan(campaign_id: str) -> dict:
    """Kick a single-keyword ``manual`` geo-grid scan for the service keyword and
    enter the scanning state. Reuses ``local_dominator.enqueue_maps_scan``."""
    from fastapi import HTTPException

    from services.local_dominator import enqueue_maps_scan

    campaign = _campaign(campaign_id)
    if campaign["state"] != "scan_ready":
        raise HTTPException(status_code=409, detail="paa_campaign_not_scan_ready")

    enqueue_maps_scan(campaign["client_id"], trigger="manual",
                      keywords=[campaign["service_keyword"]])
    now = _now()
    _apply(campaign_id, {"scan_requested_at": now.isoformat()},
           from_state="scan_ready", to_state="scanning",
           note="single-variable scan requested")
    return get_campaign(campaign_id=campaign_id)


# ── drill (human-confirmed: drill_ready → content) ────────────────────────────


async def propose_drill(campaign_id: str) -> dict:
    """Preview the drill round: pull sub-PAAs seeded from the current level's
    chosen questions (the natural PAA tree). Read-only — does not persist. Returns
    ``{seeds, candidates}`` for the human to confirm."""
    campaign = _campaign(campaign_id)
    set_row = paa_sets_service.get_set(campaign["set_id"])
    seeds = paa_campaign.drill_seed_questions(set_row.get("items") or [],
                                              int(campaign.get("drill_level") or 0))
    # Pull each seed's People-Also-Ask children; merge unique candidates. Bounded
    # to a few seeds — each seed is one billed SERP call, and the preview may be
    # re-opened, so keep the per-preview cost small.
    seen: set[str] = set()
    candidates: list[dict] = []
    for seed in seeds[:3]:  # bounded paid fan-out
        try:
            pulled = await paa_sets_service.pull_paa(
                campaign["client_id"], service_keyword=seed,
                geo_mode=set_row.get("geo_mode") or "geo",
                location_override=set_row.get("location"),
            )
        except Exception as exc:  # pragma: no cover - best-effort
            logger.warning("paa_campaign.drill_pull_failed",
                           extra={"campaign_id": campaign_id, "seed": seed, "error": str(exc)})
            continue
        for c in pulled.get("candidates") or []:
            key = (c.get("question") or "").lower()
            if key and key not in seen:
                seen.add(key)
                candidates.append(c)
    return {"seeds": seeds, "candidates": candidates,
            "drill_level": int(campaign.get("drill_level") or 0) + 1}


async def confirm_drill(campaign_id: str, items: list[dict], user_id: str,
                        acknowledge: bool = False) -> dict:
    """Add the confirmed sub-PAAs as drill_level+1 items to the SAME set + create
    their posts, and re-enter the content state. Returns ``{view, run_ids}``."""
    from fastapi import HTTPException

    campaign = _campaign(campaign_id)
    if campaign["state"] != "drill_ready":
        raise HTTPException(status_code=409, detail="paa_campaign_not_drill_ready")
    chosen = [i for i in (items or []) if (i.get("question") or "").strip()]
    if not chosen:
        raise HTTPException(status_code=400, detail="no_questions_selected")

    next_level = int(campaign.get("drill_level") or 0) + 1
    rows = []
    # Position drill items after the deepest existing position.
    existing = (
        _sb().table("paa_items").select("position").eq("set_id", campaign["set_id"])
        .order("position", desc=True).limit(1).execute()
    ).data or []
    pos = ((existing[0]["position"] if existing else 0) or 0) + 1
    for it in chosen:
        q = " ".join((it.get("question") or "").split()).strip()
        rows.append({
            "set_id": campaign["set_id"],
            "client_id": campaign["client_id"],
            "question": q,
            "slug": it.get("slug") or paa_seo.slugify_question(q),
            "volume": it.get("volume"),
            "cpc_usd": it.get("cpc_usd") if it.get("cpc_usd") is not None else it.get("cpc"),
            "competition": it.get("competition"),
            "chosen": True,
            "drill_level": next_level,
            "position": pos,
        })
        pos += 1
    _sb().table("paa_items").insert(rows).execute()

    # New baseline for this level = the current rank (measure whether the drill
    # content moves it further), captured from the latest scan before drilling.
    baseline = _latest_scan_result(campaign["client_id"], campaign["service_keyword"])
    result = await paa_sets_service.create_posts(
        campaign["set_id"], user_id=user_id, acknowledge=acknowledge
    )
    if result.get("blocked"):
        return {"blocked": True, "gates": result.get("gates"), "run_ids": [],
                "view": get_campaign(campaign_id=campaign_id)}

    _apply(campaign_id, {
        "drill_level": next_level,
        "baseline_rank": (baseline or {}).get("average_rank"),
        "current_rank": None,
    }, from_state="drill_ready", to_state="content",
        note=f"drilled to level {next_level}: {result.get('created', 0)} sub-PAA post(s)")
    return {"blocked": False, "run_ids": result.get("run_ids", []),
            "view": get_campaign(campaign_id=campaign_id)}


def reset_halted(campaign_id: str) -> dict:
    """Human action after a HALT: on-page/entity re-checked → re-arm the campaign
    for another measured cycle (back to scan_ready to re-scan the fixed page)."""
    from fastapi import HTTPException

    campaign = _campaign(campaign_id)
    if campaign["state"] != "halted":
        raise HTTPException(status_code=409, detail="paa_campaign_not_halted")
    _apply(campaign_id, {"halted_reason": None}, from_state="halted",
           to_state="scan_ready", note="halt reset — on-page/entity re-checked, re-scanning")
    return get_campaign(campaign_id=campaign_id)


# ── content completion (per drill level) ──────────────────────────────────────


def _content_ready(set_id: str, drill_level: int) -> bool:
    """True once every chosen item at ``drill_level`` has a finished + verified
    run. Runs ``verify_posts`` (best-effort) to compute checks, then confirms each
    current-level item has a run_id + a persisted verdict."""
    try:
        paa_sets_service.verify_posts(set_id)
    except Exception:  # pragma: no cover - best-effort
        pass
    items = (
        _sb().table("paa_items").select("id, run_id, checks, drill_level")
        .eq("set_id", set_id).eq("chosen", True).eq("drill_level", drill_level).execute()
    ).data or []
    if not items:
        return False
    return all(i.get("run_id") and i.get("checks") for i in items)


# ── the gate read (scanning → moved / drill_ready / halted) ───────────────────


def _read_gate(campaign: dict, scan: dict) -> dict:
    """Evaluate a completed scan against the campaign baseline. Pure delegation to
    ``paa_campaign.evaluate_gate`` (baseline top3 not tracked per-level → None)."""
    return paa_campaign.evaluate_gate(
        campaign.get("baseline_rank"),
        scan.get("average_rank"),
        current_top3=scan.get("top3_pins"),
        drill_level=int(campaign.get("drill_level") or 0),
        cap=settings.paa_campaign_drill_cap,
    )


def _on_moved(campaign: dict, gate: dict, now: datetime) -> None:
    """Moved → schedule maintenance, refresh the manifest hand-off, notify."""
    next_at = paa_campaign.next_rinse_at(now, settings.paa_campaign_rinse_days)
    _apply(campaign["id"], {
        "current_rank": None if gate.get("rank_delta") is None else campaign.get("current_rank"),
        "next_action_at": next_at.isoformat(),
    }, from_state="evaluating", to_state="maintenance",
        note=gate.get("reason"))
    # Build/refresh the prep-sheet manifest so the (tracked, never-executed)
    # authority hand-off is ready — content moved, so it's now worth amplifying
    # (reference §2). Best-effort.
    try:
        from services import paa_manifest_service

        paa_manifest_service.build_manifest(campaign["set_id"])
    except Exception as exc:  # pragma: no cover - best-effort
        logger.warning("paa_campaign.manifest_refresh_failed",
                       extra={"campaign_id": campaign["id"], "error": str(exc)})
    _notify(campaign, "paa_campaign_moved", "info",
            f"PAA content moved '{campaign['service_keyword']}'",
            paa_campaign.gate_summary_text(campaign, gate)
            + " Next: hand off the prep-sheet manifest and consider the next "
            "topically-related service.")


def _on_halted(campaign: dict, gate: dict) -> None:
    """HALT → terminal-until-human; critical notification + best-effort strategist
    escalation (re-check on-page/entity). Guardrail: HALT is a STOP."""
    _apply(campaign["id"], {"halted_reason": gate.get("reason")},
           from_state="evaluating", to_state="halted", note=gate.get("reason"))
    _notify(campaign, "paa_campaign_halted", "critical",
            f"HALT: '{campaign['service_keyword']}' hasn't moved after drilling",
            paa_campaign.gate_summary_text(campaign, gate))
    # Prepare the on-page/entity re-check case file while it's hot (best-effort;
    # no-ops when strategist is disabled) — the same hook response_episodes uses.
    try:
        from services.strategist import enqueue_strategy_review

        enqueue_strategy_review(
            campaign["client_id"], trigger="escalation",
            escalation_context={
                "kind": "paa_campaign_halted",
                "campaign_id": campaign["id"],
                "service_keyword": campaign["service_keyword"],
                "drill_level": campaign.get("drill_level"),
                "reason": gate.get("reason"),
            },
        )
    except Exception as exc:  # pragma: no cover - best-effort
        logger.warning("paa_campaign.halt_escalation_failed",
                       extra={"campaign_id": campaign["id"], "error": str(exc)})


def _notify(campaign: dict, kind: str, severity: str, title: str, summary: str) -> None:
    from services import notifications

    notifications.emit(
        campaign["client_id"], kind=kind, title=title, summary=summary,
        severity=severity,
        payload={"link": f"clients/{campaign['client_id']}/paa-sets",
                 "campaign_id": campaign["id"], "set_id": campaign["set_id"]},
    )


# ── the inline scheduler sweep ────────────────────────────────────────────────


def run_paa_campaign_sync() -> dict:
    """Advance due campaigns across all clients (the daily scheduler sweep, like
    ``response_episodes.run_episode_sync``). Best-effort per campaign — one bad row
    never stops the sweep. Only the cheap/free transitions run here; the two
    paid/content steps (scan, drill) wait on a human confirm."""
    stats = {"settled": 0, "evaluated": 0, "moved": 0, "drilled": 0,
             "halted": 0, "maintenance": 0}
    if not settings.paa_campaign_enabled:
        return stats

    now = _now()
    try:
        rows = (_sb().table("paa_campaigns").select("*").execute()).data or []
    except Exception as exc:
        logger.error("paa_campaign.sync_read_failed", extra={"error": str(exc)})
        return stats
    # Only advance the auto-advancing states; the human-gated ones (draft /
    # scan_ready / drill_ready / halted) wait on a person.
    campaigns = [c for c in rows if c.get("state") not in _HUMAN_GATED]

    for c in campaigns:
        try:
            _advance(c, now, stats)
        except Exception as exc:
            logger.warning("paa_campaign.advance_failed",
                           extra={"campaign_id": c.get("id"), "error": str(exc)})

    if any(stats.values()):
        logger.info("paa_campaign.sync_complete", extra=stats)
    return stats


def _advance(campaign: dict, now: datetime, stats: dict) -> None:
    state = campaign["state"]
    cid = campaign["id"]

    if state == "content":
        if _content_ready(campaign["set_id"], int(campaign.get("drill_level") or 0)):
            su = paa_campaign.settle_until(now, settings.paa_campaign_settle_days)
            _apply(cid, {"settle_until": su.isoformat()},
                   from_state="content", to_state="settling",
                   note="content published + verified; settling before the scan")
            stats["settled"] += 1
        return

    if state == "settling":
        if paa_campaign.is_settle_elapsed(campaign, now):
            _apply(cid, {}, from_state="settling", to_state="scan_ready",
                   note="settle elapsed — ready for the single-variable scan")
            _notify(campaign, "paa_campaign_scan_ready", "info",
                    f"Ready to scan '{campaign['service_keyword']}'",
                    "Content has settled — confirm the single-variable Maps scan to "
                    "read the gate. " + paa_campaign.GATE_CONFIDENCE_NOTE)
        return

    if state == "scanning":
        scan = _latest_scan_result(
            campaign["client_id"], campaign["service_keyword"],
            trigger="manual", after=campaign.get("scan_requested_at"),
        )
        if not scan:
            return  # scan still in flight
        gate = _read_gate(campaign, scan)
        # Record the reading first.
        _apply(cid, {"current_rank": scan.get("average_rank"),
                     "last_scan_id": scan.get("scan_id")},
               from_state="scanning", to_state="evaluating", note=gate.get("reason"))
        campaign = _campaign(cid)  # refresh for the branch handlers
        stats["evaluated"] += 1
        branch = gate.get("branch")
        if branch == "moved":
            _on_moved(campaign, gate, now); stats["moved"] += 1
        elif branch == "drill":
            _apply(cid, {}, from_state="evaluating", to_state="drill_ready",
                   note=gate.get("reason"))
            _notify(campaign, "paa_campaign_drill_ready", "info",
                    f"No movement on '{campaign['service_keyword']}' — drill deeper?",
                    paa_campaign.gate_summary_text(campaign, gate))
            stats["drilled"] += 1
        elif branch == "halt":
            _on_halted(campaign, gate); stats["halted"] += 1
        else:  # no_data — adopt this scan as the baseline, re-arm one cycle
            su = paa_campaign.settle_until(now, settings.paa_campaign_settle_days)
            _apply(cid, {"baseline_rank": scan.get("average_rank"),
                         "settle_until": su.isoformat()},
                   from_state="evaluating", to_state="settling",
                   note="no baseline — this scan set the baseline; re-measuring after settle")
        return

    if state == "maintenance":
        if not paa_campaign.is_rinse_due(campaign, now):
            return
        # Piggyback on the client's SCHEDULED scans ($0 extra) — read the latest.
        scan = _latest_scan_result(campaign["client_id"], campaign["service_keyword"],
                                   trigger="scheduled")
        next_at = paa_campaign.next_rinse_at(now, settings.paa_campaign_rinse_days)
        if scan and scan.get("average_rank") is not None:
            # A slip (rank got worse by the move threshold) surfaces for review.
            base = campaign.get("current_rank") or campaign.get("baseline_rank")
            slip = (base is not None
                    and (float(scan["average_rank"]) - float(base)) >= paa_campaign.MOVE_MIN_POSITIONS)
            _apply(cid, {"current_rank": scan.get("average_rank"),
                         "next_action_at": next_at.isoformat()},
                   from_state="maintenance", to_state="maintenance",
                   note="rinse re-check")
            if slip:
                _notify(campaign, "paa_campaign_slip", "warning",
                        f"'{campaign['service_keyword']}' slipped on the rinse check",
                        "Ranking gave ground on the maintenance re-check — consider a "
                        "refresh or the next drill round.")
        else:
            _apply(cid, {"next_action_at": next_at.isoformat()},
                   from_state="maintenance", to_state="maintenance",
                   note="rinse re-check — no scheduled scan to read yet")
        stats["maintenance"] += 1
        return
