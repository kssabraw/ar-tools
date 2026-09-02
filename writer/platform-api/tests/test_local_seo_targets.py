"""Unit tests for services.local_seo_targets — user-supplied Plan Silo targets.

Pure parsers only: the matrix/list → silo shape and the CSV/plain-list parsing.
The marking half (`plan_custom_targets`) reuses `local_seo_silo._to_items`, which
is covered by `test_local_seo_silo.py`.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import local_seo_silo
from services import local_seo_targets as lt


# ── build_matrix_silos ────────────────────────────────────────────────────────

def test_matrix_cartesian_product_grouped_by_service():
    silos = lt.build_matrix_silos(
        "Roof Restoration\nGutter Cleaning", "Melbourne\nGeelong"
    )
    assert [s["silo"] for s in silos] == ["Roof Restoration", "Gutter Cleaning"]
    roof = silos[0]["pages"]
    assert [p["keyword"] for p in roof] == [
        "Roof Restoration Melbourne",
        "Roof Restoration Geelong",
    ]
    # Each page carries the bare place so the on_site check can match a location page.
    assert roof[0]["location_name"] == "Melbourne"
    assert roof[1]["location_name"] == "Geelong"


def test_matrix_dedupes_and_ignores_blank_lines():
    silos = lt.build_matrix_silos(
        "Roofing\nroofing\n\n  ", "Melbourne\nMelbourne\n"
    )
    assert len(silos) == 1  # "roofing" dup dropped
    assert [p["keyword"] for p in silos[0]["pages"]] == ["Roofing Melbourne"]


def test_matrix_empty_axis_returns_nothing():
    assert lt.build_matrix_silos("", "Melbourne") == []
    assert lt.build_matrix_silos("Roofing", "") == []


# ── parse_list_rows ───────────────────────────────────────────────────────────

def test_list_plain_one_keyword_per_line():
    rows = lt.parse_list_rows("roof restoration melbourne\ngutter cleaning geelong\n")
    assert [r["keyword"] for r in rows] == [
        "roof restoration melbourne",
        "gutter cleaning geelong",
    ]
    assert all(r["supporting_keywords"] == [] for r in rows)
    assert all("group" not in r and "location_name" not in r for r in rows)


def test_list_positional_keyword_then_group():
    rows = lt.parse_list_rows("roof restoration melbourne,Roofing\ndrain cleaning,Plumbing")
    assert rows[0] == {
        "keyword": "roof restoration melbourne",
        "supporting_keywords": [],
        "group": "Roofing",
    }


def test_list_csv_with_header_maps_columns():
    csv_text = (
        "keyword,silo,city,supporting\n"
        "roof restoration melbourne,Roofing,Melbourne,melbourne roof restorations; roof restorer melbourne\n"
    )
    rows = lt.parse_list_rows(csv_text)
    assert rows[0]["keyword"] == "roof restoration melbourne"
    assert rows[0]["group"] == "Roofing"
    assert rows[0]["location_name"] == "Melbourne"
    assert rows[0]["supporting_keywords"] == [
        "melbourne roof restorations",
        "roof restorer melbourne",
    ]


def test_list_dedupes_and_skips_blank_rows():
    rows = lt.parse_list_rows("roof restoration\nRoof Restoration\n\n , ,\ngutter cleaning")
    assert [r["keyword"] for r in rows] == ["roof restoration", "gutter cleaning"]


def test_list_header_keyword_only():
    rows = lt.parse_list_rows("Keyword\nroof restoration melbourne\ngutter cleaning")
    assert [r["keyword"] for r in rows] == [
        "roof restoration melbourne",
        "gutter cleaning",
    ]


# ── build_list_silos ──────────────────────────────────────────────────────────

def test_list_silos_group_by_column_preserving_order():
    text = (
        "keyword,group\n"
        "roof restoration melbourne,Roofing\n"
        "gutter cleaning melbourne,Gutters\n"
        "roof repair melbourne,Roofing\n"
    )
    silos = lt.build_list_silos(text)
    assert [s["silo"] for s in silos] == ["Roofing", "Gutters"]
    assert [p["keyword"] for p in silos[0]["pages"]] == [
        "roof restoration melbourne",
        "roof repair melbourne",
    ]
    # group is consumed into the silo, not left on the page dict.
    assert all("group" not in p for p in silos[0]["pages"])


def test_list_silos_default_group_when_ungrouped():
    silos = lt.build_list_silos("roof restoration melbourne\ngutter cleaning melbourne")
    assert len(silos) == 1
    assert silos[0]["silo"] == "Custom targets"
    assert len(silos[0]["pages"]) == 2


def test_list_silos_empty_input():
    assert lt.build_list_silos("") == []


# ── build_silos dispatch ──────────────────────────────────────────────────────

def test_build_silos_dispatches_by_mode():
    matrix = lt.build_silos("matrix", "Roofing", "Melbourne", "")
    assert matrix[0]["pages"][0]["keyword"] == "Roofing Melbourne"
    listed = lt.build_silos("list", "", "", "drain cleaning geelong")
    assert listed[0]["pages"][0]["keyword"] == "drain cleaning geelong"


# ── plan_custom_targets (parse → mark, reusing the silo marking) ───────────────

def _fake_supabase_no_pages() -> MagicMock:
    sb = MagicMock()
    chain = sb.table.return_value.select.return_value.eq.return_value.is_.return_value
    chain.execute.return_value.data = []
    return sb


@pytest.mark.asyncio
async def test_plan_custom_targets_marks_matrix_against_site():
    # /roof-restoration-melbourne/ is published; geelong is not.
    with patch.object(
        local_seo_silo,
        "_build_site_url_list",
        new=AsyncMock(return_value=(["https://fcr.com/roof-restoration-melbourne/"], None)),
    ), patch.object(local_seo_silo, "get_supabase", return_value=_fake_supabase_no_pages()):
        result = await lt.plan_custom_targets(
            client_id="client-1",
            input_mode="matrix",
            services="Roof Restoration",
            locations="Melbourne\nGeelong",
            targets="",
            location="Melbourne,Victoria,Australia",
            location_code=2036,
        )
    by_kw = {i["keyword"]: i for i in result["items"]}
    assert by_kw["Roof Restoration Melbourne"]["status"] == "on_site"
    assert by_kw["Roof Restoration Geelong"]["status"] == "missing"


@pytest.mark.asyncio
async def test_plan_custom_targets_empty_input_degrades():
    result = await lt.plan_custom_targets(
        client_id="client-1",
        input_mode="matrix",
        services="",
        locations="",
        targets="",
        location="Melbourne",
        location_code=None,
    )
    assert result["items"] == []
    assert result["degraded_notes"] == ["No targets were provided."]
