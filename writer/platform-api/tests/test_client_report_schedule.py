"""Unit tests for Client Reporting Phase 5 pure helpers
(services/client_report_schedule): recipient parsing + delivery email format.
The cadence clock is brand_schedule.compute_next_run_at (tested with that
module); scheduler/delivery I/O paths are exercised on the deployed worker."""

from services.client_report_schedule import format_report_email, parse_recipients


def test_parse_recipients_string_and_list():
    assert parse_recipients("am@agency.com, ops@agency.com") == ["am@agency.com", "ops@agency.com"]
    assert parse_recipients(["am@agency.com", "  ops@agency.com "]) == ["am@agency.com", "ops@agency.com"]


def test_parse_recipients_dedupes_and_drops_junk():
    assert parse_recipients("am@agency.com, AM@agency.com, , not-an-email, x@y.z") == [
        "am@agency.com", "x@y.z",
    ]
    assert parse_recipients(None) == []
    assert parse_recipients(42) == []


def test_format_report_email():
    subject, body = format_report_email("Acme Roofing", "Acme Roofing — SEO Report (2026-07-06)", "https://signed/url")
    assert subject == "[Acme Roofing] SEO report ready"
    assert "Acme Roofing — SEO Report (2026-07-06)" in body
    assert "https://signed/url" in body
    assert body.endswith("— AR Tools")


def test_format_report_email_no_client_no_link():
    subject, body = format_report_email(None, "Report", None)
    assert subject == "SEO report ready"
    assert "http" not in body
