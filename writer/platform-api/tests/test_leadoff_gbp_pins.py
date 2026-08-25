"""Unit tests for the LeadOff live-GBP pin persistence row-builder (pure; the
insert/delete round-trips are impure and covered by CI's integration env)."""
from services.leadoff_gbp_pins import _rows_for

BATCH = "2026-08-25T00:00:00+00:00"


def pin(lat, lng, name="biz", rank=1, reviews=10, rating=4.5, place_id="p", domain="x.com"):
    return {"lat": lat, "lng": lng, "business_name": name, "rank_position": rank,
            "review_count": reviews, "rating": rating, "place_id": place_id, "domain": domain}


class TestRowsFor:
    def test_shape_and_batch_stamp(self):
        rows = _rows_for("scout", 42, "cat1", [pin(39.1, -94.6, "A", rank=2)], BATCH)
        assert len(rows) == 1
        r = rows[0]
        assert r["source"] == "scout" and r["city_id"] == 42 and r["category_id"] == "cat1"
        assert r["captured_at"] == BATCH          # explicit batch stamp, not DB default
        assert r["lat"] == 39.1 and r["lng"] == -94.6
        assert r["rank_position"] == 2 and r["place_id"] == "p" and r["review_count"] == 10
        # phone is intentionally NOT persisted (no column)
        assert "phone" not in r

    def test_drops_coordless_rows(self):
        pins = [pin(39.1, -94.6, "Geo"),
                {"business_name": "NoLat", "lng": -94.6, "rank_position": 3},
                {"business_name": "NoLng", "lat": 39.1, "rank_position": 4}]
        rows = _rows_for("tryout", 42, "cat1", pins, BATCH)
        assert [r["business_name"] for r in rows] == ["Geo"]

    def test_empty_pins_yields_no_rows(self):
        assert _rows_for("scout", 42, "cat1", [], BATCH) == []
        assert _rows_for("scout", 42, "cat1", None, BATCH) == []
