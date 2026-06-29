"""Unit tests for GBP business-type classification (no network)."""

from __future__ import annotations

from services.gbp_service import _address_hidden, classify_business_type


# --- classify_business_type -------------------------------------------------
def test_physical_has_address_no_service_area():
    assert classify_business_type({"address": "12 Help St, Chatswood NSW", "service_area_places": []}) == "physical"


def test_sab_service_area_no_address():
    assert classify_business_type({"address": "", "service_area_places": ["Chatswood", "Lane Cove"]}) == "sab"


def test_hybrid_has_both():
    assert classify_business_type({"address": "12 Help St", "service_area_places": ["Chatswood"]}) == "hybrid"


def test_unknown_when_neither():
    assert classify_business_type({"address": "", "service_area_places": []}) == "unknown"
    assert classify_business_type({}) == "unknown"
    assert classify_business_type(None) == "unknown"


# --- the tighter signal: address_hidden overrides the address heuristic ------
def test_hidden_address_is_sab_even_with_registered_address():
    # The previous weakness: a SAB that still exposes a registered address used to
    # read as 'hybrid'/'physical'. The address_hidden flag now classifies it 'sab'.
    gbp = {"address": "12 Help St, Chatswood NSW", "service_area_places": ["Chatswood"], "address_hidden": True}
    assert classify_business_type(gbp) == "sab"
    assert classify_business_type({"address": "12 Help St", "address_hidden": True}) == "sab"


def test_address_shown_with_service_areas_is_hybrid():
    gbp = {"address": "12 Help St", "service_area_places": ["Chatswood"], "address_hidden": False}
    assert classify_business_type(gbp) == "hybrid"


def test_falls_back_to_heuristic_when_flag_absent():
    # address_hidden None → same as before (address present, no areas → physical).
    assert classify_business_type({"address": "12 Help St", "address_hidden": None}) == "physical"


# --- _address_hidden extraction ---------------------------------------------
def test_address_hidden_reads_area_service_bool_and_strings():
    assert _address_hidden({"area_service": True}) is True
    assert _address_hidden({"area_service": False}) is False
    assert _address_hidden({"area_service": "true"}) is True
    assert _address_hidden({"is_service_area_business": "no"}) is False


def test_address_hidden_ignores_place_name_lists_and_missing():
    # area_service as a *list of served places* is not a hidden-address flag.
    assert _address_hidden({"area_service": ["Chatswood", "Lane Cove"]}) is None
    assert _address_hidden({}) is None
