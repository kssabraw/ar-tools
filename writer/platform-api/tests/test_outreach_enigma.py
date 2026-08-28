"""Pure-logic tests for the Enigma card-revenue spend gate — no network, no live database.

Mirrors test_outreach_enrich.py: what is worth pinning is the gate, not the plumbing — the estimate
arithmetic, the per-user daily budget refusal (which names its numbers), and the selection validation
that refuses an empty or over-cap order. Plus the two enigma-specific bits: the entity-path
normalization, and that the billable count anchors on a NAME (Enigma matches on name+address), not on
a place_id the way enrichment does.
"""
import pytest

from services import outreach as svc
from services.outreach import OutreachError


# --- cost / spend / budget (pure) --------------------------------------------------------------


def test_enigma_cost_is_billable_times_rate():
    assert svc.enigma_cost_cents(10, 50) == 500
    assert svc.enigma_cost_cents(0, 50) == 0
    assert svc.enigma_cost_cents(-3, 50) == 0


def test_spent_today_sums_order_estimates():
    orders = [{"est_cost_cents": 50}, {"est_cost_cents": 25}, {"est_cost_cents": None}]
    assert svc.enigma_spent_today_cents(orders) == 75


def test_budget_denial_names_the_numbers_and_passes_at_the_line():
    # $10 budget = 1000¢. 800 spent + 250 = 1050 > 1000 → refused.
    denial = svc.enigma_budget_denial(800, 250, 10.0)
    assert denial is not None and "10.00" in denial and "Enigma" in denial
    # Exactly at the line is allowed.
    assert svc.enigma_budget_denial(750, 250, 10.0) is None


# --- selection validation (pure) ---------------------------------------------------------------


def test_selection_is_deduped_and_bounded():
    assert svc.validate_enigma_selection(["a", "b", "a"], 10) == ["a", "b"]


def test_an_empty_selection_is_refused():
    with pytest.raises(OutreachError) as e:
        svc.validate_enigma_selection([], 10)
    assert e.value.code == "empty_selection"


def test_an_over_cap_selection_is_refused_not_truncated():
    with pytest.raises(OutreachError) as e:
        svc.validate_enigma_selection(["a", "b", "c"], 2)
    assert e.value.code == "selection_too_large"


# --- entity-path normalization -----------------------------------------------------------------


def test_entity_type_defaults_and_is_case_insensitive():
    # None / blank → the configured default ('brand'); a valid value is lowercased.
    assert svc.normalize_enigma_entity_type(None) == "brand"
    assert svc.normalize_enigma_entity_type("  ") == "brand"
    assert svc.normalize_enigma_entity_type("BRAND") == "brand"
    assert svc.normalize_enigma_entity_type("Operating_Location") == "operating_location"


def test_an_unknown_entity_type_is_refused_not_sent():
    with pytest.raises(OutreachError) as e:
        svc.normalize_enigma_entity_type("legalentity")
    assert e.value.code == "invalid_entity_type"


# --- billable anchors on a NAME, and skips durable answers (minimal fake client) ---------------


class _Resp:
    def __init__(self, data):
        self.data = data


class _Q:
    def __init__(self, db, table):
        self.db, self.table_name = db, table
        self._in: dict[str, list] = {}

    def select(self, *_a, **_k):
        return self

    def in_(self, col, vals):
        self._in[col] = list(vals)
        return self

    def execute(self):
        rows = self.db[self.table_name]
        ids = self._in.get("prospect_id") or self._in.get("id")
        out = []
        for r in rows:
            key = r.get("id", r.get("prospect_id"))
            if ids is not None and key not in ids:
                continue
            if "status" in self._in and r.get("status") not in self._in["status"]:
                continue
            out.append(r)
        return _Resp(out)


class _FakeClient:
    def __init__(self, prospects, enigma_rows):
        self.db = {"prospect": prospects, "prospect_enigma": enigma_rows}

    def table(self, name):
        return _Q(self.db, name)


def test_billable_requires_a_name_and_skips_durable_answers():
    prospects = [
        {"id": "p1", "name": "Acme Plumbing"},   # billable
        {"id": "p2", "name": "  "},              # exists but NO name → not billable (Enigma needs a name)
        {"id": "p3", "name": "Bob's Rooter"},    # already looked up → skipped
        # p4 is not in the prospect table → unknown
    ]
    enigma_rows = [{"prospect_id": "p3", "status": "matched"}]
    client = _FakeClient(prospects, enigma_rows)

    counts = svc._enigma_billable(client, ["p1", "p2", "p3", "p4"])

    assert counts["billable"] == 1          # only p1
    assert counts["already_fetched"] == 1   # p3 (durable)
    assert counts["no_name"] == 1           # p2
    assert counts["unknown"] == 1           # p4
    assert counts["selected"] == 4
    # the four buckets reconcile to the selection
    assert (counts["billable"] + counts["already_fetched"]
            + counts["no_name"] + counts["unknown"]) == counts["selected"]


def test_a_failed_prior_answer_is_not_durable_and_stays_billable():
    # `failed` is NOT in the durable set (it's retryable), so a prospect with a prior failed lookup
    # is billable again — unlike matched/no_card/no_match.
    prospects = [{"id": "p1", "name": "Acme"}]
    enigma_rows = [{"prospect_id": "p1", "status": "failed"}]
    counts = svc._enigma_billable(_FakeClient(prospects, enigma_rows), ["p1"])
    assert counts["billable"] == 1 and counts["already_fetched"] == 0
