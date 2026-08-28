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


def test_match_id_prefers_business_enigma_id_over_record_enigma_id():
    # The ID endpoint wants the `B…` business id; the record-level `E…` enigma_id 400s it. A match
    # record carries BOTH — pick the business id. (This is the fix for the first probe's 400s.)
    raw = {"businesses": [{"enigma_id": "E002a21f1a0003b1c9",
                           "business_enigma_id": "B0005383bbdb1"}]}
    assert enigma_probe.match_id_from_response(raw) == "B0005383bbdb1"


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


def test_principal_from_associated_people_in_match_response():
    # The real match envelope (logged 2026-08-27) carries the principal under `associated_people`.
    raw = {"associated_people": [{"name": "ALFRED MARZOUK",
                                  "titles": ["DIRECTOR", "CHIEF EXECUTIVE OFFICER"]}]}
    assert enigma_probe.extract_principal_name(raw) == "ALFRED MARZOUK"


def test_principal_from_registered_agents_list_of_strings():
    raw = {"registered_agents": ["ALFRED MARZOUK", "STEVEN SALANT"]}
    assert enigma_probe.extract_principal_name(raw) == "ALFRED MARZOUK"


def test_no_principal_yields_none():
    assert enigma_probe.extract_principal_name({"industries": ["plumbing"]}) is None
    assert enigma_probe.extract_principal_name(None) is None


# --- real logged match envelope (the probe's captured ground truth, 2026-08-27) ---------------

# A verbatim match record from the first live probe (market 9238e737, "MR SPEEDY PLUMBING ROOTER"):
# the ONE sampled business that carried a principal, with both id forms and the card-data source.
_REAL_MATCH_RAW = {"businesses": [{
    "match_confidence": 1.0,
    "is_matched": True,
    "enigma_id": "E00xxxxxxxxxxxxxx",
    "business_enigma_id": "B000deadbeef1",
    "names": [{"name": "MR SPEEDY PLUMBING ROOTER INC"}],
    "associated_people": [{"name": "ALFRED MARZOUK",
                           "titles": ["DIRECTOR", "SECRETARY", "CHIEF EXECUTIVE OFFICER"]}],
    "registered_agents": ["ALFRED MARZOUK", "STEVEN SALANT"],
    "year_incorporated": "2008",
    "data_sources": ["Card Transactions", "Public Web Directories", "Corporate Registrations"],
}]}


def test_real_envelope_id_is_the_business_id():
    assert enigma_probe.match_id_from_response(_REAL_MATCH_RAW) == "B000deadbeef1"


def test_real_envelope_principal_is_extracted_from_match():
    assert enigma_probe.extract_principal_name(_REAL_MATCH_RAW) == "ALFRED MARZOUK"


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


def _result(pid, *, enigma_id="", id_raw=None, match_raw=None):
    id_call = SimpleNamespace(raw=id_raw, status=(200 if id_raw is not None else None)) if id_raw is not None else None
    match_call = SimpleNamespace(ok=bool(enigma_id), raw=match_raw)
    return SimpleNamespace(prospect_id=pid, enigma_id=enigma_id, id_call=id_call, match_call=match_call)


def test_principal_name_from_result_reads_match_when_id_call_empty():
    # Principals ride the MATCH response; a matched business with no id-call principal still counts.
    r = _result("x", enigma_id="B0abc1234567",
                match_raw={"businesses": [{"associated_people": [{"name": "Dana Lee"}]}]})
    assert enigma_probe.principal_name_from_result(r) == "Dana Lee"


def test_card_transactions_from_result_reads_id_call():
    r = _result("x", enigma_id="B0abc1234567",
                id_raw={"card_transactions": {"1m": {"average_monthly_amount": 500}}})
    assert enigma_probe.card_transactions_from_result(r) == {"1m": 500}


def test_probe_metrics():
    results = [
        # un-named, matched, Enigma named the owner in the MATCH response → the headline hit
        _result("u1", enigma_id="B0aaaaaaaaaa",
                match_raw={"businesses": [{"associated_people": [{"first_name": "Amy",
                                                                  "last_name": "Cole"}]}]},
                id_raw={"card_transactions": {"12m": {"average_monthly_amount": 900}}}),
        # un-named, matched, no principal, but has card data from the id call
        _result("u2", enigma_id="B0bbbbbbbbbb",
                id_raw={"card_transactions": {"3m": {"average_monthly_amount": 700}}}),
        # un-named, no match at all
        _result("u3"),
        # named control, matched, principal in id-call attributes
        _result("n1", enigma_id="B0cccccccccc", id_raw={"principals": [{"full_name": "Ben Diaz"}]}),
    ]
    unnamed = {"u1", "u2", "u3"}
    m = enigma_probe.probe_metrics(results, unnamed)
    assert m["total"] == 4
    assert m["matched"] == 3 and m["match_rate"] == 0.75
    assert m["unnamed_sampled"] == 3
    assert m["owner_name_hits_on_unnamed"] == 1  # only u1 got a name (from its match response)
    assert m["owner_name_hit_on_unnamed"] == round(1 / 3, 3)
    assert m["card_windows_present"] == 2  # u1 + u2 (n1 has no card block)
    assert m["card_fill_of_matched"] == round(2 / 3, 3)


def test_probe_metrics_empty_is_safe():
    m = enigma_probe.probe_metrics([], set())
    assert m["match_rate"] == 0.0 and m["owner_name_hit_on_unnamed"] == 0.0
