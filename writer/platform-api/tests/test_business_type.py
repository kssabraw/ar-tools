"""Unit tests for GBP business-type classification (no network)."""

from __future__ import annotations

from services.gbp_service import classify_business_type


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
