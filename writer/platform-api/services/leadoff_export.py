"""LeadOff — rebuild the app-facing ``leadoff_board`` table from the raw scan.

The app reads ``market_scanner.leadoff_board`` (the graded/economics board). That
table is a **computed export** of ``market_scanner.market_opportunity_master``:
for the current run it keeps the ``supply_measured`` + non-``low_coverage`` rows,
recomputes xdemand / rankability / lead economics / build-score + grade, joins
``field_quality`` for the WPA columns, and materializes the 20-column board.

Historically that export was a one-off (done during the 2026-07 app integration);
nothing in the scanner pipeline regenerated it, so a re-scan (e.g. adding the
15k-30k population tier) landed in ``market_opportunity_master`` but never reached
the app. This module makes the export **repeatable and machine-independent** —
every input already lives in Supabase, so it runs from anywhere with the service
role, no scanner machine required.

This is a faithful pure-Python port of the reference ``report.py`` computation
(``docs/reference/leadoff-scanner/report.py`` lines 93-217) at the board's default
assumptions (capture 0.10, mid lead tier) — the exact settings the stored
``build``/``grade`` are computed under, so the app's default-assumption display is
reproduced and its non-default recompute (``services/leadoff.recompute_economics``)
stays consistent via the regenerated ``exp_val_percentiles``.

Pure (no I/O). The impure DB read/write is ``scripts/export_leadoff_board.py``.
Unit-tested in ``tests/test_leadoff_export.py``.
"""
from __future__ import annotations

from statistics import median
from typing import Any, Optional

# Must match services.leadoff._GRADE_BANDS and report.py's pd.cut bins exactly:
# bins [0,50,75,90,94,97,99,101] right=False, labels F/D/C/B/B+/A/A+.
GRADE_BANDS = [(99, "A+"), (97, "A"), (94, "B+"), (90, "B"), (75, "C"), (50, "D")]
DEFAULT_CAPTURE = 0.10
DEFAULT_TIER = "mid"

# The leadoff_board column set (report.py's output selection), minus as_of.
BOARD_COLUMNS = [
    "grade", "luck", "conf", "build", "roi", "exp_val", "value_mo", "rankab",
    "city_name", "state_code", "category", "xdem", "rev_win", "rating",
    "namekw", "exact_open", "v3", "city_id", "category_id", "population",
]


def _f(x: Any) -> Optional[float]:
    """Coerce to float, or None for null/blank/non-numeric (pandas NaN analog)."""
    if x is None or x == "":
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None  # drop NaN


def grade_for_score(score: Optional[float]) -> str:
    """Letter grade from a 0-100 build score. Mirrors services.leadoff.grade_for's
    band walk (highest cut first; below 50 -> F). None -> F."""
    if score is None:
        return "F"
    for cut, grade in GRADE_BANDS:
        if score >= cut:
            return grade
    return "F"


def percentile_rank(values: list[float]) -> list[float]:
    """pandas ``Series.rank(pct=True) * 100`` with the default 'average' tie
    method: each value's percentile = (mean 1-indexed position among all values)
    / n * 100. Ties share the average of their positions. Values must be present
    (the caller 0-fills exp_val, as report.py does), so there are no NaNs to skip.
    """
    n = len(values)
    if n == 0:
        return []
    order = sorted(range(n), key=lambda i: values[i])
    out = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg_pos = (i + 1 + j + 1) / 2.0  # mean of 1-indexed positions i+1..j+1
        pct = 100.0 * avg_pos / n
        for k in range(i, j + 1):
            out[order[k]] = pct
        i = j + 1
    return out


def _demand_fields(rows: list[dict[str, Any]]) -> list[dict[str, Optional[float]]]:
    """Per-row {xdemand, expected, dem_ratio} — the xFIP regression + its inputs.

    expected = per-category median(obs/pop) * pop  (falling back to obs when the
    category has no rate); winsorize obs to 4*expected; xdemand = 0.75*wins +
    0.25*expected. Mirrors report.py lines 97-114.
    """
    obs = [_f(r.get("demand_vol")) for r in rows]
    pop = [_f(r.get("population")) for r in rows]
    rates_by_cat: dict[Any, list[float]] = {}
    for r, o, p in zip(rows, obs, pop):
        if o is not None and p:
            rates_by_cat.setdefault(r.get("category_id"), []).append(o / p)
    cat_rate = {c: median(v) for c, v in rates_by_cat.items() if v}

    out: list[dict[str, Optional[float]]] = []
    for r, o, p in zip(rows, obs, pop):
        cr = cat_rate.get(r.get("category_id"))
        expected = (cr * p) if (cr is not None and p is not None) else o
        if o is not None and expected is not None:
            wins = min(o, 4.0 * expected)
        else:
            wins = o  # NaN-clip-by-NaN leaves obs unchanged
        base = wins if wins is not None else expected
        if base is not None and expected is not None:
            xdem = round(0.75 * base + 0.25 * expected)
        elif base is not None:
            xdem = round(base)
        else:
            xdem = None
        dem_ratio = (o / expected) if (o is not None and expected not in (None, 0)) else None
        out.append({"xdemand": xdem, "expected": expected,
                    "dem_ratio": round(dem_ratio, 2) if dem_ratio is not None else None})
    return out


def _luck(rows: list[dict[str, Any]],
          demand: list[dict[str, Optional[float]]]) -> list[str]:
    """BABIP luck flag, park-adjusted against the CITY's own median demand ratio.
    HOT? = rel >= 2, COLD? = rel <= 0.5, else '-'. Mirrors report.py 115-121."""
    ratios_by_city: dict[tuple, list[float]] = {}
    for r, d in zip(rows, demand):
        dr = d["dem_ratio"]
        if dr is not None:
            ratios_by_city.setdefault((r.get("city_name"), r.get("state_code")), []).append(dr)
    city_norm = {k: median(v) for k, v in ratios_by_city.items() if v}

    out: list[str] = []
    for r, d in zip(rows, demand):
        dr = d["dem_ratio"]
        norm = city_norm.get((r.get("city_name"), r.get("state_code")))
        rel = (dr / norm) if (dr is not None and norm not in (None, 0)) else None
        if rel is None:
            out.append("-")
        elif rel >= 2:
            out.append("HOT?")
        elif rel <= 0.5:
            out.append("COLD?")
        else:
            out.append("-")
    return out


def _rankability(avg_top5_reviews: Optional[float],
                 exact_cat_holders: Optional[float]) -> float:
    """0-1 win-likelihood: 0.75 field-weakness + 0.25 open-exact-category.
    Mirrors report.py 131-134."""
    rf = 1.0 / (1.0 + (avg_top5_reviews or 0.0) / 50.0)
    ef = 1.0 / (1.0 + (exact_cat_holders or 0.0) / 5.0)
    return round(0.75 * rf + 0.25 * ef, 2)


def _conf(xdemand: Optional[float]) -> str:
    """Demand-bucket confidence: <50 low, <260 med, else high (report.py 168)."""
    x = xdemand or 0.0
    if x < 50:
        return "low"
    if x < 260:
        return "med"
    return "high"


def build_board_rows(master_rows: list[dict[str, Any]],
                     field_quality: dict[tuple, dict[str, Any]],
                     cat_id_to_name: dict[Any, str],
                     cat_name_to_cpl: dict[str, float],
                     *, capture: float = DEFAULT_CAPTURE,
                     as_of: str) -> list[dict[str, Any]]:
    """Compute the leadoff_board rows from the run's ``supply_measured`` master
    rows (INCLUDING thin/low_coverage rows, so the national exp-value percentile
    denominator matches report.py — thin rows are dropped from the OUTPUT only).

    ``field_quality`` is keyed by (int city_id, str category_id) →
    {rev_to_win, top5_rating, name_match}. ``cat_name_to_cpl`` maps category name
    → the tier's CPL. Pure; returns rows ready to insert (with ``as_of``).
    """
    n = len(master_rows)
    demand = _demand_fields(master_rows)
    luck = _luck(master_rows, demand)

    names = [cat_id_to_name.get(r.get("category_id"), r.get("category_id"))
             for r in master_rows]
    rankab = [_rankability(_f(r.get("avg_top5_reviews")),
                           _f(r.get("exact_cat_holders"))) for r in master_rows]
    lead_value = [cat_name_to_cpl.get(names[i]) for i in range(n)]

    est_leads: list[int] = []
    est_value: list[Optional[int]] = []
    exp_value: list[int] = []
    for i in range(n):
        xd = demand[i]["xdemand"] or 0.0
        leads = round(xd * capture)
        est_leads.append(leads)
        lv = lead_value[i]
        val = round(leads * lv) if lv is not None else None
        est_value.append(val)
        # exp_value uses value-or-0, so it is never null (report.py line 136)
        exp_value.append(round((val or 0) * rankab[i]))

    exp_pct = percentile_rank([float(v) for v in exp_value])

    rows: list[dict[str, Any]] = []
    for i, r in enumerate(master_rows):
        if r.get("low_coverage") is True:
            continue  # thin categories: ranked above, excluded from output
        # build score: exp percentile, capped for tiny/brutal markets, 0 if no $
        bs = exp_pct[i]
        if est_leads[i] < 5 or rankab[i] < 0.15:
            bs = min(bs, 74.9)
        if lead_value[i] is None:
            bs = 0.0
        bs = round(bs, 1)

        fq = field_quality.get((int(r["city_id"]), str(r.get("category_id")))) or {}
        rev_win = _f(fq.get("rev_to_win"))
        roi = round((exp_value[i]) / max(rev_win if rev_win is not None else 10.0, 10.0), 1)

        v3 = _f(r.get("opportunity_score_v3"))
        rows.append({
            "grade": grade_for_score(bs),
            "luck": luck[i],
            "conf": _conf(demand[i]["xdemand"]),
            "build": bs,
            "roi": roi,
            "exp_val": int(exp_value[i]),
            "value_mo": int(est_value[i]) if est_value[i] is not None else None,
            "rankab": rankab[i],
            "city_name": r.get("city_name"),
            "state_code": r.get("state_code"),
            "category": names[i],
            "xdem": int(demand[i]["xdemand"]) if demand[i]["xdemand"] is not None else None,
            "rev_win": rev_win,
            "rating": _f(fq.get("top5_rating")),
            "namekw": _f(fq.get("name_match")),
            "exact_open": int(r["exact_cat_holders"]) if r.get("exact_cat_holders") is not None else None,
            "v3": round(v3, 1) if v3 is not None else None,
            "city_id": int(r["city_id"]),
            "category_id": r.get("category_id"),
            "population": int(r["population"]) if r.get("population") is not None else None,
            "as_of": as_of,
        })
    return rows


def build_percentiles(exp_vals: list[int]) -> list[dict[str, float]]:
    """The 101-point national exp_val percentile reference (pct 0..100) that
    ``services.leadoff.percentile_of`` reads for non-default-assumption grades.
    Linear-interpolated percentiles over the board's exp_val distribution."""
    if not exp_vals:
        return []
    xs = sorted(float(v) for v in exp_vals)
    m = len(xs)
    out: list[dict[str, float]] = []
    for pct in range(101):
        if m == 1:
            out.append({"pct": float(pct), "exp_val": xs[0]})
            continue
        pos = pct / 100.0 * (m - 1)
        lo = int(pos)
        frac = pos - lo
        val = xs[lo] if lo + 1 >= m else xs[lo] + frac * (xs[lo + 1] - xs[lo])
        out.append({"pct": float(pct), "exp_val": round(val, 2)})
    return out
