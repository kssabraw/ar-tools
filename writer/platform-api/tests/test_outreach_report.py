"""Pure-logic tests for the per-prospect report assembly.

No network, no database — the assembly is deterministic and fact-grounded, so it is testable from
hand-built inputs. What matters here: the maps rankings-vs-competitors table (pack presence + best
rank, prospect excluded from its own competitor list, unresolved place_ids counted but never named),
and that a signal with no scan renders as an explicit not_scanned block rather than an empty table.
"""
from services import outreach_report as orep


def _pack(seq, place, rank):
    return {"point_seq": seq, "place_id": place, "rank": rank}


def test_build_maps_comparison_scores_pack_presence_and_best_rank():
    pack = [
        _pack(0, "SELF", 3), _pack(1, "SELF", 2),        # prospect holds 2 points, best rank 2
        _pack(0, "A", 1), _pack(1, "A", 1), _pack(2, "A", 2),  # Ace: 3 points, best 1
        _pack(2, "B", 1),                                 # Bolt: 1 point, best 1
        _pack(3, "UNKNOWN", 1),                           # unresolved -> counted, never named
    ]
    section = orep.build_maps_comparison(
        prospect_place_id="SELF",
        pack_rows=pack,
        name_by_place_id={"A": "Ace Plumbing", "B": "Bolt Rooter"},
        coverage={"coverage_pct": 25.0, "points_present": 2, "best_rank": 2, "avg_rank": 2.5},
        live_points=8,
        max_competitors=3,
    )
    assert section["status"] == orep.STATUS_MEASURED
    # Named competitors, most pack presence first; the prospect is not in its own competitor list.
    assert [c["name"] for c in section["competitors"]] == ["Ace Plumbing", "Bolt Rooter"]
    assert section["competitors"][0] == {
        "place_id": "A", "name": "Ace Plumbing", "pack_points": 3,
        "pack_share_pct": round(100.0 * 3 / 8, 1), "best_rank": 1,
    }
    # The unresolved place is counted in the total but never named.
    assert section["total_competitors"] == 3  # A, B, UNKNOWN
    assert section["prospect"]["pack_points"] == 2
    assert section["prospect"]["pack_best_rank"] == 2


def test_build_maps_comparison_prospect_absent_from_pack():
    # Prospect holds no pack spot anywhere — pack_points 0, still a valid comparison row.
    pack = [_pack(0, "A", 1), _pack(1, "A", 2)]
    section = orep.build_maps_comparison(
        prospect_place_id="SELF", pack_rows=pack,
        name_by_place_id={"A": "Ace"}, coverage=None, live_points=6, max_competitors=3,
    )
    assert section["prospect"]["pack_points"] == 0
    assert section["prospect"]["coverage_pct"] == 0.0
    assert section["competitors"][0]["name"] == "Ace"


def test_build_maps_comparison_caps_named_competitors():
    pack = [_pack(i, chr(65 + i), 1) for i in range(5)]
    names = {chr(65 + i): f"biz-{i}" for i in range(5)}
    section = orep.build_maps_comparison(
        prospect_place_id="SELF", pack_rows=pack, name_by_place_id=names,
        coverage=None, live_points=10, max_competitors=2,
    )
    assert len(section["competitors"]) == 2
    assert section["total_competitors"] == 5


def test_not_scanned_section():
    s = orep.not_scanned_section(orep.SIGNAL_ORGANIC, "no scan yet")
    assert s == {"status": orep.STATUS_NOT_SCANNED, "signal": "organic", "reason": "no scan yet"}


def _prospect():
    return {"id": "p1", "name": "Drips Plumbing", "category": "plumber", "phone": "+1",
            "website": "", "address": "1 Main St", "rating": 4.1, "review_count": 4}


def test_build_report_shape_and_client_draft_gate():
    justification = {"measured": True, "hook": "…", "talking_points": [],
                     "provenance": {"snapshot_id": "snap1"}}
    maps = orep.build_maps_comparison(
        prospect_place_id="SELF", pack_rows=[_pack(0, "A", 1)],
        name_by_place_id={"A": "Ace"}, coverage=None, live_points=5, max_competitors=3,
    )
    report = orep.build_report(
        prospect=_prospect(), keyword="plumber", submarket="Van Nuys",
        justification=justification, maps_section=maps,
        organic_section=orep.not_scanned_section(orep.SIGNAL_ORGANIC, "staged"),
        llm_section=orep.not_scanned_section(orep.SIGNAL_LLM, "staged"),
        heatmap_available=True,
    )
    assert report["measured"] is True
    assert report["identity"]["name"] == "Drips Plumbing"
    assert report["signals"]["maps"]["status"] == orep.STATUS_MEASURED
    # Organic and LLM are explicit not_scanned blocks — never an empty table.
    assert report["signals"]["organic"]["status"] == orep.STATUS_NOT_SCANNED
    assert report["signals"]["llm"]["status"] == orep.STATUS_NOT_SCANNED
    # The client-facing face is a DRAFT, unapproved, until the approval slice lands.
    assert report["client_facing"]["approved"] is False
    # The hook is reused verbatim from the justification, not re-derived.
    assert report["justification"] is justification


def test_build_report_deterministic():
    justification = {"measured": True, "provenance": {}, "talking_points": []}
    kwargs = dict(
        prospect=_prospect(), keyword="plumber", submarket="Van Nuys", justification=justification,
        maps_section={"status": "measured"},
        organic_section=orep.not_scanned_section(orep.SIGNAL_ORGANIC, "x"),
        llm_section=orep.not_scanned_section(orep.SIGNAL_LLM, "x"),
        heatmap_available=False,
    )
    assert orep.build_report(**kwargs) == orep.build_report(**kwargs)
