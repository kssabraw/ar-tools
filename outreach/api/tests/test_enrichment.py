"""Parsing Outscraper "Emails & Contacts" records into contact rows.

The fixtures encode the DOCUMENTED column shape (email + `email.emails_validator.status`, phone +
`phone.phones_enricher.*`, `name_for_emails`, `full_name`/…, `contact_*`) in both the nested
list-of-dicts JSON form and a flat form — the measure-don't-infer posture: the parser must read what
this account actually returns, whichever of these it is, and `probe-enrich` confirms which. The rule
under test throughout is "store what comes back, mark status, never drop a contact for a missing
field".
"""

from api.services import enrichment


# --- is_generic_email -------------------------------------------------------------------------


def test_generic_mailboxes_are_flagged_but_a_person_address_is_not():
    assert enrichment.is_generic_email("info@acme.com") is True
    assert enrichment.is_generic_email("Contact@Acme.com") is True
    assert enrichment.is_generic_email("sales+leads@acme.com") is True  # +tag stripped
    assert enrichment.is_generic_email("jane.doe@acme.com") is False
    assert enrichment.is_generic_email(None) is False
    assert enrichment.is_generic_email("not-an-email") is False


# --- the nested JSON shape --------------------------------------------------------------------


def test_nested_emails_and_phones_become_aligned_contacts():
    record = {
        "name_for_emails": "Jane Doe",
        "emails": [
            {
                "value": "jane@acme.com",
                "emails_validator": {"status": "RECEIVING"},
                "full_name": "Jane Doe",
                "first_name": "Jane",
                "last_name": "Doe",
                "title": "Owner",
            },
            {"value": "info@acme.com", "emails_validator": {"status": "UNKNOWN"}},
        ],
        "phones": [
            {"value": "+13105551234", "phones_enricher": {"carrier_type": "mobile",
                                                          "carrier_name": "Verizon"}},
        ],
    }
    contacts = enrichment.parse_contacts(record)
    assert len(contacts) == 2

    first = contacts[0]
    assert first["email"] == "jane@acme.com"
    assert first["email_status"] == "RECEIVING"
    assert first["full_name"] == "Jane Doe"
    assert first["title"] == "Owner"
    assert first["phone"] == "+13105551234"
    assert first["phone_type"] == "mobile"
    assert first["phone_carrier"] == "Verizon"
    assert first["email_is_generic"] is False

    second = contacts[1]
    assert second["email"] == "info@acme.com"
    assert second["email_is_generic"] is True
    # only one phone → the second email gets none, not the first's
    assert second["phone"] is None
    # name_for_emails fills a contact with no name of its own
    assert second["full_name"] == "Jane Doe"


def test_whitepages_carrier_is_read_when_the_enricher_lacks_one():
    record = {
        "emails": [{"value": "a@b.com"}],
        "phones": [{"value": "555", "whitepages_phones": {"carrier": "AT&T"}}],
    }
    contacts = enrichment.parse_contacts(record)
    assert contacts[0]["phone_carrier"] == "AT&T"


# --- the flat shape ---------------------------------------------------------------------------


def test_flat_single_email_and_phone():
    record = {
        "full_name": "Bob Smith",
        "title": "Manager",
        "email": "BOB@acme.com",
        "phone": "+1 (310) 555-9999",
        "contact_phone": "+13105559999",  # same number on another key → deduped
    }
    contacts = enrichment.parse_contacts(record)
    assert len(contacts) == 1
    c = contacts[0]
    assert c["email"] == "bob@acme.com"  # lowercased
    assert c["full_name"] == "Bob Smith"
    assert c["phone"] == "+1 (310) 555-9999"


def test_numbered_flat_emails_are_folded_in():
    record = {"email_1": "one@acme.com", "email_2": "two@acme.com"}
    contacts = enrichment.parse_contacts(record)
    assert {c["email"] for c in contacts} == {"one@acme.com", "two@acme.com"}


# --- data-quality realities -------------------------------------------------------------------


def test_placeholder_name_is_dropped_but_the_contact_survives():
    """'Unknown Unknown' is Outscraper's could-not-resolve placeholder — it must not become a name,
    but a contact with a real email is never discarded for it."""
    record = {"emails": [{"value": "x@acme.com", "full_name": "Unknown Unknown"}]}
    contacts = enrichment.parse_contacts(record)
    assert len(contacts) == 1
    assert contacts[0]["full_name"] is None
    assert contacts[0]["email"] == "x@acme.com"


def test_an_invalid_email_is_rejected_not_stored():
    record = {"emails": [{"value": "notanemail"}, {"value": "good@acme.com"}]}
    contacts = enrichment.parse_contacts(record)
    assert [c["email"] for c in contacts] == ["good@acme.com"]


def test_phone_only_records_yield_phone_contacts():
    record = {"name_for_emails": "Front Desk", "phones": [{"value": "+13105550000"}]}
    contacts = enrichment.parse_contacts(record)
    assert len(contacts) == 1
    assert contacts[0]["email"] is None
    assert contacts[0]["phone"] == "+13105550000"
    assert contacts[0]["full_name"] == "Front Desk"


def test_a_name_only_record_still_yields_one_contact():
    record = {"name_for_emails": "Dana Lee", "title": "Owner"}
    contacts = enrichment.parse_contacts(record)
    assert len(contacts) == 1
    assert contacts[0]["full_name"] == "Dana Lee"
    assert contacts[0]["email"] is None and contacts[0]["phone"] is None


def test_a_record_with_no_contact_data_is_empty_no_contacts_not_an_error():
    assert enrichment.parse_contacts({"category": "plumber"}) == []
    assert enrichment.parse_contacts({}) == []
    assert enrichment.parse_contacts(None) == []


# --- contact_rows: the DB insert shape --------------------------------------------------------


def test_contact_rows_attach_keys_and_keep_raw_once():
    record = {"emails": [{"value": "a@x.com"}, {"value": "b@x.com"}]}
    rows = enrichment.contact_rows(record, prospect_id="p1", place_id="place-1")
    assert len(rows) == 2
    assert all(r["prospect_id"] == "p1" and r["place_id"] == "place-1" for r in rows)
    assert [r["contact_index"] for r in rows] == [0, 1]
    # raw stored on the FIRST contact only (one copy is enough for recovery/audit)
    assert rows[0]["raw"] == record
    assert rows[1]["raw"] is None
    assert all(r["source"] == "outscraper" for r in rows)


# --- summarize --------------------------------------------------------------------------------


def test_summarize_counts_fill_rates_and_surfaces_unmapped_fields():
    records = [
        {"emails": [{"value": "a@x.com"}], "phones": [{"value": "555"}], "mystery_field": 1},
        {"email": "info@y.com"},
    ]
    errors = ["ChIJ...: timeout"]
    out = enrichment.summarize(records, errors)
    assert out["sample"] == 2
    assert out["contacts_found"] == 2
    assert out["with_email"] == 2
    assert out["with_phone"] == 1
    assert out["generic_email"] == 1
    assert "mystery_field" in out["unmapped_fields"]
    assert out["errors"] == errors
