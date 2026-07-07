"""AI Visibility (Brand Strength) — scan-regression alerting.

After a brand scan completes, compare it to the client's previous scan and emit a
notification (in-app + Slack/email, via the shared notifications service) when
something regressed. Four triggers (per the module's notifications piece —
ports LABS' process-scan-alerts taxonomy, minus its credit-blackout):

  1. Visibility drop   — overall visibility fell by >= the configured points.
  2. Engine went dark  — the brand was visible on an engine last scan and is now
                         invisible on it.
  3. Misinformation    — an accuracy flag (AI stating wrong phone / "permanently
                         closed" vs GBP) appeared that wasn't there last scan.
  4. Reputation        — a high-confidence negative-sentiment mention appeared on
                         a keyword×engine cell that wasn't negative last scan
                         (LABS' reputation alarm, made transition-based so a
                         persistently negative cell alerts once, not every scan).

Comparison is restricted to keyword×engine cells present in BOTH scans, so a
partial / differently-scoped scan can't raise false regressions. The diff +
digest helpers are pure (no I/O) and unit-tested; only emit_scan_alerts touches
the DB + the notifications pipe. Mirrors services/rank_alerts → notifications.
"""

from __future__ import annotations

import logging
from typing import Optional

from config import settings

logger = logging.getLogger("brand_alerts")

ENGINE_LABELS = {
    "chatgpt": "ChatGPT", "claude": "Claude", "gemini": "Gemini",
    "perplexity": "Perplexity", "google_ai_overview": "Google AI Overview",
    "google_ai_mode": "Google AI Mode",
}


# ── pure: index one batch ─────────────────────────────────────────────────────
def index_batch(
    rows: list[dict],
    *,
    sentiment_threshold: float = -0.3,
    confidence_min: float = 0.7,
) -> dict:
    """Summarize a batch's completed brand rows for comparison. Pure.

    Returns {cells: {(keyword_id, engine): found_bool}, engines: {engine: (found,
    total)}, overall: (found, total), misinfo: [{keyword_id, engine, field}],
    negatives: [{keyword_id, engine, sentiment, confidence}]} — negatives are
    high-confidence negative-sentiment mentions (LABS' reputation-alarm bar:
    sentiment < threshold at confidence >= minimum)."""
    cells: dict[tuple, bool] = {}
    engines: dict[str, list] = {}
    overall = [0, 0]
    misinfo: list[dict] = []
    negatives: list[dict] = []
    for r in rows:
        if r.get("status") != "completed" or r.get("is_competitor_scan"):
            continue
        engine = r.get("engine")
        kid = r.get("keyword_id")
        if not engine:
            continue
        found = bool(r.get("mention_found"))
        cells[(kid, engine)] = found
        agg = engines.setdefault(engine, [0, 0])
        agg[1] += 1
        overall[1] += 1
        if found:
            agg[0] += 1
            overall[0] += 1
        for f in (r.get("response_analysis") or {}).get("accuracy_flags") or []:
            misinfo.append({"keyword_id": kid, "engine": engine, "field": f.get("field"),
                            "stated": f.get("stated"), "actual": f.get("actual")})
        sentiment = r.get("sentiment")
        confidence = r.get("confidence_score")
        if (
            sentiment is not None and confidence is not None
            and float(sentiment) < sentiment_threshold
            and float(confidence) >= confidence_min
        ):
            negatives.append({"keyword_id": kid, "engine": engine,
                              "sentiment": float(sentiment), "confidence": float(confidence)})
    return {
        "cells": cells,
        "engines": {e: tuple(v) for e, v in engines.items()},
        "overall": tuple(overall),
        "misinfo": misinfo,
        "negatives": negatives,
    }


def _pct(found: int, total: int) -> float:
    return round(100.0 * found / total, 1) if total else 0.0


# ── pure: detect regressions between two batches ──────────────────────────────
def detect_changes(prev: dict, curr: dict) -> dict:
    """Compare two index_batch() results over the cells they share. Pure.

    Returns {overall_prev_pct, overall_curr_pct, drop_pct, engines_dark:
    [engine], lost_cells: [(keyword_id, engine)], new_misinfo: [flag]}."""
    common = set(prev["cells"]) & set(curr["cells"])

    prev_found = sum(1 for k in common if prev["cells"][k])
    curr_found = sum(1 for k in common if curr["cells"][k])
    overall_prev = _pct(prev_found, len(common))
    overall_curr = _pct(curr_found, len(common))

    # Per-engine over the common cells.
    eng_prev: dict[str, list] = {}
    eng_curr: dict[str, list] = {}
    for (kid, engine) in common:
        ep = eng_prev.setdefault(engine, [0, 0]); ep[1] += 1; ep[0] += 1 if prev["cells"][(kid, engine)] else 0
        ec = eng_curr.setdefault(engine, [0, 0]); ec[1] += 1; ec[0] += 1 if curr["cells"][(kid, engine)] else 0
    engines_dark = sorted(
        e for e in eng_curr
        if eng_prev.get(e, [0, 0])[0] > 0 and eng_curr[e][0] == 0
    )

    lost_cells = sorted(
        k for k in common if prev["cells"][k] and not curr["cells"][k]
    )

    prev_keys = {(m["keyword_id"], m["engine"], m["field"]) for m in prev["misinfo"]}
    new_misinfo = [
        m for m in curr["misinfo"]
        if (m["keyword_id"], m["engine"], m["field"]) not in prev_keys
    ]

    # Reputation: negative cells that weren't negative last scan (transition-
    # based — a persistently negative cell alerted when it first turned).
    prev_negative_keys = {(m["keyword_id"], m["engine"]) for m in prev.get("negatives", [])}
    new_negatives = [
        m for m in curr.get("negatives", [])
        if (m["keyword_id"], m["engine"]) not in prev_negative_keys
    ]

    return {
        "overall_prev_pct": overall_prev,
        "overall_curr_pct": overall_curr,
        "drop_pct": round(overall_prev - overall_curr, 1),
        "engines_dark": engines_dark,
        "lost_cells": lost_cells,
        "new_misinfo": new_misinfo,
        "new_negatives": new_negatives,
    }


# ── pure: turn changes into a notification digest ─────────────────────────────
def summarize_changes(
    changes: dict,
    drop_threshold: int,
    keyword_labels: Optional[dict] = None,
) -> Optional[dict]:
    """Build a {title, summary, severity, triggers} digest, or None when nothing
    crosses an alert threshold. Pure."""
    keyword_labels = keyword_labels or {}
    drop = changes["drop_pct"]
    engines_dark = changes["engines_dark"]
    new_misinfo = changes["new_misinfo"]
    new_negatives = changes.get("new_negatives", [])
    lost_cells = changes.get("lost_cells", [])

    triggers: list[str] = []
    drop_hit = drop >= drop_threshold and changes["overall_prev_pct"] > 0
    if drop_hit:
        triggers.append("visibility_drop")
    if engines_dark:
        triggers.append("engine_dark")
    if new_misinfo:
        triggers.append("misinformation")
    if new_negatives:
        triggers.append("reputation")
    if not triggers:
        return None

    # Severity: misinformation is the most serious (critical pings the channel);
    # a new negative-sentiment mention / drop / dark engine warn.
    severity = "critical" if new_misinfo else "warning"

    if new_misinfo:
        title = "Possible AI misinformation detected"
    elif new_negatives:
        title = "Negative AI sentiment detected"
    elif engines_dark:
        n = len(engines_dark)
        title = f"Brand went invisible on {n} AI engine{'s' if n != 1 else ''}"
    else:
        title = f"AI visibility dropped {abs(drop)} points"

    parts: list[str] = []
    if drop_hit:
        parts.append(
            f"Overall visibility {changes['overall_curr_pct']}% (was {changes['overall_prev_pct']}%)."
        )
    if engines_dark:
        parts.append("No longer visible on: " + ", ".join(ENGINE_LABELS.get(e, e) for e in engines_dark) + ".")
    if (drop_hit or engines_dark) and lost_cells:
        bits = []
        for kid, engine in lost_cells[:5]:
            kw = keyword_labels.get(kid, "a keyword")
            bits.append(f"“{kw}” ({ENGINE_LABELS.get(engine, engine)})")
        extra = len(lost_cells) - 5
        parts.append("Went invisible: " + ", ".join(bits) + (f" +{extra} more" if extra > 0 else "") + ".")
    if new_misinfo:
        bits = []
        for m in new_misinfo[:5]:
            kw = keyword_labels.get(m["keyword_id"], "a keyword")
            bits.append(f"{m.get('field')} on “{kw}” ({ENGINE_LABELS.get(m['engine'], m['engine'])})")
        parts.append("Incorrect info stated: " + "; ".join(bits) + ".")
    if new_negatives:
        bits = []
        for m in new_negatives[:5]:
            kw = keyword_labels.get(m["keyword_id"], "a keyword")
            bits.append(
                f"“{kw}” on {ENGINE_LABELS.get(m['engine'], m['engine'])} "
                f"(sentiment {m['sentiment']:+.2f})"
            )
        parts.append("New negative mentions: " + "; ".join(bits) + ".")

    return {"title": title, "summary": " ".join(parts), "severity": severity, "triggers": triggers}


# ── DB-touching orchestration ─────────────────────────────────────────────────
def _batch_rows(supabase, client_id: str, scan_batch_id: str) -> list[dict]:
    from services.brand_service import list_history

    return list_history(client_id, limit=2000, scan_batch_id=scan_batch_id)


def _previous_batch_id(supabase, client_id: str, current_batch_id: str) -> Optional[str]:
    """The scan_batch_id of the client's most recent completed brand scan before
    the current one (by earliest-created cell of each batch)."""
    rows = (
        supabase.table("brand_mention_history")
        .select("scan_batch_id, created_at")
        .eq("client_id", client_id)
        .eq("is_competitor_scan", False)
        .eq("status", "completed")
        .order("created_at", desc=True)
        .limit(2000)
        .execute()
        .data
    ) or []
    for r in rows:
        bid = r.get("scan_batch_id")
        if bid and bid != current_batch_id:
            return bid
    return None


def emit_scan_alerts(client_id: str, scan_batch_id: str) -> Optional[str]:
    """Compare a just-completed scan to the previous one and emit a regression
    notification if warranted. Best-effort: returns the notification id or None,
    never raises into the scan job."""
    if not settings.brand_alerts_enabled:
        return None
    try:
        from db.supabase_client import get_supabase
        from services import notifications

        supabase = get_supabase()
        prev_id = _previous_batch_id(supabase, client_id, scan_batch_id)
        if not prev_id:
            return None  # first scan — nothing to compare against

        thresholds = {
            "sentiment_threshold": settings.brand_alert_sentiment_threshold,
            "confidence_min": settings.brand_alert_confidence_min,
        }
        curr_idx = index_batch(_batch_rows(supabase, client_id, scan_batch_id), **thresholds)
        prev_idx = index_batch(_batch_rows(supabase, client_id, prev_id), **thresholds)
        changes = detect_changes(prev_idx, curr_idx)

        kw_rows = (
            supabase.table("brand_tracked_keywords").select("id, keyword")
            .eq("client_id", client_id).execute().data
        ) or []
        labels = {k["id"]: k["keyword"] for k in kw_rows}

        digest = summarize_changes(changes, settings.brand_alert_visibility_drop_pct, labels)
        if not digest:
            return None

        return notifications.emit(
            client_id=client_id,
            kind="brand_visibility",
            title=digest["title"],
            summary=digest["summary"],
            severity=digest["severity"],
            payload={
                "link": f"clients/{client_id}/ai-visibility",
                "scan_batch_id": scan_batch_id,
                "triggers": digest["triggers"],
            },
        )
    except Exception as exc:  # never break the scan job
        logger.warning("brand_alerts.emit_failed", extra={"client_id": client_id, "error": str(exc)})
        return None
