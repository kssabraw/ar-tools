"""Unit tests for the LeadOff Enigma coverage-pilot harness's pure logic (no I/O).

The Enigma GraphQL response shape is the one the outreach module verified against
a live eval key (outreach/api/services/enigma_graphql.py) — a single
``cardTransactions`` connection of ``{period, projectedQuantity, rawQuantity,
periodStartDate, periodEndDate}`` edges, with ``enigmaId: null`` on a real match.
These fixtures encode that shape; the harness's raw-envelope JSONL lets the owner
confirm/adjust the count/quality slugs on the first live run.

The harness is a standalone script (scripts/enigma_coverage_pilot.py), imported
here by path — its pure helpers drive a go/no-go vendor decision, so a
sign-flipped threshold would mislead it; that is exactly what these lock down.
"""

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "enigma_coverage_pilot.py"
_spec = importlib.util.spec_from_file_location("enigma_coverage_pilot", _SCRIPT)
ecp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ecp)


# ── helpers to build synthetic Enigma responses ────────────────────────────────

def _revenue_edges(**by_period):
    return {"edges": [{"node": {"period": p, "projectedQuantity": v,
                                "periodEndDate": "2026-06-30"}}
                      for p, v in by_period.items()]}


def _entity(*, name="ABS Restoration", revenue=None, txns=None):
    ent = {"enigmaId": None, "names": {"edges": [{"node": {"name": name}}]}}
    if revenue is not None:
        ent["revenue"] = _revenue_edges(**revenue)
    if txns is not None:
        ent["txns"] = _revenue_edges(**txns)
    return ent


def _resp(*entities):
    return {"data": {"search": list(entities)}}


# ── build_query / build_variables ──────────────────────────────────────────────

def test_build_query_brand_has_both_aliases_and_periods():
    q = ecp.build_query("brand", ["1m", "12m"], "card_transactions_count")
    assert "... on Brand" in q
    assert "revenue: cardTransactions" in q
    assert "card_revenue_amount" in q
    assert "txns: cardTransactions" in q
    assert "card_transactions_count" in q
    assert '["1m", "12m"]' in q


def test_build_query_operating_location_and_no_count():
    q = ecp.build_query("operating_location", ["12m"], None)
    assert "... on OperatingLocation" in q
    assert "txns: cardTransactions" not in q  # count alias omitted when disabled


def test_build_variables_only_sends_present_parts():
    biz = {"name": "ABS", "street": "5301 Warden Rd", "city": "Little Rock",
           "state": "AR", "postal_code": "", "website": "absrs.com"}
    v = ecp.build_variables(biz, 0.5, "brand")["si"]
    assert v["entityType"] == "BRAND"
    assert v["matchThreshold"] == 0.5
    assert v["name"] == "ABS"
    assert v["address"] == {"street1": "5301 Warden Rd", "city": "Little Rock",
                            "state": "AR"}  # no empty postalCode
    assert v["website"] == "absrs.com"


def test_build_variables_no_address_when_all_blank():
    v = ecp.build_variables({"name": "X"}, 0.4, "brand")["si"]
    assert "address" not in v and "website" not in v


# ── match detection (the enigmaId-null gotcha) ─────────────────────────────────

def test_is_match_true_even_with_null_enigma_id():
    assert ecp.is_match(_resp(_entity(revenue={"12m": 100000.0}))) is True


def test_is_match_false_on_empty_or_error_shapes():
    assert ecp.is_match({"data": {"search": []}}) is False
    assert ecp.is_match({"errors": [{"message": "bad"}]}) is False
    assert ecp.is_match(None) is False


def test_matched_name_flags_wrong_business():
    ent = _entity(name="Totally Different LLC", revenue={"12m": 5.0})
    assert ecp.matched_name(ent) == "Totally Different LLC"


# ── card parsing ───────────────────────────────────────────────────────────────

def test_card_windows_prefers_projected_and_ignores_bad():
    ent = {"revenue": {"edges": [
        {"node": {"period": "12m", "projectedQuantity": 500000, "rawQuantity": 1}},
        {"node": {"period": "1m", "rawQuantity": 40000}},          # fallback to raw
        {"node": {"period": "3m", "projectedQuantity": None}},     # dropped
    ]}}
    assert ecp.card_windows(ent, "revenue") == {"12m": 500000.0, "1m": 40000.0}


def test_avg_ticket_and_divide_by_zero_guard():
    assert ecp.avg_ticket({"12m": 120000.0}, {"12m": 800.0}) == 150.0
    assert ecp.avg_ticket({"12m": 120000.0}, {"12m": 0}) is None      # no div-by-zero
    assert ecp.avg_ticket({"12m": 120000.0}, {}) is None              # count missing


def test_card_as_of_latest_iso_date():
    ent = {"revenue": {"edges": [
        {"node": {"period": "1m", "projectedQuantity": 1, "periodEndDate": "2026-06-30"}},
        {"node": {"period": "12m", "projectedQuantity": 2, "periodEndDate": "2026-05-31"}},
    ]}}
    assert ecp.card_as_of(ent) == "2026-06-30"


# ── trend ──────────────────────────────────────────────────────────────────────

def test_revenue_trend_yoy_from_24m():
    # 12m=120k, 24m=200k -> prior year = 80k -> yoy = +50% -> up
    t = ecp.revenue_trend({"12m": 120000.0, "24m": 200000.0})
    assert t["basis"] == "yoy_24m" and t["direction"] == "up" and t["yoy_pct"] == 50.0


def test_revenue_trend_run_rate_proxy_and_flat_band():
    # 1m*12 = 96k vs 12m 100k -> -4% -> within stable band -> flat
    t = ecp.revenue_trend({"1m": 8000.0, "12m": 100000.0})
    assert t["basis"] == "run_rate" and t["direction"] == "flat"
    # 1m*12 = 240k vs 100k -> +140% -> up
    assert ecp.revenue_trend({"1m": 20000.0, "12m": 100000.0})["direction"] == "up"


def test_revenue_trend_unknown_when_insufficient():
    assert ecp.revenue_trend({"12m": 100000.0})["direction"] == "unknown"
    assert ecp.revenue_trend({})["direction"] == "unknown"


# ── plausibility (§5.3 auto read) ──────────────────────────────────────────────

def test_plausibility_auto_bands():
    assert ecp.plausibility_auto(500.0, 3000.0, 40000.0) == "implausible_low"
    assert ecp.plausibility_auto(8000.0, 3000.0, 40000.0) == "plausible"
    assert ecp.plausibility_auto(90000.0, 3000.0, 40000.0) == "above_range"
    assert ecp.plausibility_auto(None, 3000.0, 40000.0) == "unknown"
    assert ecp.plausibility_auto(500.0, None, None) == "unknown"


# ── score_business end-to-end ──────────────────────────────────────────────────

def test_score_business_matched_row():
    biz = {"id": "a2", "bucket": "A", "name": "ABS Restoration",
           "category_avg_ticket_low": "3000", "category_avg_ticket_high": "40000"}
    raw = _resp(_entity(name="ABS Restoration",
                        revenue={"12m": 500000.0, "24m": 800000.0},
                        txns={"12m": 100.0}))
    row = ecp.score_business(biz, raw)
    assert row["matched"] is True
    assert row["bucket"] == "a"
    assert row["card_revenue_12m"] == 500000.0
    assert row["avg_ticket"] == 5000.0            # 500k/100
    assert row["plausible_auto"] == "plausible"   # 5000 in [3000,40000]
    assert row["trend_direction"] in ("up", "down", "flat")


def test_score_business_unmatched_is_all_none_not_crash():
    row = ecp.score_business({"id": "x", "bucket": "a", "name": "Nope"},
                             {"data": {"search": []}})
    assert row["matched"] is False
    assert row["card_revenue_12m"] is None
    assert row["avg_ticket"] is None
    assert row["plausible_auto"] == "unknown"
    assert row["trend_direction"] == "unknown"


# ── aggregate + §5 verdicts ────────────────────────────────────────────────────

def _row(bucket, matched, *, avg=None, trend="unknown", plaus="unknown",
         known_trend=""):
    return {"bucket": bucket, "matched": matched, "avg_ticket": avg,
            "trend_direction": trend, "plausible_auto": plaus,
            "known_trend": known_trend}


def test_coverage_strong_marginal_nogo():
    strong = ecp.aggregate([_row("a", True) for _ in range(4)] + [_row("a", False)])
    assert ecp.verdict_coverage(strong)[0] == "strong"       # 80%
    marg = ecp.aggregate([_row("a", True), _row("a", True), _row("a", False),
                          _row("a", False), _row("a", False)])
    assert ecp.verdict_coverage(marg)[0] == "marginal"       # 40%
    nogo = ecp.aggregate([_row("a", True)] + [_row("a", False) for _ in range(4)])
    assert ecp.verdict_coverage(nogo)[0] == "no_go"          # 20%


def test_coverage_control_gate_inconclusive():
    agg = ecp.aggregate([_row("a", True) for _ in range(5)] + [_row("control", False)])
    # even with 100% bucket-A coverage, an unmatched control => inconclusive
    assert ecp.verdict_coverage(agg)[0] == "inconclusive"


def test_growth_pass_and_fail_and_anchor_disagreement():
    ok = ecp.aggregate([_row("a", True, trend="up") for _ in range(4)]
                       + [_row("a", True, trend="unknown")])
    assert ecp.verdict_growth(ok)[0] == "pass"               # 80% trend present
    thin = ecp.aggregate([_row("a", True, trend="up")]
                         + [_row("a", True, trend="unknown") for _ in range(4)])
    assert ecp.verdict_growth(thin)[0] == "fail"             # 20%
    # a matched anchor whose known trend disagrees fails even with full presence
    disagree = ecp.aggregate([_row("b", True, trend="down", known_trend="up")])
    assert ecp.verdict_growth(disagree)[0] == "fail"


def test_lead_value_fail_pass_insufficient():
    fail = ecp.aggregate([_row("a", True, plaus="implausible_low") for _ in range(4)]
                         + [_row("a", True, plaus="plausible")])
    assert ecp.verdict_lead_value(fail)[0] == "fail"         # 20% plausible
    good = ecp.aggregate([_row("a", True, plaus="plausible") for _ in range(4)]
                         + [_row("a", True, plaus="implausible_low")])
    assert ecp.verdict_lead_value(good)[0] == "pass_auto"    # 80%
    none = ecp.aggregate([_row("a", True, plaus="unknown") for _ in range(3)])
    assert ecp.verdict_lead_value(none)[0] == "insufficient"


def test_decision_matrix_cells():
    assert "FULL NO-GO" in ecp.decision_matrix("no_go", "fail", "fail")
    assert "INCONCLUSIVE" in ecp.decision_matrix("inconclusive", "pass", "pass_auto")
    assert "BUILD GROWTH ONLY" in ecp.decision_matrix("strong", "pass", "fail")
    assert "second phase" in ecp.decision_matrix("strong", "pass", "pass_auto")
    assert "NO USABLE SIGNAL" in ecp.decision_matrix("marginal", "fail", "fail")


# ── ground-truth CSV reader ────────────────────────────────────────────────────

def test_read_ground_truth_skips_placeholder_hash_rows(tmp_path):
    csv_path = tmp_path / "gt.csv"
    csv_path.write_text(
        "id,bucket,name,street\n"
        "a1,a,Real Biz,1 Main St\n"
        "#b1,b,<FILL IN>,<street>\n"          # placeholder — skipped
        ",a,,\n",                              # blank name — skipped
        encoding="utf-8")
    rows = ecp.read_ground_truth(csv_path)
    assert [r["name"] for r in rows] == ["Real Biz"]


def test_read_ground_truth_rejects_missing_required_columns(tmp_path):
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text("name,street\nBiz,1 Main St\n", encoding="utf-8")
    try:
        ecp.read_ground_truth(csv_path)
        assert False, "expected ValueError for missing id/bucket"
    except ValueError as exc:
        assert "missing columns" in str(exc)


# ── the shipped ground-truth file is well-formed ───────────────────────────────

def test_shipped_ground_truth_has_bucket_a_and_control():
    rows = ecp.read_ground_truth(_SCRIPT.with_name("leadoff_enigma_ground_truth.csv"))
    buckets = {r["bucket"].strip().lower() for r in rows}
    # bucket A is pre-filled (real Little Rock competitors); B/control are '#'
    # placeholders the owner fills, so only 'a' is guaranteed present here.
    assert "a" in buckets
    assert len([r for r in rows if r["bucket"].strip().lower() == "a"]) == 5


# ── render + writers + main() wiring (CI-safe; HTTP layer monkeypatched) ────────

def test_render_scorecard_runs_and_flags_wrong_match():
    rows = [ecp.score_business(
        {"id": "a1", "bucket": "a", "name": "ABS Restoration",
         "category_avg_ticket_low": "3000", "category_avg_ticket_high": "40000"},
        _resp(_entity(name="A DIFFERENT LLC", revenue={"12m": 400000.0},
                      txns={"12m": 80.0})))]
    out = ecp.render_scorecard(rows, ecp.aggregate(rows))
    assert "OUTCOME" in out
    assert "matched a DIFFERENT name" in out   # the wrong-match QA warning fires


def test_write_results_and_raw_roundtrip(tmp_path):
    rows = [ecp.score_business({"id": "a1", "bucket": "a", "name": "ABS"},
                               _resp(_entity(revenue={"12m": 1.0})))]
    out = tmp_path / "res.csv"
    raw = tmp_path / "raw.jsonl"
    ecp.write_results(out, rows)
    ecp.write_raw(raw, [{"id": "a1", "status": 200, "raw": {"data": {"search": []}}}])
    body = out.read_text(encoding="utf-8")
    assert "plausible_human" in body.splitlines()[0]   # header carries the human col
    assert "ABS" in body
    assert raw.read_text(encoding="utf-8").strip().startswith("{")


def test_main_integration_writes_files_and_scores(tmp_path, monkeypatch, capsys):
    gt = tmp_path / "gt.csv"
    gt.write_text(
        "id,bucket,name,street,city,state,postal_code,website,category,"
        "category_avg_ticket_low,category_avg_ticket_high,known_revenue,known_trend,notes\n"
        "a1,a,ABS Restoration,5301 Warden Rd,Little Rock,AR,,absrs.com,water damage,3000,40000,,,\n"
        "c1,control,Corner Diner,1 Main St,Little Rock,AR,,diner.com,restaurant,15,60,,,\n",
        encoding="utf-8")

    def fake_lookup(_client, _url, _key, biz, **_kw):
        # ABS matches with card data; the diner (control) also matches.
        return {"id": biz["id"], "name": biz["name"], "status": 200, "error": None,
                "raw": _resp(_entity(name=biz["name"],
                                     revenue={"12m": 500000.0, "24m": 800000.0},
                                     txns={"12m": 100.0}))}

    monkeypatch.setattr(ecp, "lookup_one", fake_lookup)
    out = tmp_path / "res.csv"
    raw = tmp_path / "raw.jsonl"
    rc = ecp.main(["--key", "fake", "--graphql-url", "https://example/graphql",
                   "--ground-truth", str(gt), "--out", str(out), "--raw-out", str(raw)])
    assert rc == 0
    assert out.exists() and raw.exists()
    printed = capsys.readouterr().out
    assert "§5.4 OUTCOME" in printed
    # both matched -> bucket-A coverage 100% (strong), control matched
    assert "match rate = 100%" in printed
