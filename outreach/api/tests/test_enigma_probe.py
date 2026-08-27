"""Pure Enigma-probe helpers — id/name/card extraction + the §3 decision metrics.

The real Enigma schema is unconfirmed (the probe logs the raw so it can be read on the first live
run), so these tests pin the DOCUMENTED shapes AND the tolerance: a wrapper we didn't expect, a
period alias, a nested id all still resolve, and an unrecognised shape yields None rather than
raising. When the first live run reveals the true field names, add a fixture from the logged raw."""

from types import SimpleNamespace

from api.services import enigma_probe


# --- match id extraction ----------------------------------------------------------------------


def test_looks_like_enigma_id():
    assert enigma_probe.looks_like_enigma_id("B00233ee1f5e")
    assert not enigma_probe.looks_like_enigma_id("")
    assert not enigma_probe.looks_like_enigma_id("Joe's Plumbing")  # a name, not an id
    assert not enigma_probe.looks_like_enigma_id(None)


def test_match_id_from_a_list_of_matches():
    raw = [{"id": "B00233ee1f5e", "confidence": 0.9}, {"id": "Bffffffffffff"}]
    assert enigma_probe.match_id_from_response(raw) == "B00233ee1f5e"


def test_match_id_under_a_wrapper_key():
    raw = {"matches": [{"enigma_id": "B0abc123def0", "confidence": "high"}]}
    assert enigma_probe.match_id_from_response(raw) == "B0abc123def0"


def test_match_id_nested_in_a_business_object():
    raw = {"businesses": [{"business": {"id": "B0deadbeef12"}}]}
    assert enigma_probe.match_id_from_response(raw) == "B0deadbeef12"


def test_no_match_yields_none():
    assert enigma_probe.match_id_from_response({"matches": []}) is None
    assert enigma_probe.match_id_from_response({"error": "no match"}) is None
    assert enigma_probe.match_id_from_response(None) is None


# --- principal name extraction ----------------------------------------------------------------


def test_principal_from_first_last():
    raw = {"principals": [{"first_name": "Rex", "last_name": "Mcgee", "title": "Owner"}]}
    assert enigma_probe.extract_principal_name(raw) == "Rex Mcgee"


def test_principal_from_full_name_under_owner_key():
    raw = {"owner": {"full_name": "Natalie Downey"}}
    assert enigma_probe.extract_principal_name(raw) == "Natalie Downey"


def test_no_principal_yields_none():
    assert enigma_probe.extract_principal_name({"industries": ["plumbing"]}) is None
    assert enigma_probe.extract_principal_name(None) is None


# --- card-transaction extraction --------------------------------------------------------------


def test_card_transactions_period_dict_native_windows():
    raw = {"card_transactions": {
        "1m": {"average_monthly_amount": 120},
        "3m": {"average_monthly_amount": 110},
        "12m": {"average_monthly_amount": 100},
    }}
    assert enigma_probe.extract_card_transactions(raw) == {"1m": 120, "3m": 110, "12m": 100}


def test_card_transactions_alias_periods_and_list_shape():
    raw = {"card_revenues": [
        {"three_month": {"amount": 5000}},
        {"twelve_month": {"amount": 4800}},
    ]}
    got = enigma_probe.extract_card_transactions(raw)
    assert got == {"3m": 5000, "12m": 4800}


def test_no_card_block_yields_none():
    assert enigma_probe.extract_card_transactions({"principals": []}) is None
    assert enigma_probe.extract_card_transactions(None) is None


# --- decision metrics -------------------------------------------------------------------------


def _result(pid, *, enigma_id="", id_raw=None):
    id_call = SimpleNamespace(raw=id_raw) if id_raw is not None else None
    match_call = SimpleNamespace(ok=bool(enigma_id))
    return SimpleNamespace(prospect_id=pid, enigma_id=enigma_id, id_call=id_call, match_call=match_call)


def test_probe_metrics():
    results = [
        # un-named, matched, Enigma named the owner → the headline hit
        _result("u1", enigma_id="B0aaaaaaaaaa",
                id_raw={"principals": [{"first_name": "Amy", "last_name": "Cole"}],
                        "card_transactions": {"12m": {"amount": 900}}}),
        # un-named, matched, no principal, but has card data
        _result("u2", enigma_id="B0bbbbbbbbbb",
                id_raw={"card_transactions": {"3m": {"amount": 700}}}),
        # un-named, no match at all
        _result("u3"),
        # named control, matched
        _result("n1", enigma_id="B0cccccccccc", id_raw={"principals": [{"full_name": "Ben Diaz"}]}),
    ]
    unnamed = {"u1", "u2", "u3"}
    m = enigma_probe.probe_metrics(results, unnamed)
    assert m["total"] == 4
    assert m["matched"] == 3 and m["match_rate"] == 0.75
    assert m["unnamed_sampled"] == 3
    assert m["owner_name_hits_on_unnamed"] == 1  # only u1 got a name
    assert m["owner_name_hit_on_unnamed"] == round(1 / 3, 3)
    assert m["card_windows_present"] == 2  # u1 + u2 (n1 has no card block)
    assert m["card_fill_of_matched"] == round(2 / 3, 3)


def test_probe_metrics_empty_is_safe():
    m = enigma_probe.probe_metrics([], set())
    assert m["match_rate"] == 0.0 and m["owner_name_hit_on_unnamed"] == 0.0
