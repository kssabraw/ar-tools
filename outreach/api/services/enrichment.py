"""Parse Outscraper "Emails & Contacts" enrichment records into contact rows. PURE.

One business (one place_id) returns MULTIPLE contacts — up to ~3 — so this module turns one
enriched place record into N `prospect_contact` shapes. It NEVER flattens into duplicate prospects
(that would double-count coverage and every score built on it); the multiplicity lives in the
contact rows.

**Measure-don't-infer** (the `dataforseo_client` / `pixel_probe` discipline): the exact response
field names for this account are UNCONFIRMED — outscraper.com is Cloudflare-403 from the build
sandbox and no enriched pull has run. The paths below are the DOCUMENTED Outscraper "Emails &
Contacts" column shape (email + `email.emails_validator.status`, phone + `phone.phones_enricher.*`
/ `phone.whitepages_phones.*`, `name_for_emails`, `full_name`/`first_name`/`last_name`/`title`,
`contact_*`). The parser reads them DEFENSIVELY — a missing field is skipped, never asserted — and
tolerates both the nested list-of-dicts JSON shape and a flat/numbered one, because which one this
account returns is exactly what `probe-enrich` exists to confirm on one billed call. Every record's
untouched fragment is kept in `raw`, so a corrected alias re-parses stored data for free (the
`parser.FIELD_ALIASES` discipline, ISSUES I-018).

Real enriched exports are PARTIAL and mixed quality — email ~83% filled, full_name ~51%,
contact_phone ~13%, some `full_name = "Unknown Unknown"`, generic `info@` addresses. So the rule
throughout is: store what comes back, mark validation status, never drop a contact for a missing
field.
"""

from __future__ import annotations

import re
from typing import Any

# Generic mailbox local-parts — kept as a FLAG (`email_is_generic`), never a reason to drop the
# contact. A generic address is still a real, usable contact; the caller decides how to weight it.
_GENERIC_LOCALS = frozenset(
    {
        "info", "contact", "office", "admin", "sales", "hello", "support", "mail",
        "enquiries", "inquiries", "team", "hi", "help", "service", "services",
        "booking", "bookings", "accounts", "billing", "noreply", "no-reply",
    }
)

# A permissive email shape — enough to reject an obvious non-address, not to validate deliverability
# (Outscraper's emails_validator does that, and its verdict is stored in `email_status`).
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# "Unknown Unknown" and its kin are Outscraper's placeholder for a name it could not resolve. Kept
# out of the name fields (so a contact with a real email isn't labelled "Unknown Unknown") but the
# contact itself is never dropped — the email/phone may still be good.
_PLACEHOLDER_NAMES = frozenset({"unknown unknown", "unknown", "n/a", "na", "none", "-"})

# The top-level keys this parser reads. Anything else in a record is reported by `summarize` as an
# unmapped field, so the probe surfaces what the documented shape missed (I-018 method).
_KNOWN_KEYS = frozenset(
    {
        "emails", "email", "phones", "phone", "contact_phone", "contact_name", "contacts",
        "name_for_emails", "full_name", "first_name", "last_name", "title",
    }
)


def is_generic_email(email: str | None) -> bool:
    """True for a role/shared mailbox (info@, contact@, …). A flag, never an exclusion."""
    if not email or "@" not in email:
        return False
    local = email.split("@", 1)[0].strip().lower()
    # strip a trailing +tag
    local = local.split("+", 1)[0]
    return local in _GENERIC_LOCALS


def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _clean_email(value: Any) -> str | None:
    email = _clean_str(value)
    if email is None:
        return None
    email = email.lower()
    return email if _EMAIL_RE.match(email) else None


def _clean_name(value: Any) -> str | None:
    name = _clean_str(value)
    if name is None:
        return None
    return None if name.lower() in _PLACEHOLDER_NAMES else name


def _scalar(entry: Any, *keys: str) -> Any:
    """A scalar out of a value that may be a plain scalar or a dict keyed by one of `keys`.

    An email/phone entry can arrive as "a@x.com" or as {"value": "a@x.com", ...}. This reads either
    without asserting which — the measure-don't-infer posture, at field granularity.
    """
    if isinstance(entry, dict):
        for key in keys:
            if key in entry and entry[key] not in (None, ""):
                return entry[key]
        return None
    return entry


def _dfield(entry: Any, key: str) -> Any:
    """A sub-field of a DICT entry, or None. Distinct from `_scalar`: a bare-string entry (an email
    passed as "a@x.com" rather than {"value": …}) has no name/title sub-fields, and reading one off
    it must yield None — not the string itself, which `_scalar` would return."""
    return entry.get(key) if isinstance(entry, dict) else None


def _nested(entry: Any, path: tuple[str, ...]) -> Any:
    """Walk a dotted path into a dict entry, tolerating a missing link at any step.

    `email.emails_validator.status` → `_nested(entry, ("emails_validator", "status"))`. A flat
    string entry, or any absent step, yields None rather than raising.
    """
    node: Any = entry
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _email_entries(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Every email on a record, with its per-email validation status + any aligned name fields.

    Handles: an `emails` list (of strings OR dicts carrying `emails_validator.status` and the
    contact's name fields), and a flat single `email`. Numbered `email_1`, `email_2` … are folded
    in too, since the CSV export flattens per-contact blocks that way.
    """
    out: list[dict[str, Any]] = []

    raw_list = record.get("emails")
    entries: list[Any] = list(raw_list) if isinstance(raw_list, list) else []
    if record.get("email") is not None:
        entries.append(record["email"])
    # Numbered flat keys (email_1, email_1.emails_validator.status style flattens to email_1 +
    # email_1_full_name in some exports) — pull the bare numbered emails; their siblings are read
    # opportunistically below via the record itself.
    for key in sorted(k for k in record if re.fullmatch(r"email_\d+", k)):
        entries.append(record[key])

    for entry in entries:
        email = _clean_email(_scalar(entry, "value", "email"))
        if email is None:
            continue
        status = _nested(entry, ("emails_validator", "status"))
        out.append(
            {
                "email": email,
                "email_status": _clean_str(status),
                "full_name": _clean_name(_dfield(entry, "full_name") or record.get("full_name")),
                "first_name": _clean_name(_dfield(entry, "first_name") or record.get("first_name")),
                "last_name": _clean_name(_dfield(entry, "last_name") or record.get("last_name")),
                "title": _clean_str(_dfield(entry, "title") or record.get("title")),
            }
        )
    return out


def _phone_entries(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Every phone on a record, with its enricher type/carrier where present.

    Reads a `phones` list (strings or dicts carrying `phones_enricher` / `whitepages_phones`), plus
    the flat `phone` and `contact_phone`. Deduped on the digit string so the same number arriving on
    two keys is one entry.
    """
    entries: list[Any] = []
    raw_list = record.get("phones")
    if isinstance(raw_list, list):
        entries.extend(raw_list)
    for key in ("phone", "contact_phone"):
        if record.get(key) is not None:
            entries.append(record[key])
    for key in sorted(k for k in record if re.fullmatch(r"phone_\d+", k)):
        entries.append(record[key])

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in entries:
        phone = _clean_str(_scalar(entry, "value", "phone"))
        if phone is None:
            continue
        digits = re.sub(r"\D", "", phone)
        if digits and digits in seen:
            continue
        if digits:
            seen.add(digits)
        carrier_type = _nested(entry, ("phones_enricher", "carrier_type")) or _nested(
            entry, ("phones_enricher", "type")
        )
        carrier_name = (
            _nested(entry, ("phones_enricher", "carrier_name"))
            or _nested(entry, ("whitepages_phones", "carrier"))
            or _nested(entry, ("phones_enricher", "carrier"))
        )
        out.append(
            {
                "phone": phone,
                "phone_type": _clean_str(carrier_type),
                "phone_carrier": _clean_str(carrier_name),
            }
        )
    return out


def parse_contacts(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn one enriched place record into a list of contact shapes (no prospect_id/place_id yet).

    Contacts are built email-first (an email carries the resolved person), then aligned to phones by
    position; phones with no matching email become phone-only contacts; and a record with neither an
    email nor a phone but a `name_for_emails`/`contact_name` still yields one name-only contact.
    Returns [] only when the record carries no email, no phone and no usable name — a genuine
    "enriched, found nobody" (recorded upstream as `no_contacts`, distinct from a failed call).
    """
    if not isinstance(record, dict):
        return []

    emails = _email_entries(record)
    phones = _phone_entries(record)
    name_for_emails = _clean_name(record.get("name_for_emails"))
    contact_name = _clean_name(record.get("contact_name"))

    contacts: list[dict[str, Any]] = []

    # Email-anchored contacts, each paired with the phone at the same index (best-effort alignment).
    for idx, em in enumerate(emails):
        phone = phones[idx] if idx < len(phones) else {}
        full = em["full_name"] or name_for_emails or contact_name
        contacts.append(
            {
                "full_name": full,
                "first_name": em["first_name"],
                "last_name": em["last_name"],
                "title": em["title"],
                "name_for_emails": name_for_emails,
                "email": em["email"],
                "email_status": em["email_status"],
                "email_is_generic": is_generic_email(em["email"]),
                "phone": phone.get("phone"),
                "phone_type": phone.get("phone_type"),
                "phone_carrier": phone.get("phone_carrier"),
            }
        )

    # Phones with no email of their own → phone-only contacts (carry the business name if we have
    # one, so a caller has someone to ask for).
    for phone in phones[len(emails):]:
        contacts.append(
            {
                "full_name": name_for_emails or contact_name,
                "first_name": None,
                "last_name": None,
                "title": None,
                "name_for_emails": name_for_emails,
                "email": None,
                "email_status": None,
                "email_is_generic": False,
                "phone": phone.get("phone"),
                "phone_type": phone.get("phone_type"),
                "phone_carrier": phone.get("phone_carrier"),
            }
        )

    # Name-only fallback: a resolved person with neither email nor phone is still worth recording.
    if not contacts and (name_for_emails or contact_name):
        contacts.append(
            {
                "full_name": name_for_emails or contact_name,
                "first_name": _clean_name(record.get("first_name")),
                "last_name": _clean_name(record.get("last_name")),
                "title": _clean_str(record.get("title")),
                "name_for_emails": name_for_emails,
                "email": None,
                "email_status": None,
                "email_is_generic": False,
                "phone": None,
                "phone_type": None,
                "phone_carrier": None,
            }
        )

    return contacts


def contact_rows(
    record: dict[str, Any], *, prospect_id: str, place_id: str
) -> list[dict[str, Any]]:
    """`prospect_contact` insert rows for one record — parse_contacts + the join keys + raw.

    `raw` carries the whole business record on the FIRST contact only (recovery/audit needs one copy,
    not N), so a corrected alias re-parses without a re-pull.
    """
    parsed = parse_contacts(record)
    rows: list[dict[str, Any]] = []
    for idx, contact in enumerate(parsed):
        rows.append(
            {
                "prospect_id": prospect_id,
                "place_id": place_id,
                "contact_index": idx,
                "source": "outscraper",
                "raw": record if idx == 0 else None,
                **contact,
            }
        )
    return rows


def unmapped_keys(record: dict[str, Any]) -> list[str]:
    """Top-level keys the parser did not read — surfaced by the probe so the documented shape can be
    corrected against a real response (I-018)."""
    if not isinstance(record, dict):
        return []
    return sorted(k for k in record if k not in _KNOWN_KEYS)


def summarize(records: list[dict[str, Any]], errors: list[str] | None = None) -> dict[str, Any]:
    """Aggregate an enrichment sample — the shape `probe-enrich` prints and the drain logs. Pure.

    Rates are over what actually came back; `errors` are reported ALONGSIDE (a billed chunk that
    failed must not be discarded — the pixel_probe lesson), so a partial sample still answers "how
    filled is this data" honestly.
    """
    n = len(records)
    per: list[dict[str, Any]] = []
    total_contacts = 0
    with_email = with_phone = with_name = generic = 0
    field_names: set[str] = set()
    for rec in records:
        contacts = parse_contacts(rec)
        total_contacts += len(contacts)
        with_email += sum(1 for c in contacts if c["email"])
        with_phone += sum(1 for c in contacts if c["phone"])
        with_name += sum(1 for c in contacts if c["full_name"])
        generic += sum(1 for c in contacts if c["email_is_generic"])
        field_names.update(unmapped_keys(rec))
        per.append({"contacts": len(contacts), "sample": contacts[:3]})
    return {
        "sample": n,
        "contacts_found": total_contacts,
        "with_email": with_email,
        "with_phone": with_phone,
        "with_name": with_name,
        "generic_email": generic,
        "unmapped_fields": sorted(field_names),
        "errors": list(errors or []),
        "per_record": per,
    }
