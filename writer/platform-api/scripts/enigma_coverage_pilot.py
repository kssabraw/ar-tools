"""LeadOff — Enigma card-transaction coverage pilot harness.

The go/no-go feasibility probe from
``docs/modules/leadoff-enigma-pilot-plan-v1_0.md`` (§4 test set, §5 scorecard,
§5.4 decision matrix). It answers ONE cheaply-testable question before any Enigma
contract is signed:

    Does Enigma have usable card-transaction coverage for home-service SABs
    (roofers, plumbers, water-damage restoration, tree service, pest control) —
    the categories LeadOff actually grades?

It reads a ~12-business ground-truth CSV (``scripts/leadoff_enigma_ground_truth.csv``
by default — bucket A = real Little Rock water-damage competitors LeadOff already
holds, bucket B = owner-supplied revenue anchors, control = a card-present
storefront positive control), calls Enigma's Small Business GraphQL API once per
business, and prints the §5 scorecard + the §5.4 outcome. It **writes nothing to
the app** — results go to a scratch CSV + a raw-envelope JSONL, and it **refuses
to run without a key**.

Why GraphQL (not the REST match/ID path): the outreach module already proved the
GraphQL ``search(searchInput)`` path returns card windows on a real eval key,
while the REST match path returned none (``outreach/api/services/enigma_graphql.py``
+ ``outreach/docs/enigma-graphql-api-reference.md``). This harness reuses that
LIVE-VERIFIED query shape verbatim (single ``cardTransactions`` connection filtered
by ``quantityType`` + ``period``, the ``enigmaId: null``-on-a-real-match gotcha),
so it is faithful to the one shape we know works — not a guess.

Measure, don't infer: every raw response envelope is written to the JSONL so the
real slug names (e.g. the transaction-count / average-ticket ``quantityType``) and
any match-confidence field are discoverable on the first live run, and the query's
best-effort ``card_transactions_count`` alias returns empty (never errors) if that
slug differs — adjust ``--count-quantity`` once the JSONL shows the real one.

Run it wherever the key + egress live (owner's machine or a Railway shell — the
Claude Code sandbox is egress-blocked from Enigma):

    export ENIGMA_API_KEY="..."
    # confirm the endpoint against Enigma's live docs at integration time:
    export ENIGMA_GRAPHQL_URL="https://api.enigma.com/graphql"   # or your eval URL
    python scripts/enigma_coverage_pilot.py

    # sanity-check the input CSV WITHOUT a key or egress (no API calls):
    python scripts/enigma_coverage_pilot.py --dry-run

No app imports — standalone on purpose, so it runs from a bare shell with only
``httpx`` installed (mirrors scripts/verify_everhour_api_key.py). The pure helpers
(query/variables/parsers/scoring/verdicts) are unit-tested in
tests/test_enigma_coverage_pilot.py; only the HTTP round-trip is impure.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

import httpx

# ── Defaults ───────────────────────────────────────────────────────────────────
# The GraphQL endpoint + auth header MUST be confirmed against Enigma's live docs
# at integration time (the plan §3 says treat these as capabilities). The outreach
# module uses ``x-api-key`` + a per-account GraphQL URL; there is no single public
# default, so ENIGMA_GRAPHQL_URL is required unless passed via --graphql-url.
DEFAULT_TIMEOUT = 45
DEFAULT_MATCH_THRESHOLD = 0.5
DEFAULT_PERIODS = ["1m", "3m", "12m", "24m"]
REVENUE_QUANTITY = "card_revenue_amount"          # LIVE-VERIFIED slug (outreach)
COUNT_QUANTITY = "card_transactions_count"        # best-effort; empty if the slug differs
_GROUND_TRUTH = Path(__file__).with_name("leadoff_enigma_ground_truth.csv")

# §5.1 coverage thresholds (match rate over bucket A):
COVERAGE_STRONG = 0.60
COVERAGE_MARGINAL = 0.40
# §5.2 growth: trend present on this share of matched rows to PASS:
GROWTH_TREND_PRESENT_MIN = 0.60
# Run-rate acceleration proxy band (±): within this the trend reads "stable".
TREND_STABLE_BAND = 0.15
# §5.3 lead-value: share of scored rows whose avg ticket is plausible to PASS:
LEADVALUE_PLAUSIBLE_MIN = 0.60


# ── Pure: GraphQL document + variables (faithful to outreach's proven shape) ────

def _card_selection(alias: str, quantity_type: str, periods: list[str]) -> str:
    """One aliased ``cardTransactions`` connection filtered to a single
    ``quantityType`` over the given periods. Aliasing lets us pull revenue AND a
    best-effort transaction count in one call; an unknown ``quantityType`` VALUE
    is a filter string (not an enum), so it returns an empty connection rather
    than failing the whole document."""
    plist = json.dumps(periods)  # valid GraphQL list literal for a string array
    return (
        f'{alias}: cardTransactions(conditions: {{ filter: {{ AND: ['
        f'{{ EQ: ["quantityType", "{quantity_type}"] }}, '
        f'{{ IN: ["period", {plist}] }}'
        f'] }} }}) {{ edges {{ node {{ period projectedQuantity rawQuantity '
        f'periodStartDate periodEndDate }} }} }}'
    )


def build_query(entity_type: str, periods: list[str],
                count_quantity: Optional[str] = COUNT_QUANTITY) -> str:
    """The GraphQL document for one entity type. Only the matching inline fragment
    is included (Brand vs OperatingLocation) — selecting ``names.name`` under both
    at once is a String-vs-String! field conflict (outreach lesson, measured live
    2026-08-27). Pulls revenue always + a best-effort count alias for avg-ticket."""
    et = "OPERATING_LOCATION" if str(entity_type).strip().lower() in (
        "operating_location", "operatinglocation", "location") else "BRAND"
    frag_name = "OperatingLocation" if et == "OPERATING_LOCATION" else "Brand"
    revenue = _card_selection("revenue", REVENUE_QUANTITY, periods)
    count = _card_selection("txns", count_quantity, periods) if count_quantity else ""
    body = (
        f"... on {frag_name} {{\n"
        f"  enigmaId\n"
        f"  names(first: 1) {{ edges {{ node {{ name }} }} }}\n"
        f"  {revenue}\n"
        + (f"  {count}\n" if count else "")
        + f"}}"
    )
    return (
        "query Pilot($si: SearchInput!) {\n"
        "  search(searchInput: $si) {\n"
        f"    {body}\n"
        "  }\n"
        "}"
    )


def build_variables(biz: dict[str, Any], match_threshold: float,
                    entity_type: str) -> dict[str, Any]:
    """The ``searchInput`` for one business. Only non-empty parts are sent, so a
    street-only address (LeadOff holds no zip) is fine."""
    et = "OPERATING_LOCATION" if str(entity_type).strip().lower() in (
        "operating_location", "operatinglocation", "location") else "BRAND"
    si: dict[str, Any] = {"entityType": et, "matchThreshold": match_threshold}
    if biz.get("name"):
        si["name"] = str(biz["name"]).strip()
    addr = {
        k: str(biz[src]).strip()
        for k, src in (("street1", "street"), ("city", "city"),
                       ("state", "state"), ("postalCode", "postal_code"))
        if str(biz.get(src) or "").strip()
    }
    if addr:
        si["address"] = addr
    if str(biz.get("website") or "").strip():
        si["website"] = str(biz["website"]).strip()
    return {"si": si}


# ── Pure: response parsers ─────────────────────────────────────────────────────

def _nodes(conn: Any) -> list[dict[str, Any]]:
    if not isinstance(conn, dict):
        return []
    return [e["node"] for e in (conn.get("edges") or [])
            if isinstance(e, dict) and isinstance(e.get("node"), dict)]


def first_entity(raw: Any) -> Optional[dict[str, Any]]:
    """The top matched entity from a GraphQL response, or None. ``search`` returns
    a best-first list; a match is signalled by a result dict carrying any selected
    field — NOT by a non-null ``enigmaId`` (the live API returns ``enigmaId: null``
    on a real match; keying on the id was the outreach match_rate=0 bug)."""
    if not isinstance(raw, dict):
        return None
    data = raw.get("data")
    results = data.get("search") if isinstance(data, dict) else None
    if not isinstance(results, list):
        return None
    for item in results:
        if isinstance(item, dict) and any(
            item.get(k) is not None
            for k in ("enigmaId", "names", "revenue", "txns", "cardTransactions")
        ):
            return item
    return None


def is_match(raw: Any) -> bool:
    return first_entity(raw) is not None


def matched_name(entity: Any) -> Optional[str]:
    """The matched entity's name — the QA signal for a WRONG match (a plausible
    card figure on the wrong business is the silent failure)."""
    if not isinstance(entity, dict):
        return None
    ns = _nodes(entity.get("names"))
    nm = ns[0].get("name") if ns else None
    return nm.strip() if isinstance(nm, str) and nm.strip() else None


def match_confidence(entity: Any, raw: Any) -> Optional[float]:
    """A match-confidence value IF Enigma surfaces one (the query doesn't request
    one — the shape is unverified — so this defensively reads any of a few likely
    keys off the entity/result and returns None otherwise). Captured, never
    fabricated."""
    for src in (entity, ((raw or {}).get("data") or {}) if isinstance(raw, dict) else {}):
        if isinstance(src, dict):
            for k in ("matchConfidence", "confidence", "matchScore", "score"):
                v = src.get(k)
                if isinstance(v, (int, float)):
                    return float(v)
    return None


def _amount(node: dict[str, Any]) -> Optional[float]:
    """Prefer the projected (panel-scaled) figure; fall back to raw (compliance
    floor) — the outreach convention."""
    for key in ("projectedQuantity", "rawQuantity"):
        v = node.get(key)
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            try:
                return float(v.replace(",", ""))
            except ValueError:
                pass
    return None


def card_windows(entity: Any, alias: str = "revenue") -> dict[str, float]:
    """``{period: amount}`` for one aliased connection (``revenue`` or ``txns``).
    Empty when absent — never raises."""
    out: dict[str, float] = {}
    if not isinstance(entity, dict):
        return out
    for node in _nodes(entity.get(alias)):
        period = node.get("period")
        amt = _amount(node)
        if isinstance(period, str) and period not in out and amt is not None:
            out[period] = amt
    return out


def card_as_of(entity: Any) -> Optional[str]:
    """The latest ``periodEndDate`` (a bare ``YYYY-MM-DD``) across the revenue
    windows — the "revenue as of" recency, and the §5.2 coverage-stability read."""
    if not isinstance(entity, dict):
        return None
    latest: Optional[str] = None
    for node in _nodes(entity.get("revenue")):
        end = node.get("periodEndDate")
        if isinstance(end, str) and len(end.strip()) >= 10:
            day = end.strip()[:10]
            if day[:4].isdigit() and (latest is None or day > latest):
                latest = day
    return latest


def avg_ticket(revenue: dict[str, float], counts: dict[str, float],
               period: str = "12m") -> Optional[float]:
    """Average card ticket = revenue / transaction-count at a period. None when
    either is missing or the count is zero (never a divide-by-zero, never a
    fabricated ticket)."""
    r = revenue.get(period)
    c = counts.get(period)
    if r is None or not c:
        return None
    return round(r / c, 2)


def revenue_trend(revenue: dict[str, float]) -> dict[str, Any]:
    """A single-call momentum read. Prefers a real trailing-YoY when both 12m and
    24m are present (prior-year = 24m − 12m); else a run-rate acceleration proxy
    (recent months annualized vs the trailing year). Returns
    {direction: up|down|flat|unknown, basis, yoy_pct}. Honest about what it
    measures — a true YoY needs a second pull or a growth quantityType."""
    r12 = revenue.get("12m")
    r24 = revenue.get("24m")
    if r12 is not None and r24 is not None and (r24 - r12) > 0:
        prior = r24 - r12
        yoy = (r12 - prior) / prior
        return {"direction": _dir(yoy), "basis": "yoy_24m", "yoy_pct": round(yoy * 100, 1)}
    # run-rate acceleration proxy: 1m×12 (or 3m×4) vs 12m
    recent = None
    if revenue.get("1m") is not None:
        recent = revenue["1m"] * 12
    elif revenue.get("3m") is not None:
        recent = revenue["3m"] * 4
    if recent is not None and r12:
        delta = (recent - r12) / r12
        return {"direction": _dir(delta), "basis": "run_rate", "yoy_pct": round(delta * 100, 1)}
    return {"direction": "unknown", "basis": "insufficient", "yoy_pct": None}


def _dir(frac: float) -> str:
    if frac > TREND_STABLE_BAND:
        return "up"
    if frac < -TREND_STABLE_BAND:
        return "down"
    return "flat"


def _to_float(v: Any) -> Optional[float]:
    try:
        s = str(v).strip().replace(",", "").replace("$", "")
        return float(s) if s else None
    except (TypeError, ValueError):
        return None


def plausibility_auto(avg: Optional[float], low: Optional[float],
                      high: Optional[float]) -> str:
    """A FIRST-PASS auto read of §5.3 avg-ticket plausibility vs the category's
    real per-job range. The human column (``plausible_human``) is authoritative —
    this only flags the obvious insurance-undercount failure. Returns
    implausible_low | plausible | above_range | unknown."""
    if avg is None:
        return "unknown"
    if low is not None and avg < low:
        return "implausible_low"     # the insurance/invoice-undercount failure mode
    if high is not None and avg > high:
        return "above_range"
    if low is not None or high is not None:
        return "plausible"
    return "unknown"


def score_business(biz: dict[str, Any], raw: Any) -> dict[str, Any]:
    """The per-business scorecard row (pure) from the ground-truth input + the
    Enigma response. Never raises; missing data is None/unknown, never fabricated."""
    entity = first_entity(raw)
    rev = card_windows(entity, "revenue")
    cnt = card_windows(entity, "txns")
    low = _to_float(biz.get("category_avg_ticket_low"))
    high = _to_float(biz.get("category_avg_ticket_high"))
    avg = avg_ticket(rev, cnt)
    trend = revenue_trend(rev)
    return {
        "id": biz.get("id", ""),
        "bucket": (biz.get("bucket") or "").strip().lower(),
        "name": biz.get("name", ""),
        "matched": bool(entity),
        "match_confidence": match_confidence(entity, raw),
        "matched_name": matched_name(entity),
        "card_revenue_12m": rev.get("12m"),
        "card_revenue_3m": rev.get("3m"),
        "card_revenue_1m": rev.get("1m"),
        "card_txns_12m": cnt.get("12m"),
        "avg_ticket": avg,
        "trend_direction": trend["direction"],
        "trend_basis": trend["basis"],
        "trend_pct": trend["yoy_pct"],
        "card_as_of": card_as_of(entity),
        "known_revenue": biz.get("known_revenue", ""),
        "known_trend": (biz.get("known_trend") or "").strip().lower(),
        "plausible_auto": plausibility_auto(avg, low, high),
        "plausible_human": "",          # the owner fills y/n/unsure vs ground truth
    }


# ── Pure: aggregate scorecard + §5 verdicts ────────────────────────────────────

def _rate(n: int, d: int) -> float:
    return round(n / d, 3) if d else 0.0


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The §5.1/5.2/5.3 aggregate metrics. Coverage is measured on bucket A (home
    services); the control row is judged separately (§5.1 positive control)."""
    a = [r for r in rows if r["bucket"] == "a"]
    control = [r for r in rows if r["bucket"] == "control"]
    matched_a = [r for r in a if r["matched"]]
    matched_all = [r for r in rows if r["matched"]]
    trend_present = [r for r in matched_all if r["trend_direction"] != "unknown"]
    scored_lv = [r for r in matched_all if r["plausible_auto"] != "unknown"]
    plausible_lv = [r for r in scored_lv if r["plausible_auto"] == "plausible"]
    # anchor sign-agreement (rows carrying a known_trend)
    anchors = [r for r in matched_all if r["known_trend"] in ("up", "down", "flat")]
    agree = [r for r in anchors if r["trend_direction"] == r["known_trend"]]
    return {
        "n_total": len(rows),
        "n_bucket_a": len(a),
        "n_matched_a": len(matched_a),
        "match_rate_a": _rate(len(matched_a), len(a)),
        "control_present": len(control),
        "control_matched": sum(1 for r in control if r["matched"]),
        "n_matched_all": len(matched_all),
        "trend_present": len(trend_present),
        "trend_present_rate": _rate(len(trend_present), len(matched_all)),
        "anchors": len(anchors),
        "anchor_sign_agree": len(agree),
        "lead_value_scored": len(scored_lv),
        "lead_value_plausible": len(plausible_lv),
        "lead_value_plausible_rate": _rate(len(plausible_lv), len(scored_lv)),
        "implausible_low": sum(1 for r in matched_all
                               if r["plausible_auto"] == "implausible_low"),
    }


def verdict_coverage(agg: dict[str, Any]) -> tuple[str, str]:
    """§5.1. The positive control gates everything: an unmatched control means the
    trial key / matching is the problem, so the pilot is INCONCLUSIVE, not a NO-GO."""
    if agg["control_present"] and agg["control_matched"] == 0:
        return ("inconclusive",
                "positive-control storefront did NOT match — fix matching/key "
                "before judging category coverage (§5.1)")
    rate = agg["match_rate_a"]
    if agg["n_bucket_a"] == 0:
        return ("inconclusive", "no bucket-A (home-service) rows to measure")
    if rate >= COVERAGE_STRONG:
        return ("strong", f"match rate {rate:.0%} ≥ {COVERAGE_STRONG:.0%}")
    if rate >= COVERAGE_MARGINAL:
        return ("marginal",
                f"match rate {rate:.0%} in [{COVERAGE_MARGINAL:.0%}, "
                f"{COVERAGE_STRONG:.0%}) — usable only if matched rows are also "
                f"plausible (§5.2/5.3)")
    return ("no_go",
            f"match rate {rate:.0%} < {COVERAGE_MARGINAL:.0%} — home-service "
            f"coverage too thin to build on")


def verdict_growth(agg: dict[str, Any]) -> tuple[str, str]:
    """§5.2. PASS needs a trend on ≥60% of matched rows AND (no anchors, or the
    anchors' signs agree). INSUFFICIENT when there is nothing matched to judge."""
    if agg["n_matched_all"] == 0:
        return ("insufficient", "nothing matched to judge a trend on")
    rate = agg["trend_present_rate"]
    ok_present = rate >= GROWTH_TREND_PRESENT_MIN
    ok_anchor = agg["anchors"] == 0 or agg["anchor_sign_agree"] == agg["anchors"]
    if ok_present and ok_anchor:
        note = f"trend present on {rate:.0%} of matched"
        if agg["anchors"]:
            note += f"; anchor signs agree {agg['anchor_sign_agree']}/{agg['anchors']}"
        return ("pass", note)
    reasons = []
    if not ok_present:
        reasons.append(f"trend present only {rate:.0%} (< {GROWTH_TREND_PRESENT_MIN:.0%})")
    if not ok_anchor:
        reasons.append(f"anchor signs agree only {agg['anchor_sign_agree']}/{agg['anchors']}")
    return ("fail", "; ".join(reasons))


def verdict_lead_value(agg: dict[str, Any]) -> tuple[str, str]:
    """§5.3 — the harder, expected-to-FAIL bar. The AUTO read only flags the
    insurance-undercount failure (avg ticket far below the category floor); the
    owner's ``plausible_human`` column is authoritative and should be reviewed
    before trusting a PASS."""
    scored = agg["lead_value_scored"]
    if scored == 0:
        return ("insufficient",
                "no avg-ticket computed (needs a transaction-count quantityType — "
                "check the raw JSONL for the real slug, set --count-quantity)")
    rate = agg["lead_value_plausible_rate"]
    if rate >= LEADVALUE_PLAUSIBLE_MIN:
        return ("pass_auto",
                f"avg ticket plausible on {rate:.0%} of scored — CONFIRM by hand "
                f"(plausible_human) before trusting")
    return ("fail",
            f"avg ticket plausible on only {rate:.0%}; {agg['implausible_low']} "
            f"row(s) implausibly low (the insurance-undercount failure)")


def decision_matrix(coverage: str, growth: str, lead_value: str) -> str:
    """§5.4. Collapse the three verdicts into the outcome cell."""
    if coverage in ("no_go",):
        return ("FULL NO-GO — neither use. Home-service card coverage is too thin; "
                "revisit only if card-present categories (salons, retail) are added.")
    if coverage == "inconclusive":
        return ("INCONCLUSIVE — fix the positive control / matching / key, then "
                "re-run before drawing any conclusion.")
    g_pass = growth == "pass"
    lv_pass = lead_value == "pass_auto"
    if g_pass and not lv_pass:
        return ("BUILD GROWTH ONLY (§7) — lead value stays on agency close data "
                "via leadoff_calibration. (The plan's expected outcome.)")
    if g_pass and lv_pass:
        return ("BUILD GROWTH; PILOT LEAD-VALUE as a second phase (confirm §5.3 by "
                "hand first).")
    if not g_pass and lv_pass:
        return ("UNUSUAL — lead-value alone rarely justifies the contract; "
                "reconsider.")
    return ("NO USABLE SIGNAL at this coverage — neither growth nor lead-value "
            "cleared its bar; do not sign.")


# ── I/O: ground-truth CSV, Enigma call, scorecard render ───────────────────────

_REQUIRED_COLS = {"id", "bucket", "name"}


def read_ground_truth(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = [dict(r) for r in reader
                if str(r.get("name") or "").strip()
                and not str(r.get("id") or "").strip().startswith("#")]
    if rows and not _REQUIRED_COLS.issubset(set(rows[0])):
        missing = _REQUIRED_COLS - set(rows[0])
        raise ValueError(f"ground-truth CSV missing columns: {sorted(missing)}")
    return rows


def lookup_one(client: httpx.Client, url: str, api_key: str, biz: dict[str, Any],
               *, entity_type: str, match_threshold: float, periods: list[str],
               count_quantity: str) -> dict[str, Any]:
    """POST one GraphQL search. Never raises — a transport/HTTP failure is recorded
    on the returned envelope so one bad lookup can't abort the sample."""
    body = {"query": build_query(entity_type, periods, count_quantity),
            "variables": build_variables(biz, match_threshold, entity_type)}
    env: dict[str, Any] = {"id": biz.get("id"), "name": biz.get("name"),
                           "status": None, "raw": None, "error": None,
                           "request": body}
    try:
        resp = client.post(url, headers={
            "x-api-key": api_key, "content-type": "application/json",
            "Accept": "application/json"}, json=body)
        env["status"] = resp.status_code
        try:
            env["raw"] = resp.json()
        except ValueError:
            env["error"] = f"non-JSON body: {resp.text[:300]}"
    except httpx.RequestError as exc:
        env["error"] = f"{type(exc).__name__}: {exc}"
    return env


def _fmt(v: Any) -> str:
    if v is None:
        return "-"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:,.0f}" if abs(v) >= 100 else f"{v:g}"
    return str(v)


def render_scorecard(rows: list[dict[str, Any]], agg: dict[str, Any]) -> str:
    cov = verdict_coverage(agg)
    grw = verdict_growth(agg)
    lv = verdict_lead_value(agg)
    outcome = decision_matrix(cov[0], grw[0], lv[0])
    lines: list[str] = []
    lines.append("=" * 78)
    lines.append("LeadOff — Enigma coverage pilot — §5 scorecard")
    lines.append("=" * 78)
    lines.append("")
    lines.append("Per-business (bucket · matched · card_rev_12m · avg_ticket · trend):")
    for r in rows:
        lines.append(
            f"  [{r['bucket'].upper():<7}] {str(r['name'])[:34]:<34} "
            f"match={_fmt(r['matched']):<3} "
            f"rev12m={_fmt(r['card_revenue_12m']):>10} "
            f"avg_ticket={_fmt(r['avg_ticket']):>8} "
            f"trend={r['trend_direction']}({r['trend_basis']})")
        if r["matched"] and r["matched_name"] and \
                str(r["matched_name"]).lower() != str(r["name"]).lower():
            lines.append(f"           ⚠ matched a DIFFERENT name: {r['matched_name']!r}")
    lines.append("")
    lines.append("§5.1 Coverage (bucket A / home services):")
    lines.append(f"     match rate = {agg['match_rate_a']:.0%} "
                 f"({agg['n_matched_a']}/{agg['n_bucket_a']}); "
                 f"control matched {agg['control_matched']}/{agg['control_present']}")
    lines.append(f"     → {cov[0].upper()}: {cov[1]}")
    lines.append("§5.2 Growth signal (matched rows):")
    lines.append(f"     trend present = {agg['trend_present_rate']:.0%} "
                 f"({agg['trend_present']}/{agg['n_matched_all']}); "
                 f"anchor signs agree {agg['anchor_sign_agree']}/{agg['anchors']}")
    lines.append(f"     → {grw[0].upper()}: {grw[1]}")
    lines.append("§5.3 Lead-value calibration (avg ticket vs category range):")
    lines.append(f"     plausible = {agg['lead_value_plausible_rate']:.0%} "
                 f"({agg['lead_value_plausible']}/{agg['lead_value_scored']}); "
                 f"{agg['implausible_low']} implausibly-low")
    lines.append(f"     → {lv[0].upper()}: {lv[1]}")
    lines.append("")
    lines.append("§5.4 OUTCOME:")
    lines.append(f"     {outcome}")
    lines.append("")
    lines.append("NOTE: §5.3 and the anchor checks need a HUMAN read — fill the "
                 "plausible_human column")
    lines.append("      in the results CSV vs your ground truth before trusting a "
                 "PASS. Paste this")
    lines.append("      block + the results CSV into §8 of the plan doc as the "
                 "findings record.")
    lines.append("=" * 78)
    return "\n".join(lines)


_RESULT_COLS = ["id", "bucket", "name", "matched", "match_confidence",
                "matched_name", "card_revenue_12m", "card_revenue_3m",
                "card_revenue_1m", "card_txns_12m", "avg_ticket",
                "trend_direction", "trend_basis", "trend_pct", "card_as_of",
                "known_revenue", "known_trend", "plausible_auto", "plausible_human"]


def write_results(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_RESULT_COLS)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: ("" if r.get(k) is None else r.get(k))
                             for k in _RESULT_COLS})


def write_raw(path: Path, envelopes: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for env in envelopes:
            fh.write(json.dumps(env, default=str) + "\n")


# ── main ───────────────────────────────────────────────────────────────────────

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--key", default=os.environ.get("ENIGMA_API_KEY", ""),
                        help="Enigma API key (or ENIGMA_API_KEY)")
    parser.add_argument("--graphql-url",
                        default=os.environ.get("ENIGMA_GRAPHQL_URL", ""),
                        help="Enigma GraphQL endpoint (or ENIGMA_GRAPHQL_URL) — "
                             "confirm against Enigma's live docs")
    parser.add_argument("--ground-truth", type=Path, default=_GROUND_TRUTH,
                        help=f"input CSV (default {_GROUND_TRUTH.name})")
    parser.add_argument("--out", type=Path, default=Path("enigma_pilot_results.csv"),
                        help="results CSV path")
    parser.add_argument("--raw-out", type=Path,
                        default=Path("enigma_pilot_raw.jsonl"),
                        help="raw response envelopes (JSONL) — measure-don't-infer")
    parser.add_argument("--entity-type", default="brand",
                        choices=["brand", "operating_location"])
    parser.add_argument("--match-threshold", type=float,
                        default=DEFAULT_MATCH_THRESHOLD)
    parser.add_argument("--count-quantity", default=COUNT_QUANTITY,
                        help="quantityType slug for transaction count (for avg "
                             "ticket); '' to skip. Check the raw JSONL for the "
                             "real slug on the first run.")
    parser.add_argument("--periods", default=",".join(DEFAULT_PERIODS),
                        help="comma-separated card periods")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--dry-run", action="store_true",
                        help="validate the CSV + print the query/variables; no API "
                             "calls, no key required")
    args = parser.parse_args(argv)

    if not args.ground_truth.exists():
        print(f"[FAIL] ground-truth CSV not found: {args.ground_truth}", file=sys.stderr)
        return 2
    try:
        businesses = read_ground_truth(args.ground_truth)
    except (ValueError, OSError) as exc:
        print(f"[FAIL] could not read ground truth: {exc}", file=sys.stderr)
        return 2
    if not businesses:
        print(f"[FAIL] no usable rows in {args.ground_truth} (fill in name/address "
              f"— placeholder rows starting with '#' are skipped)", file=sys.stderr)
        return 2

    periods = [p.strip() for p in args.periods.split(",") if p.strip()]
    count_quantity = args.count_quantity.strip()

    if args.dry_run:
        print(f"[dry-run] {len(businesses)} business row(s) in {args.ground_truth}")
        by_bucket: dict[str, int] = {}
        for b in businesses:
            by_bucket[(b.get("bucket") or "?").lower()] = \
                by_bucket.get((b.get("bucket") or "?").lower(), 0) + 1
        print(f"[dry-run] buckets: {by_bucket}  (need bucket 'a' rows + a 'control')")
        print(f"[dry-run] GraphQL document for entity_type={args.entity_type}:\n")
        print(build_query(args.entity_type, periods, count_quantity or None))
        print("\n[dry-run] example variables (first row):")
        print(json.dumps(build_variables(businesses[0], args.match_threshold,
                                          args.entity_type), indent=2))
        print("\n[dry-run] no API calls made. Provide ENIGMA_API_KEY + "
              "ENIGMA_GRAPHQL_URL to run for real.")
        return 0

    if not args.key:
        print("[FAIL] ENIGMA_API_KEY not set (env var or --key). This pilot needs "
              "a trial/eval key; nothing runs without one.", file=sys.stderr)
        return 2
    if not args.graphql_url:
        print("[FAIL] ENIGMA_GRAPHQL_URL not set (env var or --graphql-url). "
              "Confirm the endpoint against Enigma's live docs.", file=sys.stderr)
        return 2

    rows: list[dict[str, Any]] = []
    envelopes: list[dict[str, Any]] = []
    with httpx.Client(timeout=args.timeout) as client:
        for biz in businesses:
            env = lookup_one(client, args.graphql_url, args.key, biz,
                             entity_type=args.entity_type,
                             match_threshold=args.match_threshold,
                             periods=periods, count_quantity=count_quantity)
            envelopes.append(env)
            if env["error"]:
                print(f"  [warn] {biz.get('name')!r}: {env['error']}", file=sys.stderr)
            elif env["status"] and env["status"] != 200:
                print(f"  [warn] {biz.get('name')!r}: HTTP {env['status']}",
                      file=sys.stderr)
            rows.append(score_business(biz, env.get("raw")))

    agg = aggregate(rows)
    write_results(args.out, rows)
    write_raw(args.raw_out, envelopes)
    print(render_scorecard(rows, agg))
    print(f"\nResults CSV : {args.out}")
    print(f"Raw JSONL   : {args.raw_out}  (inspect for the real count/quality slugs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
