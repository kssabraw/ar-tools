"""Unit tests for the pure assembly helpers in services/authority_report.py and
the bulk parsers in services/backlinks_api.py — no network, no DB."""

import pytest

from services import authority_report as ar
from services import backlinks_api


# ---------------------------------------------------------------------------
# bulk parsers
# ---------------------------------------------------------------------------
def test_parse_bulk_ranks_maps_targets_to_ratings():
    body = {"tasks": [{"status_code": 20000, "result": [{"items": [
        {"target": "a.com", "rank": 350},
        {"target": "https://a.com/page", "rank": 120},
        {"target": "b.com", "rank": None},
    ]}]}]}
    out = backlinks_api.parse_bulk_ranks(body)
    assert out == {"a.com": 35.0, "https://a.com/page": 12.0, "b.com": None}


def test_parse_bulk_referring_domains_fallback():
    body = {"tasks": [{"status_code": 20000, "result": [{"items": [
        {"target": "a.com", "referring_domains": 40},
        {"target": "b.com", "referring_domains": None, "referring_main_domains": 12},
    ]}]}]}
    out = backlinks_api.parse_bulk_referring_domains(body)
    assert out == {"a.com": 40, "b.com": 12}


def test_parse_bulk_ranks_raises_on_error():
    body = {"tasks": [{"status_code": 40400, "status_message": "bad", "result": None}]}
    with pytest.raises(RuntimeError, match="dataforseo_backlinks_bulk_ranks_error"):
        backlinks_api.parse_bulk_ranks(body)


# ---------------------------------------------------------------------------
# organic_rows
# ---------------------------------------------------------------------------
_RESULTS = [
    {"position": 1, "url": "https://a.com/x", "domain": "a.com"},
    {"position": 2, "url": "https://client.com/page", "domain": "client.com"},
    {"position": 3, "url": "https://b.com/y", "domain": "b.com"},
]


def test_organic_rows_flags_client_in_serp():
    rows = ar.organic_rows(_RESULTS, "client.com", 2, "https://client.com/page")
    assert len(rows) == 3
    assert [r["is_client"] for r in rows] == [False, True, False]


def test_organic_rows_appends_unranked_client():
    rows = ar.organic_rows(_RESULTS[:1] + _RESULTS[2:], "client.com", None, None)
    assert len(rows) == 3
    tail = rows[-1]
    assert tail["is_client"] is True and tail["position"] is None
    assert tail["url"] == "https://client.com/"  # homepage fallback


def test_organic_rows_subdomain_counts_as_client():
    rows = ar.organic_rows([{"position": 1, "url": "u", "domain": "blog.client.com"}], "client.com", None, None)
    assert rows[0]["is_client"] is True and len(rows) == 1


# ---------------------------------------------------------------------------
# maps_rows
# ---------------------------------------------------------------------------
_LEADERBOARD = [
    {"place_id": "p1", "name": "Rival Roofing", "website": "https://rival.com", "top3_pins": 5, "found_pins": 20},
    {"place_id": "p1", "name": "Rival Roofing", "website": None, "top3_pins": 3, "found_pins": 10},
    {"place_id": "p2", "name": "Other Co", "website": "https://other.com/", "top3_pins": 1, "found_pins": 4},
    {"place_id": "p3", "name": "Client Biz", "website": "https://client.com", "top3_pins": 9, "found_pins": 30},
]


def test_maps_rows_aggregates_and_leads_with_client():
    rows = ar.maps_rows(_LEADERBOARD, "client.com", "Client Biz")
    assert rows[0] == {"name": "Client Biz", "domain": "client.com", "top3_pins": None,
                       "found_pins": None, "is_client": True}
    rival = next(r for r in rows if r["name"] == "Rival Roofing")
    assert rival["top3_pins"] == 8 and rival["found_pins"] == 30  # aggregated across entries
    assert rival["domain"] == "rival.com"
    # client's own leaderboard entry is not duplicated as a competitor
    assert sum(1 for r in rows if r["domain"] == "client.com") == 1


def test_maps_rows_sorted_by_presence_and_capped():
    board = [{"place_id": f"p{i}", "name": f"c{i}", "website": f"https://c{i}.com",
              "top3_pins": i, "found_pins": i} for i in range(15)]
    rows = ar.maps_rows(board, "client.com", "Me", limit=5)
    comps = [r for r in rows if not r["is_client"]]
    assert len(comps) == 5
    assert comps[0]["top3_pins"] == 14  # strongest first


# ---------------------------------------------------------------------------
# collect_targets + merge_authority
# ---------------------------------------------------------------------------
def test_collect_targets_dedup_and_homepage_fallback():
    rows = [
        {"domain": "a.com", "url": "https://a.com/x"},
        {"domain": "a.com", "url": "https://a.com/y"},
        {"domain": "b.com", "url": None},
    ]
    rank_targets, rd_targets = ar.collect_targets(rows)
    assert rd_targets == ["a.com", "b.com"]
    assert rank_targets == ["a.com", "b.com", "https://a.com/x", "https://a.com/y", "https://b.com/"]


def test_merge_authority_attaches_metrics():
    rows = [{"domain": "a.com", "url": "https://a.com/x", "is_client": False}]
    out = ar.merge_authority(rows, {"a.com": 40.0, "https://a.com/x": 22.0}, {"a.com": 310})
    assert out[0]["dr"] == 40.0 and out[0]["ur"] == 22.0 and out[0]["rd"] == 310


def test_merge_authority_homepage_ur_for_maps_rows():
    rows = [{"domain": "b.com", "is_client": True}]
    out = ar.merge_authority(rows, {"b.com": 30.0, "https://b.com/": 28.0}, {})
    assert out[0]["ur"] == 28.0
    assert out[0]["rd"] is None


# ---------------------------------------------------------------------------
# SerMaStr formatting (slack_assistant.actions.format_authority_rows)
# ---------------------------------------------------------------------------
def test_format_authority_rows_organic_marks_client():
    from services.slack_assistant.actions import format_authority_rows
    rows = [
        {"position": 1, "domain": "a.com", "dr": 40.0, "ur": 22.0, "rd": 310, "is_client": False},
        {"position": None, "domain": "client.com", "dr": 12.0, "ur": None, "rd": 45, "is_client": True},
    ]
    out = format_authority_rows(rows, "organic")
    assert "#1 a.com — DR 40.0 · UR 22.0 · RD 310" in out
    assert "#n/r client.com" in out
    assert "← *you*" in out


def test_format_authority_rows_maps_uses_names_and_caps():
    from services.slack_assistant.actions import format_authority_rows
    rows = [{"name": f"biz{i}", "domain": f"b{i}.com", "dr": i, "ur": None, "rd": None,
             "is_client": False} for i in range(12)]
    out = format_authority_rows(rows, "maps", limit=8)
    assert out.count("• biz") == 8
    assert "RD —" in out
