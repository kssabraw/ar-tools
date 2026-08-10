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


# --- Report signal scans (organic / AI-visibility UI triggers — outreach 2026-08-10) ----------
#
# The per-prospect report already renders four signals — maps, organic, AI, paid — but only the
# maps geogrid had an in-app trigger. These place the two signed orders that let the report's
# "Run organic" / "Run AI" buttons fill the organic and AI sections. Same money-gate carrier as
# scan_request: platform-api WRITES the order (admin-gated), the outreach `tick` DRAINS and runs it;
# platform-api never spends. Organic attaches to the exact snapshot the report reads; AI targets an
# `ai_region` (a coarse human-seeded place name, not a submarket), so it also needs the small region
# create/list surface below (name_level is a human judgement the module forbids deriving — I-073).

ORGANIC_SCAN_REQUEST_ACTIVE_STATUSES: tuple[str, ...] = ("pending", "running")
AI_SCAN_REQUEST_ACTIVE_STATUSES: tuple[str, ...] = ("pending", "running")
AI_REGION_NAME_LEVELS: tuple[str, ...] = ("metro", "city", "suburb", "neighbourhood")


def create_organic_scan_request(
    *, prospect_id: str, note: str | None, actor_id: str
) -> dict[str, Any]:
    """Place a signed organic-scan order for the snapshot the prospect's report reads.

    Admin-gated at the router — this row authorizes one paid organic SERP capture on the next tick.
    It resolves the EXACT rolled-up snapshot the report's organic section reads (via
    `_latest_rolled_up_snapshot`, the same resolver the justification uses) so the capture lands
    where the report will look, and refuses `not_measured` when the area has no rolled-up scan
    (there is no snapshot to attach organic to). The one-active partial unique index dedupes clicks
    across prospects sharing a submarket snapshot — a dozen clicks collapse to one billed capture.
    """
    client = get_outreach_client()
    rows = (
        client.table("prospect")
        .select("id, submarket_id")
        .eq("id", prospect_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise OutreachError("prospect_not_found", "no such prospect")
    snapshot = _latest_rolled_up_snapshot(client, rows[0].get("submarket_id"), None)
    if snapshot is None:
        raise OutreachError(
            "not_measured",
            "this prospect's area has no rolled-up scan to attach an organic capture to",
        )
    snapshot_id = snapshot["id"]
    keyword_id = snapshot["keyword_id"]

    active = (
        client.table("organic_scan_request")
        .select("id, status")
        .eq("snapshot_id", snapshot_id)
        .eq("keyword_id", keyword_id)
        .in_("status", list(ORGANIC_SCAN_REQUEST_ACTIVE_STATUSES))
        .limit(1)
        .execute()
        .data
        or []
    )
    if active:
        raise OutreachError(
            "organic_scan_request_already_active",
            "an organic scan for this area is already pending or running",
        )

    row = {
        "snapshot_id": snapshot_id,
        "keyword_id": keyword_id,
        "requested_by": actor_id,
        "note": (note or "").strip() or None,
    }
    try:
        written = client.table("organic_scan_request").insert(row).execute().data or []
    except Exception as exc:
        if "organic_scan_request_one_active" in str(exc):
            raise OutreachError(
                "organic_scan_request_already_active",
                "an organic scan for this area is already pending or running",
            ) from exc
        raise
    if not written:
        raise OutreachError("organic_scan_request_not_created")
    return written[0]


def _resolve_ai_target(client: Any, prospect: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Resolve the (ai_region, keyword_id) the report's AI section reads for this prospect.

    The region is the seeded `ai_region` whose name matches the prospect's submarket name (the same
    ilike join `_llm_section` uses at read time); the keyword is the one the report shows — the
    latest rolled-up snapshot's keyword when the area is measured, else the market's primary. Raises
    `ai_region_not_seeded` when no region matches, which the frontend turns into the seed modal.
    """
    market_id = prospect.get("market_id")
    submarket_id = prospect.get("submarket_id")
    if not market_id:
        raise OutreachError("prospect_market_unknown", "this prospect has no market")

    submarket_name = None
    if submarket_id:
        sub = (
            client.table("submarket").select("name").eq("id", submarket_id).limit(1).execute().data
            or []
        )
        if sub:
            submarket_name = sub[0]["name"]
    if not submarket_name:
        raise OutreachError(
            "ai_region_not_seeded", "this prospect has no area name to match an AI region"
        )

    regions = (
        client.table("ai_region")
        .select("id, name, name_level")
        .eq("market_id", market_id)
        .ilike("name", submarket_name)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not regions:
        raise OutreachError(
            "ai_region_not_seeded",
            f"no AI region named {submarket_name!r} is seeded for this market — seed one first",
        )
    region = regions[0]

    keyword_id: str | None = None
    snapshot = _latest_rolled_up_snapshot(client, submarket_id, None)
    if snapshot is not None:
        keyword_id = snapshot.get("keyword_id")
    if not keyword_id:
        prim = (
            client.table("keyword")
            .select("id")
            .eq("market_id", market_id)
            .order("is_primary", desc=True)
            .limit(1)
            .execute()
            .data
            or []
        )
        if not prim:
            raise OutreachError("no_keyword", "this market has no keyword to scan")
        keyword_id = prim[0]["id"]
    return region, keyword_id


def create_ai_scan_request(*, prospect_id: str, note: str | None, actor_id: str) -> dict[str, Any]:
    """Place a signed AI-visibility order for the prospect's ai_region × keyword.

    Admin-gated — authorizes one ChatGPT + one Google-AI-Overview call on the next tick. The scan is
    per REGION, shared by every prospect in it, so the order targets the region (the report does the
    per-prospect "is this business named" read). Raises `ai_region_not_seeded` when the prospect's
    area has no seeded region — the frontend then offers the region-seed modal and retries.
    """
    client = get_outreach_client()
    rows = (
        client.table("prospect")
        .select("id, market_id, submarket_id, name")
        .eq("id", prospect_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise OutreachError("prospect_not_found", "no such prospect")
    region, keyword_id = _resolve_ai_target(client, rows[0])

    active = (
        client.table("ai_scan_request")
        .select("id, status")
        .eq("ai_region_id", region["id"])
        .eq("keyword_id", keyword_id)
        .in_("status", list(AI_SCAN_REQUEST_ACTIVE_STATUSES))
        .limit(1)
        .execute()
        .data
        or []
    )
    if active:
        raise OutreachError(
            "ai_scan_request_already_active",
            "an AI scan for this region is already pending or running",
        )

    row = {
        "ai_region_id": region["id"],
        "keyword_id": keyword_id,
        "requested_by": actor_id,
        "note": (note or "").strip() or None,
    }
    try:
        written = client.table("ai_scan_request").insert(row).execute().data or []
    except Exception as exc:
        if "ai_scan_request_one_active" in str(exc):
            raise OutreachError(
                "ai_scan_request_already_active",
                "an AI scan for this region is already pending or running",
            ) from exc
        raise
    if not written:
        raise OutreachError("ai_scan_request_not_created")
    order = written[0]
    order["ai_region"] = {"name": region.get("name"), "name_level": region.get("name_level")}
    return order


def list_organic_scan_requests(
    status: str | None = None, limit: int | None = None, offset: int | None = None
) -> dict[str, Any]:
    """Organic-scan orders newest-first, keyword term embedded — the queue/status view."""
    size, start = clamp_page(limit, offset)
    query = (
        get_outreach_client()
        .table("organic_scan_request")
        .select("*, keyword(term)", count="exact")
        .order("created_at", desc=True)
        .range(start, start + size - 1)
    )
    if status:
        query = query.eq("status", status)
    response = query.execute()
    return {
        "organic_scan_requests": response.data or [],
        "total": response.count or 0,
        "limit": size,
        "offset": start,
    }


def organic_scan_request_detail(request_id: str) -> dict[str, Any]:
    """One organic order — the poll a useResumableJob reads. The status IS the progress (a single
    capture), so this is just the row plus its keyword term."""
    rows = (
        get_outreach_client()
        .table("organic_scan_request")
        .select("*, keyword(term)")
        .eq("id", request_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise OutreachError("organic_scan_request_not_found", "no such order")
    return {"organic_scan_request": rows[0]}


def cancel_organic_scan_request(request_id: str, actor_id: str) -> dict[str, Any]:
    """Withdraw a PENDING organic order. Conditional on status, like every other order cancel: one
    the tick has claimed is already running and resolves on its own."""
    from datetime import datetime, timezone

    client = get_outreach_client()
    hit = (
        client.table("organic_scan_request")
        .update({"status": "cancelled", "finished_at": datetime.now(timezone.utc).isoformat()})
        .eq("id", request_id)
        .eq("status", "pending")
        .execute()
        .data
        or []
    )
    if hit:
        return {"organic_scan_request": hit[0]}
    existing = (
        client.table("organic_scan_request").select("id, status").eq("id", request_id).limit(1)
        .execute().data
    )
    if not existing:
        raise OutreachError("organic_scan_request_not_found", "no such order")
    raise OutreachError(
        "organic_scan_request_not_cancellable",
        f"order is {existing[0]['status']!r}; only a pending order can be withdrawn",
    )


def list_ai_scan_requests(
    status: str | None = None, limit: int | None = None, offset: int | None = None
) -> dict[str, Any]:
    """AI-scan orders newest-first, region + keyword embedded — the queue/status view."""
    size, start = clamp_page(limit, offset)
    query = (
        get_outreach_client()
        .table("ai_scan_request")
        .select("*, ai_region(name, name_level), keyword(term)", count="exact")
        .order("created_at", desc=True)
        .range(start, start + size - 1)
    )
    if status:
        query = query.eq("status", status)
    response = query.execute()
    return {
        "ai_scan_requests": response.data or [],
        "total": response.count or 0,
        "limit": size,
        "offset": start,
    }


def ai_scan_request_detail(request_id: str) -> dict[str, Any]:
    """One AI order — the poll a useResumableJob reads."""
    rows = (
        get_outreach_client()
        .table("ai_scan_request")
        .select("*, ai_region(name, name_level), keyword(term)")
        .eq("id", request_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise OutreachError("ai_scan_request_not_found", "no such order")
    return {"ai_scan_request": rows[0]}


def cancel_ai_scan_request(request_id: str, actor_id: str) -> dict[str, Any]:
    """Withdraw a PENDING AI order. Conditional on status."""
    from datetime import datetime, timezone

    client = get_outreach_client()
    hit = (
        client.table("ai_scan_request")
        .update({"status": "cancelled", "finished_at": datetime.now(timezone.utc).isoformat()})
        .eq("id", request_id)
        .eq("status", "pending")
        .execute()
        .data
        or []
    )
    if hit:
        return {"ai_scan_request": hit[0]}
    existing = (
        client.table("ai_scan_request").select("id, status").eq("id", request_id).limit(1)
        .execute().data
    )
    if not existing:
        raise OutreachError("ai_scan_request_not_found", "no such order")
    raise OutreachError(
        "ai_scan_request_not_cancellable",
        f"order is {existing[0]['status']!r}; only a pending order can be withdrawn",
    )


def list_ai_regions(market_id: str) -> dict[str, Any]:
    """The seeded AI regions for a market — the seed modal's picker. Read-only."""
    rows = (
        get_outreach_client()
        .table("ai_region")
        .select("id, name, name_level, created_at")
        .eq("market_id", market_id)
        .order("name")
        .execute()
        .data
        or []
    )
    return {"ai_regions": rows}


def create_ai_region(*, market_id: str, name: str, name_level: str) -> dict[str, Any]:
    """Seed one coarse AI region (a human-judged place name + name_level) for a market.

    Admin-gated. `name_level` (metro/city/suburb/neighbourhood) is a human judgement the module
    forbids deriving from data (invariant I-073/I-004) — this is the deliberate human-in-the-loop
    step that lets the AI scan run for a typed any-city market. Idempotent on (market_id, name): a
    re-seed of an existing region returns it rather than erroring, so the modal is safe to re-submit.
    """
    clean = (name or "").strip()
    if not clean:
        raise OutreachError("ai_region_name_required", "a region name is required")
    if name_level not in AI_REGION_NAME_LEVELS:
        raise OutreachError(
            "invalid_name_level",
            f"name_level must be one of {', '.join(AI_REGION_NAME_LEVELS)}",
        )
    client = get_outreach_client()
    market = client.table("market").select("id").eq("id", market_id).limit(1).execute().data or []
    if not market:
        raise OutreachError("market_not_found", "no such market")

    row = {"market_id": market_id, "name": clean, "name_level": name_level}
    try:
        written = client.table("ai_region").insert(row).execute().data or []
    except Exception as exc:
        if "ai_region_market_id_name" in str(exc) or "duplicate key" in str(exc).lower():
            existing = (
                client.table("ai_region")
                .select("*")
                .eq("market_id", market_id)
                .ilike("name", clean)
                .limit(1)
                .execute()
                .data
                or []
            )
            if existing:
                return existing[0]
        raise
    if not written:
        raise OutreachError("ai_region_not_created")
    return written[0]


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


def _organic_summary_for(
    client: Any, snapshot_id: str, cache: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """The stored `serp_result.payload_summary` for a snapshot's organic capture, or None. This is
    the read the organic AND paid-placement signals both come off (paid rides the organic capture —
    outreach HANDOFF §12 item 3a). Best-effort: a missing table / cold-dropped row returns None so
    the report and hook still assemble without those sections.

    `cache` is an optional per-request memo. `prospect_report` calls `prospect_justification`, and
    both need this row — without the memo one report render makes the same cross-region round trip
    twice. The cache is passed in (never module state) so it lives exactly as long as one request.
    """
    key = f"serp:{snapshot_id}"
    if cache is not None and key in cache:
        return cache[key]
    try:
        rows = (
            client.table("serp_result")
            .select("payload_summary")
            .eq("snapshot_id", snapshot_id)
            .eq("engine", "google_organic")
            .limit(1)
            .execute()
            .data
            or []
        )
        summary = rows[0].get("payload_summary") if rows else None
        if cache is not None:
            cache[key] = summary
        return summary
    except Exception as exc:  # noqa: BLE001 — the report stands without the organic/paid section
        logger.warning("outreach_report_organic_unavailable", extra={"error": str(exc)})
        return None


def _latest_tech_signal(
    client: Any, prospect_id: str, cache: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """The most recent `prospect_tech_signal` row for a prospect (Slice B1 site ad tech), or None.
    Best-effort — before the migration is applied / before `scan-tech` has run, returns None so the
    paid signal degrades to Slice A's SERP-only read. `cache` is the same per-request memo
    `_organic_summary_for` takes, for the same reason (the report reads this twice otherwise)."""
    key = f"tech:{prospect_id}"
    if cache is not None and key in cache:
        return cache[key]
    try:
        rows = (
            client.table("prospect_tech_signal")
            .select("fetch_status, meta_pixel, google_ads_conversion, vendor_tags, gtm_container_ids")
            .eq("prospect_id", prospect_id)
            .order("fetched_at", desc=True)
            .limit(1)
            .execute()
            .data
            or []
        )
        row = rows[0] if rows else None
        if cache is not None:
            cache[key] = row
        return row
    except Exception as exc:  # noqa: BLE001 — the paid signal stands on the SERP read alone
        logger.warning("outreach_tech_signal_unavailable", extra={"error": str(exc)})
        return None


def _paid_signal_for(
    client: Any, orep: Any, snapshot_id: str, prospect: dict[str, Any], *, max_named: int,
    cache: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """The derived paid-placement facts for one prospect, or None when no organic scan has run.
    Threads the stored SERP summary (Slice A) AND the latest site tech signal (Slice B1) through the
    pure `derive_paid_signal`, so a justification's paid talking point and the report's paid section
    read one source of truth."""
    summary = _organic_summary_for(client, snapshot_id, cache)
    if not summary or "paid" not in summary:
        return None
    return orep.derive_paid_signal(
        summary.get("paid"),
        prospect_website=prospect.get("website"),
        prospect_name=prospect.get("name"),
        max_named=max_named,
        tech=_latest_tech_signal(client, prospect["id"], cache),
    )


def prospect_justification(
    prospect_id: str, snapshot_id: str | None = None, _cache: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Assemble the deterministic call-hook justification for one prospect.

    Reads-only: the prospect + submarket, the latest rolled-up coverage, the map-pack competitors
    from `grid_result`, and the submarket's review field — then hands them to the pure assembler.
    Returns `{measured: False, …}` when the area has no rolled-up scan (nothing to point at), and
    degrades gracefully when the competitive detail can't be read (a cold-dropped `grid_result`
    partition — outreach ISSUES I-094): coverage, reviews and gaps still stand.
    """
    from config import settings
    from services import outreach_justification as oj
    from services import outreach_report as orep

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

    # Paid-placement signal (outreach HANDOFF §12 item 3a): the organic capture for this snapshot
    # already carries the paid ads. Derive the prospect's paid facts so a "competitors are buying
    # this search and you're not" talking point can fire. Best-effort — no organic scan / no serp
    # row → no paid talking point (never a fabricated ad).
    paid_signal = _paid_signal_for(client, orep, snapshot["id"], prospect,
                                   max_named=settings.outreach_justification_max_competitors,
                                   cache=_cache)

    justification = oj.build_justification(
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
        paid=paid_signal,
        losing_deficit_pct=settings.outreach_paying_losing_deficit_pct,
    )
    # Loss-framed LLM phrasing on top of the deterministic hook — cached per (prospect, snapshot),
    # best-effort, guarded against fabricated numbers. Falls back to the deterministic hook on any
    # failure. Both report faces read this justification, so the report + the "Why call?" panel share
    # the same generated hook.
    _apply_call_hook_phrasing(client, justification, prospect_id, snapshot["id"])
    return justification


def _apply_hook_to_justification(
    justification: dict[str, Any], hook: str, points: list[dict[str, Any]]
) -> None:
    """Swap the deterministic hook for the generated one and rephrase the talking points KEYED BY
    ELEMENT — the model can only re-word points it was given, never add, drop, or reorder them (the
    element+facts stay the deterministic ones, so provenance is intact). Pure mutation."""
    justification["hook"] = hook
    justification["hook_generated"] = True
    by_el: dict[str, str] = {}
    for p in points or []:
        el, txt = p.get("element"), p.get("text")
        if el and isinstance(txt, str) and txt.strip():
            by_el.setdefault(el, txt.strip())
    for tp in justification.get("talking_points") or []:
        if tp.get("element") in by_el:
            tp["text"] = by_el[tp["element"]]


def _apply_call_hook_phrasing(
    client: Any, justification: dict[str, Any], prospect_id: str, snapshot_id: str
) -> None:
    """Apply the cached loss-framed hook, or generate + cache one. Best-effort — never raises past a
    log; the deterministic hook stands on any failure (no key, LLM error, guard rejection, a
    not-yet-migrated cache table)."""
    from config import settings

    if not settings.outreach_call_hook_llm_enabled or not justification.get("measured"):
        return
    try:
        from services import outreach_call_hook as och

        fingerprint = och.facts_fingerprint(justification)
        cached = _get_cached_call_hook(client, prospect_id, snapshot_id)
        if cached and cached.get("facts_fingerprint") == fingerprint and cached.get("hook"):
            _apply_hook_to_justification(
                justification, cached["hook"], cached.get("talking_points") or []
            )
            return
        generated = och.generate_hook(justification)
        if not generated:
            return
        _apply_hook_to_justification(
            justification, generated["hook"], generated.get("talking_points") or []
        )
        _store_call_hook(client, prospect_id, snapshot_id, fingerprint, generated)
    except Exception as exc:  # noqa: BLE001 — phrasing is a nicety; the report must render regardless
        logger.warning("outreach_call_hook_apply_failed", extra={"error": str(exc)[:200]})


def _get_cached_call_hook(client: Any, prospect_id: str, snapshot_id: str) -> dict[str, Any] | None:
    """The stored generated hook for this (prospect, snapshot), or None. Returns None (not an error)
    when the cache table doesn't exist yet, so the feature degrades to live generation."""
    try:
        rows = (
            client.table("prospect_call_hook")
            .select("hook, talking_points, facts_fingerprint")
            .eq("prospect_id", prospect_id)
            .eq("snapshot_id", snapshot_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        return rows[0] if rows else None
    except Exception:  # noqa: BLE001 — table not migrated / read failed → no cache, generate live
        return None


def _store_call_hook(
    client: Any,
    prospect_id: str,
    snapshot_id: str,
    fingerprint: str,
    generated: dict[str, Any],
) -> None:
    """Persist the generated hook so a re-read is a cheap, identical replay. Upsert on (prospect_id,
    snapshot_id); a store failure is logged, never fatal."""
    from config import settings

    row = {
        "prospect_id": prospect_id,
        "snapshot_id": snapshot_id,
        "facts_fingerprint": fingerprint,
        "hook": generated["hook"],
        "talking_points": generated.get("talking_points") or [],
        "model": f"{settings.outreach_call_hook_provider}:{settings.outreach_call_hook_model}",
    }
    try:
        client.table("prospect_call_hook").upsert(
            row, on_conflict="prospect_id,snapshot_id"
        ).execute()
    except Exception as exc:  # noqa: BLE001 — the hook already rendered; caching is opportunistic
        logger.warning("outreach_call_hook_store_failed", extra={"error": str(exc)[:200]})


def _latest_report_approval(client: Any, prospect_id: str) -> dict[str, Any] | None:
    """The most recent client-facing approval for a prospect, or None. Best-effort — before the
    report_approval migration exists this returns None (the report reads as an unapproved draft)."""
    try:
        rows = (
            client.table("report_approval")
            .select("approved_by, content_hash, created_at, storage_path")
            .eq("prospect_id", prospect_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
            .data
            or []
        )
        return rows[0] if rows else None
    except Exception as exc:  # noqa: BLE001 — an unapproved report is the safe default
        logger.warning("outreach_report_approval_read_failed", extra={"error": str(exc)})
        return None


def _sign_report_url(client: Any, path: str) -> str | None:
    """A signed URL for a stored report PDF, valid for the configured TTL. reporting-layer-spec §5:
    a prospect reads the audit through a signed URL with an expiry, no auth. Best-effort — a signing
    failure returns None so the caller can still hand back the bytes rather than 500."""
    from config import settings

    if not path:
        return None
    try:
        ttl = int(settings.outreach_report_url_ttl_days) * 86400
        res = client.storage.from_(settings.outreach_report_bucket).create_signed_url(path, ttl)
        return (res or {}).get("signedURL") or (res or {}).get("signedUrl")
    except Exception as exc:  # noqa: BLE001
        logger.warning("outreach_report_sign_failed", extra={"error": str(exc)})
        return None


def generate_client_report_pdf(
    prospect_id: str, actor_id: str, snapshot_id: str | None = None
) -> dict[str, Any]:
    """Render the client-facing report to PDF, STORE it, and RECORD the approval. The admin click is
    the approval (reporting-layer-spec §4a; the no-unapproved-asset invariant), so this is the one
    path that turns the draft into a shippable prospect-facing asset. It writes a `report_approval`
    row naming the actor, the exact bytes' content_hash, and the storage path, then returns the PDF
    bytes AND a signed URL (reporting §5 — a client gets a link with an expiry, not an emailed file).

    Refuses an unmeasured area: there is no honest client-facing report to render when nothing has
    been scanned, so it raises rather than producing an empty asset.
    """
    import hashlib

    from config import settings
    from services import client_report, outreach_report as orep

    report = prospect_report(prospect_id, snapshot_id)
    if not report.get("measured"):
        raise OutreachError("report_not_measured", "no rolled-up scan for this prospect's area yet")

    html = orep.render_client_report_html(report, agency_name=settings.outreach_report_agency_name)
    content_hash = hashlib.sha256(html.encode("utf-8")).hexdigest()
    pdf = client_report.render_pdf(html)

    snap_id = (report.get("justification", {}).get("provenance") or {}).get("snapshot_id")
    client = get_outreach_client()

    # Store the bytes, keyed by content_hash so identical inputs reuse one object (reporting §6). A
    # storage failure must not lose the approval or the download, so it is best-effort — the row is
    # still written and the bytes still returned; only the shareable link is absent.
    storage_path = f"{prospect_id}/{content_hash}.pdf"
    signed_url: str | None = None
    try:
        client.storage.from_(settings.outreach_report_bucket).upload(
            storage_path, pdf, {"content-type": "application/pdf", "upsert": "true"}
        )
        signed_url = _sign_report_url(client, storage_path)
    except Exception as exc:  # noqa: BLE001 — the download still works without the stored copy
        logger.warning("outreach_report_store_failed", extra={"error": str(exc)})
        storage_path = None  # type: ignore[assignment]

    row: dict[str, Any] = {
        "prospect_id": prospect_id,
        "content_hash": content_hash,
        "approved_by": actor_id,
    }
    if snap_id:
        row["snapshot_id"] = snap_id
    if storage_path:
        row["storage_path"] = storage_path
    written = client.table("report_approval").insert(row).execute().data or []
    approval = written[0] if written else row
    logger.info("outreach_client_report_approved", extra={"prospect_id": prospect_id, "content_hash": content_hash})
    return {
        "pdf": pdf,
        "approval": approval,
        "signed_url": signed_url,
        "content_hash": content_hash,
        "expires_days": int(settings.outreach_report_url_ttl_days),
    }


def latest_client_report_url(prospect_id: str) -> dict[str, Any]:
    """A fresh signed URL for the prospect's most recent approved report, re-signed from the stored
    path (so a link that expired is refreshed without re-approving). 404s when there is no approval
    with a stored PDF."""
    client = get_outreach_client()
    approval = _latest_report_approval(client, prospect_id)
    path = (approval or {}).get("storage_path")
    if not approval or not path:
        raise OutreachError("report_not_found", "no approved report PDF for this prospect")
    url = _sign_report_url(client, path)
    if not url:
        raise OutreachError("report_not_found", "the stored report could not be signed")
    from config import settings

    return {
        "signed_url": url,
        "content_hash": approval.get("content_hash"),
        "approved_at": approval.get("created_at"),
        "expires_days": int(settings.outreach_report_url_ttl_days),
    }


def _llm_section(client: Any, orep: Any, prospect: dict[str, Any], region_name: str, *, keyword: str | None) -> dict[str, Any]:
    """The report's AI-visibility section for a prospect: find the ai_region matching its submarket
    name, read the latest AI scan per engine for that region × keyword, and hand the rows to the
    pure builder. Best-effort — before the ai_visibility migration is applied (or when no scan has
    run) it degrades to a not_scanned block rather than raising."""
    empty = orep.build_llm_section(
        engine_rows=[], prospect_name=prospect.get("name"),
        prospect_domain=orep.domain_of(prospect.get("website")),
        region=region_name, name_level=None,
    )
    market_id = prospect.get("market_id")
    if not market_id or not region_name:
        return empty
    try:
        regions = (
            client.table("ai_region")
            .select("id, name, name_level")
            .eq("market_id", market_id)
            .ilike("name", region_name)
            .limit(1)
            .execute()
            .data
            or []
        )
        if not regions:
            return empty
        region = regions[0]

        if keyword:
            krows = (
                client.table("keyword").select("id").eq("market_id", market_id)
                .ilike("term", keyword).limit(1).execute().data or []
            )
        else:
            krows = (
                client.table("keyword").select("id").eq("market_id", market_id)
                .order("is_primary", desc=True).limit(1).execute().data or []
            )
        if not krows:
            return empty
        keyword_id = krows[0]["id"]

        scan_rows = (
            client.table("ai_scan_result")
            .select("engine, present, named_businesses, reference_domains, raw_excerpt, scanned_at")
            .eq("ai_region_id", region["id"])
            .eq("keyword_id", keyword_id)
            .order("scanned_at", desc=True)
            .range(0, MAX_PAGE_SIZE - 1)
            .execute()
            .data
            or []
        )
        latest: dict[str, Any] = {}
        for row in scan_rows:
            latest.setdefault(row["engine"], row)
        return orep.build_llm_section(
            engine_rows=list(latest.values()),
            prospect_name=prospect.get("name"),
            prospect_domain=orep.domain_of(prospect.get("website")),
            region=region["name"],
            name_level=region.get("name_level"),
        )
    except Exception as exc:  # noqa: BLE001 — the report stands without the LLM section
        logger.warning("outreach_report_llm_unavailable", extra={"error": str(exc)})
        return empty


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
            "id, name, market_id, submarket_id, place_id, phone, website, address, category, rating, "
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

    # One memo per report render: prospect_justification and the sections below read the same
    # serp_result / prospect_tech_signal rows, and this database is a second Supabase project in
    # another region — paying for those round trips twice per report is pure waste.
    cache: dict[str, Any] = {}
    justification = prospect_justification(prospect_id, snapshot_id, cache)
    llm = _llm_section(client, orep, prospect, submarket_name, keyword=None)
    approval = _latest_report_approval(client, prospect_id)

    if not justification.get("measured"):
        organic = orep.not_scanned_section(
            orep.SIGNAL_ORGANIC, "The organic-search scan hasn't run for this prospect yet."
        )
        paid = orep.not_scanned_section(
            orep.SIGNAL_PAID, "The paid-placement scan hasn't run for this prospect yet."
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
            paid_section=paid,
            heatmap_available=False,
            approval=approval,
        )

    prov = justification["provenance"]
    snap_id = prov["snapshot_id"]
    keyword = prov["keyword"]
    live_points = prov["live_points"]

    # Recompute the LLM section against the snapshot's actual keyword + region (the early call used
    # the primary keyword for the not-measured path).
    llm = _llm_section(client, orep, prospect, prov.get("submarket") or submarket_name, keyword=keyword)

    # Organic-SERP signal (increment 2) + paid-placement signal (increment/slice A): the stored
    # capture for this snapshot, if the organic scan has run for it. The paid ads ride the SAME
    # capture (outreach HANDOFF §12 item 3a), so one read feeds both. Absent → each builder returns
    # a not_scanned block (never an empty table that would read as "no competitors / no ads").
    organic_summary = _organic_summary_for(client, snap_id, cache)
    organic = orep.build_organic_section(
        organic_summary,
        prospect_website=prospect.get("website"),
        max_competitors=settings.outreach_justification_max_competitors,
    )
    paid = orep.build_paid_section(
        organic_summary,
        prospect_website=prospect.get("website"),
        prospect_name=prospect.get("name"),
        max_competitors=settings.outreach_justification_max_competitors,
        tech=_latest_tech_signal(client, prospect_id, cache),
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
        paid_section=paid,
        heatmap_available=coverage is not None,
        approval=approval,
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


# --- Emit + touch (Phase 3 — the learning substrate) -------------------------------------------
#
# `emit_prospect` sends a prospect to the external outreach queue (n8n / Encharge) and writes the
# `outcome` row the Phase-4 model will one day fit against — the row that cannot be backfilled
# (scoring-spec §8). `record_touch` logs an actual contact attempt and rolls it up into the outcome.
#
# The teed-up 2026-08-06 question — whether emit bulk-backfills outcomes for pre-existing hand-picked
# leads — is resolved by these two functions together (DECISIONS 2026-08-09): an outcome is created
# by whichever of emit/first-touch comes first, both idempotent, and there is NO bulk backfill. A
# hand-picked lead becomes modellable the moment it is CONTACTED (a touch), not when it is promoted —
# recording an outcome for a prospect nobody called would inject a fabricated contact event into the
# substrate, which is worse than the model not seeing it.
#
# Nothing here spends money: a webhook POST to the agency's own automation tool is not a paid
# provider call (the "platform-api must not spend" invariant is about Outscraper/DataForSEO).


def _ensure_outcome(
    client: Any,
    prospect_id: str,
    *,
    selection_reason: str,
    sequence_version: str,
    touches_per_sequence: int,
    agg: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], bool]:
    """Create the outcome if missing (idempotent), or update its touch rollup if it exists.

    Never overwrites an existing `selection_reason` — the first writer (emit or first-touch) owns it.
    `agg` is the recomputed `{touch_count, first_contacted_at}` from `aggregate_touches`; when given,
    it is applied on both the create and the update path so the derived fields never drift. Returns
    `(row, created)`.

    Relies on the composite FK: a lead with (prospect_id, 'outbound_scan') must already exist, which
    both callers guarantee (emit via `promote_prospect`, touch because it read the lead first).
    """
    from services import outreach_emit as oe

    existing = (
        client.table("outcome").select("*").eq("prospect_id", prospect_id).limit(1).execute().data
        or []
    )
    if existing:
        row = existing[0]
        if agg is not None:
            updated = (
                client.table("outcome").update(agg).eq("prospect_id", prospect_id).execute().data
                or []
            )
            row = updated[0] if updated else {**row, **agg}
        return row, False

    insert = oe.build_outcome_row(
        prospect_id=prospect_id,
        selection_reason=selection_reason,
        sequence_version=sequence_version,
        touches_per_sequence=touches_per_sequence,
    )
    if agg is not None:
        insert.update(agg)
    try:
        written = client.table("outcome").insert(insert).execute().data or []
    except Exception:
        # Raced a concurrent create (the PK refused). The row exists, which is the outcome the caller
        # wanted — re-read and, if we brought a rollup, apply it.
        raced = (
            client.table("outcome").select("*").eq("prospect_id", prospect_id).limit(1).execute().data
            or []
        )
        if not raced:
            raise
        row = raced[0]
        if agg is not None:
            updated = (
                client.table("outcome").update(agg).eq("prospect_id", prospect_id).execute().data
                or []
            )
            row = updated[0] if updated else row
        return row, False
    return (written[0] if written else insert), True


def _post_emit_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    """POST the audit-ready queue row to the configured webhook. Best-effort — the DB write is the
    source of truth, so a delivery failure is reported for retry (re-emit is idempotent), never
    raised. An unset URL means the external queue is not wired yet: the outcome is still captured and
    the `touch` path records real contacts regardless."""
    from config import settings
    from services import outreach_emit as oe

    url = (settings.outreach_emit_webhook_url or "").strip()
    if not url:
        return {"configured": False, "delivered": False, "status": None, "reason": "webhook_not_configured"}

    import httpx

    try:
        resp = httpx.post(
            url,
            json=payload,
            headers=oe.build_webhook_headers(settings.outreach_emit_webhook_token),
            timeout=settings.outreach_emit_webhook_timeout_s,
        )
        ok = 200 <= resp.status_code < 300
        return {
            "configured": True,
            "delivered": ok,
            "status": resp.status_code,
            "reason": None if ok else "webhook_http_error",
        }
    except Exception as exc:  # noqa: BLE001 — a webhook hiccup must not lose the captured outcome
        logger.warning("outreach_emit_webhook_failed", extra={"error": str(exc)})
        return {
            "configured": True,
            "delivered": False,
            "status": None,
            "reason": "webhook_request_failed",
            "error": str(exc),
        }


def emit_prospect(
    prospect_id: str,
    actor_id: str,
    *,
    selection_reason: str | None = None,
    channel: str | None = None,
    snapshot_id: str | None = None,
) -> dict[str, Any]:
    """Emit a prospect to the outbound queue: write the lead + outcome and post the webhook.

    Requires a rolled-up scan (`prospect_justification.measured`) — there is no honest queue row for a
    prospect whose invisibility was never measured, and emitting an empty pitch would manufacture the
    picture the module guards against. The cadence / evidence-age emit gates (PRD §183/§198) are the
    Phase-4 selector's and are deferred (ISSUES I-101); v1 emit is manual and bootstrap-gated.
    """
    from config import settings
    from services import outreach_emit as oe

    try:
        sel = oe.resolve_selection_reason(
            selection_reason, default=settings.outreach_default_selection_reason
        )
        chan = oe.validate_channel(channel or settings.outreach_emit_channel_default)
    except ValueError as e:
        raise OutreachError("invalid_emit_request", str(e)) from e

    # The pitch + evidence. Reused verbatim as the payload's primary_pitch so the queue row and the
    # on-screen call hook can never disagree.
    justification = prospect_justification(prospect_id, snapshot_id)
    if not justification.get("measured"):
        raise OutreachError(
            "not_measured", "cannot emit a prospect whose area has no rolled-up scan"
        )

    client = get_outreach_client()
    rows = (
        client.table("prospect")
        .select("id, name, place_id, category, phone, website, submarket_id")
        .eq("id", prospect_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise OutreachError("prospect_not_found", "no such prospect")
    prospect = rows[0]

    # Ensure the lead exists (idempotent — a hand-picked lead is reused, a fresh one created). Same
    # source an emit writes under, so the unique (prospect_id, source) dedupes hand-picks and emits.
    lead = promote_prospect(prospect_id, actor_id)

    contacts = {
        "phone": prospect.get("phone"),
        "website": prospect.get("website"),
        "email": lead.get("email"),
    }

    ph_rows = (
        client.table("v_prospect_placeholder_score")
        .select("*")
        .eq("prospect_id", prospect_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    placeholder = ph_rows[0] if ph_rows else None

    payload = oe.build_emit_payload(
        prospect=prospect,
        channel=chan,
        contacts=contacts,
        justification=justification,
        placeholder=placeholder,
        selection_reason=sel,
    )

    # Write the outcome stub (touch_count 0, first_contacted_at null — emit enqueues, a touch
    # contacts). Idempotent: a re-emit keeps the original selection_reason.
    outcome, created = _ensure_outcome(
        client,
        prospect_id,
        selection_reason=sel,
        sequence_version=settings.outreach_sequence_version,
        touches_per_sequence=settings.outreach_touches_per_sequence,
    )

    delivery = _post_emit_webhook(payload)

    # Append-only audit trail (a system row, not a contact — a contact is a touch). Best-effort.
    try:
        client.table("lead_activity").insert(
            {
                "lead_id": lead["id"],
                "kind": "system",
                "body": "Emitted to outreach queue",
                "actor_id": actor_id,
                "metadata": {
                    "event": "emitted",
                    "channel": chan,
                    "selection_reason": sel,
                    "delivered": delivery.get("delivered"),
                    "webhook_status": delivery.get("status"),
                    "webhook_configured": delivery.get("configured"),
                },
            }
        ).execute()
    except Exception as exc:  # noqa: BLE001
        logger.warning("outreach_emit_activity_failed", extra={"error": str(exc)})

    return {
        "prospect_id": prospect_id,
        "lead": lead,
        "outcome": outcome,
        "payload": payload,
        "delivery": delivery,
        "already_emitted": not created,
    }


def record_touch(
    lead_id: str,
    actor_id: str,
    *,
    channel: str,
    sequence_version: str | None = None,
    touch_number: int | None = None,
    disposition: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Record one contact attempt against a lead and roll it up into the outcome.

    A touch is authoritative for "a contact attempt happened" (CLAUDE.md invariant). For an
    `outbound_scan` lead it creates the outcome if missing (this is how a hand-picked lead becomes
    modellable — at first contact, not at promotion) and recomputes `touch_count` /
    `first_contacted_at` from all its touches. A touch on an inbound/referral lead is recorded but
    never rolls up (the outbound-only rule).
    """
    from config import settings
    from services import outreach_emit as oe

    try:
        chan = oe.validate_channel(channel)
    except ValueError as e:
        raise OutreachError("invalid_channel", str(e)) from e

    client = get_outreach_client()
    leads = (
        client.table("lead")
        .select("id, source, prospect_id, deleted_at")
        .eq("id", lead_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not leads:
        raise OutreachError("lead_not_found", "no such lead")
    lead = leads[0]

    seq = sequence_version if sequence_version is not None else settings.outreach_sequence_version
    touch_row = oe.build_touch_row(
        lead_id=lead_id,
        channel=chan,
        sequence_version=seq,
        touch_number=touch_number,
        disposition=disposition,
        note=note,
        actor_id=actor_id,
    )
    written = client.table("touch").insert(touch_row).execute().data or []
    if not written:
        raise OutreachError("touch_not_created", "the touch was not written")
    touch = written[0]

    # A call note is human commentary ON a call, and only a call_note may carry a touch_id (the DB
    # check). Email sends are recorded by the touch row itself — there is no 'email_sent' activity
    # kind, by design (touch is authoritative, lead_activity is commentary).
    if chan == "phone" and note and note.strip():
        try:
            client.table("lead_activity").insert(
                {
                    "lead_id": lead_id,
                    "kind": "call_note",
                    "body": note.strip(),
                    "actor_id": actor_id,
                    "touch_id": touch["id"],
                }
            ).execute()
        except Exception as exc:  # noqa: BLE001
            logger.warning("outreach_touch_call_note_failed", extra={"error": str(exc)})

    outcome = None
    if lead.get("source") == "outbound_scan" and lead.get("prospect_id"):
        touches = (
            client.table("touch")
            .select("touched_at")
            .eq("lead_id", lead_id)
            .order("touched_at")
            .range(0, MAX_PAGE_SIZE - 1)
            .execute()
            .data
            or []
        )
        agg = oe.aggregate_touches(touches)
        outcome, _ = _ensure_outcome(
            client,
            lead["prospect_id"],
            selection_reason=settings.outreach_default_selection_reason,
            sequence_version=settings.outreach_sequence_version,
            touches_per_sequence=settings.outreach_touches_per_sequence,
            agg=agg,
        )

    return {"touch": touch, "outcome": outcome}


def get_outcome(prospect_id: str) -> dict[str, Any]:
    """The outcome row for a prospect, or `{outcome: None}` — the modelling substrate is write-mostly,
    but the CRM reads it to show contact/reply state."""
    rows = (
        get_outreach_client()
        .table("outcome")
        .select("*")
        .eq("prospect_id", prospect_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    return {"outcome": rows[0] if rows else None}


def list_touches(lead_id: str, limit: int | None = None, offset: int | None = None) -> dict[str, Any]:
    """A page of a lead's contact attempts, newest first — the CRM's contact history."""
    size, start = clamp_page(limit, offset)
    response = (
        get_outreach_client()
        .table("touch")
        .select("*", count="exact")
        .eq("lead_id", lead_id)
        .order("touched_at", desc=True)
        .range(start, start + size - 1)
        .execute()
    )
    return {
        "touches": response.data or [],
        "total": response.count or 0,
        "limit": size,
        "offset": start,
    }


# --- Lead enrichment (contact names / phones / emails) -----------------------------------------
#
# On-demand enrichment of a selected prospect (or a selected set / all) with contact names, phone
# numbers and emails via Outscraper. This surface WRITES A SIGNED ORDER (`enrichment_request`) and
# NOTHING MORE — the money moves in the outreach job's `tick`, which drains the order and bills
# Outscraper. The order is the confirmation, exactly like a scan order (outreach DECISIONS.md
# 2026-08-06). Two spend guards sit in front of it: a FREE preflight cost estimate the UI shows, and
# a per-user daily budget guard (mirroring LeadOff's leadoff_spend check) that uses the order rows
# themselves as the ledger. This is DELIBERATELY separate from the mass ingest, whose base-tier
# invariant it never touches.

ENRICHMENT_REQUEST_ACTIVE_STATUSES: tuple[str, ...] = ("pending", "running")
# The enrichment statuses that mean "already billed, answer is durable" — the drain skips these, and
# the estimate/budget count only prospects NOT in one of them.
_ENRICH_DONE_STATUSES: tuple[str, ...] = ("enriched", "no_contacts")


def enrich_enrichments() -> list[str]:
    """The configured enricher set, parsed. A guess to confirm via `probe-enrich`."""
    from config import settings

    return [e.strip() for e in (settings.outreach_enrich_enrichments or "").split(",") if e.strip()]


def enrich_cost_cents(billable: int, rate_cents: int) -> int:
    """Estimated cost of enriching `billable` places at `rate_cents` each. Pure."""
    return max(0, billable) * max(0, rate_cents)


def enrich_spent_today_cents(orders: list[dict[str, Any]]) -> int:
    """Sum of est_cost_cents across a user's orders placed today — the per-user ledger. Pure."""
    return sum(int(o.get("est_cost_cents") or 0) for o in orders)


def enrich_budget_denial(spent_cents: int, add_cents: int, budget_usd: float) -> str | None:
    """Why placing this order would breach the daily budget, or None. Pure, so the gate is testable
    without a database — mirrors LeadOff's check_budget shape (a refusal names the numbers)."""
    budget_cents = int(round(budget_usd * 100))
    if spent_cents + add_cents > budget_cents:
        return (
            f"daily enrichment budget ${budget_usd:.2f} would be exceeded — "
            f"${spent_cents / 100:.2f} spent today, this order is ${add_cents / 100:.2f}"
        )
    return None


def validate_enrich_selection(prospect_ids: list[str], cap: int) -> list[str]:
    """De-dupe and bound a selection. Pure. Refuses an empty selection (nothing to enrich) and one
    past the per-order cap (a bigger 'select all' is split into several orders by the UI)."""
    ids = [p for p in dict.fromkeys(prospect_ids) if p]
    if not ids:
        raise OutreachError("empty_selection", "select at least one prospect to enrich")
    if len(ids) > cap:
        raise OutreachError(
            "selection_too_large",
            f"a single enrichment order is capped at {cap} prospects (got {len(ids)}); "
            "split a larger selection into several orders",
        )
    return ids


def _enrich_billable(client: Any, prospect_ids: list[str]) -> dict[str, Any]:
    """How many of a selection would actually be billed: prospects that exist, carry a place_id, and
    are not already enriched. Reads `prospect` + `prospect_enrichment`, chunked under the 1000-row
    cap. Returns counts the estimate and the order both use."""
    existing: dict[str, dict[str, Any]] = {}
    for start in range(0, len(prospect_ids), 500):
        chunk = prospect_ids[start : start + 500]
        if not chunk:
            continue
        for row in (
            client.table("prospect")
            .select("id, place_id")
            .in_("id", chunk)
            .execute()
            .data
            or []
        ):
            existing[row["id"]] = row
    done: set[str] = set()
    for start in range(0, len(prospect_ids), 500):
        chunk = prospect_ids[start : start + 500]
        if not chunk:
            continue
        for row in (
            client.table("prospect_enrichment")
            .select("prospect_id, status")
            .in_("prospect_id", chunk)
            .in_("status", list(_ENRICH_DONE_STATUSES))
            .execute()
            .data
            or []
        ):
            done.add(row["prospect_id"])
    billable = [
        pid
        for pid in prospect_ids
        if pid in existing and existing[pid].get("place_id") and pid not in done
    ]
    return {
        "selected": len(prospect_ids),
        "already_enriched": sum(1 for pid in prospect_ids if pid in done),
        "unknown": sum(1 for pid in prospect_ids if pid not in existing),
        "billable": len(billable),
    }


def _enrich_spent_today(client: Any, user_id: str) -> int:
    """A user's est_cost_cents summed over orders they placed today (UTC). The ledger read."""
    from datetime import datetime, timezone

    day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    rows = (
        client.table("enrichment_request")
        .select("est_cost_cents")
        .eq("requested_by", user_id)
        .gte("created_at", day_start.isoformat())
        .execute()
        .data
        or []
    )
    return enrich_spent_today_cents(rows)


def estimate_enrichment(prospect_ids: list[str], user_id: str) -> dict[str, Any]:
    """Free preflight: what a selection would cost, and whether the daily budget allows it. Spends
    nothing — the UI shows this before the admin confirms."""
    from config import settings

    ids = validate_enrich_selection(prospect_ids, settings.outreach_enrich_max_places_per_order)
    client = get_outreach_client()
    counts = _enrich_billable(client, ids)
    est_cents = enrich_cost_cents(counts["billable"], settings.outreach_enrich_cost_per_place_cents)
    spent = _enrich_spent_today(client, user_id)
    denial = enrich_budget_denial(spent, est_cents, settings.outreach_enrich_daily_budget_usd)
    return {
        **counts,
        "est_cost_cents": est_cents,
        "est_cost_usd": round(est_cents / 100, 2),
        "spent_today_cents": spent,
        "daily_budget_usd": settings.outreach_enrich_daily_budget_usd,
        "allowed": denial is None,
        "denial": denial,
    }


def create_enrichment_request(
    *, prospect_ids: list[str], note: str | None, actor_id: str
) -> dict[str, Any]:
    """Place a signed enrichment order. Admin-gated at the router — this row authorizes billed
    enrichment on the next tick. Validates the selection, checks the per-user daily budget against
    the estimate, records the estimate on the order (the row is the ledger), and inserts. platform-api
    never spends: the order is drained by the outreach job. A selection that is entirely already
    enriched is refused (nothing to bill) so a click that would do nothing says so."""
    from config import settings

    ids = validate_enrich_selection(prospect_ids, settings.outreach_enrich_max_places_per_order)
    client = get_outreach_client()
    counts = _enrich_billable(client, ids)
    if counts["billable"] == 0:
        raise OutreachError(
            "nothing_to_enrich",
            "every selected prospect is already enriched (or has no place_id) — nothing to bill",
        )
    est_cents = enrich_cost_cents(counts["billable"], settings.outreach_enrich_cost_per_place_cents)
    spent = _enrich_spent_today(client, actor_id)
    denial = enrich_budget_denial(spent, est_cents, settings.outreach_enrich_daily_budget_usd)
    if denial:
        raise OutreachError("enrich_budget_exceeded", denial)

    row = {
        "prospect_ids": ids,
        "enrichments": enrich_enrichments(),
        "requested_by": actor_id,
        "est_cost_cents": est_cents,
        "requested_count": len(ids),
        "note": (note or "").strip() or None,
    }
    written = client.table("enrichment_request").insert(row).execute().data or []
    if not written:
        raise OutreachError("enrichment_request_not_created", "the order was not written")
    order = written[0]
    order["estimate"] = {**counts, "est_cost_cents": est_cents}
    return order


def list_enrichment_requests(
    *, status: str | None = None, limit: int | None = None, offset: int | None = None
) -> dict[str, Any]:
    """Enrichment orders, newest first — the queue/progress view."""
    size, start = clamp_page(limit, offset)
    query = (
        get_outreach_client()
        .table("enrichment_request")
        .select("*", count="exact")
        .order("created_at", desc=True)
        .range(start, start + size - 1)
    )
    if status:
        query = query.eq("status", status)
    response = query.execute()
    return {
        "enrichment_requests": response.data or [],
        "total": response.count or 0,
        "limit": size,
        "offset": start,
    }


def enrichment_request_detail(request_id: str) -> dict[str, Any]:
    """One order plus a small progress read (the counters live on the row itself)."""
    rows = (
        get_outreach_client()
        .table("enrichment_request")
        .select("*")
        .eq("id", request_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise OutreachError("enrichment_request_not_found", "no such order")
    order = rows[0]
    done = order["enriched_count"] + order["skipped_count"] + order["failed_count"]
    order["progress"] = {
        "requested": order["requested_count"],
        "done": done,
        "enriched": order["enriched_count"],
        "skipped": order["skipped_count"],
        "failed": order["failed_count"],
        "contacts": order["contact_count"],
    }
    return {"enrichment_request": order}


def cancel_enrichment_request(request_id: str, actor_id: str) -> dict[str, Any]:
    """Withdraw a PENDING order. Conditional on status, like the scan-order cancel: one the tick has
    claimed is already enriching (real money) and resolves on its own."""
    from datetime import datetime, timezone

    client = get_outreach_client()
    hit = (
        client.table("enrichment_request")
        .update({"status": "cancelled", "finished_at": datetime.now(timezone.utc).isoformat()})
        .eq("id", request_id)
        .eq("status", "pending")
        .execute()
        .data
        or []
    )
    if hit:
        return {"enrichment_request": hit[0]}
    existing = (
        client.table("enrichment_request").select("id, status").eq("id", request_id).limit(1)
        .execute().data
    )
    if not existing:
        raise OutreachError("enrichment_request_not_found", "no such order")
    raise OutreachError(
        "enrichment_request_not_cancellable",
        f"order is {existing[0]['status']!r}; only a pending order can be withdrawn",
    )


def list_prospect_contacts(prospect_id: str) -> dict[str, Any]:
    """A prospect's enriched contacts + its enrichment status. Read-only; the CRM lead drawer and the
    coverage table both read this to show names/phones/emails. Bounded by construction — a business
    returns a handful of contacts, far under the 1000-row cap."""
    client = get_outreach_client()
    contacts = (
        client.table("prospect_contact")
        .select(
            "id, place_id, contact_index, full_name, first_name, last_name, title, name_for_emails, "
            "email, email_status, email_is_generic, phone, phone_type, phone_carrier, "
            "source, enriched_at"
        )
        .eq("prospect_id", prospect_id)
        .order("contact_index")
        .range(0, MAX_PAGE_SIZE - 1)
        .execute()
        .data
        or []
    )
    status_rows = (
        client.table("prospect_enrichment")
        .select("status, contact_count, enrichments, error, enriched_at")
        .eq("prospect_id", prospect_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    prospect_rows = (
        client.table("prospect")
        .select("website")
        .eq("id", prospect_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    return {
        "prospect_id": prospect_id,
        "enrichment": status_rows[0] if status_rows else None,
        "website": prospect_rows[0].get("website") if prospect_rows else None,
        "contacts": contacts,
    }


_CONTACT_COLUMNS = (
    "prospect_id, id, place_id, contact_index, full_name, first_name, last_name, title, "
    "name_for_emails, email, email_status, email_is_generic, phone, phone_type, phone_carrier, "
    "source, enriched_at"
)


def list_prospect_contacts_batch(prospect_ids: list[str]) -> dict[str, Any]:
    """Contacts + enrichment status + website for a SET of prospects in one read — the coverage
    table's batch, so a 200-row table costs a few queries instead of 200 (no N+1). Reads are chunked
    under the 1000-row cap. Every existing requested prospect appears in `by_prospect` carrying its
    `website` (so the website shows for every row, enriched or not); `enrichment`/`contacts` are
    filled where present. Bounded: the caller passes the page it is showing."""
    ids = [p for p in dict.fromkeys(prospect_ids) if p]
    if not ids:
        return {"by_prospect": {}}
    client = get_outreach_client()
    contacts_by: dict[str, list[dict[str, Any]]] = {}
    enrichment_by: dict[str, dict[str, Any]] = {}
    website_by: dict[str, str | None] = {}
    for start in range(0, len(ids), 200):
        chunk = ids[start : start + 200]
        for row in (
            client.table("prospect_contact")
            .select(_CONTACT_COLUMNS)
            .in_("prospect_id", chunk)
            .order("contact_index")
            .execute()
            .data
            or []
        ):
            contacts_by.setdefault(row["prospect_id"], []).append(row)
        for row in (
            client.table("prospect_enrichment")
            .select("prospect_id, status, contact_count, enrichments, error, enriched_at")
            .in_("prospect_id", chunk)
            .execute()
            .data
            or []
        ):
            enrichment_by[row["prospect_id"]] = row
        for row in (
            client.table("prospect").select("id, website").in_("id", chunk).execute().data or []
        ):
            website_by[row["id"]] = row.get("website")
    by_prospect: dict[str, Any] = {}
    # Key on every EXISTING prospect (website_by), plus any with contacts/enrichment, so a website
    # shows for every row even before it is enriched.
    for pid in set(website_by) | set(contacts_by) | set(enrichment_by):
        # Sort each prospect's contacts by contact_index (the .order above is a global sort; grouping
        # preserves it, but be explicit so a provider quirk can't reorder a person's rows).
        rows = sorted(contacts_by.get(pid, []), key=lambda r: r.get("contact_index") or 0)
        by_prospect[pid] = {
            "enrichment": enrichment_by.get(pid),
            "website": website_by.get(pid),
            "contacts": rows,
        }
    return {"by_prospect": by_prospect}
