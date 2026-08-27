"""Pure Enigma GraphQL parsers — match id / owner / card windows + the §3 decision metrics.

Grounded in the documented GraphQL response shapes (Relay edges/node nesting) and the console-batch
output columns the GraphQL paths mirror. The parsers are tolerant: an unrecognised shape yields
None/empty, never raises. The first live probe run logs the raw so a real fixture can be pinned.
"""

from types import SimpleNamespace

from api.services import enigma_graphql as eg


# --- variables ---------------------------------------------------------------------------------


def test_build_variables_name_and_address():
    v = eg.build_variables(
        {"name": "MR SPEEDY PLUMBING ROOTER INC", "street": "3130 E OLYMPIC BLVD",
         "city": "LOS ANGELES", "state": "CA", "postal_code": "90023"},
        0.7,
    )
    si = v["si"]
    assert si["entityType"] == "BRAND" and si["matchThreshold"] == 0.7
    assert si["name"] == "MR SPEEDY PLUMBING ROOTER INC"
    assert si["address"] == {"street1": "3130 E OLYMPIC BLVD", "city": "LOS ANGELES",
                             "state": "CA", "postalCode": "90023"}


def test_build_variables_omits_empty_address():
    v = eg.build_variables({"name": "Joe's Plumbing"}, 0.5)
    assert "address" not in v["si"] and v["si"]["name"] == "Joe's Plumbing"


def test_build_variables_entity_type():
    assert eg.build_variables({"name": "X"}, 0.7)["si"]["entityType"] == "BRAND"
    v = eg.build_variables({"name": "X"}, 0.7, "operating_location")
    assert v["si"]["entityType"] == "OPERATING_LOCATION"


def test_build_query_is_single_fragment_per_entity():
    # Both fragments in one document collide (BrandName.name String vs OperatingLocationName.name
    # String!), so each query carries ONLY the fragment for its entity type.
    brand_q = eg.build_query("brand")
    assert "... on Brand" in brand_q and "... on OperatingLocation" not in brand_q
    ol_q = eg.build_query("operating_location")
    assert "... on OperatingLocation" in ol_q and "... on Brand" not in ol_q
    # roles are read directly on the OperatingLocation, nested under operatingLocations for a Brand.
    assert "operatingLocations" in brand_q
    assert "fragment RoleFields on Role" in brand_q and "fragment RoleFields on Role" in ol_q


# --- a realistic matched-brand response --------------------------------------------------------

_BRAND = {
    "enigmaId": "5f53e079-c66a-487e-8a9d-08efc39652ee",
    "names": {"edges": [{"node": {"name": "MR SPEEDY PLUMBING ROOTER INC"}}]},
    "cardTransactions": {"edges": [
        {"node": {"period": "1m", "projectedQuantity": 83971,
                  "periodStartDate": "2025-06-01", "periodEndDate": "2025-06-30"}},
        {"node": {"period": "3m", "projectedQuantity": 250000,
                  "periodStartDate": "2025-04-01", "periodEndDate": "2025-06-30"}},
        {"node": {"period": "12m", "projectedQuantity": 900000,
                  "periodStartDate": "2024-07-01", "periodEndDate": "2025-06-30"}},
    ]},
    "operatingLocations": {"edges": [{"node": {"roles": {"edges": [
        {"node": {
            "jobTitle": "OWNER", "jobFunction": "Management", "managementLevel": "owner",
            # Person name comes via legalEntities→names (legalEntityType "Person"), NOT persons.fullName
            # (the deployed search schema rejects Person.fullName). A company LE here must be ignored.
            "legalEntities": {"edges": [
                {"node": {"names": {"edges": [
                    {"node": {"name": "MR SPEEDY PLUMBING ROOTER INC", "legalEntityType": "Corporation"}}]}}},
                {"node": {"names": {"edges": [
                    {"node": {"name": "ALFRED MARZOUK", "legalEntityType": "Person"}}]}}},
            ]},
            "phoneNumbers": {"edges": [{"node": {"phoneNumber": "+13235551234"}}]},
            "emailAddresses": {"edges": [{"node": {"emailAddress": "owner@example.com"}}]},
        }}
    ]}}}]},
}


def test_first_brand_and_enigma_id():
    raw = {"data": {"search": [_BRAND]}}
    brand = eg.first_brand(raw)
    assert brand is _BRAND
    assert eg.extract_enigma_id(brand) == "5f53e079-c66a-487e-8a9d-08efc39652ee"


def test_first_brand_none_on_empty_or_bad():
    assert eg.first_brand({"data": {"search": []}}) is None
    assert eg.first_brand({"errors": [{"message": "x"}]}) is None
    assert eg.first_brand(None) is None


def test_first_entity_matches_on_null_enigma_id():
    # The live API returns enigmaId: null on a real match; a named result must still count as a match.
    raw = {"data": {"search": [{"enigmaId": None, "names": {"edges": [{"node": {"name": "ACME"}}]}}]}}
    ent = eg.first_entity(raw)
    assert ent is not None and eg.extract_enigma_id(ent) is None


def test_first_entity_matches_operating_location_with_roles():
    raw = {"data": {"search": [{"enigmaId": None, "roles": {"edges": []},
                                "names": {"edges": [{"node": {"name": "ACME"}}]}}]}}
    assert eg.first_entity(raw) is not None


def test_extract_card_windows_all_three():
    assert eg.extract_card_windows(_BRAND) == {"1m": 83971, "3m": 250000, "12m": 900000}


def test_extract_card_windows_falls_back_to_raw_when_projected_null():
    brand = {"cardTransactions": {"edges": [
        {"node": {"period": "12m", "projectedQuantity": None, "rawQuantity": 12345}},
    ]}}
    assert eg.extract_card_windows(brand) == {"12m": 12345}


def test_extract_card_windows_none_when_absent():
    assert eg.extract_card_windows({"names": {"edges": []}}) is None
    assert eg.extract_card_windows(None) is None


def test_extract_owner_full_record():
    owner = eg.extract_owner(_BRAND)
    assert owner == {
        "full_name": "ALFRED MARZOUK",
        "job_title": "OWNER",
        "management_level": "owner",
        "job_function": "Management",
        "phone": "+13235551234",
        "email": "owner@example.com",
    }


def test_extract_owner_prefers_role_with_a_person():
    brand = {"operatingLocations": {"edges": [{"node": {"roles": {"edges": [
        {"node": {"jobTitle": "STAFF", "legalEntities": {"edges": []}}},  # no person
        {"node": {"jobTitle": "OWNER",
                  "legalEntities": {"edges": [{"node": {"names": {"edges": [
                      {"node": {"name": "Dana Lee", "legalEntityType": "Person"}}]}}}]}}},
    ]}}}]}}
    owner = eg.extract_owner(brand)
    assert owner["full_name"] == "Dana Lee" and owner["job_title"] == "OWNER"


def test_extract_owner_ignores_company_legal_entity_name():
    # A role whose only legal entity is a Corporation is NOT an owner name.
    brand = {"operatingLocations": {"edges": [{"node": {"roles": {"edges": [
        {"node": {"jobTitle": "OWNER",
                  "legalEntities": {"edges": [{"node": {"names": {"edges": [
                      {"node": {"name": "ACME LLC", "legalEntityType": "Corporation"}}]}}}]},
                  "phoneNumbers": {"edges": [{"node": {"phoneNumber": "+13230000000"}}]}}},
    ]}}}]}}
    owner = eg.extract_owner(brand)
    assert owner["full_name"] is None and owner["phone"] == "+13230000000"


def test_extract_owner_falls_back_to_titled_role_without_person():
    brand = {"operatingLocations": {"edges": [{"node": {"roles": {"edges": [
        {"node": {"jobTitle": "Manager", "legalEntities": {"edges": []},
                  "phoneNumbers": {"edges": [{"node": {"phoneNumber": "+13230000000"}}]}}},
    ]}}}]}}
    owner = eg.extract_owner(brand)
    assert owner["full_name"] is None and owner["job_title"] == "Manager"
    assert owner["phone"] == "+13230000000"


def test_extract_owner_from_direct_roles_operating_location_shape():
    # OPERATING_LOCATION match: roles hang directly on the entity, not under operatingLocations.
    ol = {"roles": {"edges": [
        {"node": {"jobTitle": "OWNER", "managementLevel": "owner",
                  "legalEntities": {"edges": [{"node": {"names": {"edges": [
                      {"node": {"name": "Sam Rivera", "legalEntityType": "Person"}}]}}}]}}}
    ]}}
    owner = eg.extract_owner(ol)
    assert owner["full_name"] == "Sam Rivera" and owner["job_title"] == "OWNER"


def test_extract_owner_none_when_no_roles():
    assert eg.extract_owner({"operatingLocations": {"edges": []}}) is None
    assert eg.extract_owner({"roles": {"edges": []}}) is None
    assert eg.extract_owner(None) is None


# --- decision metrics --------------------------------------------------------------------------


def _lookup(pid, *, enigma_id="", brand=None):
    call = SimpleNamespace(ok=bool(enigma_id))
    return SimpleNamespace(prospect_id=pid, enigma_id=enigma_id, brand=brand, call=call)


def test_probe_metrics():
    results = [
        # un-named prospect, matched, Enigma named the owner + has card data → the headline hit
        _lookup("u1", enigma_id="e1", brand=_BRAND),
        # un-named, matched, card data but no owner name
        _lookup("u2", enigma_id="e2", brand={"cardTransactions": {"edges": [
            {"node": {"period": "3m", "projectedQuantity": 700}}]}}),
        # un-named, no match
        _lookup("u3"),
        # named control, matched, no card
        _lookup("n1", enigma_id="e3", brand={"names": {"edges": [{"node": {"name": "X"}}]}}),
    ]
    m = eg.probe_metrics(results, {"u1", "u2", "u3"})
    assert m["total"] == 4
    assert m["matched"] == 3 and m["match_rate"] == 0.75
    assert m["unnamed_sampled"] == 3
    assert m["owner_name_hits_on_unnamed"] == 1  # only u1
    assert m["owner_name_hit_on_unnamed"] == round(1 / 3, 3)
    assert m["card_windows_present"] == 2  # u1 + u2
    assert m["card_fill_of_matched"] == round(2 / 3, 3)


def test_is_match_keys_on_entity_not_id():
    # A brand present with an empty enigma_id (the live null-id case) is still a match.
    assert eg.is_match(_lookup("x", enigma_id="", brand={"names": {"edges": []}})) is True
    assert eg.is_match(_lookup("y")) is False


def test_probe_metrics_counts_matches_with_null_enigma_id():
    # All matched but enigma_id empty (the real API behaviour) — match_rate must NOT be 0.
    results = [
        _lookup("a", brand={"names": {"edges": [{"node": {"name": "A"}}]}}),
        _lookup("b", brand={"cardTransactions": {"edges": [
            {"node": {"period": "12m", "projectedQuantity": 100}}]}}),
        _lookup("c"),  # no match
    ]
    m = eg.probe_metrics(results, set())
    assert m["matched"] == 2 and m["match_rate"] == round(2 / 3, 3)


def test_probe_metrics_empty_is_safe():
    m = eg.probe_metrics([], set())
    assert m["match_rate"] == 0.0 and m["owner_name_hit_on_unnamed"] == 0.0
