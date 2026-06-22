"""Unit tests for services/gsc_service (Organic Rank Tracker M1).

All Google API access is mocked — these never hit the network.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from services import gsc_service


# ---------------------------------------------------------------------------
# infer_property_type
# ---------------------------------------------------------------------------
def test_infer_property_type_domain():
    assert gsc_service.infer_property_type("sc-domain:acmehvac.com") == "domain"


def test_infer_property_type_url_prefix():
    assert gsc_service.infer_property_type("https://acmehvac.com/") == "url_prefix"


# ---------------------------------------------------------------------------
# normalize_site_url
# ---------------------------------------------------------------------------
def test_normalize_url_prefix_adds_trailing_slash():
    assert (
        gsc_service.normalize_site_url("https://acmehvac.com", "url_prefix")
        == "https://acmehvac.com/"
    )


def test_normalize_url_prefix_keeps_existing_slash():
    assert (
        gsc_service.normalize_site_url("https://acmehvac.com/blog/", "url_prefix")
        == "https://acmehvac.com/blog/"
    )


def test_normalize_domain_passes_through():
    assert (
        gsc_service.normalize_site_url("sc-domain:acmehvac.com", "domain")
        == "sc-domain:acmehvac.com"
    )


@pytest.mark.parametrize(
    "site_url,property_type",
    [
        ("acmehvac.com", "url_prefix"),            # missing scheme
        ("sc-domain:acmehvac.com", "url_prefix"),  # domain value, url-prefix type
        ("https://acmehvac.com/", "domain"),       # url value, domain type
        ("sc-domain:acme.com/path", "domain"),     # domain can't carry a path
        ("", "url_prefix"),                        # empty
    ],
)
def test_normalize_rejects_mismatches(site_url, property_type):
    with pytest.raises(ValueError):
        gsc_service.normalize_site_url(site_url, property_type)


# ---------------------------------------------------------------------------
# error classification
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("code", [401, 403])
def test_classify_no_access(code):
    result = gsc_service.classify_access_error(code)
    assert result.status == "no_access"


@pytest.mark.parametrize("code", [400, 404])
def test_classify_unrecognized_site_url(code):
    result = gsc_service.classify_access_error(code)
    assert result.status == "no_access"
    assert result.detail == "site_url_not_recognized"


def test_classify_other_is_error():
    assert gsc_service.classify_access_error(500).status == "error"
    assert gsc_service.classify_access_error(None).status == "error"


def test_extract_status_code_from_resp():
    exc = Exception("boom")
    exc.resp = MagicMock(status=403)  # type: ignore[attr-defined]
    assert gsc_service._extract_status_code(exc) == 403


def test_extract_status_code_from_status_code_attr():
    exc = Exception("boom")
    exc.status_code = 404  # type: ignore[attr-defined]
    assert gsc_service._extract_status_code(exc) == 404


def test_extract_status_code_absent():
    assert gsc_service._extract_status_code(Exception("boom")) is None


# ---------------------------------------------------------------------------
# verify_property_access
# ---------------------------------------------------------------------------
def _fake_client():
    """A Search Console client whose query().execute() succeeds."""
    client = MagicMock()
    client.searchanalytics.return_value.query.return_value.execute.return_value = {"rows": []}
    return client


def test_verify_ok(monkeypatch):
    monkeypatch.setattr(gsc_service, "build_search_console_client", _fake_client)
    result = gsc_service.verify_property_access("https://acmehvac.com/", "url_prefix")
    assert result.status == "ok"


def test_verify_no_access_on_403(monkeypatch):
    def boom():
        client = MagicMock()
        exc = Exception("forbidden")
        exc.resp = MagicMock(status=403)  # type: ignore[attr-defined]
        client.searchanalytics.return_value.query.return_value.execute.side_effect = exc
        return client

    monkeypatch.setattr(gsc_service, "build_search_console_client", boom)
    result = gsc_service.verify_property_access("sc-domain:acmehvac.com", "domain")
    assert result.status == "no_access"


def test_verify_error_when_key_missing(monkeypatch):
    def unconfigured():
        raise RuntimeError("google_service_account_key_not_configured")

    monkeypatch.setattr(gsc_service, "build_search_console_client", unconfigured)
    result = gsc_service.verify_property_access("https://acmehvac.com/", "url_prefix")
    assert result.status == "error"
    assert result.detail == "google_service_account_key_not_configured"


def test_verify_rejects_bad_site_url_before_network(monkeypatch):
    # Should never build a client when the site_url/type mismatch.
    monkeypatch.setattr(
        gsc_service,
        "build_search_console_client",
        lambda: (_ for _ in ()).throw(AssertionError("should not be called")),
    )
    result = gsc_service.verify_property_access("acmehvac.com", "url_prefix")
    assert result.status == "error"


# ---------------------------------------------------------------------------
# service-account email parsing
# ---------------------------------------------------------------------------
def test_get_service_account_email(monkeypatch):
    monkeypatch.setattr(
        gsc_service.settings,
        "google_service_account_key",
        '{"client_email": "ar-tools@proj.iam.gserviceaccount.com"}',
    )
    assert gsc_service.get_service_account_email() == "ar-tools@proj.iam.gserviceaccount.com"


def test_get_service_account_email_unconfigured(monkeypatch):
    monkeypatch.setattr(gsc_service.settings, "google_service_account_key", "")
    with pytest.raises(RuntimeError):
        gsc_service.get_service_account_email()
