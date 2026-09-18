"""Unit tests for the per-market income local modifier + the CPC/income blend
(valuation plan v1.5). All pure — no DB, no config."""
from services import leadoff_income_modifier as lim

INC = {"lo": 0.85, "hi": 1.2, "min_income": 20000}
NATL = 78921.0

# A params bundle mirroring config defaults (kept explicit so the tests don't
# depend on config): CPC bounds [0.7, 1.5], income bounds [0.85, 1.2], weights
# 0.7 / 0.3, total clamp = widest of both = [0.7, 1.5].
P = {
    "enabled": True,
    "cpc_lo": 0.7, "cpc_hi": 1.5, "cpc_min_cpc": 0.5,
    "inc_lo": 0.85, "inc_hi": 1.2, "min_income": 20000, "national_median": NATL,
    "w_cpc": 0.7, "w_income": 0.3, "total_lo": 0.7, "total_hi": 1.5,
}


# ── income_modifier (bidirectional ratio) ──────────────────────────────────────

def test_income_modifier_above_and_below_median():
    # above the national median → premium (capped at hi)
    assert lim.income_modifier(NATL * 1.1, NATL, **INC) == 1.1
    assert lim.income_modifier(NATL * 3, NATL, **INC) == 1.2      # capped
    # below → discount (floored at lo)
    assert lim.income_modifier(NATL * 0.9, NATL, **INC) == 0.9
    assert lim.income_modifier(NATL * 0.3, NATL, **INC) == 0.85   # floored
    # exactly at the median → 1.0 (present, not absent)
    assert lim.income_modifier(NATL, NATL, **INC) == 1.0


def test_income_modifier_absent_on_missing_or_thin():
    assert lim.income_modifier(None, NATL, **INC) is None
    assert lim.income_modifier(90000, None, **INC) is None
    assert lim.income_modifier(5000, NATL, **INC) is None         # below min_income
    assert lim.income_modifier(90000, 100, **INC) is None         # national thin
    assert lim.income_modifier("bad", NATL, **INC) is None


# ── combine (renormalizing weighted-deviation blend) ───────────────────────────

def test_combine_single_signal_is_returned_unchanged():
    # CPC-only (income absent) → the CPC modifier verbatim (byte-identical to v1)
    assert lim.combine([(1.5, 0.7), (None, 0.3)], lo=0.7, hi=1.5) == 1.5
    assert lim.combine([(0.7, 0.7), (None, 0.3)], lo=0.7, hi=1.5) == 0.7
    # income-only → the income modifier verbatim
    assert lim.combine([(None, 0.7), (1.2, 0.3)], lo=0.7, hi=1.5) == 1.2
    # a present genuine 1.0 is still the single signal (not treated as absent)
    assert lim.combine([(1.0, 0.7), (None, 0.3)], lo=0.7, hi=1.5) == 1.0


def test_combine_no_present_signal_is_neutral():
    assert lim.combine([(None, 0.7), (None, 0.3)], lo=0.7, hi=1.5) == 1.0
    assert lim.combine([], lo=0.7, hi=1.5) == 1.0
    # a zero weight is not "present"
    assert lim.combine([(1.5, 0.0), (None, 0.3)], lo=0.7, hi=1.5) == 1.0


def test_combine_both_present_is_weighted_deviation_and_conservative():
    # cpc 1.5 (dev +0.5), income 1.2 (dev +0.2), weights .7/.3
    #   dev = (.7*.5 + .3*.2)/1.0 = .41 → 1.41
    assert lim.combine([(1.5, 0.7), (1.2, 0.3)], lo=0.7, hi=1.5) == 1.41
    # both cold: cpc .7 (−0.3), income .85 (−0.15) → (.7*−.3 + .3*−.15) = −0.255 → 0.745
    assert lim.combine([(0.7, 0.7), (0.85, 0.3)], lo=0.7, hi=1.5) == 0.745
    # the blend always sits BETWEEN the two individual modifiers (never more extreme)
    blended = lim.combine([(1.5, 0.7), (1.2, 0.3)], lo=0.7, hi=1.5)
    assert 1.2 <= blended <= 1.5


def test_combine_clamps_to_total_bounds():
    # two signals pulling the same way can't exceed the total clamp
    assert lim.combine([(1.5, 0.7), (1.5, 0.3)], lo=0.7, hi=1.5) == 1.5


# ── local_modifier (the caller entry: CPC baseline lookup + blend + detail) ────

def test_local_modifier_blends_and_records_detail():
    baseline = {"roofing contractor": 20.0}  # national median CPC for the category
    # market CPC 30 → cpc ratio 1.5; city income 1.1× national → income 1.1
    combined, detail = lim.local_modifier(30.0, "Roofing Contractor",
                                          NATL * 1.1, baseline, P)
    assert detail == {"cpc": 1.5, "income": 1.1}
    # cpc 1.5 (dev +0.5), income 1.1 (dev +0.1), weights .7/.3 → 1 + .38 = 1.38
    assert combined == 1.38


def test_local_modifier_cpc_only_is_byte_identical_when_income_absent():
    baseline = {"roofing contractor": 20.0}
    # no city income → income signal absent → combined == the CPC modifier exactly
    combined, detail = lim.local_modifier(30.0, "Roofing Contractor",
                                          None, baseline, P)
    assert detail == {"cpc": 1.5, "income": None}
    assert combined == 1.5


def test_local_modifier_income_disabled_drops_income():
    baseline = {"roofing contractor": 20.0}
    p_off = {**P, "enabled": False}
    combined, detail = lim.local_modifier(30.0, "Roofing Contractor",
                                          NATL * 1.1, baseline, p_off)
    assert detail == {"cpc": 1.5, "income": None}   # income not computed
    assert combined == 1.5                           # byte-identical to CPC-only


def test_local_modifier_income_only_when_cpc_absent():
    # category not in the baseline → CPC absent; income carries full weight
    combined, detail = lim.local_modifier(30.0, "Unknown", NATL * 1.1, {}, P)
    assert detail == {"cpc": None, "income": 1.1}
    assert combined == 1.1


def test_local_modifier_neutral_when_both_absent():
    combined, detail = lim.local_modifier(None, "Unknown", None, {}, P)
    assert detail == {"cpc": None, "income": None}
    assert combined == 1.0
