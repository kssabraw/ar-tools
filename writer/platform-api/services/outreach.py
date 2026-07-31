"""Outreach pipeline — the suite's read/write surface over the Outreacher project.

The outreach pipeline is an AR Tools MODULE (outreach/HANDOFF.md §2): the database stays in its
own Supabase project, the API lives here. This module is the whole of that API's logic; the
router is thin.

Two halves, with different characters:

**The pipeline half is read-only.** Markets, the filter funnel, prospects. Nothing here writes to
the pipeline tables and nothing here can spend money — ingestion is the Railway job's business and
stays there. Aggregation happens in Postgres (`outreach_market_summary`, `v_prospect_status`), per
storage-retention-spec §9 and because the alternative is pulling 8,000+ `filter_result` rows over
the wire to count them.

**The CRM half is read/write.** Leads, their activity timeline, suppression.

Every list read is explicitly bounded. PostgREST silently caps an unbounded `select()` at 1,000
rows — no error, no header, nothing a caller notices — which is how the Phase 1 filter run
reported 1,000 of 1,388 prospects and left 215 unfiltered (outreach ISSUES I-036). Here the
defence is a hard page ceiling plus an exact `count`, so a caller can always tell whether it has
seen everything. Never add an unbounded read to this file.
"""
from __future__ import annotations

import logging
from typing import Any

from services.outreach_db import get_outreach_client

logger = logging.getLogger(__name__)

# --- Vocabularies -----------------------------------------------------------------------------
#
# These mirror CHECK constraints in the Outreacher database, which remains authoritative. They are
# duplicated here only so a bad value returns a named 422 naming the legal values, instead of a
# raw Postgres constraint string surfacing as a 500. If the two ever disagree the database wins
# and the request simply fails later — this is a friendlier front door, not a second gate.

LEAD_SOURCES: tuple[str, ...] = (
    "outbound_scan",
    "inbound_form",
    "inbound_call",
    "referral",
    "manual",
    "partner",
)

# `qualified` and `proposal` are deliberately absent — crm-layer-spec §8a collapsed both into
# `in_conversation` so lead history stays comparable across a vocabulary change. Read the live
# `lead_stage` table for labels and ordering; this tuple is only the write-side allowlist.
LEAD_STAGES: tuple[str, ...] = (
    "new",
    "contacted",
    "replied",
    "in_conversation",
    "won",
    "lost",
    "nurture",
)

LOST_REASONS: tuple[str, ...] = (
    "no_response",
    "not_interested",
    "no_budget",
    "has_agency",
    "timing",
    "went_elsewhere",
    "disqualified",
    "unreachable",
    "opted_out",
)

# `email_sent` and `call` are NOT activity kinds. A send or a dial writes a `touch` row (Phase 3);
# what was said writes a `call_note` referencing it. crm-layer-spec §3 removed them precisely so
# the two never duplicate, `touch` staying authoritative for "a contact attempt happened".
ACTIVITY_KINDS: tuple[str, ...] = (
    "note",
    "call_note",
    "email_reply",
    "meeting",
    "proposal",
    "stage_change",
    "asset_viewed",
    "system",
)

# Written by the `lead_log_changes` trigger, not by a caller. Accepting them over the API would
# let a human fabricate stage history that never happened.
TRIGGER_OWNED_KINDS: frozenset[str] = frozenset({"stage_change", "system"})

SUPPRESSION_SCOPES: tuple[str, ...] = ("email", "phone", "place_id", "domain", "all")

PROSPECT_STATUSES: tuple[str, ...] = ("all", "survived", "excluded", "flagged", "unevaluated")

# Columns a caller may PATCH onto a lead. Deliberately excludes `source` (reclassifying a lead
# that already has an `outcome` is blocked at the database anyway — see PHASE3-outcome-constraint),
# `prospect_id` (the join the whole scoring model rests on), the suppression columns (trigger-owned)
# and every timestamp.
LEAD_MUTABLE_FIELDS: frozenset[str] = frozenset(
    {
        "stage",
        "owner_id",
        "company_name",
        "contact_name",
        "email",
        "phone",
        "website",
        "city",
        "state",
        "postal_code",
        "country",
        "category",
        "notes_intake",
        "lost_reason",
        "lost_to",
        "next_action",
        "next_action_due",
    }
)

MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50

# Never `select("*")` on `prospect`: the row carries the untouched provider payload in `raw`,
# which is ~2 KB each and is not what a list view wants (storage spec §9 — no SELECT * on
# jsonb-bearing tables). The status view omits it entirely; this is the list projection over it.
_PROSPECT_COLUMNS = (
    "id,market_id,submarket_id,submarket_name,place_id,name,category,address,phone,website,"
    "rating,review_count,lat,lng,business_status,franchise_status,ingested_at,"
    "evaluated,excluded,rules_failed"
)

# Same rule for `lead`, which carries `intake_payload` — an entire inbound form or webhook body.
# A board of 50 leads has no use for 50 of those, and the detail read (`get_lead`) is where the
# payload is actually wanted, so only that one asks for the whole row.
_LEAD_LIST_COLUMNS = (
    "id,source,stage,owner_id,prospect_id,company_name,contact_name,email,phone,website,"
    "city,state,postal_code,country,category,intake_channel,notes_intake,"
    "suppressed_at,suppression_reason,lost_reason,lost_to,next_action,next_action_due,"
    "stage_changed_at,created_by,updated_by,created_at,updated_at"
)

# `metadata` is included: on an activity row it is the content (the assignment's from/to, the
# suppression's reason), not an opaque payload, and it defaults to '{}'.
_ACTIVITY_COLUMNS = (
    "id,lead_id,occurred_at,actor_id,kind,touch_id,body,metadata,from_stage,to_stage,created_at"
)


class OutreachError(Exception):
    """A validation failure with a stable machine-readable code.

    Carries the code the router turns into an HTTP detail, so the vocabulary of errors is defined
    beside the validation that produces it rather than in the route handlers.
    """

    def __init__(self, code: str, message: str | None = None):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


# --- Pure helpers -----------------------------------------------------------------------------


def clamp_page(limit: int | None, offset: int | None) -> tuple[int, int]:
    """Bound a page request into (limit, offset).

    A ceiling rather than an error: a caller asking for 10,000 rows wants everything, and refusing
    it teaches them to loop with a smaller limit, which is the same read with more round trips.
    Giving them MAX_PAGE_SIZE plus the exact total (every list read returns one) lets them page
    correctly.
    """
    size = DEFAULT_PAGE_SIZE if not limit or limit < 1 else min(int(limit), MAX_PAGE_SIZE)
    start = max(int(offset or 0), 0)
    return size, start


def validate_lead_write(payload: dict[str, Any], *, creating: bool) -> dict[str, Any]:
    """Validate and narrow a lead create/update body. Pure — no database access.

    Enforces, before the round trip, the three couplings the database also enforces, so each one
    comes back as a named code rather than a constraint-violation string:

      lost_requires_reason      stage 'lost' without a reason. crm-layer-spec §5 calls the lost
                                reason the highest-value field in the layer and notes it is
                                unrecoverable after the moment of loss — a lost lead without one
                                is a lost label, and labels are the point.
      outbound_requires_prospect an `outbound_scan` lead with no prospect. Grid results join on
                                that id; without it the lead can never be scored or audited.
      non_prospect_needs_identity a lead with neither a prospect nor a company name is unnameable.
    """
    unknown = set(payload) - LEAD_MUTABLE_FIELDS - ({"source", "prospect_id"} if creating else set())
    if unknown:
        raise OutreachError(
            "unknown_field", f"not writable: {', '.join(sorted(unknown))}"
        )

    # Taken as given, including explicit nulls: the router sends only fields the caller actually
    # set, so `None` here means "clear this" (unassign an owner, drop a due date) rather than
    # "omitted". Dropping nulls would make clearing a field impossible over the API.
    fields = dict(payload)

    if creating:
        source = fields.get("source")
        if source not in LEAD_SOURCES:
            raise OutreachError("invalid_source", f"source must be one of {', '.join(LEAD_SOURCES)}")
        if source == "outbound_scan" and not fields.get("prospect_id"):
            raise OutreachError(
                "outbound_requires_prospect",
                "an outbound_scan lead must reference the prospect it came from",
            )
        if not fields.get("prospect_id") and not fields.get("company_name"):
            raise OutreachError(
                "non_prospect_needs_identity",
                "a lead needs either a prospect_id or a company_name",
            )

    stage = fields.get("stage")
    if stage is not None and stage not in LEAD_STAGES:
        raise OutreachError("invalid_stage", f"stage must be one of {', '.join(LEAD_STAGES)}")

    reason = fields.get("lost_reason")
    if reason is not None and reason not in LOST_REASONS:
        raise OutreachError(
            "invalid_lost_reason", f"lost_reason must be one of {', '.join(LOST_REASONS)}"
        )

    # Only checkable here when the transition is to 'lost' in this same call. Moving to 'lost'
    # without touching lost_reason on a lead that already has one is legal and the database
    # confirms it; moving without one is caught by `lost_requires_reason` there.
    if stage == "lost" and "lost_reason" in fields and not reason:
        raise OutreachError(
            "lost_requires_reason", "a lead cannot be marked lost without a lost_reason"
        )

    return fields


def validate_activity(kind: str, body: str | None, touch_id: int | None) -> None:
    """Validate a lead_activity write.

    `stage_change` and `system` are rejected outright: those rows come from the `lead_log_changes`
    trigger, which sees the actual before/after values. Accepting them over the API would let a
    human write stage history that never happened, into an append-only table that has no way to
    take it back.
    """
    if kind not in ACTIVITY_KINDS:
        raise OutreachError("invalid_kind", f"kind must be one of {', '.join(ACTIVITY_KINDS)}")
    if kind in TRIGGER_OWNED_KINDS:
        raise OutreachError(
            "trigger_owned_kind",
            f"'{kind}' rows are written by the database when a lead actually changes",
        )
    if not (body or "").strip():
        raise OutreachError("empty_body", "an activity row needs a body")
    # crm-layer-spec §3: `touch_id` links commentary to the send it concerns, and only a call note
    # concerns one. Mirrors the DB's lead_activity_touch_on_call_note_only check.
    if touch_id is not None and kind != "call_note":
        raise OutreachError("touch_requires_call_note", "touch_id is only valid on a call_note")


def apply_prospect_status(query: Any, status: str) -> Any:
    """Narrow a `v_prospect_status` query to one funnel bucket.

    'survived' means evaluated AND not excluded — not merely "not excluded". An unfiltered
    prospect is not a survivor, and conflating the two is how a run that filtered 1,000 of 1,388
    rows reports 388 extra survivors it never looked at (ISSUES I-036).
    """
    if status not in PROSPECT_STATUSES:
        raise OutreachError(
            "invalid_status", f"status must be one of {', '.join(PROSPECT_STATUSES)}"
        )
    if status == "survived":
        return query.eq("evaluated", True).eq("excluded", False)
    if status == "excluded":
        return query.eq("excluded", True)
    if status == "flagged":
        return query.eq("franchise_status", "flagged")
    if status == "unevaluated":
        return query.eq("evaluated", False)
    return query


# --- Reads ------------------------------------------------------------------------------------


def list_markets() -> list[dict[str, Any]]:
    """Every market, with its submarket and keyword counts.

    Unbounded by intent and safe by scale: a market is a city × vertical and the recorded
    portfolio ceiling is 50 of them (DECISIONS.md), three orders of magnitude below PostgREST's
    silent cap.
    """
    client = get_outreach_client()
    markets = (
        client.table("market")
        .select("*, submarket(count), keyword(count)")
        .order("name")
        .execute()
        .data
        or []
    )
    for market in markets:
        market["submarket_count"] = _embedded_count(market.pop("submarket", None))
        market["keyword_count"] = _embedded_count(market.pop("keyword", None))
    return markets


def _embedded_count(embedded: Any) -> int:
    """Unwrap PostgREST's `table(count)` embedding, which arrives as [{'count': n}] or []."""
    if isinstance(embedded, list) and embedded:
        return int(embedded[0].get("count") or 0)
    if isinstance(embedded, dict):
        return int(embedded.get("count") or 0)
    return 0


def market_summary(market_id: str) -> dict[str, Any]:
    """The funnel, per-rule counts and spend for one market.

    One round trip into `outreach_market_summary`, which aggregates in SQL. Note the per-rule
    numbers report `not_evaluated` separately from `passed`: `review_recency` is deferred to
    Phase 5 and writes `passed = true, observed_value = 'not_evaluated'` for every prospect
    (ISSUES I-016), so folding the two together would claim every business in the market has a
    recent review when not one was checked.
    """
    client = get_outreach_client()
    result = client.rpc("outreach_market_summary", {"p_market_id": market_id}).execute().data
    if not result or not result.get("market"):
        raise OutreachError("market_not_found", "no such market")
    return result


def list_prospects(
    *,
    market_id: str | None = None,
    submarket_id: str | None = None,
    status: str = "all",
    search: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> dict[str, Any]:
    """A page of prospects with their filter verdict, plus the exact total.

    Ordered by review count descending — the Phase 1 brief's "order by review count if an order is
    needed for inspection". There is deliberately no score to order by: Phase 1 writes none, and
    the placeholder belongs to Phase 2 because it needs grid data that does not exist yet.
    """
    size, start = clamp_page(limit, offset)
    client = get_outreach_client()

    query = client.table("v_prospect_status").select(_PROSPECT_COLUMNS, count="exact")
    if market_id:
        query = query.eq("market_id", market_id)
    if submarket_id:
        query = query.eq("submarket_id", submarket_id)
    query = apply_prospect_status(query, status)
    if search and search.strip():
        query = query.ilike("name", f"%{search.strip()}%")

    response = (
        query.order("review_count", desc=True, nullsfirst=False)
        .order("id")
        .range(start, start + size - 1)
        .execute()
    )
    return {
        "prospects": response.data or [],
        "total": response.count or 0,
        "limit": size,
        "offset": start,
    }


def get_prospect(prospect_id: str) -> dict[str, Any]:
    """One prospect with every rule that was evaluated against it.

    All rules, not just failing ones. The brief requires every rule to be evaluated and logged for
    every prospect precisely so tuning data is not first-match-only, and a detail view that showed
    only failures would hide that the guarantee is being kept.
    """
    client = get_outreach_client()
    rows = (
        client.table("v_prospect_status")
        .select(_PROSPECT_COLUMNS)
        .eq("id", prospect_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise OutreachError("prospect_not_found", "no such prospect")

    prospect = rows[0]
    prospect["filter_results"] = (
        client.table("filter_result")
        .select("rule,passed,observed_value,evaluated_at")
        .eq("prospect_id", prospect_id)
        .order("rule")
        .execute()
        .data
        or []
    )
    # The lead this prospect was promoted into, if any. One row at most in practice — the CRM's
    # unique (prospect_id, source) permits several sources, but an outbound prospect has one.
    prospect["leads"] = (
        client.table("lead")
        .select("id,source,stage,owner_id,next_action,next_action_due")
        .eq("prospect_id", prospect_id)
        .is_("deleted_at", "null")
        .execute()
        .data
        or []
    )
    return prospect


def list_submarkets(market_id: str) -> list[dict[str, Any]]:
    """Submarkets for a market.

    Geometry columns are included deliberately: `grid_radius_miles` / `grid_spacing_miles` are
    immutable from the first scan onward (CLAUDE.md), so a UI that shows them is showing something
    permanent, and `last_scanned_at` is what says whether that has happened yet.
    """
    return (
        get_outreach_client()
        .table("submarket")
        .select("*")
        .eq("market_id", market_id)
        .order("name")
        .execute()
        .data
        or []
    )


# --- CRM --------------------------------------------------------------------------------------


def list_lead_stages() -> list[dict[str, Any]]:
    """The stage lookup, in board order.

    A table rather than an enum on purpose: the board needs `sort_order` and `is_terminal`, and
    neither survives in a Postgres enum.
    """
    return (
        get_outreach_client()
        .table("lead_stage")
        .select("*")
        .eq("active", True)
        .order("sort_order")
        .execute()
        .data
        or []
    )


def list_leads(
    *,
    stage: str | None = None,
    source: str | None = None,
    owner_id: str | None = None,
    overdue: bool = False,
    search: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> dict[str, Any]:
    """A page of live leads, newest first, with the exact total.

    `overdue` implements crm-layer-spec §10's forcing function — a due date in the past on a lead
    that is neither won nor lost. That view is what makes manual reply capture work at all; a
    pipeline nobody is prompted to touch silently stops being updated.
    """
    size, start = clamp_page(limit, offset)
    query = (
        get_outreach_client()
        .table("lead")
        .select(_LEAD_LIST_COLUMNS, count="exact")
        .is_("deleted_at", "null")
    )

    if stage:
        query = query.eq("stage", stage)
    if source:
        query = query.eq("source", source)
    if owner_id:
        query = query.eq("owner_id", owner_id)
    if overdue:
        from datetime import date

        query = query.lt("next_action_due", date.today().isoformat()).not_.in_(
            "stage", ["won", "lost"]
        )
    if search and search.strip():
        term = search.strip()
        query = query.or_(
            f"company_name.ilike.%{term}%,contact_name.ilike.%{term}%,email.ilike.%{term}%"
        )

    response = query.order("created_at", desc=True).range(start, start + size - 1).execute()
    return {
        "leads": response.data or [],
        "total": response.count or 0,
        "limit": size,
        "offset": start,
    }


def get_lead(lead_id: str) -> dict[str, Any]:
    """One lead with its full activity timeline.

    The timeline is bounded like everything else here. A lead with more than MAX_PAGE_SIZE
    activity rows is not a lead anyone is still working, but an unbounded read would truncate at
    1,000 without saying so, and a timeline missing its oldest entries with no indication is worse
    than one that says how many it is showing.
    """
    client = get_outreach_client()
    rows = client.table("lead").select("*").eq("id", lead_id).limit(1).execute().data or []
    if not rows:
        raise OutreachError("lead_not_found", "no such lead")

    lead = rows[0]
    activity = (
        client.table("lead_activity")
        .select(_ACTIVITY_COLUMNS, count="exact")
        .eq("lead_id", lead_id)
        .order("occurred_at", desc=True)
        .range(0, MAX_PAGE_SIZE - 1)
        .execute()
    )
    lead["activity"] = activity.data or []
    lead["activity_total"] = activity.count or 0

    if lead.get("prospect_id"):
        prospect = (
            client.table("v_prospect_status")
            .select(_PROSPECT_COLUMNS)
            .eq("id", lead["prospect_id"])
            .limit(1)
            .execute()
            .data
            or []
        )
        lead["prospect"] = prospect[0] if prospect else None
    else:
        lead["prospect"] = None
    return lead


def create_lead(payload: dict[str, Any], actor_id: str) -> dict[str, Any]:
    """Create a lead.

    Suppression is not checked here — the `lead_suppression_check` trigger stamps `suppressed_at`
    and `suppression_reason` on insert and logs it. Doing it in the application as well would give
    two answers to one question, and the database's is the one that cannot be bypassed.
    """
    fields = validate_lead_write(payload, creating=True)
    fields["created_by"] = actor_id
    fields["updated_by"] = actor_id

    rows = get_outreach_client().table("lead").insert(fields).execute().data or []
    if not rows:
        raise OutreachError("lead_not_created", "the lead was not written")
    return rows[0]


def update_lead(lead_id: str, payload: dict[str, Any], actor_id: str) -> dict[str, Any]:
    """Patch a lead.

    `updated_by` is set on every update, not just stage changes: the `lead_log_changes` trigger
    reads it to attribute the activity rows it writes, and under the module ruling `auth.uid()` is
    always NULL here because platform-api connects with the service role (see migration
    20260801110000 and ISSUES I-040). An update that forgot it would log anonymously.

    The stage-change and reassignment activity rows come from that trigger, so this function
    deliberately does not write them — two writers would mean two rows for one event, in an
    append-only table.
    """
    fields = validate_lead_write(payload, creating=False)
    if not fields:
        raise OutreachError("empty_update", "nothing to update")
    fields["updated_by"] = actor_id

    rows = (
        get_outreach_client()
        .table("lead")
        .update(fields)
        .eq("id", lead_id)
        .is_("deleted_at", "null")
        .execute()
        .data
        or []
    )
    if not rows:
        raise OutreachError("lead_not_found", "no such lead")
    return rows[0]


def add_activity(
    lead_id: str,
    *,
    kind: str,
    body: str | None,
    actor_id: str,
    touch_id: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append a note to a lead's timeline.

    Append-only, by specification: corrections are new rows, never edits, which is why there is no
    update or delete counterpart in this module.
    """
    validate_activity(kind, body, touch_id)

    client = get_outreach_client()
    exists = client.table("lead").select("id").eq("id", lead_id).limit(1).execute().data or []
    if not exists:
        raise OutreachError("lead_not_found", "no such lead")

    row: dict[str, Any] = {
        "lead_id": lead_id,
        "kind": kind,
        "body": (body or "").strip(),
        "actor_id": actor_id,
        "metadata": metadata or {},
    }
    if touch_id is not None:
        row["touch_id"] = touch_id

    written = client.table("lead_activity").insert(row).execute().data or []
    if not written:
        raise OutreachError("activity_not_created", "the activity row was not written")
    return written[0]


def list_suppressions(limit: int | None = None, offset: int | None = None) -> dict[str, Any]:
    size, start = clamp_page(limit, offset)
    response = (
        get_outreach_client()
        .table("suppression")
        .select("*", count="exact")
        .order("created_at", desc=True)
        .range(start, start + size - 1)
        .execute()
    )
    return {
        "suppressions": response.data or [],
        "total": response.count or 0,
        "limit": size,
        "offset": start,
    }


def add_suppression(
    *, scope: str, value: str, reason: str | None, actor_id: str
) -> dict[str, Any]:
    """Record a do-not-contact.

    There is no delete counterpart and there must not be one. crm-layer-spec §4: a suppression
    must not be deleted, ever. Someone who asked not to be contacted and was contacted anyway
    because a row was tidied away is the one failure in this system that cannot be apologised
    into non-existence.
    """
    if scope not in SUPPRESSION_SCOPES:
        raise OutreachError(
            "invalid_scope", f"scope must be one of {', '.join(SUPPRESSION_SCOPES)}"
        )
    if not (value or "").strip():
        raise OutreachError("empty_value", "a suppression needs a value")

    client = get_outreach_client()
    value = value.strip()

    # Read-then-insert rather than an upsert. The table's uniqueness lives in an EXPRESSION index
    # — `(scope, lower(value))` — and PostgREST's `on_conflict` can only name plain columns, so an
    # upsert here fails outright with "no unique or exclusion constraint matching". Suppressing an
    # address that is already suppressed must be a no-op that reports success, not an error the
    # caller has to interpret.
    existing = (
        client.table("suppression")
        .select("*")
        .eq("scope", scope)
        .ilike("value", value)
        .limit(1)
        .execute()
        .data
        or []
    )
    if existing:
        return existing[0]

    row = {"scope": scope, "value": value, "reason": reason, "created_by": actor_id}
    try:
        written = client.table("suppression").insert(row).execute().data or []
    except Exception:
        # Lost a race against a concurrent insert of the same value. The row exists, which is the
        # outcome the caller wanted; re-read rather than failing.
        raced = (
            client.table("suppression")
            .select("*")
            .eq("scope", scope)
            .ilike("value", value)
            .limit(1)
            .execute()
            .data
            or []
        )
        if raced:
            return raced[0]
        raise

    if not written:
        raise OutreachError("suppression_not_created", "the suppression was not written")
    return written[0]
