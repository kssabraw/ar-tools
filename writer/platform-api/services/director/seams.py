"""Director of Operations — seam predicates (build spec §5).

Pure functions over the read model assembled by
``services.director.read_model.build_read_model``. Each predicate resolves to
zero or more **flags** — evidence, never a verdict:

    {"seam", "client_id", "ident", "evidence", "since", "threshold_days"}

``ident`` is a stable per-flag identifier the reconciler (§6.1) uses to build
an idempotent ``source_ref`` (``f"{seam}:{client_id}:{ident}"``) so opening
the same flag twice is a no-op and clearing it auto-closes the task.

No I/O here — every DB read already happened in ``providers.py``; these
functions only interpret the assembled dicts. Pure + unit-tested.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional


def age_days(since: Optional[str], today: date) -> Optional[int]:
    """Days between an ISO date/timestamp ``since`` and ``today``. ``None`` if
    ``since`` is missing or unparsable — callers must not treat that as 0."""
    if not since:
        return None
    try:
        text = str(since)
        when = (
            datetime.fromisoformat(text.replace("Z", "+00:00")).date()
            if "T" in text
            else date.fromisoformat(text[:10])
        )
        return (today - when).days
    except (ValueError, TypeError):
        return None


def strategist_approved_unplaced(model: dict, today: date, threshold_days: int) -> list[dict]:
    strategy = model.get("strategy") or {}
    flags: list[dict] = []
    for item in strategy.get("approved_unplaced") or []:
        age = age_days(item.get("since"), today)
        if age is None or age < threshold_days:
            continue
        flags.append({
            "seam": "strategist_approved_unplaced",
            "client_id": item.get("client_id"),
            "ident": f"{item.get('review_id')}:{item.get('proposal_index')}",
            "evidence": {
                "title": item.get("title"),
                "review_id": item.get("review_id"),
                "days_unplaced": age,
            },
            "since": item.get("since"),
            "threshold_days": threshold_days,
        })
    return flags


def autonomy_proposed_unactioned(model: dict, today: date, threshold_days: int) -> list[dict]:
    autonomy = model.get("autonomy") or {}
    flags: list[dict] = []
    for item in autonomy.get("proposed_unactioned") or []:
        age = age_days(item.get("since"), today)
        if age is None or age < threshold_days:
            continue
        flags.append({
            "seam": "autonomy_proposed_unactioned",
            "client_id": item.get("client_id"),
            "ident": f"{item.get('run_id')}:{item.get('action')}",
            "evidence": {
                "action": item.get("action"),
                "keyword": item.get("keyword"),
                "run_id": item.get("run_id"),
                "days_unactioned": age,
            },
            "since": item.get("since"),
            "threshold_days": threshold_days,
        })
    return flags


def qa_idle(model: dict, today: date, threshold_days: int) -> Optional[dict]:
    """Portfolio-only (§2.3) — zero tasks entered QA in N days while completed
    work exists in the window. Returns one flag or ``None``, never a per-client
    list (there is no client to blame for a suite-wide gap)."""
    qa = model.get("qa")
    if qa is None:
        return None
    if (qa.get("entered_in_qa_count") or 0) > 0:
        return None
    age = age_days(qa.get("last_entered_at"), today)
    if age is not None and age < threshold_days:
        return None
    return {
        "seam": "qa_idle",
        "client_id": None,
        "ident": "portfolio",
        "evidence": {
            "last_entered_at": qa.get("last_entered_at"),
            "reviews_considered": qa.get("reviews_considered", 0),
        },
        "since": qa.get("last_entered_at"),
        "threshold_days": threshold_days,
    }


def content_shipped_degraded(model: dict) -> list[dict]:
    """Immediate (no dwell) — evidence is pre-gathered by
    ``providers.prov_content`` (a completed run at a ``-degraded``/
    ``-no-context`` schema version, or a page with an unresolved voice-critical
    scorecard); this just shapes it into flags."""
    content = model.get("content") or {}
    flags: list[dict] = []
    for item in content.get("degraded") or []:
        flags.append({
            "seam": "content_shipped_degraded",
            "client_id": item.get("client_id"),
            "ident": item.get("ident"),
            "evidence": {k: v for k, v in item.items() if k not in {"client_id", "ident"}},
            "since": item.get("since"),
            "threshold_days": 0,
        })
    return flags


def duplicate_target(model: dict) -> list[dict]:
    """Two live items with DIFFERENT ``source`` sharing one normalized target
    key for a client (§9). Flag-only (decision 3) — never merges."""
    duplicates = model.get("duplicates") or {}
    flags: list[dict] = []
    for item in duplicates.get("duplicates") or []:
        flags.append({
            "seam": "duplicate_target",
            "client_id": item.get("client_id"),
            "ident": item.get("target_key"),
            "evidence": {"target_key": item.get("target_key"), "items": item.get("items")},
            "since": None,
            "threshold_days": 0,
        })
    return flags


def unwatched_seam(model: dict) -> list[dict]:
    """E1 — an open task whose ``source`` the read model doesn't recognize.
    Portfolio-scoped: a new/renamed producer is a suite-wide code gap, not one
    client's problem."""
    producers = model.get("producers") or {}
    flags: list[dict] = []
    for source, count in (producers.get("unwatched_seam") or {}).items():
        flags.append({
            "seam": "unwatched_seam",
            "client_id": None,
            "ident": source,
            "evidence": {"source": source, "open_count": count},
            "since": None,
            "threshold_days": 0,
        })
    return flags


def compute_flags(model: dict, today: date, thresholds: dict) -> dict:
    """Assemble every seam predicate into one ``{flags: [...], count}`` block.

    ``thresholds`` = {"approved_unplaced_days", "qa_idle_days",
    "autonomy_unactioned_days"} — callers pass the ``settings.director_seam_*``
    values (or overrides in tests). Pure."""
    flags: list[dict] = []
    flags += strategist_approved_unplaced(model, today, thresholds["approved_unplaced_days"])
    flags += autonomy_proposed_unactioned(model, today, thresholds["autonomy_unactioned_days"])
    idle = qa_idle(model, today, thresholds["qa_idle_days"])
    if idle:
        flags.append(idle)
    flags += content_shipped_degraded(model)
    flags += duplicate_target(model)
    flags += unwatched_seam(model)
    return {"flags": flags, "count": len(flags)}
