import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import client_report  # noqa: E402


# ── Organic section ──────────────────────────────────────────────────────────

def test_organic_section_prompts_when_empty():
    html = client_report._section_prospect_organic(None)
    assert "Organic search" in html
    assert "Domain Intelligence" in html  # tells the reader what to run


def test_organic_section_renders_overview_and_keywords():
    d = {
        "overview": {"organic_traffic_est": 1200, "ranked_keyword_count": 340,
                     "dr": 22, "rd": 85, "traffic_value_est": 4300},
        "ranked_keywords": [
            {"keyword": "emergency plumber tampa", "position": 4, "volume": 900, "est_value": 210},
        ],
        "keyword_gaps": [
            {"keyword": "burst pipe repair", "competitor_domain": "rival.com",
             "competitor_position": 3, "volume": 480},
        ],
    }
    html = client_report._section_prospect_organic(d)
    assert "emergency plumber tampa" in html
    assert "burst pipe repair" in html
    assert "rival.com" in html
    # KPI values render (traffic value with a $).
    assert "$4,300" in html or "4,300" in html


# ── Competitors section ──────────────────────────────────────────────────────

def test_competitors_section_prompts_when_empty():
    assert "Competitive Intel" in client_report._section_prospect_competitors({"competitors": []})
    assert "Competitive Intel" in client_report._section_prospect_competitors(None)


def test_competitors_section_renders_rows():
    ci = {"competitors": [
        {"name": "Rival Plumbing", "domain": "rival.com",
         "gbp": {"rating": 4.6, "review_count": 210},
         "backlinks": {"domain_rating": 31, "referring_domains": 140},
         "organic": {"top10_keyword_count": 55},
         "local_pack": {"avg_rank": 2.3}},
    ]}
    html = client_report._section_prospect_competitors(ci)
    assert "Rival Plumbing" in html
    assert "4.6" in html and "(210)" in html
    assert "31" in html  # DR


# ── Maps gather (latest completed scan, any trigger) ─────────────────────────

def test_gather_geogrid_any_reads_latest_manual_scan():
    supabase = MagicMock()

    def table(name):
        t = MagicMock()
        if name == "maps_scans":
            t.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
                data=[{"id": "scan-1", "created_at": "2026-09-15T00:00:00Z"}]
            )
        elif name == "maps_scan_results":
            # .select(...).eq("scan_id", ...).limit(6).execute()  AND
            # .select(...).eq("scan_id", ...).execute() (presence helper)
            chain = t.select.return_value.eq.return_value
            chain.limit.return_value.execute.return_value = MagicMock(data=[
                {"keyword": "plumber tampa", "average_rank": 5.0, "top3_pins": 6,
                 "total_pins": 20, "rank_grid": [[1, 2]], "map_image_url": None,
                 "report_weak_locations": None},
            ])
            chain.execute.return_value = MagicMock(data=[
                {"top3_pins": 6, "total_pins": 20},
            ])
        return t

    supabase.table.side_effect = table
    g = client_report._gather_geogrid_any(supabase, "c1")
    assert g is not None
    assert g["scan_at"] == "2026-09-15T00:00:00Z"
    assert g["keywords"][0]["keyword"] == "plumber tampa"
    assert g["presence_now"] == 30.0  # 6/20
    # No period-over-period fields for a one-off prospect scan.
    assert g["presence_prev"] is None and g["presence_horizons"] is None


def test_gather_geogrid_any_none_without_scan():
    supabase = MagicMock()
    supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
    assert client_report._gather_geogrid_any(supabase, "c1") is None
