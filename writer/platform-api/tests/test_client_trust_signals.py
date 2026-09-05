"""Unit tests for ClientDetail.trust_signals read-side sanitization.

The write path validates trust_signals at the request model, but a malformed or
legacy value written directly to the DB must not 500 GET /clients/{id}. The
`_sanitize_trust_signals` before-validator repairs any stored shape into
something TrustSignals accepts. Pure + offline.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models.clients import ClientDetail, TrustSignals  # noqa: E402


def _sanitize(v):
    return ClientDetail._sanitize_trust_signals(v)


def test_none_and_non_dict_coerce_to_none():
    assert _sanitize(None) is None
    assert _sanitize("nope") is None
    assert _sanitize(["a", "b"]) is None
    assert _sanitize(42) is None


def test_wellformed_passes_through_and_builds():
    v = {
        "certifications": [{"name": "BBB", "logo_url": "b.png"}],
        "affiliations": [],
        "financing_partners": [{"name": "Wisetack", "logo_url": ""}],
        "license_number": "CCC123",
        "years_founded": 1998,
        "founding_date": "since 1998",
    }
    out = _sanitize(v)
    ts = TrustSignals(**out)  # must not raise
    assert ts.certifications[0].name == "BBB"
    assert ts.license_number == "CCC123"
    assert ts.years_founded == 1998


def test_malformed_badge_lists_are_repaired_not_500():
    # A legacy list-of-strings + partial dicts + junk — the exact shapes that
    # would raise TrustBadge validation errors if passed through unsanitized.
    v = {
        "certifications": ["BBB", {"name": "Angi", "logo": "a.png"}, {}, 7, {"logo_url": "x.png"}],
        "affiliations": "not-a-list",
        "years_founded": "1998",   # numeric string
    }
    out = _sanitize(v)
    ts = TrustSignals(**out)  # must not raise
    names = [b.name for b in ts.certifications]
    assert "BBB" in names          # bare string repaired
    assert "Angi" in names         # `logo` alias picked up
    assert ts.certifications[-1].logo_url == "x.png"  # logo-only kept
    assert all(b.name or b.logo_url for b in ts.certifications)  # junk dropped
    assert ts.affiliations == []   # non-list → []
    assert ts.years_founded == 1998


def test_bad_years_founded_becomes_none():
    assert _sanitize({"years_founded": "n/a"})["years_founded"] is None
    assert _sanitize({"years_founded": None})["years_founded"] is None
    assert _sanitize({})["years_founded"] is None


def test_client_detail_get_does_not_raise_on_malformed_trust_signals():
    # Full round-trip: a client row carrying a legacy list-of-strings must build.
    row = {
        "id": "00000000-0000-0000-0000-000000000001",
        "name": "Acme",
        "website_url": "https://acme.example",
        "website_analysis_status": "complete",
        "brand_guide_source_type": "text",
        "brand_guide_text": "",
        "icp_source_type": "text",
        "icp_text": "",
        "archived": False,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "client_type": "local",
        "is_sab": False,
        "trust_signals": {"certifications": ["BBB Accredited"]},
    }
    detail = ClientDetail(**row)  # must not raise
    assert detail.trust_signals.certifications[0].name == "BBB Accredited"
