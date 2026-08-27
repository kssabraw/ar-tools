"""Unit tests for the Website Builder's release (drip-publish) schedule.

The pure surface is what's worth pinning: which pages a release claims and in
what order, the cadence math for daily/weekly/monthly, and the decision to keep
ticking or mark the schedule complete.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services import website_release as wr

UTC = timezone.utc


def page(pid, page_type="post", *, status="draft", released_at=None, tier=3, route=""):
    return {
        "id": pid,
        "page_type": page_type,
        "status": status,
        "released_at": released_at,
        "tier": tier,
        "route": route or f"/blog/{pid}/",
    }


class TestReleasable:
    def test_a_fresh_post_is_releasable(self):
        assert wr.is_releasable(page("a"))

    def test_published_or_claimed_or_wrong_type_is_not(self):
        assert not wr.is_releasable(page("a", status="published"))
        assert not wr.is_releasable(page("a", released_at="2026-01-01T00:00:00Z"))
        # A core page is not dripped — it's the site's frame, published up front.
        assert not wr.is_releasable(page("a", page_type="home"))


class TestSelectBatch:
    def test_posts_release_before_pillars(self):
        pages = [
            page("pil", page_type="pillar", tier=2, route="/roofing/"),
            page("p1", route="/blog/p1/"),
            page("p2", route="/blog/p2/"),
        ]
        batch = wr.select_batch(pages, 3)
        assert [p["id"] for p in batch] == ["p1", "p2", "pil"]

    def test_count_caps_the_batch(self):
        pages = [page(f"p{i}") for i in range(5)]
        assert len(wr.select_batch(pages, 2)) == 2

    def test_excludes_published_and_claimed(self):
        pages = [
            page("done", status="published"),
            page("claimed", released_at="2026-01-01T00:00:00Z"),
            page("fresh"),
        ]
        assert [p["id"] for p in wr.select_batch(pages, 10)] == ["fresh"]

    def test_zero_or_negative_count_is_empty(self):
        assert wr.select_batch([page("a")], 0) == []

    def test_releasable_count_counts_only_the_pool(self):
        pages = [page("a"), page("b", status="published"), page("c", page_type="pillar")]
        assert wr.releasable_count(pages) == 2


class TestNormalizeAnchors:
    def test_weekly_defaults_to_setup_weekday_and_clears_dom(self):
        now = datetime(2026, 8, 26, 14, 0, tzinfo=UTC)  # a Wednesday
        wd, dom = wr.normalize_anchors("weekly", None, 15, now)
        assert wd == now.weekday()
        assert dom is None

    def test_monthly_defaults_to_setup_day_capped_at_28(self):
        now = datetime(2026, 8, 31, 14, 0, tzinfo=UTC)
        wd, dom = wr.normalize_anchors("monthly", 3, None, now)
        assert wd is None
        assert dom == 28

    def test_daily_clears_both_anchors(self):
        now = datetime(2026, 8, 26, tzinfo=UTC)
        assert wr.normalize_anchors("daily", 4, 10, now) == (None, None)


class TestNextRunAfter:
    NOW = datetime(2026, 8, 26, 14, 30, tzinfo=UTC)  # Wednesday (weekday()==2)

    def test_daily_is_one_day_out(self):
        assert wr.next_run_after("daily", None, None, self.NOW) == self.NOW + timedelta(days=1)

    def test_weekly_same_weekday_is_a_full_week_out(self):
        nxt = wr.next_run_after("weekly", self.NOW.weekday(), None, self.NOW)
        assert nxt == self.NOW + timedelta(days=7)

    def test_weekly_other_weekday_is_within_the_week(self):
        target = (self.NOW.weekday() + 3) % 7
        nxt = wr.next_run_after("weekly", target, None, self.NOW)
        assert nxt.weekday() == target
        assert 1 <= (nxt - self.NOW).days <= 6

    def test_monthly_later_day_is_this_month(self):
        nxt = wr.next_run_after("monthly", None, 28, self.NOW)
        assert (nxt.year, nxt.month, nxt.day) == (2026, 8, 28)

    def test_monthly_earlier_day_rolls_to_next_month(self):
        nxt = wr.next_run_after("monthly", None, 10, self.NOW)
        assert (nxt.year, nxt.month, nxt.day) == (2026, 9, 10)

    def test_monthly_same_day_rolls_forward_not_same_instant(self):
        nxt = wr.next_run_after("monthly", None, self.NOW.day, self.NOW)
        assert (nxt.year, nxt.month, nxt.day) == (2026, 9, 26)

    def test_december_monthly_rolls_the_year(self):
        dec = datetime(2026, 12, 20, tzinfo=UTC)
        nxt = wr.next_run_after("monthly", None, 5, dec)
        assert (nxt.year, nxt.month, nxt.day) == (2027, 1, 5)


class TestAdvance:
    NOW = datetime(2026, 8, 26, 14, 30, tzinfo=UTC)

    def test_empty_pool_completes_and_stops(self):
        patch = wr.advance({"mode": "daily"}, 0, self.NOW)
        assert patch["status"] == "complete"
        assert patch["next_run_at"] is None
        assert patch["last_run_at"] == self.NOW.isoformat()

    def test_remaining_pool_clocks_the_next_run(self):
        patch = wr.advance({"mode": "daily"}, 5, self.NOW)
        assert "status" not in patch  # stays active
        assert patch["next_run_at"] == (self.NOW + timedelta(days=1)).isoformat()


class TestLocalSiteReleasability:
    def test_local_content_pages_are_releasable(self):
        for pt in ("service", "location", "local_landing", "neighborhood", "sub_service"):
            assert wr.is_releasable(page("x", page_type=pt)), pt

    def test_core_and_template_only_pages_are_never_dripped(self):
        # The site's frame publishes up front / trivially, not through the drip.
        for pt in ("home", "about", "contact", "privacy", "blog_archive",
                   "sitemap", "services_index", "areas_we_serve"):
            assert not wr.is_releasable(page("x", page_type=pt)), pt

    def test_local_order_foundation_before_matrix_before_longtail(self):
        pages = [
            page("nb", page_type="neighborhood", tier=3, route="/anaheim/downtown/"),
            page("mx", page_type="local_landing", tier=1, route="/anaheim/ac-repair/"),
            page("svc", page_type="service", tier=1, route="/ac-repair/"),
            page("city", page_type="location", tier=1, route="/anaheim/"),
        ]
        assert [p["id"] for p in wr.select_batch(pages, 4)] == ["svc", "city", "mx", "nb"]
