"""Enigma enrichment — the pure decision logic and the defensive parse.

No network: `build_enigma_row` takes a raw response dict, so the fabrication gate, the role-based
owner choice, and the provenance tag are all testable off hand-built responses. The response SHAPE
is provisional (ISSUES), so these fixtures encode the shape the client's query currently produces;
the LOGIC they exercise (gate, owner choice, evidence) is shape-independent.
"""
from api.services import enigma_enrich as ee


# --- role scoring + owner choice ---------------------------------------------------------------

def test_role_score_compound_title_takes_the_max():
    assert ee.role_score("Managing Member / Owner") == 100   # owner beats managing member
    assert ee.role_score("Managing Member") == 95
    assert ee.role_score("Registered Agent") == 20
    assert ee.role_score("") == 0
    assert ee.role_score("Chief Bottle Washer") == 0         # unknown → 0


def test_role_score_respects_word_boundaries():
    # "member" must not match inside another word; a bare unrelated title stays 0.
    assert ee.role_score("Remembrance Coordinator") == 0


def test_choose_owner_prefers_highest_role_and_excludes_registered_agent():
    people = [
        {"name": "Jane Doe", "title": "Registered Agent"},
        {"name": "John Smith", "title": "Managing Member"},
        {"name": "Bob Roe", "title": "Manager"},
    ]
    owner, score = ee.choose_owner(people)
    assert owner["name"] == "John Smith" and score == 95


def test_choose_owner_returns_none_when_only_administrative_people():
    # A registered agent is NOT the owner — the gate must yield None, never a false owner.
    owner, score = ee.choose_owner([{"name": "XYZ Registered Agents LLC", "title": "Registered Agent"}])
    assert owner is None and score == 0


# --- name similarity + match score -------------------------------------------------------------

def test_name_similarity_strips_generic_suffixes():
    assert ee.name_similarity("ABC Plumbing", "ABC PLUMBING SERVICES LLC") == 1.0
    assert 0.0 <= ee.name_similarity("ABC Plumbing", "XYZ Plumbing") < 1.0


def test_match_score_name_alone_does_not_clear_a_sensible_gate():
    prospect = {"name": "ABC Plumbing", "phone": "", "website": ""}
    cand = {"name": "ABC Plumbing", "phone": None, "website": None}
    # Perfect name, no corroboration → 0.55, below the default 0.7 gate.
    assert ee.compute_match_score(prospect, cand) == 0.55


def test_match_score_name_plus_phone_clears():
    prospect = {"name": "ABC Plumbing", "phone": "(714) 555-1234", "website": "abcplumbing.com"}
    cand = {"name": "ABC Plumbing Services LLC", "phone": "714-555-1234", "website": "http://abcplumbing.com/"}
    assert ee.compute_match_score(prospect, cand) == 1.0   # 0.55 + 0.30 + 0.15, capped


# --- build_enigma_row: the whole resolution --------------------------------------------------

def _response(*, people, name="ABC Plumbing", phone="714-555-1234", website="abcplumbing.com",
             revenue=1800000, growth=24.0, locations=1):
    return {"data": {"search": [{
        "id": "brand-1",
        "names": {"edges": [{"node": {"name": name}}]},
        "cardRevenueAmount": revenue,
        "cardRevenueGrowth": growth,
        "locationCount": locations,
        "phone": phone,
        "website": website,
        "legalEntities": {"edges": [{"node": {
            "id": "le-1",
            "names": {"edges": [{"node": {"name": "ABC PLUMBING SERVICES LLC"}}]},
            "people": {"edges": [{"node": p} for p in people]},
        }}]},
    }]}}


_PROSPECT = {"id": "p1", "name": "ABC Plumbing", "phone": "714-555-1234", "website": "abcplumbing.com"}


def test_build_row_resolves_owner_with_contact_and_evidence():
    raw = _response(people=[
        {"fullName": "John Smith", "title": "Managing Member",
         "email": "john@abcplumbing.com", "phone": "714-555-9876"},
        {"fullName": "Jane Doe", "title": "Registered Agent"},
    ])
    row = ee.build_enigma_row(_PROSPECT, raw, min_match_score=0.7, place_id="pl1")

    assert row["status"] == "resolved"
    assert row["owner_name"] == "John Smith"
    assert row["owner_title"] == "Managing Member"
    assert row["owner_role_score"] == 95
    assert row["owner_email"] == "john@abcplumbing.com"
    assert row["owner_phone"] == "714-555-9876"
    assert row["owner_evidence"] == "both"          # role + contact on the same node
    assert row["match_score"] >= 0.7
    assert row["location_count"] == 1
    assert row["card_revenue_cents"] == 180000000   # dollars → cents
    assert row["revenue_growth_pct"] == 24.0
    assert len(row["officers"]) == 2
    assert row["raw"] is raw                         # untouched, for recovery


def test_build_row_below_gate_asserts_no_owner():
    # A different business that happens to share nothing — name mismatch, no phone/site corroboration.
    raw = _response(name="Zeta Roofing", phone="", website="",
                    people=[{"fullName": "Someone Else", "title": "Owner",
                             "email": "x@zeta.com", "phone": "111"}])
    row = ee.build_enigma_row(_PROSPECT, raw, min_match_score=0.7, place_id="pl1")

    assert row["status"] == "no_match"
    assert "owner_name" not in row                   # nothing attributed below the gate
    assert "card_revenue_cents" not in row
    assert row["officers"] == []
    assert row["match_score"] < 0.7


def test_build_row_registered_agent_only_is_no_contacts_not_a_fake_owner():
    raw = _response(people=[{"fullName": "XYZ Registered Agents LLC", "title": "Registered Agent"}])
    row = ee.build_enigma_row(_PROSPECT, raw, min_match_score=0.7, place_id="pl1")

    assert row["status"] == "no_contacts"            # matched the business, but no real decision-maker
    assert "owner_name" not in row
    assert len(row["officers"]) == 1                 # the agent is kept for inspection, not asserted


def test_build_row_no_candidate_is_no_match():
    row = ee.build_enigma_row(_PROSPECT, {"data": {"search": []}}, min_match_score=0.7, place_id="pl1")
    assert row["status"] == "no_match" and row["officers"] == []


def test_build_row_prefers_enigma_provided_score_over_computed():
    raw = _response(name="Totally Different Name", phone="", website="",
                    people=[{"fullName": "Ann Owner", "title": "Owner", "phone": "999"}])
    raw["data"]["search"][0]["matchScore"] = 0.95    # Enigma says it's confident despite name mismatch
    row = ee.build_enigma_row(_PROSPECT, raw, min_match_score=0.7, place_id="pl1")
    assert row["status"] == "resolved" and row["match_score"] == 0.95
    assert row["owner_name"] == "Ann Owner"
