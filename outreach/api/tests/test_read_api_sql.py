"""Drift guard for the suite read API's SQL.

`v_prospect_status` decides `excluded` in SQL, and `services/filters.py` decides it in Python.
They must agree. The view cannot import the frozenset, so the literal is duplicated there and
this test is what keeps the duplication honest — add a rule to `NON_EXCLUSIONARY_RULES` and this
fails until the migration is updated too.

The failure it prevents is silent and one-directional: a newly non-exclusionary rule would keep
FLAGGING in the pipeline while the suite's prospect list started EXCLUDING on it. Both halves
would look correct in isolation, and the only visible symptom would be a survivor count that
quietly dropped. That is the same shape as the franchise rule's original bug (hard exclusion made
the −87 coefficient dead code, ISSUES R-003) — a filter behaving more harshly than anyone
intended, with nothing in the output saying so.
"""

from __future__ import annotations

import re
from pathlib import Path

from api.services.filters import NON_EXCLUSIONARY_RULES

MIGRATION = (
    Path(__file__).resolve().parents[2] / "migrations" / "20260801100000_read_api.sql"
)


def _view_body() -> str:
    """The lateral subquery that computes `excluded`, isolated from the surrounding view."""
    sql = MIGRATION.read_text()
    start = sql.index("bool_or(not fr.passed")
    return sql[start : sql.index(")", sql.index("as excluded", start))]


def test_migration_exists():
    assert MIGRATION.exists(), f"read API migration missing at {MIGRATION}"


def test_excluded_skips_exactly_the_non_exclusionary_rules():
    body = _view_body()
    named = set(re.findall(r"fr\.rule <> '([a-z_]+)'", body))
    assert named == set(NON_EXCLUSIONARY_RULES), (
        "v_prospect_status and filters.NON_EXCLUSIONARY_RULES disagree about which failing rules "
        f"exclude a prospect: SQL names {sorted(named)}, Python names "
        f"{sorted(NON_EXCLUSIONARY_RULES)}"
    )


def test_franchise_is_still_the_non_exclusionary_one():
    """Pinned separately from the comparison above, which would pass if BOTH sides were emptied.

    Franchise-flag-never-exclude is a recorded decision, not an implementation detail: a false
    positive on a chain-name pattern permanently loses a real prospect, and hard exclusion is what
    made the franchise coefficient unable to fire at all.
    """
    assert NON_EXCLUSIONARY_RULES == frozenset({"not_franchise"})


def test_read_api_is_not_reachable_by_anon_or_authenticated():
    """Service-role only, matching every other table in the estate.

    Supabase grants ALL on new objects in `public` to anon/authenticated by DEFAULT, so a missing
    revoke does not fail closed — it publishes the whole prospect list. PR #534 found the same
    default silently defeating an append-only grant on the CRM tables.
    """
    sql = MIGRATION.read_text()
    assert "revoke all on v_prospect_status from anon, authenticated;" in sql
    assert "revoke all on function outreach_market_summary(uuid)" in sql
