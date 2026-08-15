"""Validation for the GBP dashboard custom date-range (start/end) selection."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException

from routers import gbp_metrics as r


def test_parse_custom_range_valid():
    start, end = r._parse_custom_range("2026-07-01", "2026-07-31")
    assert start == date(2026, 7, 1)
    assert end == date(2026, 7, 31)


def test_parse_custom_range_single_day():
    start, end = r._parse_custom_range("2026-07-15", "2026-07-15")
    assert start == end == date(2026, 7, 15)


def test_parse_custom_range_end_before_start():
    with pytest.raises(HTTPException) as exc:
        r._parse_custom_range("2026-07-31", "2026-07-01")
    assert exc.value.status_code == 422
    assert "invalid_range" in exc.value.detail


@pytest.mark.parametrize("bad", [("nope", "2026-07-01"), ("2026-07-01", "2026-13-40")])
def test_parse_custom_range_bad_dates(bad):
    with pytest.raises(HTTPException) as exc:
        r._parse_custom_range(*bad)
    assert exc.value.status_code == 422
    assert "invalid_date" in exc.value.detail


def test_parse_custom_range_too_large():
    with pytest.raises(HTTPException) as exc:
        r._parse_custom_range("2025-01-01", "2026-12-31")
    assert exc.value.status_code == 422
    assert "range_too_large" in exc.value.detail
