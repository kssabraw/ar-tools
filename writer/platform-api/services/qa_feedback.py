"""QA Agent — verdict-accuracy feedback loop (the measurement half of QA).

QA emits a verdict per review; humans then act on the board. When their action
CONTRADICTS the verdict — shipping a deliverable QA flagged, or bouncing one QA
passed — the verdict was inaccurate. Capturing that is what turns "QA runs" into
"QA is trustworthy": without it a false-fail epidemic (like the CTA-check bug,
2026-09-09) is invisible until someone hand-queries the DB.

Design mirrors the intervention-outcome loop (services/interventions.py) and the
response-episode verify loop: a pure classification core + a best-effort daily
sweep that reads already-recorded board state and writes a disposition back onto
the ``qa_reviews`` row. No new table, no LLM, no board effects — read-only
measurement.

**Why board TRAJECTORY, not actor attribution.** QA's own outcome move is
actor-less but auto-advance (a VA ticking the last Rework subtask) carries the
human's id, so "who moved it" can't cleanly separate a deliberate human override
from the rework loop. Instead we key on status transitions **QA itself never
makes**: QA-fail lands a task in ``for_revision`` and QA-pass never moves it to
``for_revision`` — so a *shipped-ward* move after a fail, or a *for_revision*
move after a pass, is necessarily human/client-driven. A subsequent review
closes the prior review's window (the board then reflects the NEW verdict), so
the normal fail → rework → re-QA-pass → advance happy path reads as UPHELD, not
an overturn.

Everything here is pure except ``run_qa_feedback_sweep`` / ``accuracy_report``
(clearly separated at the bottom), so the classification + stats are unit-tested
in isolation.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------
PENDING = "pending"
UPHELD = "upheld"
OVERTURNED = "overturned"
RESOLVED_ACCEPT = "resolved_accept"
RESOLVED_REJECT = "resolved_reject"
NOT_APPLICABLE = "not_applicable"

TOO_STRICT = "too_strict"      # QA flagged; humans shipped it anyway (false alarm)
TOO_LENIENT = "too_lenient"    # QA passed; humans bounced it / re-review flagged (missed defect)

# Statuses QA never moves a deliverable to, so their appearance after a review is
# a human/client signal. Kept as module constants (the seeded task_statuses set):
# shipping-ward = past QA toward/at the client; rework = the revision lane.
SHIPPED_STATUSES: frozenset[str] = frozenset({"sent_to_client", "client_approved", "complete"})
REWORK_STATUSES: frozenset[str] = frozenset({"for_revision"})

# Verdict classes (from qa_signals): a "shippable" verdict claims the deliverable
# is ready; a "flagged" verdict claims it needs work.
_SHIPPABLE = frozenset({"pass", "advisory"})
_FLAGGED = frozenset({"fail", "revisions"})


def _d(disposition: str, direction: Optional[str] = None, signal: str = "") -> dict[str, Any]:
    return {"disposition": disposition, "direction": direction, "signal": signal}


# ---------------------------------------------------------------------------
# Event assembly (pure)
# ---------------------------------------------------------------------------
def _parse_ts(value: Any) -> Optional[datetime]:
    """Parse a Supabase timestamptz string to an aware datetime; None if unparsable.
    Tolerant of a trailing 'Z'. Pure."""
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def build_events(
    status_activity: list[dict],
    reviews: list[dict],
    review_id: Any,
    review_at: Any,
) -> list[dict]:
    """Merge a task's later status changes + its later QA reviews into one
    chronological event stream AFTER the review under judgement. Pure.

    ``status_activity`` are ``task_activity`` rows of kind ``status_changed``
    (``detail.to`` = the new status key); ``reviews`` are the task's ``qa_reviews``
    rows (``id`` + ``verdict`` + ``created_at``). Events at/before the review's
    own timestamp — and the review row itself — are excluded. Rows with an
    unparsable timestamp are dropped (can't be ordered)."""
    cutoff = _parse_ts(review_at)
    if cutoff is None:
        return []
    events: list[dict] = []
    for a in status_activity:
        at = _parse_ts(a.get("created_at"))
        if at is None or at <= cutoff:
            continue
        to = (a.get("detail") or {}).get("to")
        if to:
            events.append({"type": "status", "status": to, "_at": at})
    for rv in reviews:
        if rv.get("id") == review_id:
            continue
        at = _parse_ts(rv.get("created_at"))
        if at is None or at <= cutoff:
            continue
        events.append({"type": "review", "verdict": rv.get("verdict"), "_at": at})
    events.sort(key=lambda e: e["_at"])
    return events


# ---------------------------------------------------------------------------
# Classification (pure) — the disposition decision
# ---------------------------------------------------------------------------
def classify_disposition(
    verdict: Optional[str],
    events: list[dict],
    *,
    shipped: frozenset[str] = SHIPPED_STATUSES,
    rework: frozenset[str] = REWORK_STATUSES,
) -> dict[str, Any]:
    """Fold a review's verdict + the board events after it into a disposition.

    A subsequent REVIEW closes the window — the prior review is judged only on
    what happened before the board took a fresh verdict. Precedence within the
    window is: an explicit contradicting status move, then the closing review's
    verdict, then a confirming status move. Pure. Returns
    ``{disposition, direction, signal}``.

    - shippable verdict (pass/advisory): OVERTURNED/too_lenient if bounced to
      rework or the closing re-review flagged it; UPHELD if it advanced shipped-
      ward or the re-review agreed; else PENDING.
    - flagged verdict (fail/revisions): OVERTURNED/too_strict if it shipped
      before any re-review vouched for it; UPHELD if a re-review ran (reworked →
      passed, or still flagged = consistent); else PENDING.
    - needs_human: RESOLVED_ACCEPT/REJECT from the first decisive human move or
      re-review; else PENDING.
    - skipped / unknown: NOT_APPLICABLE.
    """
    if verdict == "skipped" or verdict not in (_SHIPPABLE | _FLAGGED | {"needs_human"}):
        return _d(NOT_APPLICABLE)

    # Window = events up to (and including) the first subsequent review.
    window: list[dict] = []
    next_review: Optional[dict] = None
    for e in events:
        if e["type"] == "review":
            next_review = e
            break
        window.append(e)

    shipped_hit = next((e for e in window if e["type"] == "status" and e["status"] in shipped), None)
    rework_hit = next((e for e in window if e["type"] == "status" and e["status"] in rework), None)
    nr_verdict = (next_review or {}).get("verdict")

    if verdict in _SHIPPABLE:
        if rework_hit:
            return _d(OVERTURNED, TOO_LENIENT, f"bounced to {rework_hit['status']} after a passing review")
        if nr_verdict in _FLAGGED:
            return _d(OVERTURNED, TOO_LENIENT, f"re-review returned {nr_verdict}")
        if shipped_hit:
            return _d(UPHELD, None, f"advanced to {shipped_hit['status']}")
        if nr_verdict in _SHIPPABLE:
            return _d(UPHELD, None, "re-review agreed")
        return _d(PENDING)

    if verdict in _FLAGGED:
        if shipped_hit:
            return _d(OVERTURNED, TOO_STRICT, f"shipped to {shipped_hit['status']} with no passing re-review")
        if nr_verdict in _SHIPPABLE:
            return _d(UPHELD, None, "reworked, then passed re-review")
        if nr_verdict in _FLAGGED:
            return _d(UPHELD, None, "re-review still flagged")
        return _d(PENDING)

    # needs_human
    if shipped_hit:
        return _d(RESOLVED_ACCEPT, None, f"advanced to {shipped_hit['status']}")
    if rework_hit:
        return _d(RESOLVED_REJECT, None, f"bounced to {rework_hit['status']}")
    if nr_verdict in _SHIPPABLE:
        return _d(RESOLVED_ACCEPT, None, "re-review passed")
    if nr_verdict in _FLAGGED:
        return _d(RESOLVED_REJECT, None, "re-review flagged")
    return _d(PENDING)


# ---------------------------------------------------------------------------
# Accuracy rollup (pure)
# ---------------------------------------------------------------------------
def _verdict_class(verdict: Optional[str]) -> Optional[str]:
    if verdict in _SHIPPABLE:
        return "shippable"
    if verdict in _FLAGGED:
        return "flagged"
    if verdict == "needs_human":
        return "deferred"
    return None


def accuracy_stats(rows: list[dict], *, min_samples: int = 3) -> dict[str, Any]:
    """Roll disposition rows into verdict-accuracy metrics. Pure.

    ``rows`` are ``{rubric, verdict, human_disposition}``. Reports, over the
    reviews whose disposition is DECIDED (upheld/overturned — pending, resolved_*
    and not_applicable are excluded from a rate):
      - per verdict class (shippable / flagged): upheld, overturned, rate;
        a flagged overturn is a **false alarm** (too_strict), a shippable
        overturn a **missed defect** (too_lenient);
      - per rubric: decided + overturned;
      - overall overturn rate + counts of pending / resolved / not_applicable.
    ``headline`` is populated only when ``decided >= min_samples`` (a rate off 1–2
    reviews is noise)."""
    by_class: dict[str, dict[str, int]] = {}
    by_rubric: dict[str, dict[str, int]] = defaultdict(lambda: {"decided": 0, "overturned": 0})
    pending = resolved = not_applicable = 0
    false_alarms = missed_defects = 0

    for r in rows:
        disp = r.get("human_disposition")
        cls = _verdict_class(r.get("verdict"))
        if disp in (PENDING, None):
            pending += 1
            continue
        if disp in (RESOLVED_ACCEPT, RESOLVED_REJECT):
            resolved += 1
            continue
        if disp == NOT_APPLICABLE:
            not_applicable += 1
            continue
        # decided: upheld / overturned
        if cls in ("shippable", "flagged"):
            slot = by_class.setdefault(cls, {"upheld": 0, "overturned": 0})
            rubric = r.get("rubric") or "unknown"
            by_rubric[rubric]["decided"] += 1
            if disp == OVERTURNED:
                slot["overturned"] += 1
                by_rubric[rubric]["overturned"] += 1
                if cls == "flagged":
                    false_alarms += 1
                else:
                    missed_defects += 1
            else:
                slot["upheld"] += 1

    def _rate(slot: dict[str, int]) -> Optional[float]:
        n = slot["upheld"] + slot["overturned"]
        return round(slot["overturned"] / n, 3) if n else None

    for slot in by_class.values():
        slot["overturn_rate"] = _rate(slot)

    decided = sum(s["upheld"] + s["overturned"] for s in by_class.values())
    overturned = sum(s["overturned"] for s in by_class.values())
    overall_rate = round(overturned / decided, 3) if decided else None

    out: dict[str, Any] = {
        "decided": decided,
        "overturned": overturned,
        "overturn_rate": overall_rate,
        "false_alarms": false_alarms,      # flagged deliverables shipped anyway
        "missed_defects": missed_defects,  # passed deliverables later bounced
        "pending": pending,
        "resolved": resolved,
        "not_applicable": not_applicable,
        "by_class": by_class,
        "by_rubric": {k: v for k, v in by_rubric.items()},
    }
    if decided >= min_samples and overall_rate is not None:
        out["headline"] = (
            f"{overturned}/{decided} decided QA verdicts overturned "
            f"({overall_rate:.0%}) — {false_alarms} false alarm(s), {missed_defects} missed defect(s)"
        )
    return out


# ===========================================================================
# Impure: the daily sweep + the read the endpoint / context use.
# ===========================================================================
def run_qa_feedback_sweep(*, window_days: Optional[int] = None, limit: Optional[int] = None) -> dict:
    """Classify (or re-classify) the disposition of recent QA reviews from the
    board's own record, writing it back onto ``qa_reviews``. Best-effort, no
    board effects. Self-gated: no-ops unless ``qa_enabled AND qa_feedback_enabled``.

    Targets reviews within the window whose disposition is not yet terminal
    (null / pending), grouped by task so each task's activity + reviews are read
    once. A terminal disposition is written once and left alone; a still-pending
    one is re-evaluated on the next sweep as the board moves."""
    from config import settings

    if not (settings.qa_enabled and settings.qa_feedback_enabled):
        return {"skipped": "disabled"}
    from db.supabase_client import get_supabase

    supabase = get_supabase()
    window_days = window_days or settings.qa_feedback_window_days
    limit = limit or settings.qa_feedback_sweep_limit
    since = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
    try:
        reviews = (
            supabase.table("qa_reviews")
            .select("id, task_id, verdict, created_at, human_disposition")
            .gte("created_at", since)
            .or_("human_disposition.is.null,human_disposition.eq.pending")
            .order("created_at", desc=False)
            .limit(limit)
            .execute()
        ).data or []
    except Exception as exc:
        logger.warning("qa_feedback_sweep_query_failed", extra={"error": str(exc)})
        return {"skipped": "query_failed"}

    by_task: dict[str, list[dict]] = defaultdict(list)
    for r in reviews:
        if r.get("task_id"):
            by_task[r["task_id"]].append(r)

    scanned = updated = 0
    for task_id, task_reviews in by_task.items():
        try:
            acts = (
                supabase.table("task_activity")
                .select("kind, detail, created_at")
                .eq("task_id", task_id).eq("kind", "status_changed")
                .order("created_at", desc=False).execute()
            ).data or []
            all_reviews = (
                supabase.table("qa_reviews")
                .select("id, verdict, created_at")
                .eq("task_id", task_id).order("created_at", desc=False).execute()
            ).data or []
        except Exception as exc:
            logger.warning("qa_feedback_task_read_failed", extra={"task_id": task_id, "error": str(exc)})
            continue
        for r in task_reviews:
            scanned += 1
            events = build_events(acts, all_reviews, r["id"], r.get("created_at"))
            res = classify_disposition(r.get("verdict"), events)
            disp = res["disposition"]
            # No change (still pending) → skip the write to avoid churn.
            if disp == PENDING and (r.get("human_disposition") in (None, PENDING)):
                continue
            patch: dict[str, Any] = {
                "human_disposition": disp,
                "disposition_direction": res["direction"],
                "disposition_signal": res["signal"] or None,
            }
            if disp != PENDING:
                patch["disposition_at"] = datetime.now(timezone.utc).isoformat()
            try:
                supabase.table("qa_reviews").update(patch).eq("id", r["id"]).execute()
                updated += 1
            except Exception as exc:
                logger.warning("qa_feedback_write_failed", extra={"review_id": r["id"], "error": str(exc)})
    logger.info("qa_feedback_sweep_done", extra={"scanned": scanned, "updated": updated})
    return {"scanned": scanned, "updated": updated}


def accuracy_report(*, window_days: int = 90, client_id: Optional[str] = None,
                    min_samples: Optional[int] = None) -> dict:
    """The verdict-accuracy rollup over a recent window (optionally one client) —
    the read behind ``GET /tasks/qa-accuracy`` and the SerMaStr QA context. Uses
    the latest review per task so a rework loop's attempts don't multiply-count
    the same deliverable. Best-effort → an empty rollup on any error."""
    from config import settings
    from db.supabase_client import get_supabase

    if min_samples is None:
        min_samples = settings.qa_feedback_min_samples
    since = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
    try:
        q = (
            get_supabase().table("qa_reviews")
            .select("task_id, rubric, verdict, human_disposition, disposition_direction, created_at")
            .gte("created_at", since).order("created_at", desc=True).limit(2000)
        )
        if client_id:
            q = q.eq("client_id", client_id)
        rows = q.execute().data or []
    except Exception as exc:
        logger.warning("qa_accuracy_report_failed", extra={"error": str(exc)})
        return {"window_days": window_days, "decided": 0, "by_class": {}, "by_rubric": {}}
    latest: dict[str, dict] = {}
    for r in rows:  # newest-first → first per task wins
        if r.get("task_id"):
            latest.setdefault(r["task_id"], r)
    stats = accuracy_stats(list(latest.values()), min_samples=min_samples)
    stats["window_days"] = window_days
    stats["reviewed_tasks"] = len(latest)
    return stats
