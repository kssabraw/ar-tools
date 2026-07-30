"""Pure-helper tests for services.site_inventory — the client's live-site
inventory that grounds "do they already have a page for this?"."""

from services import site_inventory


# --- normalize_path ---------------------------------------------------------


def test_normalize_path_strips_host_query_and_trailing_slash():
    assert site_inventory.normalize_path("https://acme.com/services/roofing/") == "/services/roofing"
    assert site_inventory.normalize_path("https://acme.com/a/b?utm=1#top") == "/a/b"


def test_normalize_path_maps_the_homepage_to_a_single_slash():
    for url in ("https://acme.com", "https://acme.com/", "https://acme.com/?x=1"):
        assert site_inventory.normalize_path(url) == "/", url


def test_normalize_path_lowercases_and_tolerates_junk():
    assert site_inventory.normalize_path("https://acme.com/Fort-Lauderdale") == "/fort-lauderdale"
    assert site_inventory.normalize_path("") == ""
    assert site_inventory.normalize_path(None) == ""


# --- classify_path ----------------------------------------------------------


def test_classify_path_buckets_by_segment():
    cases = {
        "/": "home",
        "/blog/how-to-fix-a-roof": "blog",
        "/news/2026-update": "blog",
        "/locations/pompano-beach": "location",
        "/service-area/tampa": "location",
        "/services/roof-repair": "service",
        "/products/widget": "product",
        "/wp-content/uploads/x.jpg": "noise",
        "/privacy-policy": "noise",
        "/about-us": "other",
    }
    for path, expected in cases.items():
        assert site_inventory.classify_path(path) == expected, path


# --- summarize_inventory ----------------------------------------------------


_URLS = [
    "https://acme.com/",
    "https://acme.com/services/roof-repair",
    "https://acme.com/services/roof-replacement",
    "https://acme.com/locations/fort-lauderdale",
    "https://acme.com/locations/tampa",
    "https://acme.com/about",
    "https://acme.com/blog/post-one",
    "https://acme.com/blog/post-two",
    "https://acme.com/blog/post-three",
    "https://acme.com/wp-content/uploads/a.png",
]


def test_summarize_counts_every_unique_page_by_type():
    s = site_inventory.summarize_inventory(_URLS)
    assert s["page_count"] == 10
    assert s["counts"] == {
        "home": 1, "service": 2, "location": 2, "other": 1, "blog": 3, "noise": 1,
    }


def test_summarize_lists_landing_pages_and_excludes_blog_and_noise():
    s = site_inventory.summarize_inventory(_URLS)
    assert "/blog/post-one" not in s["landing_pages"]
    assert "/wp-content/uploads/a.png" not in s["landing_pages"]
    assert "/locations/tampa" in s["landing_pages"]
    # The absent city is the whole point — a strategy must be able to see it.
    assert not any("pompano" in p for p in s["landing_pages"])


def test_summarize_orders_landing_pages_shallowest_first():
    s = site_inventory.summarize_inventory(_URLS)
    depths = [len([x for x in p.split("/") if x]) for p in s["landing_pages"]]
    assert depths == sorted(depths)


def test_summarize_dedupes_urls_that_normalize_together():
    s = site_inventory.summarize_inventory([
        "https://acme.com/services/roofing",
        "https://acme.com/services/roofing/",
        "https://acme.com/services/roofing?utm_source=x",
    ])
    assert s["page_count"] == 1


def test_summarize_caps_landing_pages_and_reports_the_remainder():
    urls = [f"https://acme.com/p{i}" for i in range(50)]
    s = site_inventory.summarize_inventory(urls, max_paths=10)
    assert len(s["landing_pages"]) == 10
    assert s["landing_truncated"] == 40


def test_summarize_handles_an_empty_site():
    s = site_inventory.summarize_inventory([])
    assert s == {"page_count": 0, "counts": {}, "landing_pages": [], "landing_truncated": 0}


# ---------------------------------------------------------------------------
# Local pack extraction — free, because the organic and local-pack blocks come
# back in the SAME SERP response.
# ---------------------------------------------------------------------------


def test_find_local_pack_reads_entries_in_order():
    from services import dataforseo_rank

    items = [
        {"type": "organic", "domain": "acme.com", "rank_group": 1},
        {"type": "local_pack", "rank_group": 1, "title": "Bob's Roofing",
         "domain": "bobsroofing.com", "rating": {"value": 4.8, "votes_count": 120}},
        {"type": "local_pack", "rank_group": 2, "title": "Ace Roofing",
         "domain": "aceroofing.com", "rating": {"value": 4.5, "votes_count": 60}},
    ]
    pack = dataforseo_rank.find_local_pack_in_items(items)
    assert [p["title"] for p in pack] == ["Bob's Roofing", "Ace Roofing"]
    assert pack[0]["rating"] == 4.8 and pack[0]["reviews"] == 120


def test_find_local_pack_is_empty_when_the_serp_has_none():
    from services import dataforseo_rank

    items = [{"type": "organic", "domain": "acme.com", "rank_group": 1}]
    assert dataforseo_rank.find_local_pack_in_items(items) == []
    assert dataforseo_rank.find_local_pack_in_items([]) == []


def test_find_local_pack_tolerates_a_missing_rating():
    from services import dataforseo_rank

    pack = dataforseo_rank.find_local_pack_in_items(
        [{"type": "local_pack", "rank_group": 1, "title": "No Rating Co"}]
    )
    assert pack[0]["rating"] is None and pack[0]["reviews"] is None
