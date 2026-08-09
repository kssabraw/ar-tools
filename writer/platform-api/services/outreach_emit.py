"""Pure builders for Phase 3 emit + touch — the outbound queue and the contact-attempt record.

No network, no database. The service layer (`services/outreach`) does the I/O and hands these
functions plain dicts, exactly like `outreach_report`/`outreach_justification`. Keeping the payload
shape, the outcome/touch row shapes, and the touch rollup here makes them deterministic and testable
from hand-built inputs — the same discipline every other outreach render follows.

The two rules this module encodes:

- **The emit payload is an audit-ready QUEUE, never a generated asset** (outreach PRD §C). It carries
  identity, channel, contacts, the placeholder score + empty `score_factors` (the Phase-4 model
  fills those), the call-hook as `primary_pitch`, and evidence references — nothing a prospect sees.
  Asset generation stays behind the approval gate; a test pins that this payload has no rendered
  asset and no PDF trigger.

- **`selection_reason` is recorded on 100% of contacts** (scoring-spec §7, §10). The allowlist adds
  `manual` to the spec's `{thompson, random_control}` for the pre-Phase-4 era: a hand-picked contact
  is neither a Thompson draw nor the random-control hold-out, and labelling it `random_control` would
  poison the one unbiased baseline that bucket measures (ISSUES I-102).
"""
from __future__ import annotations

from typing import Any, Optional

EMIT_PAYLOAD_VERSION = "1.0"

# scoring-spec §7 names {thompson, random_control}; `manual` is the honest pre-Phase-4 default
# (ISSUES I-102). The `outcome` DDL leaves selection_reason unconstrained text, so this allowlist is
# the application's guard and can tighten at Phase 4 without a migration.
SELECTION_REASONS = ("thompson", "random_control", "manual")

CHANNELS = ("phone", "email")


def resolve_selection_reason(value: Optional[str], *, default: str) -> str:
    """Validate a `selection_reason`, falling back to `default` when unset.

    Raises ValueError on an unknown value (the service layer maps it to a named 422). `default` is
    itself validated, so a misconfigured default fails loudly rather than writing an unmodellable
    value into the substrate.
    """
    chosen = (value or "").strip() or (default or "").strip()
    if chosen not in SELECTION_REASONS:
        raise ValueError(
            f"selection_reason must be one of {', '.join(SELECTION_REASONS)}"
        )
    return chosen


def validate_channel(value: Optional[str]) -> str:
    """Validate a contact channel. Phone and email are never pooled in one model fit (scoring-spec
    §8), so the channel is a required, checked property of every contact."""
    chosen = (value or "").strip()
    if chosen not in CHANNELS:
        raise ValueError(f"channel must be one of {', '.join(CHANNELS)}")
    return chosen


def build_outcome_row(
    *,
    prospect_id: str,
    selection_reason: str,
    sequence_version: str,
    touches_per_sequence: int,
) -> dict[str, Any]:
    """The insert payload for a fresh outcome.

    `touch_count` starts 0 and `first_contacted_at` is omitted (stays null): a touch is authoritative
    for "a contact attempt happened", so emit — which only enqueues — never claims a contact. The
    `lead_source` is fixed to 'outbound_scan'; the DB check and composite FK enforce it, this just
    supplies it (the column is not-null with that default, but writing it explicitly documents intent).
    """
    return {
        "prospect_id": prospect_id,
        "lead_source": "outbound_scan",
        "selection_reason": selection_reason,
        "sequence_version": sequence_version,
        "touches_per_sequence_at_send": int(touches_per_sequence),
        "touch_count": 0,
    }


def build_touch_row(
    *,
    lead_id: str,
    channel: str,
    sequence_version: Optional[str] = None,
    touch_number: Optional[int] = None,
    disposition: Optional[str] = None,
    note: Optional[str] = None,
    actor_id: Optional[str] = None,
) -> dict[str, Any]:
    """The insert payload for one contact attempt. Only non-empty optional fields are included so the
    row carries what was actually recorded rather than a wall of nulls."""
    row: dict[str, Any] = {"lead_id": lead_id, "channel": validate_channel(channel)}
    if sequence_version and sequence_version.strip():
        row["sequence_version"] = sequence_version.strip()
    if touch_number is not None:
        row["touch_number"] = int(touch_number)
    if disposition and disposition.strip():
        row["disposition"] = disposition.strip()
    if note and note.strip():
        row["note"] = note.strip()
    if actor_id:
        row["actor_id"] = actor_id
    return row


def aggregate_touches(touch_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Recompute the outcome's touch rollup from the lead's touch rows.

    Recompute-on-write (never an increment that can drift): `touch_count` is the count of touches and
    `first_contacted_at` is the EARLIEST `touched_at`. This is what keeps the two derived fields
    honest against the touch rows they summarise — the same "derive, don't drift" rule the coverage
    rollup follows.
    """
    times = sorted(t["touched_at"] for t in touch_rows if t.get("touched_at"))
    return {
        "touch_count": len(touch_rows),
        "first_contacted_at": times[0] if times else None,
    }


def build_score_block(placeholder: Optional[dict[str, Any]]) -> dict[str, Any]:
    """The emit payload's score section.

    There is no fitted score yet (`prospect_score` is the Phase-4 model's table and stays empty —
    ISSUES I-082), so this carries the deterministic PLACEHOLDER (coverage deficit) explicitly
    labelled, never dressed up as a model output. `score_factors` is empty; the Phase-4 model fills
    it. Labelling `model: 'placeholder'` is what stops a downstream reader treating the deficit as a
    reply-probability score.
    """
    if not placeholder:
        return {"model": "placeholder", "available": False}
    return {
        "model": "placeholder",
        "available": True,
        "coverage_pct": placeholder.get("coverage_pct"),
        "coverage_deficit": placeholder.get("coverage_deficit"),
        "best_rank": placeholder.get("best_rank"),
        "centroid_dist_at_loss": placeholder.get("centroid_dist_at_loss"),
        "keywords_measured": placeholder.get("keywords_measured"),
        "keywords_present": placeholder.get("keywords_present"),
    }


def build_emit_payload(
    *,
    prospect: dict[str, Any],
    channel: str,
    contacts: dict[str, Any],
    justification: dict[str, Any],
    placeholder: Optional[dict[str, Any]],
    selection_reason: str,
) -> dict[str, Any]:
    """Assemble the audit-ready QUEUE row posted to the emit webhook (PRD §C).

    Deterministic and fact-grounded. Reuses the justification's call hook as `primary_pitch` and its
    provenance as `evidence`, so the queue row and the on-screen hook can never disagree. Carries NO
    generated asset — asset generation is not triggered by emission (a hard invariant).
    """
    provenance = justification.get("provenance") or {}
    return {
        "schema_version": EMIT_PAYLOAD_VERSION,
        "prospect": {
            "id": prospect.get("id"),
            "name": prospect.get("name"),
            "place_id": prospect.get("place_id"),
            "category": prospect.get("category"),
            "submarket": provenance.get("submarket"),
        },
        "channel": channel,
        "selection_reason": selection_reason,
        "contacts": {
            "phone": contacts.get("phone"),
            "email": contacts.get("email"),
            "website": contacts.get("website"),
        },
        "score": build_score_block(placeholder),
        # The Phase-4 model owns score_factors (scoring-spec §8); empty until it exists.
        "score_factors": [],
        "primary_pitch": {
            "hook": justification.get("hook"),
            "element": justification.get("hook_element"),
            "available_elements": justification.get("available_elements") or [],
            "talking_points": justification.get("talking_points") or [],
        },
        # No case studies in the target verticals yet (ISSUES I-012); a delta needs >=2 snapshots
        # (the same seam the heatmap delta leaves open). Both explicit, never fabricated.
        "matched_case_study": None,
        "deltas": [],
        "deltas_note": "single scan — deltas require at least two snapshots",
        "evidence": {
            "snapshot_id": provenance.get("snapshot_id"),
            "submarket": provenance.get("submarket"),
            "keyword": provenance.get("keyword"),
            "scanned_at": provenance.get("scanned_at"),
            "geometry_version": provenance.get("geometry_version"),
            "live_points": provenance.get("live_points"),
            "caveats": justification.get("caveats") or [],
        },
    }


def build_webhook_headers(token: Optional[str]) -> dict[str, str]:
    """Headers for the emit POST. JSON always; a bearer only when a token is configured (n8n /
    Encharge both accept a plain Authorization header)."""
    headers = {"Content-Type": "application/json"}
    if token and token.strip():
        headers["Authorization"] = f"Bearer {token.strip()}"
    return headers
