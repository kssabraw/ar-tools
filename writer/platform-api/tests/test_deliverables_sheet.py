"""Tests for the Deliverables Sheet Sync pure helpers
(docs/modules/deliverables-sheet-sync-prd-v1_0.md).

No DB, no Sheets API — the mapper (tab/dropdown/row assembly), link
extraction, and the Notes diff. The impure hook/jobs are thin composition over
these + the shared job/notification rails.
"""

from __future__ import annotations

from datetime import date

from services import deliverables_sheet as D


# ---------------------------------------------------------------------------
# Link extraction + hyperlink formula
# ---------------------------------------------------------------------------
def test_extract_url_finds_first_http_url():
    text = "Delivered!\nDoc: https://docs.google.com/spreadsheets/d/abc123/edit and more"
    assert D.extract_url(text) == "https://docs.google.com/spreadsheets/d/abc123/edit"


def test_extract_url_strips_trailing_punctuation():
    assert D.extract_url("see https://example.com/page.") == "https://example.com/page"


def test_extract_url_none_cases():
    assert D.extract_url(None) is None
    assert D.extract_url("no links here") is None
    assert D.extract_url("") is None


def test_hyperlink_formula_titled():
    got = D.hyperlink_formula("https://x.com/d", "05-2026_UMH_Citations_Oak Tree.xlsx")
    assert got == '=HYPERLINK("https://x.com/d", "05-2026_UMH_Citations_Oak Tree.xlsx")'


def test_hyperlink_formula_escapes_quotes():
    got = D.hyperlink_formula("https://x.com", 'The "Best" Guide')
    assert got == '=HYPERLINK("https://x.com", "The ""Best"" Guide")'


def test_hyperlink_formula_bare_url_when_untitled():
    assert D.hyperlink_formula("https://x.com", None) == "https://x.com"
    assert D.hyperlink_formula("https://x.com", "https://x.com") == "https://x.com"


def test_hyperlink_formula_empty_when_no_url():
    assert D.hyperlink_formula(None, "title") == ""


def test_format_sheet_date_matches_va_style():
    assert D.format_sheet_date(date(2026, 7, 9)) == "July 9, 2026"
    assert D.format_sheet_date(date(2026, 5, 14)) == "May 14, 2026"


# ---------------------------------------------------------------------------
# Dropdown matching (live vocabulary + fallback)
# ---------------------------------------------------------------------------
def test_match_dropdown_case_insensitive_exact():
    opts = ["Blog Post", "Service Page", "Other"]
    assert D.match_dropdown(opts, "blog post") == "Blog Post"
    assert D.match_dropdown(opts, "Service Page") == "Service Page"


def test_match_dropdown_falls_back_to_sheets_other_value():
    # The real UMH sheet uses "Other Links" (with a space) — match the sheet's
    # own value, never a hardcoded spelling.
    opts = ["Niche Edit", "Citations", "Other Links"]
    assert D.match_dropdown(opts, "Tiered Link Pyramid") == "Other Links"


def test_match_dropdown_unmatched_without_other_returns_desired():
    assert D.match_dropdown(["Alpha", "Beta"], "Gamma") == "Gamma"


# ---------------------------------------------------------------------------
# Tab classification + notes column detection
# ---------------------------------------------------------------------------
def test_classify_tabs_by_header_row():
    got = D.classify_tabs({
        "Sheet1": ["Content Type", "Keyword", "Google Doc Link", "Date", "Status", "Notes"],
        "Sheet2": ["Links Type", "Keyword", "Google Doc Link", "Date", "Notes"],
        "Sheet3": ["Description", "Google Doc Link", "Date", "Notes"],  # 'Other' tab — ignored
    })
    assert got == {"content": "Sheet1", "links": "Sheet2"}


def test_classify_tabs_robust_to_renames_and_partial():
    got = D.classify_tabs({"My Content": ["content type"], "Empty": []})
    assert got == {"content": "My Content"}


def test_notes_column_index_rightmost():
    content = ["Content Type", "Keyword", "Google Doc Link", "Date", "Status", "Notes"]
    links = ["Links Type", "Keyword", "Google Doc Link", "Date", "Notes"]
    assert D.notes_column_index(content) == 5
    assert D.notes_column_index(links) == 4
    assert D.notes_column_index(["A", "B"]) is None


# ---------------------------------------------------------------------------
# Tab routing (PRD §5.2 step 2)
# ---------------------------------------------------------------------------
def test_pick_tab_content_category():
    assert D.pick_tab({"category": "content", "name": "Write blog post"}) == "content"


def test_pick_tab_link_building_category():
    assert D.pick_tab({"category": "link_building", "name": "SEO NEO — DAS v2"}) == "links"


def test_pick_tab_content_run_producer_task_is_content():
    # Producer tasks are category-less; source=content_run is clearly content.
    assert D.pick_tab({"category": None, "source": "content_run", "name": "Review & publish"}) == "content"


def test_pick_tab_gbp_authority_only_gbp_posts():
    assert D.pick_tab({"category": "gbp_authority", "name": "GBP Post — July offers"}) == "content"
    # GBP Blast / Sniper are ranking work, not client deliverables (PRD §6 note).
    assert D.pick_tab({"category": "gbp_authority", "name": "GBP Sniper — roof repair"}) is None


def test_pick_tab_skips_strategy_and_alert_tasks():
    assert D.pick_tab({"category": "strategy", "name": "Quarterly review"}) is None
    assert D.pick_tab({"category": None, "source": "rank_drop", "name": "Diagnose drop"}) is None
    assert D.pick_tab({"name": "Loose task"}) is None


# ---------------------------------------------------------------------------
# Content-type mapping (PRD §6, content tab)
# ---------------------------------------------------------------------------
def test_map_content_type_prefers_linked_run():
    assert D.map_content_type({"name": "whatever"}, "blog_post") == "Blog Post"
    assert D.map_content_type({"name": "whatever"}, "service_page") == "Service Page"
    assert D.map_content_type({"name": "whatever"}, "location_page") == "Location Page"


def test_map_content_type_from_task_name():
    assert D.map_content_type({"name": "Write blog post — roof repair"}) == "Blog Post"
    assert D.map_content_type({"name": "Local Landing Page — Perrysburg"}) == "Local Landing Page"
    assert D.map_content_type({"name": "New Service Page: emergency plumbing"}) == "Service Page"
    assert D.map_content_type({"name": "GBP post — spring promo"}) == "GBP Post"


def test_map_content_type_unmapped_is_other():
    assert D.map_content_type({"name": "Misc deliverable"}) == "Other"


# ---------------------------------------------------------------------------
# Link-type mapping (PRD §6, links tab — task-NAME derived)
# ---------------------------------------------------------------------------
def test_map_link_type_seo_neo_override():
    # SEO NEO is a link-building TOOL; tasks are named "SEO NEO — <diagram>".
    assert D.map_link_type("SEO NEO — DAS v2") == "Tiered Link Pyramid"
    assert D.map_link_type("seo neo — RD100") == "Tiered Link Pyramid"
    # The override beats other keywords in the same name.
    assert D.map_link_type("SEO NEO citations booster") == "Tiered Link Pyramid"


def test_map_link_type_keyword_rules():
    assert D.map_link_type("Niche Edit — OurKidsMom") == "Niche Edit"
    assert D.map_link_type("2x Guest Posts") == "Guest Post"
    assert D.map_link_type("Order citations — Oak Tree") == "Citations"
    assert D.map_link_type("Tier 2 booster to citations") == "Tier 2"
    assert D.map_link_type("Cloud stack build") == "Cloud Stack"
    assert D.map_link_type("Google Stack — Fairview") == "Google Stack"
    assert D.map_link_type("Press release — new location") == "Press Release"


def test_map_link_type_unmapped_is_other_links():
    assert D.map_link_type("Authority links batch") == "Other Links"
    assert D.map_link_type(None) == "Other Links"


# ---------------------------------------------------------------------------
# Row assembly (columns A..D only — Status/Notes stay client-owned)
# ---------------------------------------------------------------------------
def test_build_row_shape_and_content():
    row = D.build_row("Blog Post", "roof repair perrysburg",
                      "https://docs.google.com/document/d/x", "Best Roof Repair",
                      date(2026, 7, 12))
    assert len(row) == 4  # never writes E (Status) / F (Notes)
    assert row[0] == "Blog Post"
    assert row[1] == "roof repair perrysburg"
    assert row[2] == '=HYPERLINK("https://docs.google.com/document/d/x", "Best Roof Repair")'
    assert row[3] == "July 12, 2026"


def test_build_row_missing_link_and_keyword_blank():
    row = D.build_row("Other Links", None, None, None, date(2026, 1, 2))
    assert row == ["Other Links", "", "", "January 2, 2026"]


# ---------------------------------------------------------------------------
# Notes diff (PRD §5.3)
# ---------------------------------------------------------------------------
def test_diff_notes_new_note_alerts():
    alerts, snap = D.diff_notes({}, {"Sheet1!2": "Please fix the title"})
    assert len(alerts) == 1
    assert alerts[0]["key"] == "Sheet1!2"
    assert alerts[0]["text"] == "Please fix the title"
    assert snap == {"Sheet1!2": D.note_hash("Please fix the title")}


def test_diff_notes_unchanged_is_silent():
    old = {"Sheet1!2": D.note_hash("Approved, thanks!")}
    alerts, snap = D.diff_notes(old, {"Sheet1!2": "Approved, thanks!"})
    assert alerts == []
    assert snap == old


def test_diff_notes_edited_note_realerts():
    old = {"Sheet1!2": D.note_hash("v1")}
    alerts, _ = D.diff_notes(old, {"Sheet1!2": "v2 — actually change the CTA"})
    assert len(alerts) == 1


def test_diff_notes_cleared_note_drops_silently():
    old = {"Sheet1!2": D.note_hash("old note")}
    alerts, snap = D.diff_notes(old, {"Sheet1!2": ""})
    assert alerts == []
    assert snap == {}


def test_diff_notes_ignores_empty_and_whitespace():
    alerts, snap = D.diff_notes({}, {"Sheet1!2": "   ", "Sheet1!3": ""})
    assert alerts == []
    assert snap == {}


def test_diff_notes_multiple_rows_mixed():
    old = {"Content!2": D.note_hash("keep"), "Links!4": D.note_hash("old")}
    cells = {"Content!2": "keep", "Links!4": "new text", "Links!7": "brand new"}
    alerts, snap = D.diff_notes(old, cells)
    assert {a["key"] for a in alerts} == {"Links!4", "Links!7"}
    assert set(snap) == {"Content!2", "Links!4", "Links!7"}
