"""Which geo-grid scans count as REPORTING data.

Every `maps_scans` row carries a `trigger`. Only the **scheduled** weekly series
is the client's record of local-pack visibility; a `manual` scan is a one-off the
team ran by hand — to sanity-check a config change, to look at a single keyword
after a fix, or just to see the grid right now. Those are a scratchpad, and the
owner's rule (2026-08-08) is that they never appear in reporting.

"Reporting" here means anything that aggregates scans over time or is read as the
campaign's truth: trend/SoLV/period series, the client PDF, the scan-over-scan
analyzer (and therefore geo-grid alerts, their notifications and the Action Plan
items they drive), goal measurement, the strategist digest, and the SerMaStr
context/tools. It does NOT mean the Heatmap tab or the History list — a one-off's
whole purpose is to be looked at, so both keep showing every scan.

Two properties matter more than the one-line filter:

- The rule lives in ONE place. It was previously implicit in ~12 separate
  Supabase queries, none of which mentioned `trigger` at all, so a one-off
  silently became both a trend point and the alert baseline the next scheduled
  scan was diffed against.
- It is an ALLOWLIST. A new trigger value is excluded from reporting until
  someone adds it here deliberately — the safe direction, since the cost of
  wrongly including a scan is a false client-facing alert, while the cost of
  wrongly excluding one is a missing point on a chart.

Keyword-subset scans (see `local_dominator.start_client_scan`) can only ever be
manual, so a partial grid can never land in a series that assumes full coverage.
"""

from typing import Any, Iterable

# Trigger values whose scans are the client's reporting record. Scheduled weekly
# scans only: `manual` is a one-off, `parallel_test` is the §7 provider-comparison
# quarantine (already excluded from the completion hooks).
REPORTING_TRIGGERS: tuple[str, ...] = ("scheduled",)


def is_reporting_scan(scan: Any) -> bool:
    """Is this scan part of the reporting series? Accepts a `maps_scans` row or a
    bare trigger string. A row with no `trigger` at all is treated as scheduled —
    the column is NOT NULL in practice, and defaulting a real scan out of every
    chart would be a worse failure than defaulting it in."""
    if isinstance(scan, str) or scan is None:
        trigger = scan
    else:
        trigger = scan.get("trigger")
    if trigger is None:
        return True
    return trigger in REPORTING_TRIGGERS


def filter_reporting(scans: Iterable[dict]) -> list[dict]:
    """The reporting subset of already-fetched scan rows. For call sites that
    fetch by id (or in bulk across clients) and filter in memory."""
    return [s for s in scans if is_reporting_scan(s)]


def only_reporting(query):
    """Narrow a Supabase `maps_scans` query to the reporting series.

    Applies to the query builder, so it composes with whatever `.select()` the
    call site already uses — the filter does not require `trigger` to be selected.
    """
    return query.in_("trigger", list(REPORTING_TRIGGERS))
