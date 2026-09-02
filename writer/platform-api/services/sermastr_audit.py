"""SerMaStr — the action log (audit + learning ledger).

Records, best-effort, every STRATEGIST PROPOSAL and the human decision on it
(approved / dismissed / still pending / senior-required), plus — reusing the
intervention-outcome loop, never rebuilding it — whether an approved, goal-linked
tactic actually WORKED (worked/partial/no_effect at its 6-week mark).

The strategist PROPOSES and a human approves / dismisses / escalates, so the
human decision is the core signal. One row per proposal (``public.
sermastr_action_log``), keyed by the SAME ``source_ref`` the interventions loop
uses (``strategy_proposal:{review_id}:{idx}``) so outcome enrichment is a
one-column join.

Two jobs, one stream:
  1. Debuggability — "what did SerMaStr propose, who decided, and did it work?"
  2. Learning — a training-grade corpus SerMaStr reads back (approve/dismiss +
     worked/no_effect rates per proposal kind + per client) to steer what it
     proposes.

Design: logging happens at SerMaStr's OWN seams — review completion
(``run_strategy_review``) and the proposal approve/dismiss endpoint — never at
the shared ``strategy_reviews`` / ``interventions`` layer. ``strategy_reviews``
stays the source of truth for proposal CONTENT; this is the queryable,
agent-attributed STREAM on top. Every write is best-effort — a logging failure
NEVER breaks a review. Gated on ``settings.sermastr_audit_enabled`` (default True).

Pure helpers (``proposal_kind`` / ``proposal_row`` / ``decision_stats`` /
``learning_signals`` / ``format_history`` / ``build_track_record_block`` /
``build_learning_digest``) are unit-tested; the impure I/O (``log_proposals`` /
``record_decision`` / ``run_outcome_sweep`` / ``list_log`` / …) is mockable.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from config import settings
from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

# The intervention tactic types that carry an outcome verdict — the deterministic
# learning key when a proposal has a measurable target.
_TACTIC_KINDS = ("link_building", "reoptimization")


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested)
# ---------------------------------------------------------------------------
def _clip(text: Any, limit: int) -> Optional[str]:
    if text is None:
        return None
    s = str(text)
    return s if len(s) <= limit else s[: limit - 1] + "…"


def source_ref(review_id: str, idx: int) -> str:
    """The shared idempotency key — identical to
    ``interventions.source_ref_for_proposal`` so the outcome sweep joins by it."""
    return f"strategy_proposal:{review_id}:{idx}"


def proposal_kind(proposal: Optional[dict]) -> str:
    """A deterministic learning key for a proposal. Pure.

    Prefer the intervention ``target.tactic_type`` (link_building /
    reoptimization — the measurable kinds); else the leading DOC token of the SOP
    citation (``Link_Building_Recipe_Engine §4`` → ``Link_Building_Recipe_Engine``),
    which groups proposals by the playbook they invoke; else ``"general"``.
    """
    if not isinstance(proposal, dict):
        return "general"
    target = proposal.get("target")
    if isinstance(target, dict):
        tactic = (target.get("tactic_type") or "").strip()
        if tactic in _TACTIC_KINDS:
            return tactic
    cite = (proposal.get("sop_citation") or "").strip()
    if cite:
        # Leading doc token: everything up to the first space or section mark.
        for sep in (" §", "§", " ", "\t", "\n"):
            if sep in cite:
                cite = cite.split(sep, 1)[0]
        cite = cite.strip().strip(",;:")
        if cite:
            return cite[:120]
    return "general"


def proposal_row(review_id: str, idx: int, client_id: Optional[str],
                 client_name: Optional[str], trigger: Optional[str],
                 proposal: dict) -> dict:
    """Project a sanitized strategist proposal → a ``sermastr_action_log`` row
    (decision NULL — the proposal is born pending). Pure."""
    proposal = proposal or {}
    requires = proposal.get("requires")
    if requires not in ("none", "approval", "senior"):
        requires = "approval"
    target = proposal.get("target")
    return {
        "review_id": str(review_id) if review_id else None,
        "proposal_idx": idx,
        "source_ref": source_ref(review_id, idx),
        "client_id": client_id,
        "client_name": _clip(client_name, 200),
        "trigger": _clip(trigger, 60),
        "proposal_kind": proposal_kind(proposal),
        "title": _clip(proposal.get("title"), 400),
        "action": _clip(proposal.get("action"), 2000),
        "sop_citation": _clip(proposal.get("sop_citation"), 300),
        "rationale": _clip(proposal.get("rationale"), 2000),
        "requires": requires,
        "est_cost_usd": proposal.get("est_cost_usd"),
        "target": target if isinstance(target, dict) else None,
    }


def _blank_stats() -> dict:
    return {"approved": 0, "dismissed": 0, "pending": 0, "superseded": 0,
            "worked": 0, "partial": 0, "no_effect": 0, "total": 0}


def _tally_stats(bucket: dict, row: dict) -> None:
    bucket["total"] += 1
    dec = row.get("decision")
    if dec == "approved":
        bucket["approved"] += 1
    elif dec == "dismissed":
        bucket["dismissed"] += 1
    elif dec == "superseded":
        # Replaced by a newer recovery plan — a system event, never a human
        # verdict, so it counts in neither the approve nor the dismiss rate.
        bucket["superseded"] += 1
    else:
        bucket["pending"] += 1
    ov = row.get("outcome_verdict")
    if ov in ("worked", "partial", "no_effect"):
        bucket[ov] += 1


def decision_stats(rows: list[dict]) -> dict:
    """Roll log rows into approve/dismiss/pending + worked/partial/no_effect counts
    overall, per proposal kind, and per actor — the learning substrate + the log
    view's summary strip. Pure."""
    overall = _blank_stats()
    by_kind: dict[str, dict] = {}
    by_actor: dict[str, dict] = {}
    for r in rows or []:
        _tally_stats(overall, r)
        _tally_stats(by_kind.setdefault(r.get("proposal_kind") or "general", _blank_stats()), r)
        who = r.get("actor_name") or r.get("decided_by") or "—"
        # Only rows that carry an actual decision meaningfully belong to an actor.
        if r.get("decision"):
            _tally_stats(by_actor.setdefault(str(who), _blank_stats()), r)
    return {"overall": overall, "by_kind": by_kind, "by_actor": by_actor}


def learning_signals(rows: list[dict]) -> dict:
    """Per-kind and per-(client, kind) approve/dismiss/pending + worked/no_effect
    counts, with a ``dismiss_rate`` = dismissed/(approved+dismissed) over DECIDED
    proposals and an ``ineffective_rate`` = no_effect/(worked+partial+no_effect)
    over GRADED proposals. The shared substrate for the weekly digest and the
    prompt track-record block. Pure."""
    def _rate(b: dict) -> dict:
        decided = b["approved"] + b["dismissed"]
        graded = b["worked"] + b["partial"] + b["no_effect"]
        b["decided"] = decided
        b["graded"] = graded
        b["dismiss_rate"] = round(b["dismissed"] / decided, 3) if decided else 0.0
        b["ineffective_rate"] = round(b["no_effect"] / graded, 3) if graded else 0.0
        return b

    by_kind: dict[str, dict] = {}
    by_client_kind: dict[str, dict] = {}
    for r in rows or []:
        kind = r.get("proposal_kind") or "general"
        _tally_stats(by_kind.setdefault(kind, _blank_stats()), r)
        key = f"{r.get('client_id') or '-'}::{kind}"
        _tally_stats(by_client_kind.setdefault(key, _blank_stats()), r)
    for b in by_kind.values():
        _rate(b)
    for b in by_client_kind.values():
        _rate(b)
    return {"by_kind": by_kind, "by_client_kind": by_client_kind}


# ---------------------------------------------------------------------------
# Self-analysis (WS1) — "what tactics work best", sliced + ranked. Pure.
# ---------------------------------------------------------------------------
def _rate_perf(b: dict, min_n: int) -> dict:
    """Attach approval/worked/no_effect rates, a `signal` (measured vs
    approval-only vs thin), and a `rank_score` to a stats bucket. Pure.

    `measured` = enough GRADED outcomes to trust the worked-rate (the honest
    signal). `approval-only` = enough DECIDED but not yet outcome-proven, so its
    rank is the approval rate discounted ×0.7. `thin` = below the sample gate,
    excluded from ranking."""
    decided = b["approved"] + b["dismissed"]
    graded = b["worked"] + b["partial"] + b["no_effect"]
    b["decided"] = decided
    b["graded"] = graded
    b["approval_rate"] = round(b["approved"] / decided, 3) if decided else 0.0
    b["worked_rate"] = round(b["worked"] / graded, 3) if graded else 0.0
    b["no_effect_rate"] = round(b["no_effect"] / graded, 3) if graded else 0.0
    if graded >= min_n:
        b["signal"] = "measured"
        b["rank_score"] = b["worked_rate"]
    elif decided >= min_n:
        b["signal"] = "approval-only"
        b["rank_score"] = round(b["approval_rate"] * 0.7, 3)
    else:
        b["signal"] = "thin"
        b["rank_score"] = 0.0
    return b


def tactic_performance(rows: list[dict], client_types: Optional[dict] = None,
                       min_samples: Optional[int] = None) -> dict:
    """Rank SerMaStr's tactics by how well they perform, sliced three ways. Pure.

    Slices the log into per-`kind`, per-`client_type` (local/enterprise, from the
    passed `client_types` map keyed by client_id) and per-`trigger` buckets, each
    rate-annotated by :func:`_rate_perf`. `leaders` = the tactics that actually
    work or get approved (rank_score > 0, above the sample gate), ranked best
    first — the "lean into these" list. `underperformers` = measured tactics that
    clearly don't move the metric (worked_rate 0 over ≥ min graded) — the
    "consider retiring" list. Ranking prefers MEASURED worked-rate; approval-only
    is discounted (unproven) so a much-approved-but-never-graded tactic can't
    outrank a proven one."""
    client_types = client_types or {}
    min_n = min_samples if min_samples is not None else settings.sermastr_audit_learning_min_samples
    by_kind: dict[str, dict] = {}
    by_client_type: dict[str, dict] = {}
    by_trigger: dict[str, dict] = {}
    for r in rows or []:
        kind = r.get("proposal_kind") or "general"
        _tally_stats(by_kind.setdefault(kind, _blank_stats()), r)
        ct = client_types.get(r.get("client_id")) or "unknown"
        _tally_stats(by_client_type.setdefault(ct, _blank_stats()), r)
        trig = r.get("trigger") or "unknown"
        _tally_stats(by_trigger.setdefault(trig, _blank_stats()), r)
    for d in (by_kind, by_client_type, by_trigger):
        for b in d.values():
            _rate_perf(b, min_n)

    def _leader(kind: str, b: dict) -> dict:
        return {"kind": kind, "signal": b["signal"], "rank_score": b["rank_score"],
                "approved": b["approved"], "decided": b["decided"],
                "worked": b["worked"], "graded": b["graded"],
                "approval_rate": b["approval_rate"], "worked_rate": b["worked_rate"]}

    leaders = sorted(
        (_leader(k, b) for k, b in by_kind.items()
         if b["signal"] != "thin" and b["rank_score"] > 0),
        key=lambda x: (-x["rank_score"], -x["graded"], -x["decided"]))
    underperformers = sorted(
        (_leader(k, b) for k, b in by_kind.items()
         if b["signal"] == "measured" and b["worked_rate"] == 0.0),
        key=lambda x: (-x["graded"], -x["decided"]))
    total = sum(b["total"] for b in by_kind.values())
    return {
        "by_kind": by_kind, "by_client_type": by_client_type, "by_trigger": by_trigger,
        "leaders": leaders, "underperformers": underperformers,
        "total": total, "min_samples": min_n,
    }


def _pct(x: float) -> int:
    return int(round((x or 0.0) * 100))


def build_self_analysis_report(perf: dict, learn: Optional[dict] = None) -> str:
    """The deterministic "what's working best" report body (Slack mrkdwn). Pure.

    Leads with the leaders SerMaStr should lean into (measured worked-rate, or an
    approval rate flagged unproven), the best-performing client type / trigger
    segment when informative, and — folding in the learning signals — the tactics
    to retire. Returns "" when there's nothing worth saying (thin history), so the
    caller posts nothing."""
    if not perf:
        return ""
    leaders = perf.get("leaders") or []
    unders = perf.get("underperformers") or []
    lines: list[str] = [
        f"*SerMaStr — what's working best* ({perf.get('total', 0)} proposal"
        f"{'s' if perf.get('total', 0) != 1 else ''} in the window)"
    ]
    if leaders:
        lines.append("*Leaders — lean into these:*")
        for l in leaders[:6]:
            if l["signal"] == "measured":
                lines.append(f"• `{l['kind']}` — moved the metric {l['worked']}/{l['graded']} "
                             f"({_pct(l['worked_rate'])}% worked)")
            else:
                lines.append(f"• `{l['kind']}` — approved {l['approved']}/{l['decided']} "
                             f"({_pct(l['approval_rate'])}%), outcomes not yet measured")
    # Best segment (client type / trigger), only when a measured winner stands out.
    for label, key in (("client type", "by_client_type"), ("trigger", "by_trigger")):
        seg = perf.get(key) or {}
        best = sorted(((k, b) for k, b in seg.items()
                       if k != "unknown" and b.get("signal") == "measured" and b.get("worked_rate", 0) > 0),
                      key=lambda kv: -kv[1]["worked_rate"])
        if best:
            k, b = best[0]
            lines.append(f"*Best by {label}:* `{k}` — {_pct(b['worked_rate'])}% worked "
                         f"({b['worked']}/{b['graded']})")
    if unders:
        lines.append("*Not moving the metric — consider retiring or changing the approach:*")
        for u in unders[:3]:
            lines.append(f"• `{u['kind']}` — 0/{u['graded']} graded attempts worked")
    # Fold in the dismiss signal (what humans keep rejecting) when available.
    if learn:
        sig = learn.get("by_kind") or {}
        dismissed = sorted(
            ((k, s) for k, s in sig.items() if s.get("decided", 0) >= 2 and s.get("dismiss_rate", 0) > 0),
            key=lambda kv: -kv[1]["dismiss_rate"])[:3]
        if dismissed:
            lines.append("*Most-dismissed by humans:*")
            for k, s in dismissed:
                lines.append(f"• `{k}` — {_pct(s['dismiss_rate'])}% dismissed "
                             f"({s['dismissed']}/{s['decided']})")
    # Nothing beyond the header → say nothing.
    return "\n".join(lines) if len(lines) > 1 else ""


def format_history(rows: list[dict]) -> str:
    """Compact, LLM-readable lines for a self-read. Pure."""
    if not rows:
        return "No SerMaStr proposals on record for this scope yet."
    lines = []
    for r in rows:
        when = (r.get("created_at") or "")[:10]
        dec = r.get("decision") or "pending"
        client = r.get("client_name") or "—"
        kind = r.get("proposal_kind") or "general"
        what = r.get("title") or r.get("action") or "?"
        tail = ""
        if r.get("requires") == "senior" and dec == "pending":
            tail = " [senior-required]"
        ov = r.get("outcome_verdict")
        if ov:
            tail += f" [{ov}]"
        lines.append(f"- {when} · {client} · {kind} · {dec}: {_clip(what, 120)}{tail}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Learning → prompt steering (pure) — the "lean into approved/working, away from
# dismissed/ineffective" block injected into the strategist RUN prompt when
# sermastr_audit_learning_enabled. Advice, never a hard filter.
# ---------------------------------------------------------------------------
def build_track_record_block(signals: dict, client_id: Optional[str]) -> str:
    """Render the "YOUR TRACK RECORD" prompt block from learning signals. Pure.

    Names proposal kinds this client (falling back to agency-wide) keeps
    DISMISSING or that consistently DON'T MOVE the metric (avoid / justify), and
    kinds that get APPROVED and WORK (favour). Gated by
    ``sermastr_audit_learning_min_samples`` so a thin history stays silent
    (returns "" → the prompt is byte-identical to today)."""
    if not signals:
        return ""
    min_n = settings.sermastr_audit_learning_min_samples
    dismiss_thr = settings.sermastr_audit_learning_dismiss_threshold
    by_kind = signals.get("by_kind") or {}
    by_client_kind = signals.get("by_client_kind") or {}

    def _client_bucket(kind: str) -> Optional[dict]:
        return by_client_kind.get(f"{client_id or '-'}::{kind}")

    avoid: list[str] = []
    favour: list[str] = []
    for kind, agg in by_kind.items():
        # Prefer the per-client signal when it has enough samples; else agency.
        cb = _client_bucket(kind)
        sig = cb if (cb and cb.get("decided", 0) >= min_n) else agg
        scope = "for this client" if sig is cb else "agency-wide"
        decided = sig.get("decided", 0)
        graded = sig.get("graded", 0)
        if decided >= min_n and sig.get("dismiss_rate", 0.0) >= dismiss_thr:
            avoid.append(
                f"`{kind}` — dismissed {sig['dismissed']}/{decided} recent times "
                f"({scope}); don't re-propose it unless the evidence is materially new")
        elif graded >= min_n and sig.get("ineffective_rate", 0.0) >= dismiss_thr:
            avoid.append(
                f"`{kind}` — showed no_effect on {sig['no_effect']}/{graded} graded "
                f"attempts ({scope}); pause it or change the approach, and say why")
        elif decided >= min_n and sig.get("approved", 0) and sig.get("worked", 0):
            favour.append(
                f"`{kind}` — approved {sig['approved']}/{decided} and has moved the "
                f"metric ({sig['worked']} worked, {scope}); lean into it")
    if not avoid and not favour:
        return ""
    parts = [
        "YOUR TRACK RECORD (from the action log — WEIGH it, don't obey it; it is "
        "small-sample history of how humans have decided on your past proposals "
        "and whether they worked, not a rule):"
    ]
    if favour:
        parts.append("Favour:\n" + "\n".join(f"  - {x}" for x in favour[:6]))
    if avoid:
        parts.append("Avoid / justify:\n" + "\n".join(f"  - {x}" for x in avoid[:6]))
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Impure I/O (best-effort — never raises into a review)
# ---------------------------------------------------------------------------
def log_proposals(review_id: str, client_id: Optional[str], client_name: Optional[str],
                  trigger: Optional[str], proposals: list[dict]) -> None:
    """Insert one pending ``sermastr_action_log`` row per proposal of a completed
    review. Idempotent (upsert on source_ref, IGNORE duplicates) so a review
    re-persist never clobbers a decision already recorded. Best-effort — gated on
    ``sermastr_audit_enabled`` and any failure is swallowed + logged (a logging
    error must never break the review)."""
    if not settings.sermastr_audit_enabled:
        return
    if not proposals:
        return
    rows = [proposal_row(review_id, i, client_id, client_name, trigger, p)
            for i, p in enumerate(proposals) if isinstance(p, dict)]
    if not rows:
        return
    try:
        (get_supabase().table("sermastr_action_log")
         .upsert(rows, on_conflict="source_ref", ignore_duplicates=True).execute())
    except Exception as exc:  # never surface into the review path
        logger.warning("sermastr_audit_log_proposals_failed",
                       extra={"review_id": str(review_id), "error": str(exc)})


def record_decision(*, review_id: str, idx: int, proposal: dict,
                    client_id: Optional[str] = None, client_name: Optional[str] = None,
                    trigger: Optional[str] = None, decision: str,
                    actor_profile_id: Optional[str] = None,
                    actor_role: Optional[str] = None, actor_source: str = "web") -> None:
    """Record a human's decision on one proposal (approved / dismissed). UPSERTS by
    source_ref (create-if-missing from the proposal dict, so a decision is never
    lost even if the pending row wasn't logged — e.g. audit was off at review time
    then turned on). Only the columns present here are written, so a later outcome
    verdict is preserved. Best-effort."""
    if not settings.sermastr_audit_enabled:
        return
    if decision not in ("approved", "dismissed", "superseded"):
        return
    from datetime import datetime, timezone

    row = proposal_row(review_id, idx, client_id, client_name, trigger, proposal or {})
    row.update({
        "decision": decision,
        "decided_by": actor_profile_id,
        "decided_at": datetime.now(timezone.utc).isoformat(),
        "actor_role": actor_role,
        "actor_source": actor_source or "web",
    })
    # Drop None-valued keys so an UPSERT-MERGE onto an existing pending row never
    # NULLs data it already snapshotted — notably client_name, which we snapshot
    # precisely so it survives a client deletion (which sets client_id → null, so
    # a later re-decision would otherwise arrive with client_name=None). On a
    # create-if-missing insert, an absent key simply defaults to NULL. source_ref
    # is always present; decision/decided_at are always set above.
    row = {k: v for k, v in row.items() if v is not None}
    try:
        (get_supabase().table("sermastr_action_log")
         .upsert(row, on_conflict="source_ref").execute())
    except Exception as exc:
        logger.warning("sermastr_audit_record_decision_failed",
                       extra={"review_id": str(review_id), "idx": idx, "error": str(exc)})


# ---------------------------------------------------------------------------
# Self-read (learning) — recent history for the passive context surface
# ---------------------------------------------------------------------------
def record_superseded(*, review_id: str, idx: int, proposal: dict,
                      client_id: Optional[str] = None, client_name: Optional[str] = None,
                      trigger: Optional[str] = None) -> None:
    """A proposal replaced by a newer recovery plan (services/goal_recovery.py).
    Recorded as its OWN decision value, by the system — excluded from the
    approve/dismiss learning rates. Best-effort."""
    record_decision(
        review_id=review_id, idx=idx, proposal=proposal, client_id=client_id,
        client_name=client_name, trigger=trigger, decision="superseded",
        actor_profile_id=None, actor_role=None, actor_source="system",
    )


def _attach_actor_names(rows: list[dict]) -> list[dict]:
    """Best-effort: fold ``actor_name`` onto each row from profiles."""
    ids = sorted({str(r["decided_by"]) for r in rows if r.get("decided_by")})
    if not ids:
        return rows
    try:
        profs = (get_supabase().table("profiles").select("id, full_name")
                 .in_("id", ids).execute()).data or []
        names = {p["id"]: p.get("full_name") for p in profs}
    except Exception:
        names = {}
    for r in rows:
        r["actor_name"] = names.get(r.get("decided_by"))
    return rows


def recent_actions(*, client_id: Optional[str] = None, proposal_kind: Optional[str] = None,
                   limit: Optional[int] = None, attach_names: bool = True) -> list[dict]:
    """Recent log rows for a scope, newest first. ``attach_names`` False skips the
    profiles join — used by the passive context summary, which needs only counts.
    Best-effort — [] on any error."""
    limit = limit or settings.sermastr_audit_history_limit
    try:
        q = (get_supabase().table("sermastr_action_log")
             .select("created_at, review_id, proposal_idx, client_id, client_name, "
                     "trigger, proposal_kind, title, action, sop_citation, rationale, "
                     "requires, decision, decided_by, outcome_verdict")
             .order("created_at", desc=True).limit(limit))
        if client_id:
            q = q.eq("client_id", client_id)
        if proposal_kind:
            q = q.eq("proposal_kind", proposal_kind)
        rows = q.execute().data or []
    except Exception as exc:
        logger.warning("sermastr_audit_recent_failed", extra={"error": str(exc)})
        return []
    return _attach_actor_names(rows) if attach_names else rows


def history_summary(*, client_id: Optional[str] = None, limit: Optional[int] = None,
                    attach_names: bool = True) -> dict:
    """Recent proposals + a decision-rate rollup for the passive context surface.
    ``attach_names`` False skips the profiles join. Best-effort."""
    rows = recent_actions(client_id=client_id, limit=limit, attach_names=attach_names)
    return {"recent": rows, "stats": decision_stats(rows), "count": len(rows)}


# ---------------------------------------------------------------------------
# Read API (admin-gated /strategist/action-log)
# ---------------------------------------------------------------------------
_LOG_COLUMNS = (
    "id, created_at, review_id, proposal_idx, source_ref, client_id, client_name, "
    "trigger, proposal_kind, title, action, sop_citation, rationale, requires, "
    "est_cost_usd, target, decision, decided_by, decided_at, actor_role, "
    "actor_source, outcome_verdict, outcome_at, intervention_id, context"
)


def _apply_log_filters(q, *, client_id=None, proposal_kind=None, decision=None,
                       trigger=None, outcome_verdict=None, decided=None,
                       since=None, until=None):
    if decided is True:
        q = q.not_.is_("decision", "null")
    elif decided is False:
        q = q.is_("decision", "null")
    if client_id:
        q = q.eq("client_id", client_id)
    if proposal_kind:
        q = q.eq("proposal_kind", proposal_kind)
    if decision:
        q = q.eq("decision", decision)
    if trigger:
        q = q.eq("trigger", trigger)
    if outcome_verdict:
        q = q.eq("outcome_verdict", outcome_verdict)
    if since:
        q = q.gte("created_at", since)
    if until:
        q = q.lte("created_at", until)
    return q


def list_log(*, client_id=None, proposal_kind=None, decision=None, trigger=None,
             outcome_verdict=None, decided=None, since=None, until=None,
             limit: int = 100, offset: int = 0) -> dict:
    """A filtered page of the action log for the admin read API, with actor names
    joined. Returns {rows, total, limit, offset}. Best-effort."""
    limit = max(1, min(int(limit or 100), 500))
    offset = max(0, int(offset or 0))
    try:
        q = (get_supabase().table("sermastr_action_log").select(_LOG_COLUMNS, count="exact")
             .order("created_at", desc=True).range(offset, offset + limit - 1))
        q = _apply_log_filters(q, client_id=client_id, proposal_kind=proposal_kind,
                               decision=decision, trigger=trigger,
                               outcome_verdict=outcome_verdict, decided=decided,
                               since=since, until=until)
        resp = q.execute()
        rows = resp.data or []
        total = resp.count if resp.count is not None else len(rows)
    except Exception as exc:
        logger.warning("sermastr_audit_list_failed", extra={"error": str(exc)})
        return {"rows": [], "total": 0, "limit": limit, "offset": offset}
    return {"rows": _attach_actor_names(rows), "total": total, "limit": limit, "offset": offset}


def stats_window(*, client_id=None, proposal_kind=None, since=None, until=None,
                 limit: int = 2000) -> dict:
    """Decision-rate rollup over a filtered window for the log view's summary
    strip + the learning read. Best-effort."""
    cap = min(int(limit or 2000), 5000)
    try:
        q = (get_supabase().table("sermastr_action_log")
             .select("proposal_kind, decision, decided_by, outcome_verdict")
             .order("created_at", desc=True).limit(cap))
        q = _apply_log_filters(q, client_id=client_id, proposal_kind=proposal_kind,
                               since=since, until=until)
        rows = _attach_actor_names(q.execute().data or [])
    except Exception as exc:
        logger.warning("sermastr_audit_stats_failed", extra={"error": str(exc)})
        rows = []
    return decision_stats(rows)


# ---------------------------------------------------------------------------
# Outcome sweep (impure, daily, read-only w.r.t. interventions)
# ---------------------------------------------------------------------------
def run_outcome_sweep() -> dict:
    """Stamp the reused intervention verdict onto approved, goal-linked proposal
    rows still lacking one. Read-only w.r.t. interventions — reads their verdict
    and writes only sermastr_action_log. Self-gated on sermastr_audit_enabled;
    best-effort. Returns {checked, stamped}."""
    from datetime import datetime, timedelta, timezone

    if not settings.sermastr_audit_enabled:
        return {"checked": 0, "stamped": 0, "reason": "disabled"}
    since = (datetime.now(timezone.utc)
             - timedelta(days=settings.sermastr_audit_outcome_window_days)).isoformat()
    try:
        rows = (get_supabase().table("sermastr_action_log")
                .select("id, source_ref")
                .eq("decision", "approved").is_("outcome_verdict", "null")
                .gte("created_at", since).limit(2000).execute()).data or []
    except Exception as exc:
        logger.warning("sermastr_audit_outcome_query_failed", extra={"error": str(exc)})
        return {"checked": 0, "stamped": 0, "reason": "error"}
    refs = sorted({r["source_ref"] for r in rows if r.get("source_ref")})
    if not refs:
        return {"checked": 0, "stamped": 0}
    verdicts: dict[str, dict] = {}
    try:
        # Chunk the ref list so a big backlog stays under URL/row limits.
        for i in range(0, len(refs), 200):
            chunk = refs[i:i + 200]
            got = (get_supabase().table("interventions")
                   .select("id, source_ref, verdict, evaluated_at")
                   .in_("source_ref", chunk).not_.is_("verdict", "null")
                   .execute()).data or []
            for iv in got:
                verdicts[iv["source_ref"]] = iv
    except Exception as exc:
        logger.warning("sermastr_audit_outcome_read_failed", extra={"error": str(exc)})
        return {"checked": 0, "stamped": 0, "reason": "error"}
    stamped = 0
    for r in rows:
        iv = verdicts.get(r.get("source_ref"))
        if not iv or iv.get("verdict") not in ("worked", "partial", "no_effect"):
            continue
        try:
            (get_supabase().table("sermastr_action_log")
             .update({"outcome_verdict": iv["verdict"],
                      "outcome_at": iv.get("evaluated_at") or datetime.now(timezone.utc).isoformat(),
                      "intervention_id": iv.get("id")})
             .eq("id", r["id"]).execute())
        except Exception as exc:
            logger.warning("sermastr_audit_outcome_mark_failed",
                           extra={"id": r["id"], "error": str(exc)})
            continue
        stamped += 1
    return {"checked": len(rows), "stamped": stamped}


def _window_rows(client_id: Optional[str] = None, days: Optional[int] = None) -> list[dict]:
    """The log rows over a rolling window (the learning window by default), with
    just the columns the rollups need — one read, reused by the learning signals,
    the self-analysis snapshot, and the digest. Best-effort ([] on error)."""
    from datetime import datetime, timedelta, timezone

    days = days if days is not None else settings.sermastr_audit_learning_window_days
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        q = (get_supabase().table("sermastr_action_log")
             .select("proposal_kind, client_id, trigger, decision, outcome_verdict")
             .gte("created_at", since).limit(5000))
        if client_id:
            q = q.eq("client_id", client_id)
        return q.execute().data or []
    except Exception:
        return []


def _client_types_map(client_ids) -> dict:
    """{client_id: client_type} for the ids present, for the client-type slice.
    Best-effort ({} on error → segment collapses to 'unknown', never breaks)."""
    ids = sorted({c for c in (client_ids or []) if c})
    if not ids:
        return {}
    try:
        rows = (get_supabase().table("clients").select("id, client_type")
                .in_("id", ids).execute()).data or []
        return {r["id"]: (r.get("client_type") or "unknown") for r in rows}
    except Exception:
        return {}


def _learning_signals_window() -> dict:
    """Learning signals over the configured window — one read, reused across a
    plan build. Best-effort ([] on error → empty signals)."""
    return learning_signals(_window_rows())


def tactic_snapshot(client_id: Optional[str] = None, days: Optional[int] = None) -> dict:
    """Tactic performance + learning signals over the window for a client (or the
    whole agency when client_id is None) — the shared read behind the on-demand
    context providers. Best-effort. Returns {perf, learn, rows}."""
    rows = _window_rows(client_id, days)
    client_types = _client_types_map([r.get("client_id") for r in rows])
    return {"perf": tactic_performance(rows, client_types),
            "learn": learning_signals(rows), "rows": len(rows)}


def narrate_self_analysis(report_text: str, model: Optional[str] = None) -> str:
    """Best-effort LLM rewrite of the deterministic report into a punchy owner-
    facing Slack update. The exact numbers are already in `report_text` and the
    prompt forbids changing them, so there's no fabrication surface. Returns "" on
    any failure — the caller then keeps the deterministic body."""
    if not report_text:
        return ""
    from services import report_llm

    system = (
        "You are SerMaStr, an SEO strategist reporting to the agency owner in Slack. "
        "Rewrite the tactic-performance summary below into a short, punchy update "
        "(a lead line plus a few bullets). Slack mrkdwn only: *bold* not **bold**, "
        "no # headers, no tables. Lead with what's working and that you're leaning "
        "into it. Keep EVERY number, fraction, percentage and tactic name EXACTLY "
        "as given — never invent, round, or drop a figure. If a tactic is flagged "
        "unproven or as not moving the metric, keep that caveat."
    )
    try:
        txt = report_llm.generate_text_sync(
            user=report_text, max_tokens=700, system=system,
            model=model or settings.sermastr_self_analysis_model,
            log_tag="sermastr_self_analysis")
        return (txt or "").strip()
    except Exception as exc:
        logger.warning("sermastr_self_analysis_narrate_failed", extra={"error": str(exc)})
        return ""


# ---------------------------------------------------------------------------
# Weekly learning digest (mirrors pace_audit.maybe_emit_weekly_learning)
# ---------------------------------------------------------------------------
def build_learning_digest(rows: list[dict]) -> str:
    """A Slack-mrkdwn weekly digest of SerMaStr's track record over ``rows``. Pure.
    Empty string when nothing was logged (the caller then posts nothing)."""
    if not rows:
        return ""
    stats = decision_stats(rows)
    ov = stats["overall"]
    sig = learning_signals(rows)["by_kind"]
    lines = [f"*SerMaStr learning digest* — {ov['total']} proposal"
             f"{'s' if ov['total'] != 1 else ''} logged this week"]
    lines.append(
        f"• {ov['approved']} approved · {ov['dismissed']} dismissed · "
        f"{ov['pending']} still pending · outcomes so far: "
        f"{ov['worked']} worked / {ov['partial']} partial / {ov['no_effect']} no-effect")
    # Most-dismissed proposal kinds (min 2 decided).
    dismissed = sorted(
        ((k, s) for k, s in sig.items() if s["decided"] >= 2 and s["dismiss_rate"] > 0),
        key=lambda kv: -kv[1]["dismiss_rate"])[:3]
    if dismissed:
        lines.append("*Most-dismissed:*")
        for k, s in dismissed:
            lines.append(f"• `{k}` — {int(s['dismiss_rate'] * 100)}% dismissed "
                         f"({s['dismissed']}/{s['decided']})")
    # Kinds that don't move the metric (min 2 graded).
    ineffective = sorted(
        ((k, s) for k, s in sig.items() if s["graded"] >= 2 and s["ineffective_rate"] > 0),
        key=lambda kv: -kv[1]["ineffective_rate"])[:3]
    if ineffective:
        lines.append("*Not moving the metric:*")
        for k, s in ineffective:
            lines.append(f"• `{k}` — {int(s['ineffective_rate'] * 100)}% no-effect "
                         f"({s['no_effect']}/{s['graded']} graded)")
    return "\n".join(lines)


def maybe_emit_weekly_learning(today: Optional[Any] = None) -> dict:
    """Emit ONE learning digest per week on ``sermastr_audit_digest_weekday``.
    Double-gated on strategist_enabled + sermastr_audit_enabled + a configured
    weekday (off by default); best-effort. Routed to the default (strategy) Slack
    channel — not PACE/Director. Called inline from the daily scheduler tick
    (mirrors pace_audit.maybe_emit_weekly_learning)."""
    from datetime import date, datetime, timedelta, timezone

    from services import notifications

    if not (settings.strategist_enabled and settings.sermastr_audit_enabled):
        return {"emitted": False, "reason": "disabled"}
    weekday = settings.sermastr_audit_digest_weekday
    today = today or date.today()
    if weekday is None or today.weekday() != int(weekday):
        return {"emitted": False, "reason": "not_due"}
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    try:
        rows = (get_supabase().table("sermastr_action_log")
                .select("proposal_kind, client_id, trigger, decision, outcome_verdict")
                .gte("created_at", since).limit(5000).execute()).data or []
        # WS1: when self-analysis is on, the weekly digest carries the richer
        # "what's working best — lean in / retire" report (best-effort LLM
        # narrative over the deterministic body); else the legacy learning digest.
        if settings.sermastr_self_analysis_enabled:
            client_types = _client_types_map([r.get("client_id") for r in rows])
            perf = tactic_performance(rows, client_types)
            body = build_self_analysis_report(perf, learning_signals(rows))
            if body:
                narrated = narrate_self_analysis(body)
                if narrated:
                    body = narrated
            title = "SerMaStr tactic report"
        else:
            body = build_learning_digest(rows)
            title = "SerMaStr learning digest"
        if not body:
            return {"emitted": False, "reason": "nothing_logged"}
        notifications.emit(
            client_id=None, kind="strategy_learning_digest",
            title=title,
            summary=body, severity="info",
            payload={"link": "/strategist/log"},
            dedupe_key=f"sermastr_learning_digest:{today.isoformat()}",
        )
        return {"emitted": True, "rows": len(rows)}
    except Exception as exc:
        logger.warning("sermastr_learning_digest_failed", extra={"error": str(exc)})
        return {"emitted": False, "reason": "error"}
