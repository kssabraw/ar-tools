"""PACE — Proactive Interventions (the managerial layer).

docs/modules/pace-proactive-interventions-plan-v1_0.md. Where the Chase Plan
(`pace_proposals.py`) reacts per-task, this steps back and notices a **systemic**
delivery problem — a member at 293% of capacity, 450 items blocked by ambiguous
duplicate task names, an untriaged/overdue/slip cluster — and opens ONE durable
**intervention** (a problem + a concrete fix plan) the PM dispositions four ways:

    approve  → PACE executes the fix plan (bulk), records the result
    deny     → nothing runs; the signature is suppressed for a cooldown
    defer    → snoozed to a date; re-surfaces then
    conditions (approve-with-conditions) → a free-text constraint is interpreted
               into a structured directive, applied deterministically, then run

Execution re-stages every action through the tested `PACE_ACTIONS` stage→run
contract, so a target that moved since detection is re-validated (never blindly
written), and each fix is reversible (renames not merges; only not-yet-started
work is moved).

Lifecycle (one OPEN row per `signature`, mirrors `response_episodes`):
- open when first detected; refresh in place while `proposed` if the plan drifts.
- resolve an open row whose signature is absent from a fresh FULL scan.
- a `denied` signature waits `deny_cooldown_days`; an executed one waits
  `reexecute_cooldown_days`; then re-raises if still a problem.
- a `deferred` row surfaces again once `deferred_until` arrives.

Ships dark: `enabled()` needs pace_enabled ∧ pace_initiative_enabled ∧
pace_interventions_enabled. Pure helpers (grouping, lifecycle decision, condition
parsing/application, Slack reply parsing) are unit-tested; DB reads/writes are
thin and batched.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from middleware.auth import role_rank
from services import notifications, pace_auth
from services.pace_actions import PACE_ACTIONS
from services.pace_auth import ActionContext

logger = logging.getLogger(__name__)

_SEV_RANK = {"info": 0, "warning": 1, "critical": 2}
_OPEN_STATUSES = ("proposed", "deferred", "executing")
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def enabled() -> bool:
    return bool(settings.pace_enabled and settings.pace_initiative_enabled
               and settings.pace_interventions_enabled)


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested)
# ---------------------------------------------------------------------------
def normalize_name(name: Optional[str]) -> str:
    """Casefold + collapse whitespace + strip trailing punctuation — the key the
    duplicate detector (and `match_open_tasks`) collide on. Pure."""
    return " ".join((name or "").casefold().split()).rstrip(" .!:-—")


def plan_fingerprint(actions: list[dict]) -> str:
    """A stable hash of a fix plan's action list, so a scan can tell whether an
    open problem's plan has drifted. Order-independent per action identity. Pure."""
    keys = sorted(
        json.dumps({"a": a.get("action"), "c": a.get("client_id"), "g": a.get("args", {})},
                   sort_keys=True, default=str)
        for a in actions
    )
    return hashlib.sha256("|".join(keys).encode()).hexdigest()[:16]


def cap_actions(actions: list[dict], max_actions: int) -> tuple[list[dict], int]:
    """Trim to the cap; return (kept, overflow). Pure."""
    if max_actions <= 0 or len(actions) <= max_actions:
        return actions, 0
    return actions[:max_actions], len(actions) - max_actions


def group_duplicates(tasks: list[dict], min_group: int) -> dict[str, list[dict]]:
    """Open tasks bucketed by normalized name, keeping only real collisions
    (≥ min_group sharing a non-empty name). Pure."""
    buckets: dict[str, list[dict]] = defaultdict(list)
    for t in tasks:
        buckets[normalize_name(t.get("name"))].append(t)
    return {k: v for k, v in buckets.items() if k and len(v) >= max(2, min_group)}


def disambiguation_renames(group_tasks: list[dict],
                           section_label_by_id: dict) -> list[tuple[dict, str]]:
    """For one colliding-name group, keep the earliest-created task's name and
    propose a disambiguated name for the rest — distinguisher precedence
    assignee → section (month) → a counter, uniqueness-guarded. Returns
    [(task, new_name)]. Pure (append-a-suffix, always reversible)."""
    ordered = sorted(group_tasks, key=lambda t: (str(t.get("created_at") or ""), str(t.get("id"))))
    primary, rest = ordered[0], ordered[1:]
    used = {normalize_name(primary.get("name"))}
    out: list[tuple[dict, str]] = []
    for i, t in enumerate(rest, start=2):
        base = (t.get("name") or "").strip()
        dist = (t.get("assignee_name") or "").strip() or (section_label_by_id.get(t.get("section_id")) or "").strip()
        candidate = f"{base} — {dist}" if dist else f"{base} ({i})"
        if normalize_name(candidate) in used:
            candidate = f"{base} — {dist} ({i})" if dist else f"{base} ({i})"
        used.add(normalize_name(candidate))
        out.append((t, candidate))
    return out


def _cooldown_elapsed(row: dict, today: date, days: int) -> bool:
    ref = row.get("decided_at") or row.get("updated_at") or row.get("created_at")
    try:
        d = datetime.fromisoformat(str(ref).replace("Z", "+00:00")).date()
    except (ValueError, TypeError):
        return True  # unknown timestamp → don't suppress forever
    return (today - d).days >= max(0, days)


def _to_date(value) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def decide_scan_action(row: Optional[dict], today: date, *, new_fingerprint: str,
                       deny_cooldown_days: int, reexec_cooldown_days: int) -> str:
    """What a scan should do about a currently-detected problem given the latest
    stored row for its signature: 'create' | 'refresh' | 'resurface' | 'skip'.
    Pure — unit-tested (the lifecycle heart)."""
    if not row:
        return "create"
    status = row.get("status")
    if status == "executing":
        return "skip"  # mid-run — never touch
    if status == "proposed":
        return "refresh" if row.get("plan_fingerprint") != new_fingerprint else "skip"
    if status == "deferred":
        until = _to_date(row.get("deferred_until"))
        return "skip" if (until and until > today) else "resurface"
    if status == "denied":
        return "skip" if not _cooldown_elapsed(row, today, deny_cooldown_days) else "create"
    if status in ("executed", "failed"):
        return "skip" if not _cooldown_elapsed(row, today, reexec_cooldown_days) else "create"
    # resolved / superseded → recurrence
    return "create"


# --- approve-with-conditions: pure directive application ---
def heuristic_conditions(conditions: str, actions: list[dict]) -> dict:
    """A deterministic read of the common condition phrasings, so approve-with-
    conditions works without the LLM. Returns a directive dict (see
    apply_conditions). Pure — unit-tested."""
    text = (conditions or "").lower()
    directive: dict = {}
    # cap / max / first N / no more than N
    m = re.search(r"\b(?:cap|caps|max|maximum|no more than|first|top|limit|only|up to|at most)\b[^\d]{0,8}(\d+)", text)
    if m and ("cap" in text or "max" in text or "no more than" in text or "first" in text
              or "top" in text or "limit" in text or "up to" in text or "at most" in text):
        directive["max_actions"] = int(m.group(1))
    # only / just <member> — match against the assignees the plan actually targets
    assignees = {(a.get("args") or {}).get("assignee") for a in actions if (a.get("args") or {}).get("assignee")}
    assignees = {a for a in assignees if a}
    if ("only" in text or "just" in text or "to " in text):
        for name in assignees:
            first = name.split()[0].lower()
            if re.search(rf"\b{re.escape(first)}\b", text):
                directive["only_assignee"] = name
                break
    # skip / except / exclude <client>
    if any(w in text for w in ("skip", "except", "exclude", "not ")):
        clients = {a.get("client_name") for a in actions if a.get("client_name")}
        excl = [c for c in clients if c and re.search(rf"\b{re.escape(c.split()[0].lower())}\b", text)]
        if excl:
            directive["exclude_clients"] = excl
    return directive


def apply_conditions(actions: list[dict], directive: dict) -> list[dict]:
    """Apply a structured condition directive to a fix plan, deterministically.
    Directive keys: drop_indexes[int 1-based], exclude_clients[str],
    only_assignee[str], assignee_overrides{task_name:member}, max_actions[int].
    Pure — unit-tested."""
    drop = {int(i) for i in (directive.get("drop_indexes") or []) if str(i).isdigit()}
    exclude = {(c or "").casefold() for c in (directive.get("exclude_clients") or [])}
    only = (directive.get("only_assignee") or "").casefold().strip()
    overrides = {(k or "").strip().casefold(): v for k, v in (directive.get("assignee_overrides") or {}).items()}
    kept: list[dict] = []
    for i, a in enumerate(actions, start=1):
        if i in drop:
            continue
        if exclude and (a.get("client_name") or "").casefold() in exclude:
            continue
        args = dict(a.get("args") or {})
        tname = (args.get("task_name") or "").strip().casefold()
        if tname in overrides:
            args["assignee"] = overrides[tname]
        assignee = (args.get("assignee") or "").casefold()
        if only and args.get("assignee") is not None and only not in assignee and assignee not in only:
            continue  # a targeted move to someone other than the allowed member
        kept.append({**a, "args": args})
    max_actions = directive.get("max_actions")
    if isinstance(max_actions, int) and max_actions > 0:
        kept = kept[:max_actions]
    return kept


# --- Slack reply parsing ---
def parse_relative_date(text: str, today: date) -> Optional[date]:
    """Parse a defer date from a fragment: ISO YYYY-MM-DD, 'in N days' / 'N days',
    'tomorrow', 'next week', a weekday name / 'next <weekday>'. None if unknown.
    Pure — unit-tested."""
    t = re.sub(r"^to\s+", "", (text or "").strip().lower()).strip()
    if not t:
        return None
    m = re.search(r"(\d{4}-\d{2}-\d{2})", t)
    if m:
        try:
            return date.fromisoformat(m.group(1))
        except ValueError:
            return None
    if "tomorrow" in t:
        return today + timedelta(days=1)
    if "next week" in t:
        return today + timedelta(days=7)
    m = re.search(r"(?:in\s+)?(\d+)\s*days?", t)
    if m:
        return today + timedelta(days=int(m.group(1)))
    for i, wd in enumerate(_WEEKDAYS):
        if wd in t:
            ahead = (i - today.weekday()) % 7
            ahead = ahead or 7  # today's weekday name → next week's occurrence
            return today + timedelta(days=ahead)
    return None


def parse_intervention_reply(text: str) -> Optional[dict]:
    """Parse a Slack disposition reply → {index, disposition, until?, conditions?}
    or None. 'approve 2' / 'deny 2' / 'defer 2 to 2026-09-05' /
    'approve 2 but only reassign to Ivy'. Pure — unit-tested."""
    m = re.match(r"^\s*(approve|accept|deny|dismiss|reject|decline|defer|snooze)\s+#?(\d+)\b(.*)$",
                 (text or "").strip(), re.IGNORECASE)
    if not m:
        return None
    verb, idx, rest = m.group(1).lower(), int(m.group(2)), (m.group(3) or "").strip()
    if verb in ("deny", "dismiss", "reject", "decline"):
        return {"index": idx, "disposition": "deny", "conditions": rest or None}
    if verb in ("defer", "snooze"):
        return {"index": idx, "disposition": "defer", "until_text": rest}
    # approve / accept — a trailing constraint turns it into approve-with-conditions
    lead = rest.lstrip()
    if lead:
        cleaned = re.sub(r"^(but|if|only|except|however|though|-|,|:)\s*", "", lead, flags=re.IGNORECASE).strip()
        return {"index": idx, "disposition": "conditions", "conditions": cleaned or lead}
    return {"index": idx, "disposition": "approve"}


# ---------------------------------------------------------------------------
# Small DB reads
# ---------------------------------------------------------------------------
def _client_names(client_ids) -> dict:
    ids = sorted({c for c in client_ids if c})
    if not ids:
        return {}
    rows = (get_supabase().table("clients").select("id, name").in_("id", ids).execute()).data or []
    return {r["id"]: r.get("name") for r in rows}


def _open_rows() -> list[dict]:
    return (
        get_supabase().table("pace_interventions").select("*")
        .in_("status", list(_OPEN_STATUSES)).execute()
    ).data or []


def _latest_rows(signatures: set[str]) -> dict[str, dict]:
    """Newest row per signature (any status) — the lifecycle decision input."""
    if not signatures:
        return {}
    rows = (
        get_supabase().table("pace_interventions").select("*")
        .in_("signature", sorted(signatures))
        .order("created_at", desc=True).execute()
    ).data or []
    latest: dict[str, dict] = {}
    for r in rows:
        latest.setdefault(r["signature"], r)  # first seen = newest (desc order)
    return latest


# ---------------------------------------------------------------------------
# Detectors — each returns proposals: {kind, scope_client_id, signature,
# severity, title, problem, evidence, actions[]}. Uniform signature
# (today, digest, critical_only); reuse the one board digest the scan builds.
# ---------------------------------------------------------------------------
def detect_member_overload(today: date, digest: Optional[dict], critical_only: bool) -> list[dict]:
    from services import pace_rebalance, pm_assign, task_workload

    report = (digest or {}).get("workload") or task_workload.build_team_workload()
    overloaded = report.get("overloaded") or []
    if not overloaded:
        return []
    members = pm_assign._active_members()
    member_ids = [m["gid"] for m in members]
    skills = pm_assign._skills_by_member(member_ids)
    load = task_workload.open_hours_for_members(member_ids)
    initial_keys = pace_rebalance._initial_status_keys()
    default_weekly = settings.asana_default_weekly_hours
    by_gid = {m.get("gid"): m for m in report.get("members") or []}

    proposals: list[dict] = []
    for om in overloaded:
        gid = om.get("gid")
        rm = by_gid.get(gid) or om
        cap = rm.get("weekly_hours") if rm.get("weekly_hours") is not None else default_weekly
        if not cap or float(cap) <= 0:
            continue
        open_hours = float(rm.get("open_hours") or 0)
        pct = open_hours / float(cap)
        if pct < settings.pace_intervention_overload_pct:
            continue  # only SEVERE overload becomes an intervention (routine → Chase Plan)
        severe = pct >= settings.pace_intervention_overload_critical_pct
        if critical_only and not severe:
            continue
        over_hours = max(0.0, open_hours - float(cap))
        movable = pace_rebalance._movable_tasks(gid, initial_keys)
        plan = {"moves": [], "freed": 0.0, "remaining_over": over_hours}
        if movable and over_hours > 0:
            eligible_by_client = {cid: pm_assign._eligible_member_ids(cid)
                                  for cid in sorted({t["client_id"] for t in movable})}
            plan = pm_assign.build_rebalance(
                gid, over_hours, movable, members, skills, eligible_by_client, load,
                default_hours=settings.asana_default_task_hours, default_weekly_hours=default_weekly,
            )
        names = _client_names([mv["client_id"] for mv in plan["moves"]])
        actions = [
            {"action": "reassign_task", "client_id": mv["client_id"],
             "client_name": names.get(mv["client_id"], "client"),
             "args": {"task_name": mv["task_name"], "assignee": mv["to_name"]},
             "reason": f"move “{mv['task_name']}” ({mv['est']:g}h) → {mv['to_name']}",
             "perm": "reassign_task"}
            for mv in plan["moves"]
        ]
        actions, overflow = cap_actions(actions, settings.pace_intervention_max_actions)
        who = rm.get("name") or om.get("name") or "A teammate"
        if actions:
            problem = (f"{who} has {open_hours:g}h of open work against a {cap:g}h weekly cap "
                       f"({round(pct * 100)}%). PACE can rebalance ~{plan['freed']:g}h by moving "
                       f"{len(actions)} not-yet-started task(s) to teammates with room"
                       + (f" (+{overflow} more held)." if overflow else "."))
        else:
            problem = (f"{who} has {open_hours:g}h of open work against a {cap:g}h weekly cap "
                       f"({round(pct * 100)}%), but no not-yet-started work is movable — this needs "
                       f"a manual call (extend deadlines, cut scope, or add capacity).")
        proposals.append({
            "kind": "member_overload", "scope_client_id": None,
            "signature": f"member_overload:{gid}",
            "severity": "critical" if severe else "warning",
            "title": f"{who} is overloaded ({round(pct * 100)}% of capacity)",
            "problem": problem,
            "evidence": {"member": who, "open_hours": round(open_hours, 1), "cap": float(cap),
                         "pct": round(pct, 2), "freed": round(float(plan.get("freed") or 0), 1),
                         "moves": len(actions), "overflow": overflow},
            "actions": actions,
        })
    return proposals


def detect_duplicate_names(today: date, digest: Optional[dict], critical_only: bool) -> list[dict]:
    rows = (
        get_supabase().table("tasks")
        .select("id, client_id, name, assignee_name, section_id, created_at")
        .eq("completed", False).is_("deleted_at", "null").is_("parent_task_id", "null")
        .not_.is_("client_id", "null").execute()
    ).data or []
    if not rows:
        return []
    by_client: dict[str, list[dict]] = defaultdict(list)
    for t in rows:
        by_client[t["client_id"]].append(t)
    section_ids = sorted({t["section_id"] for t in rows if t.get("section_id")})
    section_labels: dict = {}
    if section_ids:
        for s in (get_supabase().table("task_sections").select("id, name")
                  .in_("id", section_ids).execute()).data or []:
            section_labels[s["id"]] = s.get("name")
    names = _client_names(list(by_client))

    proposals: list[dict] = []
    for cid, tasks in by_client.items():
        groups = group_duplicates(tasks, settings.pace_intervention_dupe_min_group)
        if not groups:
            continue
        colliding_total = sum(len(v) for v in groups.values())
        severe = colliding_total >= settings.pace_intervention_dupe_critical_count
        if critical_only and not severe:
            continue
        cname = names.get(cid, "client")
        actions: list[dict] = []
        for group in groups.values():
            for task, new_name in disambiguation_renames(group, section_labels):
                actions.append({
                    "action": "rename_task", "client_id": cid, "client_name": cname,
                    "args": {"task_id": task["id"], "task_name": task.get("name"), "new_name": new_name},
                    "reason": f"rename “{task.get('name')}” → “{new_name}”", "perm": "rename_task",
                })
        actions, overflow = cap_actions(actions, settings.pace_intervention_max_actions)
        proposals.append({
            "kind": "duplicate_names", "scope_client_id": cid,
            "signature": f"duplicate_names:{cid}",
            "severity": "critical" if severe else "warning",
            "title": f"{cname}: {len(groups)} duplicate task name(s) blocking automation",
            "problem": (f"{colliding_total} open tasks share {len(groups)} name(s), so PACE can't tell "
                        f"which task an action targets and skips them. Disambiguating {len(actions)} name(s) "
                        f"unblocks them" + (f" (+{overflow} more held)." if overflow else ".")
                        + " (Renames only — exact duplicates to merge are left for a human.)"),
            "evidence": {"groups": [{"name": (v[0].get("name") or ""), "count": len(v)}
                                    for v in list(groups.values())[:20]],
                         "colliding_total": colliding_total, "overflow": overflow},
            "actions": actions,
        })
    return proposals


def _client_signal_lists(digest: Optional[dict], today: date):
    from services import pm_signals
    if digest and digest.get("clients") is not None:
        return digest["clients"]
    return pm_signals.build_board_digest(None, today).get("clients") or []


def detect_untriaged_backlog(today: date, digest: Optional[dict], critical_only: bool) -> list[dict]:
    if critical_only:
        return []
    proposals: list[dict] = []
    clients = _client_signal_lists(digest, today)
    names = _client_names([c.get("client_id") for c in clients])
    for c in clients:
        unassigned = c.get("unassigned") or []
        if len(unassigned) < settings.pace_intervention_untriaged_min:
            continue
        cid = c.get("client_id")
        cname = names.get(cid, "client")
        actions = [
            {"action": "assign_task", "client_id": cid, "client_name": cname,
             "args": {"task_name": u.get("name") or ""},
             "reason": f"auto-place “{u.get('name')}”", "perm": "assign_task"}
            for u in unassigned if u.get("name")
        ]
        actions, overflow = cap_actions(actions, settings.pace_intervention_max_actions)
        if not actions:
            continue
        proposals.append({
            "kind": "untriaged_backlog", "scope_client_id": cid,
            "signature": f"untriaged_backlog:{cid}",
            "severity": "warning",
            "title": f"{cname}: {len(unassigned)} unassigned tasks piling up",
            "problem": (f"{len(unassigned)} open tasks have no owner. PACE can auto-place "
                        f"{len(actions)} to the best-fit, least-loaded eligible teammate"
                        + (f" (+{overflow} more held)." if overflow else ".")),
            "evidence": {"unassigned": len(unassigned), "overflow": overflow},
            "actions": actions,
        })
    return proposals


def detect_overdue_cluster(today: date, digest: Optional[dict], critical_only: bool) -> list[dict]:
    if critical_only:
        return []
    proposals: list[dict] = []
    clients = _client_signal_lists(digest, today)
    names = _client_names([c.get("client_id") for c in clients])
    for c in clients:
        overdue = c.get("overdue") or []
        if len(overdue) < settings.pace_intervention_overdue_min:
            continue
        cid = c.get("client_id")
        cname = names.get(cid, "client")
        assigned = [o for o in overdue if o.get("assignee_name")]
        actions = [
            {"action": "nudge_assignee", "client_id": cid, "client_name": cname,
             "args": {"task_name": o.get("name") or ""},
             "reason": f"nudge {o.get('assignee_name')} — “{o.get('name')}” overdue", "perm": "nudge_other"}
            for o in assigned if o.get("name")
        ]
        actions, overflow = cap_actions(actions, settings.pace_intervention_max_actions)
        if not actions:
            continue
        unassigned_overdue = len(overdue) - len(assigned)
        tail = f" {unassigned_overdue} overdue task(s) are unassigned — assign them too." if unassigned_overdue else ""
        proposals.append({
            "kind": "overdue_cluster", "scope_client_id": cid,
            "signature": f"overdue_cluster:{cid}",
            "severity": "warning",
            "title": f"{cname}: {len(overdue)} overdue tasks",
            "problem": (f"{len(overdue)} open tasks are past due. PACE can nudge the {len(actions)} "
                        f"assignee(s) to move them" + (f" (+{overflow} more held)." if overflow else ".") + tail),
            "evidence": {"overdue": len(overdue), "unassigned_overdue": unassigned_overdue, "overflow": overflow},
            "actions": actions,
        })
    return proposals


def detect_slip_forecast(today: date, digest: Optional[dict], critical_only: bool) -> list[dict]:
    if critical_only:
        return []
    from services import pace_slips, pm_assign, task_service, task_workload

    rows = (
        get_supabase().table("tasks")
        .select("id, client_id, name, category, est_hours, status_key, assignee_id, assignee_name, due_date")
        .eq("completed", False).is_("deleted_at", "null").is_("parent_task_id", "null")
        .not_.is_("due_date", "null").not_.is_("client_id", "null").execute()
    ).data or []
    if not rows:
        return []
    members = pm_assign._active_members()
    members_by_id = {m["gid"]: m for m in members}
    initial_keys = {s["key"] for s in task_service.get_statuses(active_only=False)
                    if s.get("is_initial") or s.get("category") == "not_started"}
    slips = pace_slips.forecast_slips(
        rows, members_by_id, initial_keys, today, settings.pace_slip_horizon_days,
        default_hours=settings.asana_default_task_hours,
        default_weekly_hours=settings.asana_default_weekly_hours,
        daily_workdays=settings.asana_workload_daily_workdays,
    )
    if not slips:
        return []
    by_client: dict[str, list[dict]] = defaultdict(list)
    for s in slips:
        by_client[s["task"]["client_id"]].append(s)
    member_ids = list(members_by_id)
    skills = pm_assign._skills_by_member(member_ids)
    load = task_workload.open_hours_for_members(member_ids)
    names = _client_names(list(by_client))

    proposals: list[dict] = []
    for cid, client_slips in by_client.items():
        if len(client_slips) < settings.pace_intervention_slip_min:
            continue
        cname = names.get(cid, "client")
        eligible = pm_assign._eligible_member_ids(cid)
        actions: list[dict] = []
        for s in client_slips:
            t = s["task"]
            if s["reason"] == "unassigned":
                actions.append({"action": "assign_task", "client_id": cid, "client_name": cname,
                                "args": {"task_name": t.get("name") or ""},
                                "reason": f"place “{t.get('name')}” (due {s['due'].isoformat()})",
                                "perm": "assign_task"})
                continue
            pool = [m for m in members if m["gid"] != t.get("assignee_id")]
            pick = pm_assign.pick_assignee(
                t, pool, skills, eligible, load,
                default_hours=settings.asana_default_task_hours,
                default_weekly_hours=settings.asana_default_weekly_hours, overload="hold")
            if pick.get("gid"):
                actions.append({"action": "reassign_task", "client_id": cid, "client_name": cname,
                                "args": {"task_name": t.get("name") or "", "assignee": pick.get("name")},
                                "reason": f"move “{t.get('name')}” → {pick.get('name')} (due {s['due'].isoformat()})",
                                "perm": "reassign_task"})
        actions, overflow = cap_actions(actions, settings.pace_intervention_max_actions)
        if not actions:
            continue
        proposals.append({
            "kind": "slip_forecast", "scope_client_id": cid,
            "signature": f"slip_forecast:{cid}",
            "severity": "warning",
            "title": f"{cname}: {len(client_slips)} tasks forecast to slip",
            "problem": (f"{len(client_slips)} task(s) due soon won't be met by their current owner. "
                        f"PACE can rebalance/place {len(actions)} of them now"
                        + (f" (+{overflow} more held)." if overflow else ".")),
            "evidence": {"slips": len(client_slips), "overflow": overflow},
            "actions": actions,
        })
    return proposals


ALL_DETECTORS = [
    detect_member_overload, detect_duplicate_names, detect_untriaged_backlog,
    detect_overdue_cluster, detect_slip_forecast,
]
# The severe pass (every scheduler tick) — only the flagship, high-cost problems.
SEVERE_DETECTORS = [detect_member_overload, detect_duplicate_names]


# ---------------------------------------------------------------------------
# Scan (reconcile + surface)
# ---------------------------------------------------------------------------
def _insert(p: dict, fingerprint: str) -> Optional[dict]:
    plan = {"actions": p["actions"], "summary": p.get("problem", ""),
            "overflow": (p.get("evidence") or {}).get("overflow", 0)}
    try:
        rows = (get_supabase().table("pace_interventions").insert({
            "kind": p["kind"], "scope_client_id": p.get("scope_client_id"),
            "signature": p["signature"], "severity": p["severity"],
            "title": p["title"], "problem": p.get("problem", ""),
            "plan": plan, "plan_fingerprint": fingerprint, "evidence": p.get("evidence") or {},
            "status": "proposed",
        }).execute()).data
        return rows[0] if rows else None
    except Exception as exc:  # unique open-signature race → another tick already opened it
        logger.info("pace_intervention_insert_skipped",
                    extra={"signature": p["signature"], "error": str(exc)[:120]})
        return None


def _refresh(row_id: str, p: dict, fingerprint: str) -> None:
    plan = {"actions": p["actions"], "summary": p.get("problem", ""),
            "overflow": (p.get("evidence") or {}).get("overflow", 0)}
    get_supabase().table("pace_interventions").update({
        "severity": p["severity"], "title": p["title"], "problem": p.get("problem", ""),
        "plan": plan, "plan_fingerprint": fingerprint, "evidence": p.get("evidence") or {},
        "deferred_until": None, "status": "proposed",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", row_id).execute()


def run_intervention_scan(today: Optional[date] = None, *, severe_only: bool = False) -> dict:
    """Scan → reconcile → surface. Full scan (daily) runs every detector and
    resolves cleared problems; the severe pass (per tick) runs only the flagship
    detectors on critical problems and never resolves. Self-gated; best-effort."""
    if not enabled():
        return {"scanned": False, "reason": "disabled"}
    today = today or date.today()
    detectors = SEVERE_DETECTORS if severe_only else ALL_DETECTORS
    digest = None
    if not severe_only:
        from services import pm_signals
        try:
            digest = pm_signals.build_board_digest(None, today)
        except Exception as exc:
            logger.warning("pace_intervention_digest_failed", extra={"error": str(exc)})

    proposals: list[dict] = []
    for det in detectors:
        try:
            proposals.extend(det(today, digest, severe_only) or [])
        except Exception as exc:
            logger.warning("pace_intervention_detector_failed",
                           extra={"detector": getattr(det, "__name__", "?"), "error": str(exc)})

    by_sig: dict[str, dict] = {}
    for p in proposals:
        cur = by_sig.get(p["signature"])
        if not cur or _SEV_RANK[p["severity"]] > _SEV_RANK[cur["severity"]]:
            by_sig[p["signature"]] = p

    open_rows = _open_rows()
    open_by_sig = {r["signature"]: r for r in open_rows}
    latest = _latest_rows(set(by_sig) | set(open_by_sig))

    surfaced: list[dict] = []
    for sig, p in by_sig.items():
        fp = plan_fingerprint(p["actions"])
        action = decide_scan_action(
            latest.get(sig), today, new_fingerprint=fp,
            deny_cooldown_days=settings.pace_intervention_deny_cooldown_days,
            reexec_cooldown_days=settings.pace_intervention_reexecute_cooldown_days)
        if action == "create":
            row = _insert(p, fp)
            if row:
                surfaced.append(row)
        elif action == "refresh":
            row = latest.get(sig)
            if row:
                _refresh(row["id"], p, fp)
        elif action == "resurface":
            row = latest.get(sig)
            if row:
                _refresh(row["id"], p, fp)
                surfaced.append({**row, **p, "id": row["id"]})
        # skip → leave as-is

    resolved = 0
    if not severe_only:
        # Resolve open problems that cleared (only a full scan has looked at all of them).
        for sig, row in open_by_sig.items():
            if sig not in by_sig and row.get("status") in ("proposed", "deferred"):
                get_supabase().table("pace_interventions").update({
                    "status": "resolved", "updated_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", row["id"]).execute()
                resolved += 1

    if surfaced:
        _emit_digest(surfaced, today)
    return {"scanned": True, "severe_only": severe_only, "surfaced": len(surfaced),
            "resolved": resolved, "detected": len(by_sig)}


# ---------------------------------------------------------------------------
# Slack surface (index + digest + reply routing)
# ---------------------------------------------------------------------------
_channel_index: dict[str, dict[int, str]] = {}  # channel → {1-based index: intervention_id}


def _emit_digest(surfaced: list[dict], today: date) -> None:
    """Post the newly-surfaced interventions to the PACE channel + in-app, and
    refresh the Slack reply index (1-based, most-recent digest)."""
    surfaced = sorted(surfaced, key=lambda r: -_SEV_RANK.get(r.get("severity", "warning"), 1))
    worst = "critical" if any(r.get("severity") == "critical" for r in surfaced) else "warning"
    lines = []
    index: dict[int, str] = {}
    for i, r in enumerate(surfaced, start=1):
        index[i] = r["id"]
        n = len((r.get("plan") or {}).get("actions") or [])
        mark = "🔴" if r.get("severity") == "critical" else "🟠"
        fixes = f"{n} fix{'es' if n != 1 else ''}" if n else "manual call"
        lines.append(f"*{i}.* {mark} {r.get('title')} — {fixes}. "
                     f"`approve {i}` · `deny {i}` · `defer {i} to <date>`")
    channel = settings.pace_slack_channel
    if channel:
        _channel_index[channel] = index
    body = ("PACE spotted problems that need your call:\n" + "\n".join(lines)
            + "\nDecide here or on the PACE page → /pace")
    # Portfolio digest → the PACE channel (Slack) + the in-app feed. This is the
    # PM-facing rollup across every affected client.
    notifications.emit(
        client_id=None, kind="pace_intervention",
        title=f"PACE — {len(surfaced)} intervention{'s' if len(surfaced) != 1 else ''} need a decision",
        summary=body, severity=worst,
        payload={"link": "/pace", "slack_channel": channel or None},
        dedupe_key=f"pace_intervention:{today.isoformat()}:{plan_fingerprint([{'action': r['id']} for r in surfaced])}",
    )
    # …and a note on each individual client's workspace Alerts feed (in-app only —
    # the portfolio digest already carries the Slack copy, so skip Slack here to
    # avoid double-posting). Client-scoped kinds (duplicate/untriaged/overdue/slip
    # carry a scope_client_id); member_overload is cross-client and gets none.
    for r in surfaced:
        cid = r.get("scope_client_id")
        if not cid:
            continue
        try:
            notifications.emit(
                client_id=cid, kind="pace_intervention",
                title=r.get("title") or "PACE intervention", summary=r.get("problem") or "",
                severity=r.get("severity") or "warning",
                payload={"link": "/pace", "skip_channels": ["slack"]},
                dedupe_key=f"pace_intervention_client:{r['id']}",
            )
        except Exception as exc:
            logger.info("pace_intervention_client_note_failed",
                        extra={"client_id": cid, "error": str(exc)[:120]})


async def dispose_from_slack(channel: str, disp: dict, context: ActionContext) -> Optional[str]:
    """Route a parsed Slack disposition to `dispose`. Returns the reply text, or
    None when the index isn't known (→ the caller falls through to normal
    handling). Best-effort."""
    index = _channel_index.get(channel or "")
    iid = (index or {}).get(disp.get("index"))
    if not iid:
        return None
    until = None
    if disp.get("disposition") == "defer":
        until = parse_relative_date(disp.get("until_text") or "", date.today())
        if not until:
            return "When should I defer it to? Try `defer 2 to 2026-09-05` or `defer 2 in 3 days`."
    result = await dispose(iid, context, disp["disposition"],
                           until=until, conditions=disp.get("conditions"))
    return result.get("message") or "Done."


def resolve_channel_index(channel: str, index: Optional[int]) -> Optional[str]:
    """The intervention id a channel's 1-based reply index points at (or None)."""
    return (_channel_index.get(channel or "") or {}).get(index)


def render_plan_preview(row: dict, disposition: str, conditions: Optional[str]) -> str:
    """The itemized 'here's exactly what I'll do' rundown shown before an approve
    runs (Slack mrkdwn). Pure — unit-tested."""
    actions = (row.get("plan") or {}).get("actions") or []
    overflow = (row.get("plan") or {}).get("overflow") or 0
    lines = [f"*{row.get('title')}*"]
    if row.get("problem"):
        lines.append(row["problem"])
    if disposition == "conditions" and conditions:
        lines.append(f"_Applying your condition: “{conditions}” (I'll re-plan to honor it.)_")
    if not actions:
        lines += ["", "There's no automated fix — approving just acknowledges this (a manual call).",
                  "Reply *yes* to acknowledge, or *no* to leave it open."]
        return "\n".join(lines)
    lines += ["", f"I'll make these {len(actions)} change{'s' if len(actions) != 1 else ''}:"]
    for i, a in enumerate(actions[:25], start=1):
        who = f" — _{a['client_name']}_" if a.get("client_name") else ""
        lines.append(f"  {i}. {a.get('reason') or a.get('action')}{who}")
    if overflow:
        lines.append(f"  …and {overflow} more held for the next round.")
    lines += ["", "Reply *yes* to run all of them, or *no* to cancel."]
    return "\n".join(lines)


async def prepare_slack_approval(intervention_id: str, disposition: str,
                                 conditions: Optional[str], context: ActionContext) -> dict:
    """Build the preview for an approve/approve-with-conditions before it runs.
    Returns {text, stage}: stage=True means the caller should stash a pending
    confirm and a 'yes' then executes it. Permission is checked HERE so an
    unauthorized ask is refused before anything is staged."""
    if not _can_decide(context):
        return {"text": (
            f"That needs the *{settings.pace_intervention_decider_min_role}* role or higher."
            if not context.is_anonymous else
            "Link your Slack account first (an admin can do it on the Team page)."), "stage": False}
    row = get_intervention(intervention_id)
    if not row:
        return {"text": "That intervention no longer exists.", "stage": False}
    if row.get("status") not in ("proposed", "deferred"):
        return {"text": f"That intervention is already *{row.get('status')}*.", "stage": False}
    return {"text": render_plan_preview(row, disposition, conditions), "stage": True}


async def run_pending_disposition(pending: dict, context: ActionContext) -> str:
    """Execute a staged intervention approval on a 'yes' (from pace_agent's pending
    store). Returns the thread reply."""
    result = await dispose(pending["intervention"], context, pending.get("disposition") or "approve",
                           conditions=pending.get("conditions"))
    return result.get("message") or "Done."


# ---------------------------------------------------------------------------
# Dispositions (called by the router + Slack)
# ---------------------------------------------------------------------------
def _can_decide(context: ActionContext) -> bool:
    if context.source == "system":
        return True
    if context.is_anonymous:
        return False
    return role_rank(context.role) >= role_rank(settings.pace_intervention_decider_min_role)


def get_intervention(intervention_id: str) -> Optional[dict]:
    rows = (get_supabase().table("pace_interventions").select("*")
            .eq("id", intervention_id).limit(1).execute()).data
    return rows[0] if rows else None


def list_interventions(*, status: Optional[str] = None, limit: int = 50) -> list[dict]:
    q = get_supabase().table("pace_interventions").select("*")
    if status == "open":
        q = q.in_("status", list(_OPEN_STATUSES))
    elif status:
        q = q.eq("status", status)
    return (q.order("created_at", desc=True).limit(limit).execute()).data or []


async def _call(fn, *args):
    out = fn(*args)
    if inspect.isawaitable(out):
        out = await out
    return out


async def _execute_actions(actions: list[dict], context: ActionContext) -> dict:
    """Re-stage each action (re-resolve target + re-check permission) then run.
    A staging refusal ('reply') is a skip, never a blind write. Returns
    {ran, skipped, failed}."""
    ran, skipped, failed = [], [], []
    for a in actions:
        meta = PACE_ACTIONS.get(a.get("action"))
        if not meta:
            skipped.append({"reason": f"unknown action {a.get('action')}", "action": a.get("action")})
            continue
        cid = a.get("client_id")
        try:
            outcome, staged = await _call(meta["stage"], context, cid, a.get("args") or {})
        except Exception as exc:
            failed.append({"reason": str(exc)[:160], "action": a.get("action"), "detail": a.get("reason")})
            continue
        if outcome == "reply":
            skipped.append({"reason": str(staged)[:200], "action": a.get("action"), "detail": a.get("reason")})
            continue
        staged.pop("_confirm", None)
        staged.pop("_requester", None)
        try:
            result = await _call(meta["run"], context, cid, staged)
            ran.append(str(result))
        except Exception as exc:
            failed.append({"reason": str(exc)[:160], "action": a.get("action"), "detail": a.get("reason")})
    return {"ran": ran, "skipped": skipped, "failed": failed}


async def parse_conditions(conditions: str, actions: list[dict]) -> dict:
    """Interpret a free-text condition into a structured directive. The LLM (when
    configured) parses arbitrary phrasings; the deterministic heuristic is the
    guaranteed floor. LLM keys win where present. Best-effort."""
    directive = heuristic_conditions(conditions, actions)
    llm = {}
    try:
        llm = await _llm_conditions(conditions, actions)
    except Exception as exc:
        logger.info("pace_intervention_conditions_llm_failed", extra={"error": str(exc)[:120]})
    directive.update({k: v for k, v in (llm or {}).items() if v not in (None, "", [], {})})
    return directive


async def _llm_conditions(conditions: str, actions: list[dict]) -> dict:
    if not (settings.anthropic_api_key and conditions.strip()):
        return {}
    import anthropic

    assignees = sorted({(a.get("args") or {}).get("assignee") for a in actions
                        if (a.get("args") or {}).get("assignee")})
    clients = sorted({a.get("client_name") for a in actions if a.get("client_name")})
    tool = {
        "name": "emit_directive",
        "description": "Structured constraints to apply to the proposed fix actions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "only_assignee": {"type": "string", "description": "Keep only reassignments to this team member (exact name from the list)."},
                "exclude_clients": {"type": "array", "items": {"type": "string"}, "description": "Drop actions for these clients (exact names)."},
                "drop_indexes": {"type": "array", "items": {"type": "integer"}, "description": "1-based action numbers to drop."},
                "max_actions": {"type": "integer", "description": "Cap the number of actions run."},
                "assignee_overrides": {"type": "object", "description": "task name → team member name to reassign to instead."},
            },
        },
    }
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    msg = await client.messages.create(
        model=settings.pace_intervention_conditions_model, max_tokens=600,
        tool_choice={"type": "tool", "name": "emit_directive"}, tools=[tool],
        messages=[{"role": "user", "content": (
            f"Team members: {', '.join(assignees) or 'n/a'}. Clients: {', '.join(clients) or 'n/a'}.\n"
            f"There are {len(actions)} proposed fix actions.\n"
            f"Turn this instruction into constraints: “{conditions.strip()}”")}],
    )
    for block in msg.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "emit_directive":
            return dict(block.input or {})
    return {}


async def dispose(intervention_id: str, context: ActionContext, disposition: str, *,
                  until: Optional[date] = None, conditions: Optional[str] = None,
                  note: Optional[str] = None) -> dict:
    """Apply a PM's decision to an intervention. Staff-gated; approve/conditions
    also re-authorize each action at execution. Returns {ok, message, status, ...}."""
    if not _can_decide(context):
        return {"ok": False, "message": (
            f"That needs the *{settings.pace_intervention_decider_min_role}* role or higher."
            if not context.is_anonymous else "Link your account first to decide on interventions."),
            "status": None}
    row = get_intervention(intervention_id)
    if not row:
        return {"ok": False, "message": "That intervention no longer exists.", "status": None}
    if row.get("status") not in ("proposed", "deferred"):
        return {"ok": False, "message": f"That intervention is already *{row.get('status')}*.",
                "status": row.get("status")}
    disposition = (disposition or "").lower()
    if disposition in ("approve", "accept"):
        return await _approve(row, context, conditions=None)
    if disposition in ("conditions", "approve_conditions"):
        return await _approve(row, context, conditions=conditions)
    if disposition in ("deny", "dismiss", "reject", "decline"):
        return _deny(row, context, note or conditions)
    if disposition in ("defer", "snooze"):
        return _defer(row, context, until)
    return {"ok": False, "message": f"Unknown disposition “{disposition}”.", "status": row.get("status")}


def _decision_fields(context: ActionContext, disposition: str) -> dict:
    return {"disposition": disposition, "decided_by": context.profile_id,
            "decided_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat()}


def _deny(row: dict, context: ActionContext, note: Optional[str]) -> dict:
    get_supabase().table("pace_interventions").update({
        "status": "denied", "result": {"note": note} if note else None,
        **_decision_fields(context, "denied"),
    }).eq("id", row["id"]).execute()
    return {"ok": True, "status": "denied",
            "message": f"Denied — “{row.get('title')}”. I won't raise it again for "
                       f"{settings.pace_intervention_deny_cooldown_days} days."}


def _defer(row: dict, context: ActionContext, until: Optional[date]) -> dict:
    if not until or until <= date.today():
        return {"ok": False, "status": row.get("status"),
                "message": "Give me a future date to defer to (e.g. 2026-09-05)."}
    get_supabase().table("pace_interventions").update({
        "status": "deferred", "deferred_until": until.isoformat(),
        **_decision_fields(context, "deferred"),
    }).eq("id", row["id"]).execute()
    return {"ok": True, "status": "deferred",
            "message": f"Deferred “{row.get('title')}” until {until.isoformat()} — I'll resurface it then."}


async def _approve(row: dict, context: ActionContext, *, conditions: Optional[str]) -> dict:
    actions = list((row.get("plan") or {}).get("actions") or [])
    if conditions:
        directive = await parse_conditions(conditions, actions)
        actions = apply_conditions(actions, directive)
        if not actions:
            return {"ok": False, "status": row.get("status"),
                    "message": "Those conditions dropped every proposed action — nothing to run. "
                               "Approve as-is or adjust the conditions."}
    # Claim it (a concurrent scan skips 'executing').
    get_supabase().table("pace_interventions").update(
        {"status": "executing", "updated_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", row["id"]).execute()
    if not actions:
        result = {"ran": [], "skipped": [], "failed": [], "acknowledged": True}
        get_supabase().table("pace_interventions").update({
            "status": "executed", "result": result, "conditions": conditions,
            **_decision_fields(context, "approved"),
        }).eq("id", row["id"]).execute()
        return {"ok": True, "status": "executed",
                "message": f"Acknowledged “{row.get('title')}” — no automated fix to run (manual call)."}
    result = await _execute_actions(actions, context)
    status = "executed" if result["ran"] else ("failed" if result["failed"] else "executed")
    get_supabase().table("pace_interventions").update({
        "status": status, "result": result, "conditions": conditions,
        **_decision_fields(context, "approved"),
    }).eq("id", row["id"]).execute()
    _emit_result(row, result, status)
    ran, skipped, failed = len(result["ran"]), len(result["skipped"]), len(result["failed"])
    bits = [f"{ran} done"]
    if skipped:
        bits.append(f"{skipped} skipped")
    if failed:
        bits.append(f"{failed} failed")
    return {"ok": status == "executed", "status": status,
            "message": f"Ran the fix for “{row.get('title')}” — {', '.join(bits)}.", "result": result}


def _emit_result(row: dict, result: dict, status: str) -> None:
    ran, skipped, failed = len(result["ran"]), len(result["skipped"]), len(result["failed"])
    lines = [f"• {r}" for r in result["ran"][:12]]
    if failed:
        lines += [f"• ❌ {f.get('detail') or f.get('action')} — {f.get('reason')}" for f in result["failed"][:6]]
    notifications.emit(
        client_id=row.get("scope_client_id"), kind="pace_intervention_result",
        title=f"PACE ran “{row.get('title')}” — {ran} done"
              + (f", {failed} failed" if failed else ""),
        summary="\n".join(lines) or "Nothing to run.",
        severity="warning" if failed else "info",
        payload={"link": "/pace", "slack_channel": settings.pace_slack_channel or None},
    )


# Scheduler entrypoints (positional-arg friendly for _safe / to_thread).
def run_full_scan(today: Optional[date] = None) -> dict:
    return run_intervention_scan(today, severe_only=False)


def run_severe_scan(today: Optional[date] = None) -> dict:
    return run_intervention_scan(today, severe_only=True)


def resurface_due_deferred(today: Optional[date] = None) -> int:
    """Flip deferred interventions whose snooze elapsed back to proposed (so the
    next scan/panel shows them). Cheap; called from the scan. Returns the count."""
    if not enabled():
        return 0
    today = today or date.today()
    rows = (get_supabase().table("pace_interventions").select("id, deferred_until")
            .eq("status", "deferred").lte("deferred_until", today.isoformat()).execute()).data or []
    for r in rows:
        get_supabase().table("pace_interventions").update(
            {"status": "proposed", "updated_at": datetime.now(timezone.utc).isoformat()}
        ).eq("id", r["id"]).execute()
    return len(rows)
