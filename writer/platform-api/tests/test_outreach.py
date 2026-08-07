"""Pure-logic tests for the outreach module's suite surface.

No network and no database, matching the rest of `tests/`. What is worth testing here is the
validation that stands between an operator and a table whose whole value is that it is honest:
the couplings the database also enforces (so a bad request comes back named rather than as a
constraint string), and the two rules that exist because the alternative is a lie in the data —
`survived` meaning evaluated-and-not-excluded, and stage history being unforgeable.
"""
import pytest

from services import outreach as svc
from services.outreach import OutreachError


# --- clamp_page ---------------------------------------------------------------------------------


def test_clamp_page_defaults_and_ceiling():
    assert svc.clamp_page(None, None) == (svc.DEFAULT_PAGE_SIZE, 0)
    assert svc.clamp_page(10, 20) == (10, 20)
    # A caller asking for everything gets the ceiling rather than an error — refusing just teaches
    # them to loop, which is the same read with more round trips.
    assert svc.clamp_page(10_000, 0) == (svc.MAX_PAGE_SIZE, 0)


def test_clamp_page_rejects_nonsense_without_erroring():
    assert svc.clamp_page(0, -5) == (svc.DEFAULT_PAGE_SIZE, 0)
    assert svc.clamp_page(-1, None) == (svc.DEFAULT_PAGE_SIZE, 0)


# --- validate_lead_write ------------------------------------------------------------------------


def test_create_requires_a_known_source():
    with pytest.raises(OutreachError) as e:
        svc.validate_lead_write({"source": "cold_call", "company_name": "Acme"}, creating=True)
    assert e.value.code == "invalid_source"


def test_manual_lead_is_creatable():
    """The entire reason the CRM track runs parallel to Phase 1 — a partner typing in a lead
    before the scanner exists. PR #534 found this impossible under the first schema."""
    fields = svc.validate_lead_write(
        {"source": "manual", "company_name": "Acme Plumbing"}, creating=True
    )
    assert fields["source"] == "manual"


def test_outbound_scan_without_a_prospect_is_refused():
    """Grid results join on place_id via the prospect. An outbound lead without one can never be
    scored or audited, so it must not be creatable in the first place."""
    with pytest.raises(OutreachError) as e:
        svc.validate_lead_write(
            {"source": "outbound_scan", "company_name": "Acme"}, creating=True
        )
    assert e.value.code == "outbound_requires_prospect"


def test_lead_with_neither_prospect_nor_company_is_refused():
    with pytest.raises(OutreachError) as e:
        svc.validate_lead_write({"source": "referral", "email": "a@b.com"}, creating=True)
    assert e.value.code == "non_prospect_needs_identity"


def test_lost_without_a_reason_is_refused():
    """crm-layer-spec §5: the lost reason is the highest-value field in the layer and is
    unrecoverable after the moment of loss."""
    with pytest.raises(OutreachError) as e:
        svc.validate_lead_write({"stage": "lost", "lost_reason": None}, creating=False)
    assert e.value.code == "lost_requires_reason"


def test_lost_with_a_reason_passes():
    fields = svc.validate_lead_write(
        {"stage": "lost", "lost_reason": "went_elsewhere"}, creating=False
    )
    assert fields["stage"] == "lost"


def test_moving_to_lost_without_touching_lost_reason_is_left_to_the_database():
    """The lead may already carry one. Guessing here would refuse a legal transition; the DB's
    `lost_requires_reason` sees the merged row and is the only place that can judge it."""
    assert svc.validate_lead_write({"stage": "lost"}, creating=False) == {"stage": "lost"}


def test_unknown_lost_reason_is_refused():
    with pytest.raises(OutreachError) as e:
        svc.validate_lead_write({"lost_reason": "vibes"}, creating=False)
    assert e.value.code == "invalid_lost_reason"


def test_collapsed_stages_are_not_writable():
    """§8a collapsed `qualified` and `proposal` into `in_conversation` so lead history stays
    comparable. Accepting the old tokens would reintroduce two vocabularies in one analysis."""
    for stage in ("qualified", "proposal"):
        with pytest.raises(OutreachError) as e:
            svc.validate_lead_write({"stage": stage}, creating=False)
        assert e.value.code == "invalid_stage"


def test_immutable_fields_are_rejected_rather_than_ignored():
    """Silently dropping `prospect_id` would report success on an update that changed nothing —
    the same class of failure as the append-only grant that affected zero rows (PR #534)."""
    with pytest.raises(OutreachError) as e:
        svc.validate_lead_write({"prospect_id": "abc"}, creating=False)
    assert e.value.code == "unknown_field"

    with pytest.raises(OutreachError) as e:
        svc.validate_lead_write({"source": "manual"}, creating=False)
    assert e.value.code == "unknown_field"


def test_explicit_null_is_preserved_so_a_field_can_be_cleared():
    fields = svc.validate_lead_write({"owner_id": None, "next_action_due": None}, creating=False)
    assert fields == {"owner_id": None, "next_action_due": None}


def test_suppression_columns_are_not_writable():
    """Suppression state is stamped by the `lead_suppression_check` trigger. Letting a caller set
    it by hand would make the flag mean two different things."""
    with pytest.raises(OutreachError):
        svc.validate_lead_write({"suppressed_at": None}, creating=False)


# --- validate_activity --------------------------------------------------------------------------


def test_stage_change_rows_cannot_be_forged():
    """These come from the trigger, which sees the real before/after. Accepting them over the API
    would let a human write stage history that never happened into an append-only table."""
    for kind in ("stage_change", "system"):
        with pytest.raises(OutreachError) as e:
            svc.validate_activity(kind, "moved it along", None)
        assert e.value.code == "trigger_owned_kind"


def test_send_and_dial_are_not_activity_kinds():
    """`touch` is authoritative for 'a contact attempt happened'; lead_activity carries only the
    commentary about it (crm-layer-spec §3). Pooling them would double-count every send."""
    for kind in ("email_sent", "call"):
        with pytest.raises(OutreachError) as e:
            svc.validate_activity(kind, "rang them", None)
        assert e.value.code == "invalid_kind"


def test_touch_id_only_attaches_to_a_call_note():
    with pytest.raises(OutreachError) as e:
        svc.validate_activity("note", "some thought", 12)
    assert e.value.code == "touch_requires_call_note"
    svc.validate_activity("call_note", "spoke to the owner", 12)


def test_empty_activity_body_is_refused():
    with pytest.raises(OutreachError) as e:
        svc.validate_activity("note", "   ", None)
    assert e.value.code == "empty_body"


# --- apply_prospect_status ----------------------------------------------------------------------


class _FakeQuery:
    """Records the filters applied, so the status mapping is assertable without a database."""

    def __init__(self):
        self.filters: list[tuple[str, object]] = []

    def eq(self, column, value):
        self.filters.append((column, value))
        return self


def test_survived_means_evaluated_and_not_excluded():
    """Not merely 'not excluded'. A prospect the filter never reached is not a survivor — that
    conflation is how a run that filtered 1,000 of 1,388 rows would report 388 phantom survivors
    (outreach ISSUES I-036)."""
    q = svc.apply_prospect_status(_FakeQuery(), "survived")
    assert ("evaluated", True) in q.filters
    assert ("excluded", False) in q.filters


def test_flagged_reads_franchise_status_not_exclusion():
    """A franchise match flags and never excludes (DECISIONS.md), which is also what keeps the
    −87 franchise coefficient able to fire at all."""
    q = svc.apply_prospect_status(_FakeQuery(), "flagged")
    assert q.filters == [("franchise_status", "flagged")]


def test_all_applies_no_filter():
    assert svc.apply_prospect_status(_FakeQuery(), "all").filters == []


def test_unknown_status_is_refused():
    with pytest.raises(OutreachError) as e:
        svc.apply_prospect_status(_FakeQuery(), "good_ones")
    assert e.value.code == "invalid_status"


# --- vocabularies -------------------------------------------------------------------------------


def _service_source() -> str:
    import pathlib

    return pathlib.Path(svc.__file__).read_text()


def test_every_counted_read_is_also_ranged():
    """PostgREST caps an unbounded select() at 1,000 rows with no error, no header and nothing a
    caller notices — that is what left 215 prospects silently unfiltered in the first LA run
    (outreach ISSUES I-036). A `count="exact"` read is by definition one that expects to grow, so
    each one must be paged. The failure is invisible at runtime, which is why it is caught here.
    """
    source = _service_source()
    counted = source.count('count="exact"')
    assert counted >= 4, "expected the paged reads to still be counted"
    assert source.count(".range(") >= counted


def test_jsonb_payload_columns_never_appear_in_a_list_projection():
    """storage-retention-spec §9: never SELECT * on a table carrying jsonb. `prospect.raw` is the
    untouched provider payload and `lead.intake_payload` an entire inbound form — pulling either
    across a page of 50 is billed egress nobody asked for."""
    for projection in (svc._PROSPECT_COLUMNS, svc._LEAD_LIST_COLUMNS, svc._ACTIVITY_COLUMNS):
        columns = set(projection.split(","))
        assert "raw" not in columns
        assert "intake_payload" not in columns

    # And the reads on those three tables actually use the projections. If someone swaps one back
    # to a star the constant falls out of use, so a definition with no reference is the signal.
    # (`suppression`, `market`, `submarket` and `lead_stage` carry no jsonb and read `*` freely.)
    source = _service_source()
    for name in ("_PROSPECT_COLUMNS", "_LEAD_LIST_COLUMNS", "_ACTIVITY_COLUMNS"):
        assert source.count(name) >= 2, f"{name} is defined but nothing reads through it"


# --- scan orders (the UI trigger — outreach DECISIONS.md 2026-08-06) ----------------------------


def test_task_progress_counts_and_derived_numbers():
    progress = svc.build_task_progress(
        [
            {"status": "collected"}, {"status": "collected"}, {"status": "collected"},
            {"status": "submitted"}, {"status": "pending"}, {"status": "failed"},
        ]
    )
    assert progress["total"] == 6
    assert progress["collected"] == 3
    assert progress["outstanding"] == 2  # pending + submitted — both still owed a result
    assert progress["failed"] == 1
    assert progress["counts"] == {"collected": 3, "submitted": 1, "pending": 1, "failed": 1}


def test_task_progress_of_nothing_is_zero_not_an_error():
    """An order that has not executed yet has no snapshot and no tasks; the status screen renders
    zeros, not a crash."""
    progress = svc.build_task_progress([])
    assert progress == {"counts": {}, "total": 0, "collected": 0, "outstanding": 0, "failed": 0}


def test_active_statuses_mirror_the_one_active_index():
    """The service's duplicate pre-check and the database's partial unique index must agree on
    what "active" means, or the friendly 422 and the constraint refuse different things. The
    index predicate is `status in ('pending', 'running')` — migration 20260806120000."""
    assert svc.SCAN_REQUEST_ACTIVE_STATUSES == ("pending", "running")


def test_the_spend_authorizing_routes_are_admin_gated():
    """The click IS the spend confirmation (outreach DECISIONS.md 2026-08-06), so the role that
    can click is the role trusted with spend — admin, above the staff bar the CRM writes use.
    Checked at the source level because a Depends() swap is one autocomplete away and invisible
    at runtime until the wrong person spends money."""
    import pathlib

    # By path, not import — the module pulls in fastapi, which the source check does not need.
    source = (
        pathlib.Path(svc.__file__).resolve().parents[1] / "routers" / "outreach.py"
    ).read_text()
    for route in ("create_scan_request", "cancel_scan_request"):
        head = source.split(f"async def {route}", 1)[1].split(") -> dict")[0]
        assert "require_admin" in head, f"{route} must be admin-gated"

    # And the reads stay reads: nothing else in the scan-order section may take require_admin,
    # or the board becomes invisible to the staff who work it.
    for route in ("list_scan_requests", "scan_request_detail", "placeholder_scores"):
        head = source.split(f"async def {route}", 1)[1].split(") -> dict")[0]
        assert "require_outreach" in head, f"{route} should be readable by any authed staff"


# --- promotion (scan results -> CRM board, owner ruling 2026-08-06) -----------------------------


def test_promoted_leads_are_outbound_scan_with_the_prospect_attached():
    """The ruling: hand-picked leads ARE outbound_scan — source records provenance, not
    automation. The payload shape is what validate_lead_write requires of that source, so the
    coupling is checked here at the seam rather than discovered as a 422 in the UI."""
    source = _service_source()
    section = source.split("def promote_prospect", 1)[1]
    assert '"source": "outbound_scan"' in section
    assert '"prospect_id": prospect_id' in section
    # And the validator accepts exactly that shape.
    fields = svc.validate_lead_write(
        {"source": "outbound_scan", "prospect_id": "p-1", "company_name": "Acme"},
        creating=True,
    )
    assert fields["source"] == "outbound_scan"


def test_promotion_is_idempotent_not_an_error():
    """A button that 422s on its second press teaches people to distrust the first. Both the
    pre-check and the lost-race path must return the existing lead flagged already_existed."""
    source = _service_source()
    section = source.split("def promote_prospect", 1)[1]
    assert section.count("already_existed=True") == 2, "pre-check AND race path must both return it"
    assert "already_existed=False" in section
