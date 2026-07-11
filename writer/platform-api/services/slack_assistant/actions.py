"""Actions — SerMastr can trigger work (not just report). Anyone in the channel
may trigger (product decision); paid/side-effecting actions are gated behind
an explicit confirmation. Runners take (client_id, args) and return a reply
string; they may be sync or async.

Part of the `services.slack_assistant` package; see its docstring for the
full picture."""

from __future__ import annotations

from datetime import date
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import task_catalog


def match_named(items: list[dict], query: str, key: str = "name") -> list[dict]:
    """Items whose `key` matches the query. Pure.

    Case-insensitive; an exact match wins outright (so "citations" can't be
    ambiguous with "citations — batch 2" when the user names one exactly),
    else substring matches."""
    q = (query or "").strip().casefold()
    if not q:
        return []
    exact = [i for i in items if (i.get(key) or "").strip().casefold() == q]
    if exact:
        return exact
    return [i for i in items if q in (i.get(key) or "").casefold()]


def match_open_tasks(tasks: list[dict], query: str) -> list[dict]:
    """Open tasks whose name matches the query. Pure.

    Completed tasks are never candidates; matching per `match_named`."""
    return match_named([t for t in tasks if not t.get("completed")], query)


def merge_cities(existing, additions) -> tuple[list[str], list[str], list[str]]:
    """Append cities to a target-city list, case-insensitively deduped. Pure.

    Returns (merged, added, already_present) — `already_present` in the
    teammate's casing so the reply can name what was skipped."""
    merged = [str(c).strip() for c in (existing or []) if str(c).strip()]
    was_existing = {c.casefold() for c in merged}
    have = set(was_existing)
    added, already = [], []
    for c in additions or []:
        name = str(c).strip()
        if not name:
            continue
        key = name.casefold()
        if key in have:
            if key in was_existing:  # intra-request dupes skip silently
                already.append(name)
            continue
        have.add(key)
        merged.append(name)
        added.append(name)
    return merged, added, already


def drop_cities(existing, removals) -> tuple[list[str], list[str], list[str]]:
    """Remove cities from a target-city list, case-insensitively. Pure.

    Returns (remaining, removed, missing) — `removed` in the STORED casing
    (what actually leaves the list), `missing` in the teammate's casing."""
    current = [str(c).strip() for c in (existing or []) if str(c).strip()]
    wanted = {str(c).strip().casefold() for c in (removals or []) if str(c).strip()}
    remaining = [c for c in current if c.casefold() not in wanted]
    removed = [c for c in current if c.casefold() in wanted]
    hit = {c.casefold() for c in removed}
    missing = [str(c).strip() for c in (removals or []) if str(c).strip() and str(c).strip().casefold() not in hit]
    return remaining, removed, missing


# Client-profile fields SerMastr may edit (the Setup page's simple scalars).
# Deliberately excluded: name (used for chat client-resolution + dup-checked),
# brand guide / ICP text (long-form authored assets), GBP + page structures
# (complex objects with their own capture flows), WP/Drive credentials.
_PROFILE_FIELDS = {
    "website_url": "the website URL",
    "gsc_property": "the Search Console property",
    "business_location": "the business location",
    "retainer_monthly": "the monthly retainer",
    "client_type": "the client type",
    "is_sab": "the service-area-business (SAB) flag",
}


def coerce_profile_value(field: str, value) -> tuple[object, Optional[str]]:
    """Validate + coerce a profile edit's value. Pure. Returns (coerced, error).

    Mirrors the clients API's typing: retainer → float, client_type →
    local|enterprise, is_sab → bool, website_url → scheme-prefixed."""
    if field not in _PROFILE_FIELDS:
        editable = ", ".join(_PROFILE_FIELDS)
        return None, f"I can't edit “{field}” — I can change: {editable}."
    raw = ("" if value is None else str(value)).strip()
    if not raw:
        return None, f"What should {_PROFILE_FIELDS[field]} be set to?"
    if field == "retainer_monthly":
        try:
            return float(raw.replace("$", "").replace(",", "")), None
        except ValueError:
            return None, f"“{raw}” isn't a number — give me the monthly retainer in dollars."
    if field == "client_type":
        v = raw.lower()
        if v not in ("local", "enterprise"):
            return None, "Client type must be *local* or *enterprise*."
        return v, None
    if field == "is_sab":
        v = raw.lower()
        if v in ("true", "yes", "y", "1", "on", "sab"):
            return True, None
        if v in ("false", "no", "n", "0", "off"):
            return False, None
        return None, "Should the SAB flag be *yes* or *no*?"
    if field == "website_url":
        return (raw if raw.startswith(("http://", "https://")) else f"https://{raw}"), None
    return raw, None


def _act_rebuild_plan(client_id: str, args: Optional[dict] = None) -> str:
    from services import reopt_planner

    res = reopt_planner.build_plan(client_id, trigger="manual")
    return f"✅ Rebuilt the Action Plan — {res.get('summary')}."


def _act_maps_scan(client_id: str, args: Optional[dict] = None) -> str:
    from services import local_dominator

    started = local_dominator.enqueue_maps_scan(client_id, trigger="manual")
    return (
        "✅ Started a Maps geo-grid scan — results land in a few minutes."
        if started
        else "A Maps scan is already running for this client."
    )


def _act_gsc_research(client_id: str, args: Optional[dict] = None) -> str:
    from services import gsc_research

    job_id = gsc_research.enqueue_gsc_research(client_id, trigger="manual")
    return (
        "✅ Started a GSC Research analysis."
        if job_id
        else "A GSC Research run is already in progress for this client."
    )


def _act_strategy_review(client_id: str, args: Optional[dict] = None) -> str:
    from services import strategist

    if not settings.strategist_enabled:
        return (
            "The strategist is currently disabled (`strategist_enabled` is off) — "
            "it activates once the smoke gate is passed."
        )
    review_id = strategist.enqueue_strategy_review(client_id, trigger="on_demand", notify=True)
    return (
        "🧠 Strategist review started — the digest will post to the alerts channel "
        "when it's done; the full review (with Approve/Dismiss) lands on the client's "
        "Action Plan page."
        if review_id
        else "A strategist review is already running for this client."
    )


def _act_ai_scan(client_id: str, args: Optional[dict] = None) -> str:
    from fastapi import HTTPException

    from services import brand_service

    try:
        brand_service.start_scan(client_id, None, None, False, None)
        return "✅ Started an AI Visibility scan across the engines."
    except HTTPException as exc:
        if exc.detail == "no_keywords_to_scan":
            return "No AI-visibility keywords are set up for this client yet — add some first."
        raise


def _act_push_task_plan(client_id: str, args: Optional[dict] = None) -> str:
    from services import asana_monthly, asana_push, asana_service

    if not asana_service.is_configured():
        return "Asana isn't connected yet (ASANA_TOKEN + workspace) — set that up on the platform first."
    if not asana_monthly.get_project_gid(client_id):
        return "This client has no Asana project mapped yet — set it on their Asana Tasks page first."
    rows = (
        get_supabase()
        .table("monthly_task_plans")
        .select("id, month, plan")
        .eq("client_id", client_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    ).data
    if not rows:
        return "No monthly task plan exists for this client yet — generate one on the Task Plan page first."
    plan_row = rows[0]
    if not ((plan_row.get("plan") or {}).get("tasks")):
        return "The latest task plan has no task lines to push (empty or frozen plan)."
    asana_push.enqueue_asana_push(client_id, str(plan_row["id"]))
    return (
        f"✅ Pushing the latest task plan ({plan_row.get('month') or 'current month'}) to Asana — "
        "tasks land on the board in a moment. Already-pushed lines are skipped."
    )


def _asana_ready(client_id: str) -> tuple[Optional[str], Optional[str]]:
    """(project_gid, None) when the client's task board is usable, else
    (None, guidance string). Post-cutover (native_tasks_enabled) the native
    board needs no Asana config/mapping — returns a "native" sentinel."""
    from services import asana_monthly, asana_service

    if settings.native_tasks_enabled:
        return "native", None
    if not asana_service.is_configured():
        return None, "Asana isn't connected yet (ASANA_TOKEN + workspace) — set that up on the platform first."
    project_gid = asana_monthly.get_project_gid(client_id)
    if not project_gid:
        return None, "This client has no Asana project mapped yet — set it on their Asana Tasks page first."
    return project_gid, None


async def _stage_add_task(client_id: str, args: dict) -> tuple[str, dict | str]:
    """Resolve the assignee and build the exact confirm text for add_asana_task."""
    from services.asana_push import match_member_gid

    name = (args.get("task_name") or "").strip()
    if not name:
        return "reply", "What should the task be called?"
    _, problem = _asana_ready(client_id)
    if problem:
        return "reply", problem

    # Due date resolution (owner rule): an explicit date wins; otherwise
    # default to the task's SOP delivery turnaround; if the task isn't in the
    # SOP catalog (or its turnaround is a recurring/undefined cadence), ask the
    # teammate to confirm a date rather than creating a dateless task. An
    # explicit "leave it blank" (no_due_date) opts out of both.
    due = (args.get("due_date") or "").strip()
    due_note = ""
    if due:
        try:
            date.fromisoformat(due)
        except ValueError:
            return "reply", "The due date must be YYYY-MM-DD (e.g. 2026-12-31)."
    elif not args.get("no_due_date"):
        sop = task_catalog.due_date_for(args.get("sop_task") or "", date.today())
        if sop:
            due_date_obj, delivery_text, label = sop
            due = due_date_obj.isoformat()
            due_note = f" (SOP delivery: {delivery_text} for {label})"
        else:
            return "reply", (
                f"I couldn't find a set delivery time for *“{name}”* in the SOP task "
                "catalog. What due date should I set? (YYYY-MM-DD — or say to leave it "
                "blank and the team will fill it in.)"
            )

    assignee_note = "unassigned"
    assignee_gid = None
    wanted = (args.get("assignee") or "").strip()
    if wanted:
        members = (
            get_supabase().table("asana_team_members").select("gid, name")
            .eq("active", True).execute()
        ).data or []
        assignee_gid = match_member_gid(wanted, members)
        if assignee_gid:
            full = next((m.get("name") for m in members if m["gid"] == assignee_gid), wanted)
            assignee_note = f"assigned to *{full}*"
        else:
            assignee_note = (
                f"unassigned — I couldn't match “{wanted}” to a tracked team member "
                "(check the Workload page)"
            )
    staged = {**args, "task_name": name, "assignee_gid": assignee_gid, "due_date": due or None}
    if due:
        detail = f"{assignee_note}, due {due}{due_note}"
    else:
        detail = f"{assignee_note}, no due date"
    staged["_confirm"] = f"create the Asana task *“{name}”* ({detail})"
    return "confirm", staged


async def _act_add_task(client_id: str, args: Optional[dict] = None) -> str:
    from services import asana_push, asana_service

    args = args or {}
    if settings.native_tasks_enabled:
        # Cutover: create on the native board (same staged args — assignee_gid
        # resolved against asana_team_members, which stays the capacity roster).
        from services import task_monthly, task_service

        section = task_monthly.ensure_month_section(client_id, date.today())
        gid = args.get("assignee_gid")
        assignee_name = None
        if gid:
            rows = (
                get_supabase().table("asana_team_members").select("name").eq("gid", gid).limit(1).execute()
            ).data
            assignee_name = rows[0].get("name") if rows else None
        row = task_service.create_task(
            (args.get("task_name") or "Task")[:250],
            client_id=client_id,
            section_id=section["id"],
            assignee_gid=gid,
            assignee_name=assignee_name,
            due_date=(args.get("due_date") or "").strip() or None,
            description=(
                f"AR Tools · created via SerMastr\n{args['notes']}"
                if args.get("notes")
                else "AR Tools · created via SerMastr"
            ),
        )
        who = "" if gid else " (unassigned)"
        when = f" · due {row['due_date']}" if row.get("due_date") else ""
        return f"✅ Created *“{row['name']}”*{who}{when} — /clients/{client_id}/tasks?task={row['id']}"
    project_gid, problem = _asana_ready(client_id)
    if problem:
        return problem
    section_gid = await asana_push._ensure_month_section(project_gid, date.today())
    fields = await asana_service.resolve_project_fields(project_gid)
    due_on = (args.get("due_date") or "").strip() or None
    payload = asana_service.build_task_payload(
        (args.get("task_name") or "Task")[:250],
        project_gid,
        section_gid or "",
        assignee_gid=args.get("assignee_gid"),
        status_field_gid=fields.get("status_field_gid") or "",
        not_started_option_gid=fields.get("not_started_option_gid") or "",
        due_on=due_on,
    )
    if not section_gid:  # section create failed → land in the project top-level
        payload.pop("memberships", None)
    notes = ["AR Tools · created via SerMastr"]
    if args.get("notes"):
        notes.append(str(args["notes"]))
    payload["notes"] = "\n".join(notes)
    result = await asana_service.create_task(payload)
    gid = (result or {}).get("gid")
    if not gid:
        return "Asana didn't return the new task — check the board."
    who = "" if args.get("assignee_gid") else " (unassigned)"
    when = f" · due {due_on}" if due_on else ""
    return f"✅ Created *“{payload['name']}”*{who}{when} — {asana_push.task_url(gid)}"


async def _stage_pick_task(client_id: str, args: dict, verb: str) -> tuple[str, dict | str]:
    """Shared resolver for remove/complete: find exactly one open task by name.

    Resolution happens BEFORE the confirm so the reply-*yes* names the exact
    task (never 'yes' to a fuzzy match)."""
    from services import asana_service

    query = (args.get("task_name") or "").strip()
    if not query:
        return "reply", f"Which task should I {verb}? Give me (part of) its name."
    project_gid, problem = _asana_ready(client_id)
    if problem:
        return "reply", problem
    if settings.native_tasks_enabled:
        # Cutover: match against the native board (adapted to the Asana row
        # shape match_open_tasks already understands).
        rows = (
            get_supabase()
            .table("tasks")
            .select("id, name, assignee_name")
            .eq("client_id", client_id)
            .eq("completed", False)
            .is_("deleted_at", "null")
            .is_("parent_task_id", "null")
            .execute()
        ).data or []
        tasks = [
            {
                "gid": r["id"],
                "name": r.get("name"),
                "completed": False,
                "assignee": {"name": r["assignee_name"]} if r.get("assignee_name") else None,
            }
            for r in rows
        ]
    else:
        tasks = await asana_service.list_project_tasks(project_gid)
    matches = match_open_tasks(tasks, query)
    if not matches:
        open_names = [t.get("name") for t in tasks if not t.get("completed") and t.get("name")]
        listing = "; ".join(open_names[:8]) or "none"
        return "reply", (
            f"I couldn't find an open task matching “{query}” on this board. "
            f"Open tasks: {listing}."
        )
    if len(matches) > 1:
        listing = "\n".join(f"• {t.get('name')}" for t in matches[:8])
        return "reply", (
            f"“{query}” matches {len(matches)} open tasks — which one?\n{listing}"
        )
    task = matches[0]
    who = (task.get("assignee") or {}).get("name")
    staged = {**args, "task_gid": task.get("gid"), "task_name": task.get("name")}
    staged["_confirm"] = (
        f"{verb} the Asana task *“{task.get('name')}”*"
        + (f" (assigned to {who})" if who else " (unassigned)")
    )
    return "confirm", staged


async def _stage_remove_task(client_id: str, args: dict) -> tuple[str, dict | str]:
    return await _stage_pick_task(client_id, args, "permanently delete")


async def _stage_complete_task(client_id: str, args: dict) -> tuple[str, dict | str]:
    return await _stage_pick_task(client_id, args, "mark complete")


async def _act_remove_task(client_id: str, args: Optional[dict] = None) -> str:
    from services import asana_service

    args = args or {}
    if not args.get("task_gid"):
        return "I lost track of which task to delete — ask again naming the task."
    if settings.native_tasks_enabled:
        from services import task_service

        task_service.soft_delete_task(args["task_gid"])
        return f"🗑️ Moved *“{args.get('task_name')}”* to the board's Trash (restorable there)."
    await asana_service.delete_task(args["task_gid"])
    return f"🗑️ Deleted *“{args.get('task_name')}”* from the board."


async def _act_complete_task(client_id: str, args: Optional[dict] = None) -> str:
    from services import asana_service

    args = args or {}
    if not args.get("task_gid"):
        return "I lost track of which task to complete — ask again naming the task."
    if settings.native_tasks_enabled:
        from services import task_service

        task_service.complete_task(args["task_gid"])
        return f"✅ Marked *“{args.get('task_name')}”* complete."
    await asana_service.complete_task(args["task_gid"])
    return f"✅ Marked *“{args.get('task_name')}”* complete."


# ---------------------------------------------------------------------------
# Admin actions — client profile, target cities, tracked keywords, AI-visibility
# keywords/competitors, campaign goals, client reports. All confirm-gated
# (writes to campaign state / paid follow-on work), all staged so the confirm
# names the exact change before anything is written.
# ---------------------------------------------------------------------------
def _clean_list(values) -> list[str]:
    """Trim + case-insensitively dedupe a Claude-supplied string list."""
    seen: dict[str, str] = {}
    for v in values or []:
        name = str(v).strip() if v is not None else ""
        if name:
            seen.setdefault(name.casefold(), name)
    return list(seen.values())


def _client_row(client_id: str, columns: str) -> dict:
    rows = (
        get_supabase().table("clients").select(columns).eq("id", client_id).limit(1).execute()
    ).data
    return rows[0] if rows else {}


def _fmt_profile_value(field: str, value) -> str:
    if field == "is_sab":
        return "yes" if value else "no"
    if field == "retainer_monthly" and value is not None:
        return f"${value:,.0f}"
    return str(value) if value not in (None, "") else "(not set)"


async def _stage_update_profile(client_id: str, args: dict) -> tuple[str, dict | str]:
    field = (args.get("field") or "").strip()
    coerced, error = coerce_profile_value(field, args.get("value"))
    if error:
        return "reply", error
    current = _client_row(client_id, field).get(field)
    if current == coerced:
        return "reply", f"{_PROFILE_FIELDS[field].capitalize()} is already *{_fmt_profile_value(field, coerced)}* — nothing to change."
    staged = {**args, "field": field, "coerced_value": coerced}
    staged["_confirm"] = (
        f"set {_PROFILE_FIELDS[field]} to *{_fmt_profile_value(field, coerced)}* "
        f"(currently *{_fmt_profile_value(field, current)}*)"
    )
    return "confirm", staged


def _act_update_profile(client_id: str, args: Optional[dict] = None) -> str:
    args = args or {}
    field = args.get("field")
    if field not in _PROFILE_FIELDS or "coerced_value" not in args:
        return "I lost track of which field to change — ask again naming the field and value."
    value = args["coerced_value"]
    supabase = get_supabase()
    updates: dict = {field: value, "updated_at": "now()"}
    if field == "website_url":
        # Mirror the clients API: a website change re-runs the site analysis.
        updates.update(
            {"website_analysis_status": "pending", "website_analysis": None, "website_analysis_error": None}
        )
    supabase.table("clients").update(updates).eq("id", client_id).execute()
    if field == "website_url":
        supabase.table("async_jobs").insert(
            {
                "job_type": "website_scrape",
                "entity_id": client_id,
                "payload": {"website_url": value, "client_id": client_id},
            }
        ).execute()
        return f"✅ Website set to *{value}* — re-running the site analysis in the background."
    return f"✅ Set {_PROFILE_FIELDS[field]} to *{_fmt_profile_value(field, value)}*."


async def _stage_add_cities(client_id: str, args: dict) -> tuple[str, dict | str]:
    cities = _clean_list(args.get("cities"))
    if not cities:
        return "reply", "Which cities should I add to the target list?"
    existing = _client_row(client_id, "target_cities").get("target_cities") or []
    merged, added, already = merge_cities(existing, cities)
    if not added:
        return "reply", f"Already on the target list: {', '.join(already)} — nothing to add."
    staged = {**args, "merged": merged, "added": added, "already": already}
    note = f" ({', '.join(already)} already on the list)" if already else ""
    staged["_confirm"] = f"add *{', '.join(added)}* to the target-city list{note}"
    return "confirm", staged


def _act_add_cities(client_id: str, args: Optional[dict] = None) -> str:
    args = args or {}
    if not args.get("merged"):
        return "I lost track of which cities to add — ask again naming them."
    get_supabase().table("clients").update(
        {"target_cities": args["merged"], "updated_at": "now()"}
    ).eq("id", client_id).execute()
    return (
        f"✅ Added *{', '.join(args.get('added') or [])}* to the target cities "
        f"({len(args['merged'])} total). The Local SEO silo planner picks them up on its next run."
    )


async def _stage_remove_cities(client_id: str, args: dict) -> tuple[str, dict | str]:
    cities = _clean_list(args.get("cities"))
    if not cities:
        return "reply", "Which cities should I remove from the target list?"
    existing = _client_row(client_id, "target_cities").get("target_cities") or []
    remaining, removed, missing = drop_cities(existing, cities)
    if not removed:
        listing = ", ".join(existing[:12]) or "none"
        return "reply", (
            f"None of those are on the target list. Current target cities: {listing}."
        )
    staged = {**args, "remaining": remaining, "removed": removed}
    note = f" ({', '.join(missing)} not on the list)" if missing else ""
    staged["_confirm"] = f"remove *{', '.join(removed)}* from the target-city list{note}"
    return "confirm", staged


def _act_remove_cities(client_id: str, args: Optional[dict] = None) -> str:
    args = args or {}
    if not args.get("removed"):
        return "I lost track of which cities to remove — ask again naming them."
    get_supabase().table("clients").update(
        {"target_cities": args.get("remaining") or [], "updated_at": "now()"}
    ).eq("id", client_id).execute()
    return f"🗑️ Removed *{', '.join(args['removed'])}* from the target cities ({len(args.get('remaining') or [])} remain)."


async def _stage_add_tracked_keywords(client_id: str, args: dict) -> tuple[str, dict | str]:
    keywords = _clean_list(args.get("keywords"))
    if not keywords:
        return "reply", "Which keywords should I start tracking?"
    existing = {
        (r.get("keyword") or "").casefold()
        for r in (
            get_supabase().table("tracked_keywords").select("keyword")
            .eq("client_id", client_id).execute()
        ).data or []
    }
    new = [k for k in keywords if k.casefold() not in existing]
    dupes = [k for k in keywords if k.casefold() in existing]
    if not new:
        return "reply", f"Already tracked: {', '.join(dupes)} — nothing to add."
    staged = {**args, "new": new}
    note = f" ({', '.join(dupes)} already tracked)" if dupes else ""
    staged["_confirm"] = f"start rank-tracking *{', '.join(new)}*{note}"
    return "confirm", staged


def _act_add_tracked_keywords(client_id: str, args: Optional[dict] = None) -> str:
    from services import keyword_market, rank_materialize

    args = args or {}
    new = args.get("new") or []
    if not new:
        return "I lost track of which keywords to add — ask again naming them."
    supabase = get_supabase()
    supabase.table("tracked_keywords").upsert(
        [{"client_id": client_id, "keyword": kw, "source": "gsc"} for kw in new],
        on_conflict="client_id,keyword",
        ignore_duplicates=True,
    ).execute()
    # Same follow-on as the Rankings page: backfill the rank axis + market data.
    rank_materialize.enqueue_materialize(client_id)
    keyword_market.enqueue_keyword_market(client_id)
    return (
        f"✅ Now tracking *{', '.join(new)}* — backfilling rank history and market "
        "data in the background; they appear on the Rankings page shortly."
    )


async def _stage_remove_tracked_keyword(client_id: str, args: dict) -> tuple[str, dict | str]:
    query = (args.get("keyword") or "").strip()
    if not query:
        return "reply", "Which keyword should I stop tracking?"
    rows = (
        get_supabase().table("tracked_keywords").select("id, keyword")
        .eq("client_id", client_id).execute()
    ).data or []
    matches = match_named(rows, query, key="keyword")
    if not matches:
        listing = "; ".join(r["keyword"] for r in rows[:10]) or "none"
        return "reply", f"“{query}” isn't tracked for this client. Tracked keywords: {listing}."
    if len(matches) > 1:
        listing = "\n".join(f"• {r['keyword']}" for r in matches[:8])
        return "reply", f"“{query}” matches {len(matches)} tracked keywords — which one?\n{listing}"
    staged = {**args, "keyword_id": matches[0]["id"], "keyword": matches[0]["keyword"]}
    staged["_confirm"] = (
        f"stop tracking *“{matches[0]['keyword']}”* and delete its rank history"
    )
    return "confirm", staged


def _act_remove_tracked_keyword(client_id: str, args: Optional[dict] = None) -> str:
    args = args or {}
    if not args.get("keyword_id"):
        return "I lost track of which keyword to remove — ask again naming it."
    get_supabase().table("tracked_keywords").delete().eq("id", args["keyword_id"]).execute()
    return f"🗑️ Stopped tracking *“{args.get('keyword')}”*."


async def _stage_add_ai_keywords(client_id: str, args: dict) -> tuple[str, dict | str]:
    from services import brand_service

    keywords = _clean_list(args.get("keywords"))
    if not keywords:
        return "reply", "Which keywords should I add to AI Visibility tracking?"
    existing = {
        (r.get("keyword") or "").casefold() for r in brand_service.list_keywords(client_id)
    }
    new = [k for k in keywords if k.casefold() not in existing]
    dupes = [k for k in keywords if k.casefold() in existing]
    if not new:
        return "reply", f"Already tracked in AI Visibility: {', '.join(dupes)} — nothing to add."
    staged = {**args, "new": new}
    note = f" ({', '.join(dupes)} already tracked)" if dupes else ""
    staged["_confirm"] = f"add *{', '.join(new)}* to AI Visibility tracking{note}"
    return "confirm", staged


def _act_add_ai_keywords(client_id: str, args: Optional[dict] = None) -> str:
    from fastapi import HTTPException

    from services import brand_service

    args = args or {}
    new = args.get("new") or []
    if not new:
        return "I lost track of which keywords to add — ask again naming them."
    added = []
    for kw in new:
        try:
            brand_service.add_keyword(client_id, kw, None)
            added.append(kw)
        except HTTPException as exc:
            if exc.detail != "keyword_exists":
                raise
    return (
        f"✅ Added *{', '.join(added)}* to AI Visibility — they're included in the next scan."
        if added
        else "Those keywords were already tracked — nothing added."
    )


async def _stage_remove_ai_keyword(client_id: str, args: dict) -> tuple[str, dict | str]:
    from services import brand_service

    query = (args.get("keyword") or "").strip()
    if not query:
        return "reply", "Which AI-visibility keyword should I remove?"
    rows = brand_service.list_keywords(client_id)
    matches = match_named(rows, query, key="keyword")
    if not matches:
        listing = "; ".join(r["keyword"] for r in rows[:10]) or "none"
        return "reply", f"“{query}” isn't an AI-visibility keyword here. Tracked: {listing}."
    if len(matches) > 1:
        listing = "\n".join(f"• {r['keyword']}" for r in matches[:8])
        return "reply", f"“{query}” matches {len(matches)} keywords — which one?\n{listing}"
    staged = {**args, "keyword_id": matches[0]["id"], "keyword": matches[0]["keyword"]}
    staged["_confirm"] = f"remove *“{matches[0]['keyword']}”* from AI Visibility tracking"
    return "confirm", staged


def _act_remove_ai_keyword(client_id: str, args: Optional[dict] = None) -> str:
    from services import brand_service

    args = args or {}
    if not args.get("keyword_id"):
        return "I lost track of which keyword to remove — ask again naming it."
    brand_service.delete_keyword(client_id, args["keyword_id"])
    return f"🗑️ Removed *“{args.get('keyword')}”* from AI Visibility tracking."


async def _stage_add_ai_competitor(client_id: str, args: dict) -> tuple[str, dict | str]:
    from services import brand_service

    name = (args.get("name") or "").strip()
    if not name:
        return "reply", "Which competitor should I add to AI Visibility tracking?"
    existing = brand_service.list_competitors(client_id)
    if any((c.get("competitor_name") or "").casefold() == name.casefold() for c in existing):
        return "reply", f"*{name}* is already a tracked AI-visibility competitor."
    staged = {**args, "name": name}
    site = (args.get("website") or "").strip()
    staged["_confirm"] = (
        f"add *{name}*{f' ({site})' if site else ''} as an AI Visibility competitor"
    )
    return "confirm", staged


def _act_add_ai_competitor(client_id: str, args: Optional[dict] = None) -> str:
    from fastapi import HTTPException

    from services import brand_service

    args = args or {}
    name = (args.get("name") or "").strip()
    if not name:
        return "I lost track of which competitor to add — ask again naming them."
    try:
        brand_service.add_competitor(client_id, name, (args.get("website") or "").strip() or None, None)
    except HTTPException as exc:
        if exc.detail == "competitor_exists":
            return f"*{name}* is already a tracked AI-visibility competitor."
        raise
    return f"✅ Added *{name}* as an AI Visibility competitor — they're classified against the next scan."


async def _stage_remove_ai_competitor(client_id: str, args: dict) -> tuple[str, dict | str]:
    from services import brand_service

    query = (args.get("name") or "").strip()
    if not query:
        return "reply", "Which AI-visibility competitor should I remove?"
    rows = brand_service.list_competitors(client_id)
    matches = match_named(rows, query, key="competitor_name")
    if not matches:
        listing = "; ".join(r["competitor_name"] for r in rows[:10]) or "none"
        return "reply", f"“{query}” isn't a tracked competitor here. Tracked: {listing}."
    if len(matches) > 1:
        listing = "\n".join(f"• {r['competitor_name']}" for r in matches[:8])
        return "reply", f"“{query}” matches {len(matches)} competitors — which one?\n{listing}"
    staged = {**args, "competitor_id": matches[0]["id"], "name": matches[0]["competitor_name"]}
    staged["_confirm"] = f"remove *{matches[0]['competitor_name']}* from AI Visibility competitors"
    return "confirm", staged


def _act_remove_ai_competitor(client_id: str, args: Optional[dict] = None) -> str:
    from services import brand_service

    args = args or {}
    if not args.get("competitor_id"):
        return "I lost track of which competitor to remove — ask again naming them."
    brand_service.delete_competitor(client_id, args["competitor_id"])
    return f"🗑️ Removed *{args.get('name')}* from AI Visibility competitors."


async def _stage_add_goal(client_id: str, args: dict) -> tuple[str, dict | str]:
    from services.campaign_goals import GOAL_TYPES

    goal_type = (args.get("goal_type") or "").strip()
    if goal_type not in GOAL_TYPES:
        return "reply", f"Goal type must be one of: {', '.join(GOAL_TYPES)}."
    label = (args.get("label") or "").strip()
    if not label:
        return "reply", "What should the goal be called? Give me a short label."
    # Tolerate Claude passing numbers as strings.
    for num_field, caster in (("target_value", float), ("target_position", int)):
        if args.get(num_field) is not None:
            try:
                args[num_field] = caster(args[num_field])
            except (TypeError, ValueError):
                return "reply", f"“{args[num_field]}” isn't a number — what's the {num_field.replace('_', ' ')}?"
    # Mirror the Campaign Goals API's validation rules.
    if goal_type != "custom" and args.get("target_value") is None:
        return "reply", "What's the target value for this goal (a number)?"
    if goal_type == "keyword_position" and not (args.get("keyword") or "").strip():
        return "reply", "Which keyword is this position goal for?"
    if goal_type == "keywords_in_top" and not args.get("target_position"):
        return "reply", "Top what? Give me the position band (e.g. top 3 → 3)."
    due = (args.get("due_date") or "").strip()
    if due:
        try:
            date.fromisoformat(due)
        except ValueError:
            return "reply", "The due date must be YYYY-MM-DD (e.g. 2026-12-31)."
    staged = {**args, "label": label, "goal_type": goal_type}
    bits = [goal_type.replace("_", " ")]
    if args.get("keyword"):
        bits.append(f"keyword “{args['keyword']}”")
    if args.get("target_value") is not None:
        bits.append(f"target {args['target_value']:g}")
    if args.get("target_position"):
        bits.append(f"top {args['target_position']}")
    if due:
        bits.append(f"due {due}")
    staged["_confirm"] = f"create the campaign goal *“{label}”* ({', '.join(bits)})"
    return "confirm", staged


def _act_add_goal(client_id: str, args: Optional[dict] = None) -> str:
    from services import campaign_goals

    args = args or {}
    if not (args.get("label") and args.get("goal_type")):
        return "I lost track of the goal's details — ask again with the label and target."
    fields = {
        k: args.get(k)
        for k in ("goal_type", "label", "keyword", "target_value", "target_position", "due_date", "notes")
    }
    if isinstance(fields.get("due_date"), str) and not fields["due_date"].strip():
        fields["due_date"] = None
    row = campaign_goals.create_goal(client_id, fields, created_by=None)
    baseline = row.get("baseline_value")
    note = f" Baseline captured: {baseline:g}." if isinstance(baseline, (int, float)) else ""
    return (
        f"🎯 Created the campaign goal *“{row.get('label')}”*.{note} "
        "Progress is assessed on every read — see the Campaign Goals page."
    )


async def _stage_remove_goal(client_id: str, args: dict) -> tuple[str, dict | str]:
    query = (args.get("label") or "").strip()
    if not query:
        return "reply", "Which goal should I remove? Give me (part of) its label."
    rows = (
        get_supabase().table("campaign_goals").select("id, label, goal_type")
        .eq("client_id", client_id).execute()
    ).data or []
    matches = match_named(rows, query, key="label")
    if not matches:
        listing = "; ".join(r["label"] for r in rows[:10] if r.get("label")) or "none"
        return "reply", f"I couldn't find a goal matching “{query}”. Goals: {listing}."
    if len(matches) > 1:
        listing = "\n".join(f"• {r['label']}" for r in matches[:8])
        return "reply", f"“{query}” matches {len(matches)} goals — which one?\n{listing}"
    staged = {**args, "goal_id": matches[0]["id"], "label": matches[0]["label"]}
    staged["_confirm"] = f"permanently delete the campaign goal *“{matches[0]['label']}”*"
    return "confirm", staged


def _act_remove_goal(client_id: str, args: Optional[dict] = None) -> str:
    args = args or {}
    if not args.get("goal_id"):
        return "I lost track of which goal to delete — ask again naming it."
    get_supabase().table("campaign_goals").delete().eq("id", args["goal_id"]).eq(
        "client_id", client_id
    ).execute()
    return f"🗑️ Deleted the campaign goal *“{args.get('label')}”*."


_REPORT_TYPES = ("monthly", "weekly", "ai_visibility")


async def _stage_generate_report(client_id: str, args: dict) -> tuple[str, dict | str]:
    report_type = (args.get("report_type") or "monthly").strip()
    if report_type not in _REPORT_TYPES:
        return "reply", f"Report type must be one of: {', '.join(_REPORT_TYPES)}."
    deliver = bool(args.get("deliver"))
    staged = {**args, "report_type": report_type, "deliver": deliver}
    staged["_confirm"] = (
        f"generate a {report_type.replace('_', ' ')} client report"
        + (
            " and DELIVER it to the client per their report settings (email/Drive)"
            if deliver
            else " (internal — not delivered to the client)"
        )
    )
    return "confirm", staged


def _act_generate_report(client_id: str, args: Optional[dict] = None) -> str:
    from services import client_report

    args = args or {}
    report_type = args.get("report_type") or "monthly"
    deliver = bool(args.get("deliver"))
    client_report.enqueue_client_report(client_id, report_type, deliver=deliver)
    return (
        f"📄 Generating the {report_type.replace('_', ' ')} report — it lands on the "
        "Client Reports page in a minute or two"
        + (" and is delivered per the client's report settings." if deliver else ".")
    )


async def _stage_live_serp(client_id: str, args: dict) -> tuple[str, dict | str]:
    """Validate the keyword and name it in the confirm phrase."""
    keyword = (args.get("keyword") or "").strip()
    if not keyword:
        return (
            "reply",
            "Which keyword should I check? e.g. “check the live SERP for "
            "roof repair akron for Acme”.",
        )
    args["_confirm"] = f"run one live Google SERP check for *{keyword}*"
    return "confirm", args


async def _act_live_serp(client_id: str, args: Optional[dict] = None) -> str:
    """One live DataForSEO SERP pull: where the client's domain ranks right now."""
    from services import dataforseo_rank

    keyword = ((args or {}).get("keyword") or "").strip()
    supabase = get_supabase()
    rows = (
        supabase.table("clients")
        .select("website_url, gbp, rank_tracking_location_code")
        .eq("id", client_id)
        .limit(1)
        .execute()
    ).data
    if not rows:
        return "Client not found."
    c = rows[0]
    domain = dataforseo_rank.extract_domain(c.get("website_url") or "")
    if not domain:
        return "This client has no website URL on file — I can't identify their domain in the SERP."
    location_code = dataforseo_rank.location_code_for(c)
    try:
        urls = await dataforseo_rank.fetch_serp_rank_urls(keyword, domain, location_code)
    except Exception as exc:
        return f"Live SERP check failed: {exc}"
    if not urls:
        return (
            f"Live SERP for *{keyword}* (just checked): no page of {domain} in the "
            f"top {settings.dataforseo_serp_depth} organic results."
        )
    lines = "\n".join(f"  #{u['position']} — {u['url']}" for u in urls[:5])
    return f"Live SERP for *{keyword}* (just checked) — {domain} ranks:\n{lines}"


# ─────────────────────────────────────────────────────────────────────────────
# Backlink Explorer actions — live paid pulls, confirm-gated.
# ─────────────────────────────────────────────────────────────────────────────
async def _stage_backlink_lookup(client_id: str, args: dict) -> "tuple[str, dict | str]":
    from services import backlink_explorer

    raw = (args.get("domain") or "").strip()
    if not raw:
        return "reply", "Which domain should I look up?"
    try:
        target, target_type = backlink_explorer.normalize_target(raw)
    except ValueError:
        return "reply", f"“{raw}” doesn't look like a domain or URL I can analyze."
    staged = {"target": target, "target_type": target_type}
    staged["_confirm"] = (
        f"run a backlink lookup for *{target}* "
        "(up to 3 paid DataForSEO calls — free if it was checked in the last 24h)"
    )
    return "confirm", staged


async def _act_backlink_lookup(client_id: str, args: Optional[dict] = None) -> str:
    from services import backlink_explorer

    target = (args or {}).get("target")
    if not target:
        return "I lost track of the domain — ask again naming it."
    try:
        result = await backlink_explorer.lookup(target, client_id=client_id)
    except backlink_explorer.BudgetExceeded:
        return "The daily backlink API budget is used up — cached lookups still work; fresh pulls resume tomorrow."
    ov = result.get("overview") or {}
    dr = ov.get("domain_rating")
    lines = [
        f"*Backlink profile — {result.get('target')}*"
        + (" _(cached)_" if result.get("cached") else ""),
        f"DR {dr if dr is not None else '—'} · "
        f"{(ov.get('referring_domains') or 0):,} referring domains · "
        f"{(ov.get('backlinks') or 0):,} backlinks · "
        f"{(ov.get('pages_count') or 0):,} linked pages",
    ]
    pages = result.get("pages") or []
    if pages:
        lines.append("Top pages by referring domains:")
        lines += [
            f"  • {p.get('url')} — UR {p.get('page_rating') if p.get('page_rating') is not None else '—'}"
            f" · {(p.get('referring_domains') or 0):,} RD"
            for p in pages[:5]
        ]
    lines.append("Full detail (anchors, referring-domain list, link list) is on the Backlinks page.")
    return "\n".join(lines)


def format_authority_rows(rows: list, kind: str, limit: int = 8) -> str:
    """Compact Slack rendering of authority-report rows. Pure (unit-tested)."""
    out = []
    for r in rows[:limit]:
        who = (f"#{r.get('position') or 'n/r'} {r.get('domain') or r.get('url') or '?'}"
               if kind == "organic" else f"{r.get('name') or r.get('domain') or '?'}")
        dr = r.get("dr")
        ur = r.get("ur")
        rd = r.get("rd")
        out.append(
            f"  • {who} — DR {dr if dr is not None else '—'}"
            f" · UR {ur if ur is not None else '—'}"
            f" · RD {f'{rd:,}' if rd is not None else '—'}"
            + (" ← *you*" if r.get("is_client") else "")
        )
    return "\n".join(out)


async def _stage_authority_report(client_id: str, args: dict) -> "tuple[str, dict | str]":
    scope = (args.get("scope") or "").strip().lower()
    if scope == "maps":
        staged = {"scope": "maps"}
        staged["_confirm"] = (
            "run an RD/DR/UR authority report for the *local-pack leaderboard* "
            "vs this client (2 paid DataForSEO calls)"
        )
        return "confirm", staged
    # organic — resolve the keyword the same way the rank-tracker actions do.
    query = (args.get("keyword") or "").strip()
    if not query:
        return "reply", "Which tracked keyword should the authority report cover? (Or say 'local pack' for the Maps version.)"
    rows = (
        get_supabase().table("tracked_keywords").select("id, keyword")
        .eq("client_id", client_id).execute()
    ).data or []
    matches = match_named(rows, query, key="keyword")
    if not matches:
        listing = "; ".join(r["keyword"] for r in rows[:10]) or "none"
        return "reply", f"“{query}” isn't a tracked keyword. Tracked: {listing}."
    if len(matches) > 1:
        listing = "\n".join(f"• {r['keyword']}" for r in matches[:8])
        return "reply", f"“{query}” matches {len(matches)} tracked keywords — which one?\n{listing}"
    staged = {"scope": "organic", "keyword_id": matches[0]["id"], "keyword": matches[0]["keyword"]}
    staged["_confirm"] = (
        f"run an RD/DR/UR authority report for *“{matches[0]['keyword']}”* — everyone in its "
        "latest SERP snapshot vs this client (2 paid DataForSEO calls)"
    )
    return "confirm", staged


async def _act_authority_report(client_id: str, args: Optional[dict] = None) -> str:
    from services import authority_report
    from services.backlink_explorer import BudgetExceeded

    args = args or {}
    try:
        if args.get("scope") == "maps":
            result = await authority_report.build_maps_authority(client_id)
            if result.get("needs_scan"):
                return "No completed geo-grid scan yet — run a Maps scan first, then rerun this report."
            header = "*Authority report — local pack vs you* (DR · UR home · referring domains)"
        else:
            keyword_id = args.get("keyword_id")
            if not keyword_id:
                return "I lost track of the keyword — ask again naming it."
            result = await authority_report.build_organic_authority(client_id, keyword_id)
            if result.get("needs_snapshot"):
                return (f"No SERP snapshot exists for *“{args.get('keyword')}”* yet — capture one from the "
                        "Rankings page (camera button), then rerun the report.")
            header = f"*Authority report — “{result.get('keyword')}”* (DR · UR of ranking page · referring domains)"
    except BudgetExceeded:
        return "The daily backlink API budget is used up — try again tomorrow."
    rows = result.get("rows") or []
    if not rows:
        return "The report came back empty — nothing to compare."
    kind = "maps" if args.get("scope") == "maps" else "organic"
    return header + "\n" + format_authority_rows(rows, kind)


# SOP task-catalog labels the LLM matches a new task against so its standard
# delivery turnaround can default the Asana due date (services/task_catalog.py).
_SOP_TASK_ENUM = task_catalog.catalog_labels()


# (tool name) → {label, paid, run} + optional:
#   note   — the parenthetical in the reply-*yes* confirm (default: API-budget
#            wording). `paid` really means "confirm-gated": paid API spend OR
#            side effects on an external system (Asana writes).
#   params — JSON-schema properties/required for the tool (Claude fills them
#            from the conversation; args flow stage → confirm → run).
#   stage  — async (client_id, args) -> ("confirm", staged_args) to proceed
#            (staged_args["_confirm"] overrides the confirm verb-phrase) or
#            ("reply", text) to answer immediately (guards / disambiguation).
_ACTIONS: dict[str, dict] = {
    "rebuild_action_plan": {"label": "rebuild the Action Plan", "paid": False, "run": _act_rebuild_plan},
    "run_maps_scan": {"label": "run a Maps geo-grid scan", "paid": True, "run": _act_maps_scan},
    "run_gsc_research": {"label": "run a GSC Research analysis", "paid": True, "run": _act_gsc_research},
    "run_ai_visibility_scan": {"label": "run an AI Visibility scan", "paid": True, "run": _act_ai_scan},
    "run_backlink_lookup": {
        "label": "run a backlink lookup",
        "paid": True,
        "note": "up to 3 paid DataForSEO calls — free if checked in the last 24h",
        "run": _act_backlink_lookup,
        "stage": _stage_backlink_lookup,
        "params": {
            "properties": {
                "domain": {"type": "string", "description": "The domain, subdomain, or URL to analyze — the client's own, a competitor's, or any site named in the conversation."},
            },
            "required": ["domain"],
        },
    },
    "run_authority_report": {
        "label": "run an RD/DR/UR authority report",
        "paid": True,
        "note": "2 paid DataForSEO calls",
        "run": _act_authority_report,
        "stage": _stage_authority_report,
        "params": {
            "properties": {
                "scope": {"type": "string", "enum": ["organic", "maps"],
                          "description": "organic = everyone in a tracked keyword's latest SERP snapshot vs the client; maps = the local-pack leaderboard from the latest geo-grid scan vs the client."},
                "keyword": {"type": "string", "description": "For organic scope: the tracked keyword (or a distinctive part of it)."},
            },
            "required": ["scope"],
        },
    },
    # SerMaStr strategist mode: "strategy review for <client>". Paid gating =
    # the reply-*yes* confirm (an LLM run + up to one paid nlp audit call).
    "run_strategy_review": {"label": "run a strategist review", "paid": True, "run": _act_strategy_review},
    # Not paid-API spend, but it creates real tasks on the client's board — same
    # reply-*yes* confirm gate (the `note` swaps the budget wording).
    "push_task_plan": {
        "label": "push the latest monthly task plan to Asana",
        "paid": True,
        "note": "creates real tasks on the client's Asana board",
        "run": _act_push_task_plan,
    },
    # Conversational task management — parameterized (Claude extracts the task
    # name / assignee from the message), staged so the confirm names the exact
    # resolved task before anything is written or deleted.
    "add_asana_task": {
        "label": "create an Asana task",
        "paid": True,
        "note": "creates a real task on the client's Asana board",
        "run": _act_add_task,
        "stage": _stage_add_task,
        "params": {
            "properties": {
                "task_name": {"type": "string", "description": "The task's name, verbatim from the teammate."},
                "assignee": {"type": "string", "description": "Person to assign it to (first or full name), if the teammate named one."},
                "notes": {"type": "string", "description": "Detail for the task description — from the message OR from earlier in the conversation (e.g. the research finding, review insight, or data point the task is based on, so the assignee has the context)."},
                "due_date": {"type": "string", "description": "Due date as YYYY-MM-DD, ONLY if the teammate gave an explicit deadline (e.g. \"by Friday\", \"end of month\", \"by Q4\" → the resolved calendar date). An explicit date overrides the SOP default. Omit when they didn't state one."},
                "sop_task": {
                    "type": "string",
                    "enum": _SOP_TASK_ENUM,
                    "description": "When no explicit due_date is given, pick the SOP task-catalog entry that best matches this task so its standard delivery turnaround sets the due date (e.g. a niche-edit order → \"Niche edit\"; a citations batch → \"Citations (per 40-batch)\"; a GBP Blast → \"GBP Blast\"). Omit if none genuinely matches — don't force-fit; the teammate will be asked to confirm a date.",
                },
                "no_due_date": {"type": "boolean", "description": "True ONLY when the teammate explicitly says to leave the due date blank / let the team fill it in. Skips both the explicit date and the SOP default."},
            },
            "required": ["task_name"],
        },
    },
    "remove_asana_task": {
        "label": "delete an Asana task",
        "paid": True,
        "note": "permanently deletes a task from the client's Asana board",
        "run": _act_remove_task,
        "stage": _stage_remove_task,
        "params": {
            "properties": {
                "task_name": {"type": "string", "description": "Name (or distinctive part of the name) of the task to delete."},
            },
            "required": ["task_name"],
        },
    },
    "complete_asana_task": {
        "label": "mark an Asana task complete",
        "paid": True,
        "note": "marks a task complete on the client's Asana board",
        "run": _act_complete_task,
        "stage": _stage_complete_task,
        "params": {
            "properties": {
                "task_name": {"type": "string", "description": "Name (or distinctive part of the name) of the task to mark complete."},
            },
            "required": ["task_name"],
        },
    },
    # ── Admin actions: client profile / setup ──────────────────────────────
    "update_client_profile": {
        "label": "edit the client's profile",
        "paid": True,
        "note": "changes the client's Setup-page configuration",
        "run": _act_update_profile,
        "stage": _stage_update_profile,
        "params": {
            "properties": {
                "field": {
                    "type": "string",
                    "enum": list(_PROFILE_FIELDS),
                    "description": "Which profile field to change.",
                },
                "value": {
                    "type": "string",
                    "description": "The new value, verbatim from the teammate (retainer as a dollar amount; client_type local|enterprise; is_sab yes|no).",
                },
            },
            "required": ["field", "value"],
        },
    },
    "add_target_cities": {
        "label": "add target cities",
        "paid": True,
        "note": "adds cities to the client's Local SEO target-city list",
        "run": _act_add_cities,
        "stage": _stage_add_cities,
        "params": {
            "properties": {
                "cities": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "City names to add to the target list, verbatim from the teammate.",
                },
            },
            "required": ["cities"],
        },
    },
    "remove_target_cities": {
        "label": "remove target cities",
        "paid": True,
        "note": "removes cities from the client's Local SEO target-city list",
        "run": _act_remove_cities,
        "stage": _stage_remove_cities,
        "params": {
            "properties": {
                "cities": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "City names to remove from the target list.",
                },
            },
            "required": ["cities"],
        },
    },
    # ── Admin actions: organic rank tracker keywords ───────────────────────
    "add_tracked_keywords": {
        "label": "add tracked keywords",
        "paid": True,
        "note": "starts rank-tracking new keywords (backfills rank + market data via DataForSEO)",
        "run": _act_add_tracked_keywords,
        "stage": _stage_add_tracked_keywords,
        "params": {
            "properties": {
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Keywords to start rank-tracking, verbatim from the teammate.",
                },
            },
            "required": ["keywords"],
        },
    },
    "remove_tracked_keyword": {
        "label": "remove a tracked keyword",
        "paid": True,
        "note": "stops tracking a keyword and deletes its rank history",
        "run": _act_remove_tracked_keyword,
        "stage": _stage_remove_tracked_keyword,
        "params": {
            "properties": {
                "keyword": {"type": "string", "description": "The keyword (or a distinctive part of it) to stop tracking."},
            },
            "required": ["keyword"],
        },
    },
    # A right-now Google SERP read for one keyword — the on-demand freshness
    # escape hatch when the weekly tracked rank isn't recent enough.
    "check_live_serp": {
        "label": "run a live Google SERP check",
        "paid": True,
        "note": "one live DataForSEO SERP pull",
        "run": _act_live_serp,
        "stage": _stage_live_serp,
        "params": {
            "properties": {
                "keyword": {"type": "string", "description": "The exact search keyword to check the live Google results for."},
            },
            "required": ["keyword"],
        },
    },
    # ── Admin actions: AI Visibility keywords + competitors ────────────────
    "add_ai_keywords": {
        "label": "add AI Visibility keywords",
        "paid": True,
        "note": "adds keywords to AI Visibility tracking (scanned on the next run)",
        "run": _act_add_ai_keywords,
        "stage": _stage_add_ai_keywords,
        "params": {
            "properties": {
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Keywords to add to AI Visibility tracking.",
                },
            },
            "required": ["keywords"],
        },
    },
    "remove_ai_keyword": {
        "label": "remove an AI Visibility keyword",
        "paid": True,
        "note": "removes a keyword from AI Visibility tracking",
        "run": _act_remove_ai_keyword,
        "stage": _stage_remove_ai_keyword,
        "params": {
            "properties": {
                "keyword": {"type": "string", "description": "The AI-visibility keyword (or a distinctive part of it) to remove."},
            },
            "required": ["keyword"],
        },
    },
    "add_ai_competitor": {
        "label": "add an AI Visibility competitor",
        "paid": True,
        "note": "adds a competitor to AI Visibility tracking",
        "run": _act_add_ai_competitor,
        "stage": _stage_add_ai_competitor,
        "params": {
            "properties": {
                "name": {"type": "string", "description": "The competitor's business name."},
                "website": {"type": "string", "description": "The competitor's website, if the teammate gave one."},
            },
            "required": ["name"],
        },
    },
    "remove_ai_competitor": {
        "label": "remove an AI Visibility competitor",
        "paid": True,
        "note": "removes a competitor from AI Visibility tracking",
        "run": _act_remove_ai_competitor,
        "stage": _stage_remove_ai_competitor,
        "params": {
            "properties": {
                "name": {"type": "string", "description": "The competitor's name (or a distinctive part of it) to remove."},
            },
            "required": ["name"],
        },
    },
    # ── Admin actions: campaign goals ──────────────────────────────────────
    "add_campaign_goal": {
        "label": "add a campaign goal",
        "paid": True,
        "note": "creates a success target the strategist judges progress against",
        "run": _act_add_goal,
        "stage": _stage_add_goal,
        "params": {
            "properties": {
                "goal_type": {
                    "type": "string",
                    "enum": ["keyword_position", "keywords_in_top", "organic_clicks", "organic_impressions", "ai_visibility", "maps_pack_presence", "custom"],
                    "description": "The goal's metric. keyword_position = one keyword to position N (needs keyword); keywords_in_top = N keywords inside top X (needs target_position); organic_clicks/impressions = 30-day GSC sums; ai_visibility = visibility %; maps_pack_presence = top-3 pin share %; custom = manual.",
                },
                "label": {"type": "string", "description": "Short human label, e.g. \"'roof repair' to top 3\"."},
                "target_value": {"type": "number", "description": "The numeric target (position for keyword_position — lower is better; count/percentage otherwise)."},
                "keyword": {"type": "string", "description": "The keyword, for keyword_position goals."},
                "target_position": {"type": "integer", "description": "The top-X band, for keywords_in_top goals (top 3 → 3)."},
                "due_date": {"type": "string", "description": "Due date YYYY-MM-DD, if the teammate gave one (e.g. \"by Q4\" → 2026-12-31)."},
                "notes": {"type": "string", "description": "Any extra context the teammate gave."},
            },
            "required": ["goal_type", "label"],
        },
    },
    "remove_campaign_goal": {
        "label": "remove a campaign goal",
        "paid": True,
        "note": "permanently deletes a campaign goal",
        "run": _act_remove_goal,
        "stage": _stage_remove_goal,
        "params": {
            "properties": {
                "label": {"type": "string", "description": "The goal's label (or a distinctive part of it)."},
            },
            "required": ["label"],
        },
    },
    # ── Admin actions: client reports ──────────────────────────────────────
    "generate_client_report": {
        "label": "generate a client report",
        "paid": True,
        "note": "renders a client PDF report (uses API budget)",
        "run": _act_generate_report,
        "stage": _stage_generate_report,
        "params": {
            "properties": {
                "report_type": {
                    "type": "string",
                    "enum": ["monthly", "weekly", "ai_visibility"],
                    "description": "Which report to generate (default monthly).",
                },
                "deliver": {
                    "type": "boolean",
                    "description": "True ONLY when the teammate explicitly asks to send/deliver it to the client — delivery emails the client's recipients + saves to their Drive.",
                },
            },
            "required": [],
        },
    },
}
_ACTION_TOOLS = [
    {"name": name, "description": meta["label"].capitalize() + " for the client.",
     "input_schema": {"type": "object", **(meta.get("params") or {"properties": {}})}}
    for name, meta in _ACTIONS.items()
]

# Pending paid actions awaiting a "yes", keyed by (channel, thread_ts). In-memory
# / single-process (PLATFORM is one replica) + best-effort: a redeploy drops
# pending confirmations, which just means the user re-asks. Never executes a paid
# action without an explicit confirm.
_pending: dict[tuple, dict] = {}
