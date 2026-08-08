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


# --- Scan orders (the UI trigger — outreach DECISIONS.md 2026-08-06) ---------------------------
#
# The one write surface in this module that leads to MONEY, and the reason it is safe is the
# reason it exists: this service never spends. It writes a signed order (`scan_request`) that the
# outreach Railway job's `tick` command executes on its own schedule. The order is the
# confirmation — single-use, named to one submarket x keyword, attributed via `requested_by` —
# so the spend-authorization evidence is created here and consumed there, and neither side can
# spend without the other. platform-api holding the scan client, or calling Railway's API to
# force a deploy, were both rejected (see the decision record) — splitting a spend gate across
# two services is how it stops being one.

SCAN_REQUEST_ACTIVE_STATUSES: tuple[str, ...] = ("pending", "running")


def list_keywords(market_id: str) -> list[dict[str, Any]]:
    """A market's keywords, primary first — the scan-order form's second dropdown."""
    rows = (
        get_outreach_client()
        .table("keyword")
        .select("id, term, is_primary")
        .eq("market_id", market_id)
        .order("is_primary", desc=True)
        .order("term")
        .execute()
        .data
        or []
    )
    return rows


# --- Any-city onboarding: create-or-get the rows a typed city needs, then place the order ------
#
# The "City + Business type" form (DECISIONS.md 2026-08-08) needs market/submarket/keyword rows to
# exist before an order can name them. platform-api creates them here (free — geocoded upstream by
# `outreach_geo`), then writes an `onboard_request` the outreach `tick` executes as
# discover → filter → scan. Get-or-CREATE, never update: grid geometry is immutable once scanned,
# so a repeat pick of the same city/sub-area reuses the existing rows rather than drifting a
# centre. Idempotency key is the canonical name (Google's formatted name is stable), scoped to its
# parent — market by name, submarket by (market, name), keyword by (market, term).

ONBOARD_REQUEST_ACTIVE_STATUSES: tuple[str, ...] = ("pending", "running")


def _ensure_market(client: Any, *, name: str, lat: float, lng: float) -> str:
    from config import settings

    existing = (
        client.table("market").select("id").eq("name", name).limit(1).execute().data or []
    )
    if existing:
        return str(existing[0]["id"])
    row = {
        "name": name,
        "center_lat": lat,
        "center_lng": lng,
        "radius_miles": settings.outreach_onboard_market_radius_miles,
    }
    written = client.table("market").insert(row).execute().data or []
    if not written:
        raise OutreachError("market_not_created")
    return str(written[0]["id"])


def _ensure_submarket(client: Any, *, market_id: str, name: str, lat: float, lng: float) -> str:
    from config import settings

    existing = (
        client.table("submarket")
        .select("id")
        .eq("market_id", market_id)
        .eq("name", name)
        .limit(1)
        .execute()
        .data
        or []
    )
    if existing:
        return str(existing[0]["id"])
    row = {
        "market_id": market_id,
        "name": name,
        "center_lat": lat,
        "center_lng": lng,
        "grid_radius_miles": settings.outreach_onboard_grid_radius_miles,
        "grid_spacing_miles": settings.outreach_onboard_grid_spacing_miles,
    }
    written = client.table("submarket").insert(row).execute().data or []
    if not written:
        raise OutreachError("submarket_not_created")
    return str(written[0]["id"])


def _ensure_keyword(client: Any, *, market_id: str, term: str) -> str:
    existing = (
        client.table("keyword")
        .select("id")
        .eq("market_id", market_id)
        .eq("term", term)
        .limit(1)
        .execute()
        .data
        or []
    )
    if existing:
        return str(existing[0]["id"])
    # First keyword in a fresh market is its primary; the unique (market_id, term) index is
    # authoritative, so a racing insert is caught and re-read rather than duplicated.
    has_any = (
        client.table("keyword").select("id").eq("market_id", market_id).limit(1).execute().data
        or []
    )
    row = {"market_id": market_id, "term": term, "is_primary": not has_any}
    try:
        written = client.table("keyword").insert(row).execute().data or []
    except Exception as exc:  # noqa: BLE001
        if "keyword" in str(exc) and "term" in str(exc):
            again = (
                client.table("keyword")
                .select("id")
                .eq("market_id", market_id)
                .eq("term", term)
                .limit(1)
                .execute()
                .data
                or []
            )
            if again:
                return str(again[0]["id"])
        raise
    if not written:
        raise OutreachError("keyword_not_created")
    return str(written[0]["id"])


def create_onboard_from_place(
    *,
    city: dict[str, Any],
    subarea: dict[str, Any] | None,
    business_type: str,
    note: str | None,
    actor_id: str,
) -> dict[str, Any]:
    """The "City → sub-area (optional) → search" order: create-or-get the market/sub-area/keyword
    rows for a typed city, then place a signed `onboard_request` (discover → filter → scan).
    Admin-gated at the router — this order authorizes BOTH a paid discovery pull and a scan.

    `city` = {name, lat, lng} (resolved by `outreach_geo`); `subarea` = {name, lat, lng} (a verified
    sub-area the operator picked) or None to scan the WHOLE CITY (the submarket becomes the city
    centre grid); `business_type` = the consumer search term — one string that is both the Outscraper
    discovery query and the geogrid scan keyword (a customer's search, e.g. "emergency plumber").
    """
    business_type = (business_type or "").strip()
    city_name = str(city.get("name") or "").strip()
    if not business_type:
        raise OutreachError("business_type_required")
    if not city_name or city.get("lat") is None or city.get("lng") is None:
        raise OutreachError("city_incomplete")

    # Sub-area is optional. A picked one must carry coordinates; if none is picked, the submarket IS
    # the city centre (the "whole city" scan), so a small city with no distinct sub-areas is never a
    # dead end.
    sub = subarea or {}
    sub_name = str(sub.get("name") or "").strip()
    if sub_name and (sub.get("lat") is None or sub.get("lng") is None):
        raise OutreachError("subarea_incomplete")
    if sub_name:
        sub_lat, sub_lng = float(sub["lat"]), float(sub["lng"])
    else:
        sub_name, sub_lat, sub_lng = city_name, float(city["lat"]), float(city["lng"])

    client = get_outreach_client()
    market_id = _ensure_market(
        client, name=city_name, lat=float(city["lat"]), lng=float(city["lng"])
    )
    submarket_id = _ensure_submarket(
        client, market_id=market_id, name=sub_name, lat=sub_lat, lng=sub_lng,
    )
    keyword_id = _ensure_keyword(client, market_id=market_id, term=business_type)

    active = (
        client.table("onboard_request")
        .select("id, status")
        .eq("submarket_id", submarket_id)
        .eq("keyword_id", keyword_id)
        .in_("status", list(ONBOARD_REQUEST_ACTIVE_STATUSES))
        .limit(1)
        .execute()
        .data
        or []
    )
    if active:
        raise OutreachError(
            "onboard_request_already_active",
            "an onboard for this city sub-area x business type is already pending or running",
        )

    row = {
        "submarket_id": submarket_id,
        "keyword_id": keyword_id,
        "category": business_type,
        "region": str(city.get("region") or "").strip(),
        "requested_by": actor_id,
        "note": (note or "").strip() or None,
    }
    try:
        written = client.table("onboard_request").insert(row).execute().data or []
    except Exception as exc:  # noqa: BLE001 — the one-active index refused a race our read missed
        if "onboard_request_one_active" in str(exc):
            raise OutreachError(
                "onboard_request_already_active",
                "an onboard for this city sub-area x business type is already pending or running",
            ) from exc
        raise
    if not written:
        raise OutreachError("onboard_request_not_created")
    order = written[0]
    order["submarket"] = {"name": sub_name}
    order["keyword"] = {"term": business_type}
    order["market"] = {"name": city_name}
    return order


def list_onboard_requests(
    *, status: str | None, limit: int, offset: int
) -> dict[str, Any]:
    client = get_outreach_client()
    query = (
        client.table("onboard_request")
        .select(
            "id, submarket_id, keyword_id, category, region, status, stage, "
            "prospects_ingested, prospects_survived, snapshot_id, error, "
            "created_at, started_at, finished_at, "
            "submarket(name), keyword(term)"
        )
        .order("created_at", desc=True)
    )
    if status:
        query = query.eq("status", status)
    rows = query.range(offset, offset + limit - 1).execute().data or []
    return {"onboard_requests": rows, "total": len(rows)}


def onboard_request_detail(request_id: str) -> dict[str, Any]:
    """One onboard order plus its scan snapshot's live collection progress — so the status screen
    shows the same "X/81 collected → rolled up" bar a scan order does, once the order's scan has
    been submitted (`snapshot_id` set)."""
    client = get_outreach_client()
    rows = (
        client.table("onboard_request")
        .select("*, submarket(name), keyword(term)")
        .eq("id", request_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise OutreachError("onboard_request_not_found")
    order = rows[0]
    return {"onboard_request": order, **_snapshot_detail(client, order.get("snapshot_id"))}


def cancel_onboard_request(request_id: str, actor_id: str) -> dict[str, Any]:
    """Withdraw a PENDING onboard. Conditional on status, like the scan-order cancel: a row the
    tick has claimed is executing (mid-discovery — real money), so past `pending` the answer is to
    let it resolve and read the outcome, not orphan the spend."""
    from datetime import datetime, timezone

    client = get_outreach_client()
    hit = (
        client.table("onboard_request")
        .update(
            {
                "status": "cancelled",
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "error": None,
            }
        )
        .eq("id", request_id)
        .eq("status", "pending")
        .execute()
        .data
        or []
    )
    if not hit:
        raise OutreachError(
            "onboard_request_not_cancellable",
            "only a pending onboard can be cancelled; one already running resolves on its own",
        )
    return {"onboard_request": hit[0]}


def create_scan_request(
    *, submarket_id: str, keyword_id: str, note: str | None, actor_id: str
) -> dict[str, Any]:
    """Place a signed scan order. Admin-gated at the router — this row authorizes ~81 paid tasks.

    Validation is a friendlier front door, not the gate: the database's FKs and the one-active
    partial unique index remain authoritative. The duplicate check is read-then-insert for the
    caller's sake (a named 422 beats a constraint string), with the racing insert still caught
    and mapped — losing that race means the order EXISTS, which is not the failure it looks like:
    somebody else just authorized the same scan first, and two orders for one pair is exactly
    what the index refuses.
    """
    client = get_outreach_client()

    submarket = (
        client.table("submarket")
        .select("id, name, market_id")
        .eq("id", submarket_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not submarket:
        raise OutreachError("submarket_not_found")
    keyword = (
        client.table("keyword")
        .select("id, term, market_id")
        .eq("id", keyword_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not keyword:
        raise OutreachError("keyword_not_found")
    if str(submarket[0]["market_id"]) != str(keyword[0]["market_id"]):
        raise OutreachError(
            "cross_market_order", "the submarket and keyword belong to different markets"
        )

    active = (
        client.table("scan_request")
        .select("id, status")
        .eq("submarket_id", submarket_id)
        .eq("keyword_id", keyword_id)
        .in_("status", list(SCAN_REQUEST_ACTIVE_STATUSES))
        .limit(1)
        .execute()
        .data
        or []
    )
    if active:
        raise OutreachError(
            "scan_request_already_active",
            "an order for this submarket x keyword is already pending or running",
        )

    row = {
        "submarket_id": submarket_id,
        "keyword_id": keyword_id,
        "requested_by": actor_id,
        "note": (note or "").strip() or None,
    }
    try:
        written = client.table("scan_request").insert(row).execute().data or []
    except Exception as exc:
        # The racing case: the one-active index refused what our read missed. The caller's
        # intent — "this pair should be scanned" — is already satisfied.
        if "scan_request_one_active" in str(exc):
            raise OutreachError(
                "scan_request_already_active",
                "an order for this submarket x keyword is already pending or running",
            ) from exc
        raise
    if not written:
        raise OutreachError("scan_request_not_created")
    order = written[0]
    order["submarket"] = {"name": submarket[0]["name"]}
    order["keyword"] = {"term": keyword[0]["term"]}
    return order


def cancel_scan_request(request_id: str, actor_id: str) -> dict[str, Any]:
    """Withdraw a PENDING order. Conditional on status, mirroring the drain's claim: a row the
    tick has already claimed is being executed and cancelling its record would only orphan the
    spend — past `pending`, the answer is to let it finish and read the outcome."""
    from datetime import datetime, timezone

    client = get_outreach_client()
    hit = (
        client.table("scan_request")
        .update(
            {
                "status": "cancelled",
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "error": None,
            }
        )
        .eq("id", request_id)
        .eq("status", "pending")
        .execute()
        .data
        or []
    )
    if hit:
        return hit[0]
    existing = (
        client.table("scan_request").select("id, status").eq("id", request_id).limit(1).execute().data
    )
    if not existing:
        raise OutreachError("scan_request_not_found")
    raise OutreachError(
        "scan_request_not_cancellable",
        f"order is {existing[0]['status']!r}; only a pending order can be withdrawn",
    )


def list_scan_requests(
    status: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> dict[str, Any]:
    """Orders newest-first, with their target names embedded. The list is deliberately cheap —
    per-order task progress lives on the detail read, not here, so the queue view costs one
    query however long the history grows."""
    size, start = clamp_page(limit, offset)
    query = (
        get_outreach_client()
        .table("scan_request")
        .select("*, submarket(name), keyword(term)", count="exact")
        .order("created_at", desc=True)
        .range(start, start + size - 1)
    )
    if status:
        query = query.eq("status", status)
    response = query.execute()
    return {
        "scan_requests": response.data or [],
        "total": response.count or 0,
        "limit": size,
        "offset": start,
    }


def build_task_progress(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts by status plus the two numbers the UI renders: collected/total and whether anything
    is stuck. Pure, so the shape is testable without a database."""
    counts: dict[str, int] = {}
    for task in tasks:
        counts[str(task.get("status"))] = counts.get(str(task.get("status")), 0) + 1
    total = len(tasks)
    return {
        "counts": counts,
        "total": total,
        "collected": counts.get("collected", 0),
        "outstanding": counts.get("pending", 0) + counts.get("submitted", 0),
        "failed": counts.get("failed", 0),
    }


def _snapshot_detail(client: Any, snapshot_id: str | None) -> dict[str, Any]:
    """The status-screen read for one scan snapshot: the snapshot row, per-status task counts, and
    whether the rollup marker exists (I-069 — completeness is a recorded fact; the marker also
    gates the placeholder score's LEFT JOIN, I-076). Shared by the scan-order and onboard-order
    status screens, so a whole-city onboard shows the same live "X/81 collected → rolled up"
    progress a scan order does. The task read is bounded by construction — one snapshot holds
    `expected_points` tasks (81 on the standard grid), far under the PostgREST cap."""
    if not snapshot_id:
        return {"snapshot": None, "task_progress": None, "rolled_up": False}
    snap_rows = (
        client.table("scan_snapshot")
        .select("id, expected_points, actual_points, complete, scanned_at, geometry_version")
        .eq("id", snapshot_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    tasks = (
        client.table("scan_task").select("status").eq("snapshot_id", snapshot_id).execute().data
        or []
    )
    marker = (
        client.table("snapshot_rollup")
        .select("snapshot_id")
        .eq("snapshot_id", snapshot_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    return {
        "snapshot": snap_rows[0] if snap_rows else None,
        "task_progress": build_task_progress(tasks),
        "rolled_up": bool(marker),
    }


def scan_request_detail(request_id: str) -> dict[str, Any]:
    """One order with everything the status screen needs: the row, its snapshot, per-status task
    counts, and whether the rollup marker exists."""
    client = get_outreach_client()
    rows = (
        client.table("scan_request")
        .select("*, submarket(name), keyword(term)")
        .eq("id", request_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise OutreachError("scan_request_not_found")
    order = rows[0]
    return {"scan_request": order, **_snapshot_detail(client, order.get("snapshot_id"))}


def placeholder_scores(
    submarket_id: str,
    limit: int | None = None,
    offset: int | None = None,
) -> dict[str, Any]:
    """The placeholder score for one submarket, worst coverage first.

    Reads `v_prospect_placeholder_score`, whose two I-076 properties this surface inherits and
    must not undo: a prospect with no coverage row inside a ROLLED-UP submarket scores 100%
    deficit (zero coverage, never unknown), and a submarket with no rollup marker returns NO rows
    (nothing measured, no score to give). An empty result here therefore means "not measured
    yet", and the router says so rather than rendering an empty table that reads as no data.
    """
    size, start = clamp_page(limit, offset)
    response = (
        get_outreach_client()
        .table("v_prospect_placeholder_score")
        .select("*", count="exact")
        .eq("submarket_id", submarket_id)
        .order("coverage_deficit", desc=True)
        .range(start, start + size - 1)
        .execute()
    )
    return {
        "scores": response.data or [],
        "total": response.count or 0,
        "limit": size,
        "offset": start,
    }


# --- Call-hook justification (the caller's "why this is a lead" talking points) ----------------
#
# Reads existing scan data only — coverage, the geogrid pack, the prospect and its submarket field
# — and assembles a deterministic set of phone-call talking points via `outreach_justification`
# (pure). Spends nothing, writes nothing: it is a read-time surface generated when a caller opens a
# prospect to dial (reporting-layer-spec §4a "Call hooks are exempt"). See that pure module for the
# design-fork reasoning (deterministic assembly, not an LLM pass).


def _latest_rolled_up_snapshot(
    client: Any, submarket_id: str | None, snapshot_id: str | None
) -> dict[str, Any] | None:
    """The snapshot a justification reads from: a specific one if named, else the newest COMPLETE
    snapshot for the submarket that also carries a rollup marker.

    The marker gate matches `v_prospect_placeholder_score` exactly (outreach ISSUES I-076): an
    incomplete or unrolled snapshot has no coverage rows, so reading one would score every prospect
    as invisible purely because the scan hadn't finished. Bounded — a submarket holds a handful of
    snapshots per cycle, far under the PostgREST cap.
    """
    if not submarket_id:
        return None
    snaps = (
        client.table("scan_snapshot")
        .select("id, keyword_id, scanned_at, geometry_version, actual_points")
        .eq("submarket_id", submarket_id)
        .eq("complete", True)
        .order("scanned_at", desc=True)
        .order("id", desc=True)
        .range(0, MAX_PAGE_SIZE - 1)
        .execute()
        .data
        or []
    )
    if not snaps:
        return None
    marker_rows = (
        client.table("snapshot_rollup")
        .select("snapshot_id")
        .in_("snapshot_id", [s["id"] for s in snaps])
        .execute()
        .data
        or []
    )
    rolled = {m["snapshot_id"] for m in marker_rows}
    if snapshot_id:
        return next((s for s in snaps if s["id"] == snapshot_id and s["id"] in rolled), None)
    return next((s for s in snaps if s["id"] in rolled), None)


def _fetch_pack_rows(client: Any, snapshot_id: str, pack_size: int) -> list[dict[str, Any]]:
    """Every map-pack `grid_result` row for one snapshot: `rank <= pack_size`, so at most
    `pack_size` per grid point (~243 on the 81-point grid at pack 3) — one bounded query, well
    under the 1000-row cap, no paging. Deliberately reads only the pack, not the full ~1,600-row
    result set, because who holds the top few spots is the whole competitive signal."""
    return (
        client.table("grid_result")
        .select("point_seq, place_id, rank")
        .eq("snapshot_id", snapshot_id)
        .lte("rank", pack_size)
        .range(0, MAX_PAGE_SIZE * 5 - 1)
        .execute()
        .data
        or []
    )


def _resolve_place_names(client: Any, place_ids: list[str]) -> dict[str, str]:
    """Map competitor place_ids to business names, for the ones we actually know. A place_id with
    no matching prospect row stays unnamed — never invent a competitor (outreach/CLAUDE.md)."""
    names: dict[str, str] = {}
    for start in range(0, len(place_ids), 100):
        chunk = place_ids[start : start + 100]
        if not chunk:
            continue
        for row in (
            client.table("prospect").select("place_id, name").in_("place_id", chunk).execute().data
            or []
        ):
            if row.get("place_id") and row.get("name"):
                names[row["place_id"]] = row["name"]
    return names


def prospect_justification(prospect_id: str, snapshot_id: str | None = None) -> dict[str, Any]:
    """Assemble the deterministic call-hook justification for one prospect.

    Reads-only: the prospect + submarket, the latest rolled-up coverage, the map-pack competitors
    from `grid_result`, and the submarket's review field — then hands them to the pure assembler.
    Returns `{measured: False, …}` when the area has no rolled-up scan (nothing to point at), and
    degrades gracefully when the competitive detail can't be read (a cold-dropped `grid_result`
    partition — outreach ISSUES I-094): coverage, reviews and gaps still stand.
    """
    from config import settings
    from services import outreach_justification as oj

    client = get_outreach_client()

    rows = (
        client.table("prospect")
        .select(
            "id, name, submarket_id, place_id, phone, website, category, rating, "
            "review_count, review_count_inferred_zero, business_status"
        )
        .eq("id", prospect_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise OutreachError("prospect_not_found", "no such prospect")
    prospect = rows[0]
    submarket_id = prospect.get("submarket_id")

    submarket_name = "their area"
    if submarket_id:
        sub = (
            client.table("submarket").select("name").eq("id", submarket_id).limit(1).execute().data
            or []
        )
        if sub:
            submarket_name = sub[0]["name"]

    snapshot = _latest_rolled_up_snapshot(client, submarket_id, snapshot_id)
    if snapshot is None:
        return oj.not_measured(prospect_id, prospect.get("name"))

    keyword = "this service"
    kw = (
        client.table("keyword").select("term").eq("id", snapshot["keyword_id"]).limit(1).execute().data
        or []
    )
    if kw:
        keyword = kw[0]["term"]

    coverage_rows = (
        client.table("prospect_coverage")
        .select(
            "coverage_pct, points_present, live_points, best_rank, worst_rank, avg_rank, "
            "centroid_dist_at_loss, rank_vector"
        )
        .eq("snapshot_id", snapshot["id"])
        .eq("prospect_id", prospect_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    coverage = coverage_rows[0] if coverage_rows else None

    # The measured-point denominator is a property of the snapshot's land mask — the same for every
    # prospect in it — so a zero-coverage prospect (no row of its own, I-076) still learns how many
    # points "invisible everywhere" spans by reading any sibling row.
    if coverage:
        live_points = coverage.get("live_points")
        vector = oj.decode_rank_vector(coverage.get("rank_vector"))
    else:
        sibling = (
            client.table("prospect_coverage")
            .select("live_points")
            .eq("snapshot_id", snapshot["id"])
            .limit(1)
            .execute()
            .data
            or []
        )
        live_points = sibling[0]["live_points"] if sibling else snapshot.get("actual_points")
        vector = None
    absent_seqs = oj.absent_point_seqs(vector)

    pack_size = settings.outreach_call_hook_pack_size
    try:
        pack_rows = _fetch_pack_rows(client, snapshot["id"], pack_size)
        place_ids = sorted(
            {r["place_id"] for r in pack_rows if r.get("place_id") and r["place_id"] != prospect.get("place_id")}
        )
        competitors = oj.summarize_competitors(
            prospect_place_id=prospect.get("place_id"),
            absent_seqs=absent_seqs,
            pack_rows=pack_rows,
            name_by_place_id=_resolve_place_names(client, place_ids),
            max_named=settings.outreach_justification_max_competitors,
        )
    except Exception as exc:  # noqa: BLE001 — a cold-dropped grid partition must not lose the hook
        logger.warning("outreach_justification_competitors_unavailable", extra={"error": str(exc)})
        competitors = {"available": False, "named": [], "total": 0, "invisible_points": 0}

    field_rows = (
        client.table("prospect")
        .select("review_count, review_count_inferred_zero")
        .eq("submarket_id", submarket_id)
        .neq("id", prospect_id)
        .range(0, 999)
        .execute()
        .data
        or []
    ) if submarket_id else []
    field_reviews = oj.field_review_stats(field_rows)

    return oj.build_justification(
        prospect=prospect,
        keyword=keyword,
        submarket=submarket_name,
        snapshot=snapshot,
        coverage=coverage,
        live_points=live_points,
        competitors=competitors,
        field_reviews=field_reviews,
        field_min_sample=settings.outreach_field_review_min_sample,
        pack_size=pack_size,
    )


def prospect_report(prospect_id: str, snapshot_id: str | None = None) -> dict[str, Any]:
    """Assemble the per-prospect competitive report — the internal brief and the client-facing
    draft, over one shared document.

    Read-only, spends nothing. Reuses `prospect_justification` verbatim for the call hook (so the
    report and the "Why call?" panel never disagree) and adds a maps rankings-vs-competitors table.
    The organic and LLM sections are explicit `not_scanned` blocks until those paid scan layers land
    (outreach ISSUES I-095) — never an empty table that would read as "no competitors".
    """
    from config import settings
    from services import outreach_justification as oj
    from services import outreach_report as orep

    client = get_outreach_client()

    rows = (
        client.table("prospect")
        .select(
            "id, name, submarket_id, place_id, phone, website, address, category, rating, "
            "review_count, review_count_inferred_zero, business_status"
        )
        .eq("id", prospect_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise OutreachError("prospect_not_found", "no such prospect")
    prospect = rows[0]
    submarket_id = prospect.get("submarket_id")

    submarket_name = "their area"
    if submarket_id:
        sub = (
            client.table("submarket").select("name").eq("id", submarket_id).limit(1).execute().data
            or []
        )
        if sub:
            submarket_name = sub[0]["name"]

    justification = prospect_justification(prospect_id, snapshot_id)

    llm = orep.not_scanned_section(
        orep.SIGNAL_LLM,
        "The AI-visibility scan hasn't run for this prospect yet.",
    )

    if not justification.get("measured"):
        organic = orep.not_scanned_section(
            orep.SIGNAL_ORGANIC, "The organic-search scan hasn't run for this prospect yet."
        )
        maps_section = {"status": orep.STATUS_NOT_MEASURED, "signal": orep.SIGNAL_MAPS}
        return orep.build_report(
            prospect=prospect,
            keyword="this service",
            submarket=submarket_name,
            justification=justification,
            maps_section=maps_section,
            organic_section=organic,
            llm_section=llm,
            heatmap_available=False,
        )

    prov = justification["provenance"]
    snap_id = prov["snapshot_id"]
    keyword = prov["keyword"]
    live_points = prov["live_points"]

    # Organic-SERP signal (increment 2): the stored capture for this snapshot, if the organic scan
    # has run for it. Absent → the builder returns a not_scanned block (never an empty table).
    organic_summary = None
    try:
        serp_rows = (
            client.table("serp_result")
            .select("payload_summary")
            .eq("snapshot_id", snap_id)
            .eq("engine", "google_organic")
            .limit(1)
            .execute()
            .data
            or []
        )
        if serp_rows:
            organic_summary = serp_rows[0].get("payload_summary")
    except Exception as exc:  # noqa: BLE001 — the report stands without the organic section
        logger.warning("outreach_report_organic_unavailable", extra={"error": str(exc)})
    organic = orep.build_organic_section(
        organic_summary,
        prospect_website=prospect.get("website"),
        max_competitors=settings.outreach_justification_max_competitors,
    )

    coverage_rows = (
        client.table("prospect_coverage")
        .select("coverage_pct, points_present, live_points, best_rank, worst_rank, avg_rank")
        .eq("snapshot_id", snap_id)
        .eq("prospect_id", prospect_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    coverage = coverage_rows[0] if coverage_rows else None

    pack_size = settings.outreach_call_hook_pack_size
    try:
        pack_rows = _fetch_pack_rows(client, snap_id, pack_size)
        place_ids = sorted({r["place_id"] for r in pack_rows if r.get("place_id")})
        maps_section = orep.build_maps_comparison(
            prospect_place_id=prospect.get("place_id"),
            pack_rows=pack_rows,
            name_by_place_id=_resolve_place_names(client, place_ids),
            coverage=coverage,
            live_points=live_points,
            max_competitors=settings.outreach_justification_max_competitors,
        )
    except Exception as exc:  # noqa: BLE001 — a cold-dropped grid partition must not lose the report
        logger.warning("outreach_report_maps_unavailable", extra={"error": str(exc)})
        maps_section = orep.not_scanned_section(
            orep.SIGNAL_MAPS, "The raw ranking data for this scan has aged out."
        )

    return orep.build_report(
        prospect=prospect,
        keyword=keyword,
        submarket=prov.get("submarket") or submarket_name,
        justification=justification,
        maps_section=maps_section,
        organic_section=organic,
        llm_section=llm,
        heatmap_available=coverage is not None,
    )


def promote_prospect(prospect_id: str, actor_id: str) -> dict[str, Any]:
    """Turn a scanned prospect into a lead, prefilled — the scan-results "Send to CRM" click.

    Owner ruling 2026-08-06 (outreach DECISIONS.md): a hand-picked lead IS `outbound_scan`.
    `source` records provenance, not automation, and the `lead.unique (prospect_id, source)`
    constraint makes the promotion idempotent against both a second click and Phase 3's future
    emit path — either finding the lead already exists means somebody got there first, so the
    existing lead comes back with `already_existed` rather than an error. A button that 422s on
    its second press teaches people to distrust the first.
    """
    client = get_outreach_client()
    rows = (
        client.table("prospect")
        .select("id,name,phone,website,category")
        .eq("id", prospect_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise OutreachError("prospect_not_found")
    prospect = rows[0]

    existing = (
        client.table("lead")
        .select(_LEAD_LIST_COLUMNS)
        .eq("prospect_id", prospect_id)
        .eq("source", "outbound_scan")
        .is_("deleted_at", "null")
        .limit(1)
        .execute()
        .data
        or []
    )
    if existing:
        return dict(existing[0], already_existed=True)

    payload = {
        "source": "outbound_scan",
        "prospect_id": prospect_id,
        "company_name": prospect.get("name"),
        "phone": prospect.get("phone"),
        "website": prospect.get("website"),
        "category": prospect.get("category"),
    }
    try:
        lead = create_lead(payload, actor_id)
    except OutreachError:
        raise
    except Exception:
        # Lost a race against a concurrent promotion (the unique constraint refused). The row
        # exists, which is the outcome the caller wanted — same shape as add_suppression.
        raced = (
            client.table("lead")
            .select(_LEAD_LIST_COLUMNS)
            .eq("prospect_id", prospect_id)
            .eq("source", "outbound_scan")
            .is_("deleted_at", "null")
            .limit(1)
            .execute()
            .data
            or []
        )
        if raced:
            return dict(raced[0], already_existed=True)
        raise
    return dict(lead, already_existed=False)
