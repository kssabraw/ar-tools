"""Unit tests for the monetization print (valuation plan v1 step 3)."""
from services import leadoff_monetization as lm

P = {"rent_discount": 0.6, "shared_price_ratio": 0.35, "n_buyers": 4}


def test_three_models_computed():
    # 10 leads/mo × $200 exclusive CPL = $2,000 PPL-exclusive
    m = lm.monetization(value_mo=2000, leads_mo=10, cpl=200, **P)
    assert m["ppl_exclusive_mo"] == 2000
    assert m["rank_and_rent_mo"] == 1200                 # 2000 × 0.6
    assert m["shared_price"] == 70                       # 200 × 0.35
    assert m["ppl_shared_mo"] == 2800                    # 10 × 70 × 4
    assert m["n_buyers"] == 4


def test_rank_and_rent_is_a_discount_of_exclusive_not_a_second_stream():
    m = lm.monetization(value_mo=1000, leads_mo=5, cpl=200, **P)
    assert m["rank_and_rent_mo"] < m["ppl_exclusive_mo"]


def test_missing_inputs_are_none_not_zero():
    m = lm.monetization(value_mo=None, leads_mo=None, cpl=None, **P)
    assert m["ppl_exclusive_mo"] is None
    assert m["rank_and_rent_mo"] is None
    assert m["shared_price"] is None
    assert m["ppl_shared_mo"] is None
    # shared needs both leads and a shared price
    m2 = lm.monetization(value_mo=1000, leads_mo=None, cpl=200, **P)
    assert m2["ppl_shared_mo"] is None


def test_attach_is_best_effort_and_reads_row_fields():
    row = {"value_mo": 900, "est_leads_mo": 6, "cpl": 150}
    out = lm.attach(dict(row), value_mo_key="value_mo",
                    leads_key="est_leads_mo", cpl_key="cpl")
    assert out["monetization"]["ppl_exclusive_mo"] == 900
    # a row missing everything still gets a monetization block (all None), never raises
    out2 = lm.attach({})
    assert "monetization" in out2
