"""Unit tests for services.local_seo_matrix — the pure planner core (Phase 0).

Plain-dict fixtures, no I/O. Covers: URL pattern validation + path rendering,
cells built through #953's parser (parity pinned), the gap-fill diff, runnable /
release selectors, sibling-link selection, the deterministic link guarantee, and
the estimate + scale gates.
"""

from __future__ import annotations

from services import local_seo_matrix as m
from services import local_seo_targets as lt

SERVICES = ["Roof restoration", "Tile roof restoration", "Colorbond roof restoration"]
LOCATIONS = ["Melbourne", "Caulfield", "Hawthorn", "Moorabbin"]


def _grid(**kw) -> list[dict]:
    cells = m.build_cells(SERVICES, LOCATIONS, **kw)
    for i, c in enumerate(cells):
        c["id"] = f"c{i}"
    return cells


def _by_key(cells):
    return {m.cell_key(c): c for c in cells}


# ── URL pattern ───────────────────────────────────────────────────────────────

def test_validate_url_pattern_requires_both_tokens():
    assert m.validate_url_pattern(m.DEFAULT_URL_PATTERN) == []
    for preset in m.URL_PATTERN_PRESETS:
        assert m.validate_url_pattern(preset) == []
    assert "url_pattern_missing_location_token" in m.validate_url_pattern("/{service}/")
    assert "url_pattern_missing_service_token" in m.validate_url_pattern("/{location}/")
    assert m.validate_url_pattern("") == ["url_pattern_empty"]
    assert "url_pattern_unknown_token" in m.validate_url_pattern("/{service}/{city}/{location}/")


def test_render_path_normalises_slashes():
    assert m.render_path("/{service}-{location}/", "roof-restoration", "hawthorn") == "/roof-restoration-hawthorn/"
    assert m.render_path("{location}/{service}", "roof-restoration", "hawthorn") == "/hawthorn/roof-restoration/"
    assert m.render_path("//areas//{location}//{service}//", "a", "b") == "/areas/b/a/"


# ── cells ─────────────────────────────────────────────────────────────────────

def test_build_cells_is_the_full_cross_product_with_axis_positions():
    cells = _grid()
    assert len(cells) == len(SERVICES) * len(LOCATIONS)
    by_key = _by_key(cells)
    cell = by_key[("tile-roof-restoration", "hawthorn")]
    assert cell["keyword"] == "Tile roof restoration Hawthorn"
    assert cell["service_label"] == "Tile roof restoration"
    assert cell["location_name"] == "Hawthorn"
    assert cell["service_order"] == 1
    assert cell["location_order"] == 2
    assert cell["path"] == "/tile-roof-restoration-hawthorn/"
    assert cell["status"] == "missing"


def test_build_cells_keywords_match_the_one_shot_parser_byte_for_byte():
    # Parity guard: the matrix must never compose a keyword differently from
    # #953's "Upload your own" mode — both read build_matrix_silos.
    silos = lt.build_matrix_silos("\n".join(SERVICES), "\n".join(LOCATIONS))
    parser_keywords = [p["keyword"] for s in silos for p in s["pages"]]
    assert [c["keyword"] for c in _grid()] == parser_keywords


def test_build_cells_seed_city_cell_recovers_its_location_without_location_name():
    # With a seed city the parser omits location_name on that cell (the Option B
    # fix); the cell must still know its location + slug + path.
    silos = lt.build_matrix_silos("\n".join(SERVICES), "\n".join(LOCATIONS), seed_city="Melbourne")
    assert "location_name" not in silos[0]["pages"][0]
    cells = m.build_cells(SERVICES, LOCATIONS, seed_city="Melbourne")
    cell = _by_key(cells)[("roof-restoration", "melbourne")]
    assert cell["location_name"] == "Melbourne"
    assert cell["location_order"] == 0
    assert cell["path"] == "/roof-restoration-melbourne/"
    assert len(cells) == len(SERVICES) * len(LOCATIONS)


def test_build_cells_honours_url_pattern():
    cells = m.build_cells(["Roof restoration"], ["Hawthorn"], url_pattern="/{location}/{service}/")
    assert cells[0]["path"] == "/hawthorn/roof-restoration/"


def test_build_cells_dedupes_axes_case_insensitively():
    cells = m.build_cells(["Roofing", "roofing"], ["Melbourne", "melbourne", ""])
    assert len(cells) == 1


# ── diff_cells (gap-fill) ─────────────────────────────────────────────────────

def test_diff_adds_only_new_cells_when_a_location_is_added():
    existing = _grid()
    desired = m.build_cells(SERVICES, LOCATIONS + ["Brighton"])
    diff = m.diff_cells(existing, desired)
    assert {c["location_slug"] for c in diff["add"]} == {"brighton"}
    assert len(diff["add"]) == len(SERVICES)
    assert diff["remove"] == [] and diff["skip"] == []
    assert len(diff["keep"]) == len(existing)


def test_diff_removes_pageless_cells_but_skips_cells_with_a_page():
    existing = _grid()
    by_key = _by_key(existing)
    by_key[("roof-restoration", "moorabbin")]["page_id"] = "page-1"  # generated already
    desired = m.build_cells(SERVICES, LOCATIONS[:-1])  # Moorabbin dropped by the user
    diff = m.diff_cells(existing, desired)
    assert {cell_key for cell_key in map(m.cell_key, diff["remove"])} == {
        ("tile-roof-restoration", "moorabbin"),
        ("colorbond-roof-restoration", "moorabbin"),
    }
    assert [m.cell_key(c) for c in diff["skip"]] == [("roof-restoration", "moorabbin")]
    assert diff["add"] == []


def test_diff_keeps_a_reappearing_skipped_cell():
    existing = _grid()
    parked = _by_key(existing)[("roof-restoration", "hawthorn")]
    parked["status"], parked["page_id"] = "skipped", "page-9"
    diff = m.diff_cells(existing, m.build_cells(SERVICES, LOCATIONS))
    assert parked in diff["keep"] and diff["add"] == []


# ── selectors ─────────────────────────────────────────────────────────────────

def test_select_runnable_defaults_to_missing_and_failed_only():
    cells = _grid()
    statuses = ["missing", "failed", "found", "on_site", "queued", "done", "published", "skipped"]
    for c, s in zip(cells, statuses):
        c["status"] = s
    picked = {c["status"] for c in m.select_runnable(cells)}
    assert picked == {"missing", "failed"}
    picked = {c["status"] for c in m.select_runnable(cells, include_covered=True)}
    assert picked == {"missing", "failed", "found", "on_site"}


def test_select_runnable_by_ids_allows_covered_but_never_in_flight_or_done():
    cells = _grid()
    cells[0]["status"] = "on_site"
    cells[1]["status"] = "done"
    cells[2]["status"] = "generating"
    picked = m.select_runnable(cells, cell_ids=[cells[0]["id"], cells[1]["id"], cells[2]["id"], cells[3]["id"]])
    assert [c["id"] for c in picked] == [cells[0]["id"], cells[3]["id"]]


def test_select_release_batch_walks_location_major_and_skips_claimed():
    cells = _grid()
    _by_key(cells)[("roof-restoration", "melbourne")]["released_at"] = "2026-09-02T00:00:00Z"
    _by_key(cells)[("tile-roof-restoration", "melbourne")]["status"] = "done"
    batch = m.select_release_batch(cells, 3)
    assert [m.cell_key(c) for c in batch] == [
        ("colorbond-roof-restoration", "melbourne"),  # the rest of Melbourne first
        ("roof-restoration", "caulfield"),
        ("tile-roof-restoration", "caulfield"),
    ]
    assert m.select_release_batch(cells, 0) == []


# ── sibling links ─────────────────────────────────────────────────────────────

def test_sibling_links_other_services_here_then_other_locations_for_this_service():
    cells = _grid()
    me = _by_key(cells)[("tile-roof-restoration", "hawthorn")]
    links = m.sibling_links(me, cells, "https://fcr.com.au")
    by_rel = {}
    for l in links:
        by_rel.setdefault(l["relation"], []).append(l)
    assert [l["url"] for l in by_rel[m.SAME_LOCATION]] == [
        "https://fcr.com.au/roof-restoration-hawthorn/",
        "https://fcr.com.au/colorbond-roof-restoration-hawthorn/",
    ]
    assert [l["url"] for l in by_rel[m.SAME_SERVICE]] == [
        "https://fcr.com.au/tile-roof-restoration-melbourne/",
        "https://fcr.com.au/tile-roof-restoration-caulfield/",
        "https://fcr.com.au/tile-roof-restoration-moorabbin/",
    ]
    assert by_rel[m.SAME_LOCATION][0]["anchor"] == "Roof restoration in Hawthorn"
    assert all(l["url"] != "https://fcr.com.au/tile-roof-restoration-hawthorn/" for l in links)


def test_sibling_links_caps_locations_and_total():
    services = ["Roof restoration", "Gutters", "Skylights", "Fascias", "Solar"]
    locations = [f"Suburb {i}" for i in range(12)]
    cells = m.build_cells(services, locations)
    me = _by_key(cells)[("roof-restoration", "suburb-0")]
    links = m.sibling_links(me, cells, "", location_cap=4, max_links=10)
    assert len(links) == 8  # 4 other services + 4 locations
    assert sum(1 for l in links if l["relation"] == m.SAME_SERVICE) == 4
    links = m.sibling_links(me, cells, "", location_cap=20, max_links=6)
    assert len(links) == 6


def test_sibling_links_nearest_first_with_coords_and_never_to_parked_cells():
    cells = _grid()
    me = _by_key(cells)[("roof-restoration", "melbourne")]
    _by_key(cells)[("tile-roof-restoration", "melbourne")]["status"] = "skipped"
    coords = {"melbourne": (0.0, 0.0), "caulfield": (0.0, 3.0), "hawthorn": (0.0, 1.0), "moorabbin": (0.0, 2.0)}
    links = m.sibling_links(me, cells, "https://fcr.com.au", coords=coords)
    same_svc = [l["url"] for l in links if l["relation"] == m.SAME_SERVICE]
    assert same_svc == [
        "https://fcr.com.au/roof-restoration-hawthorn/",
        "https://fcr.com.au/roof-restoration-moorabbin/",
        "https://fcr.com.au/roof-restoration-caulfield/",
    ]
    same_loc = [l["url"] for l in links if l["relation"] == m.SAME_LOCATION]
    assert same_loc == ["https://fcr.com.au/colorbond-roof-restoration-melbourne/"]


def test_sibling_links_use_a_live_url_when_the_cell_is_on_site():
    cells = _grid()
    me = _by_key(cells)[("roof-restoration", "melbourne")]
    live = _by_key(cells)[("roof-restoration", "hawthorn")]
    live["status"], live["url"] = "on_site", "https://fcr.com.au/services/hawthorn-roof-restoration/"
    links = m.sibling_links(me, cells, "https://fcr.com.au")
    assert "https://fcr.com.au/services/hawthorn-roof-restoration/" in [l["url"] for l in links]


def test_cell_url_relative_without_base():
    assert m.cell_url({"path": "/a-b/", "status": "missing"}, "") == "/a-b/"


# ── deterministic link guarantee ──────────────────────────────────────────────

LINKS = [
    {"anchor": "Roof restoration in Hawthorn", "url": "https://fcr.com.au/roof-restoration-hawthorn/", "relation": m.SAME_LOCATION},
    {"anchor": "Tile roof restoration in Melbourne", "url": "https://fcr.com.au/tile-roof-restoration-melbourne/", "relation": m.SAME_SERVICE},
]


def test_check_internal_links_matches_by_path_ignoring_host_and_trailing_slash():
    html = '<p>See <a href="https://www.fcr.com.au/roof-restoration-hawthorn">this</a>.</p>'
    cov = m.check_internal_links(html, LINKS)
    assert cov["expected"] == 2
    assert cov["present"] == [LINKS[0]["url"]]
    assert cov["missing"] == [LINKS[1]]


def test_ensure_internal_links_appends_only_the_missing_and_is_idempotent():
    html = '<article><h1>Tile roof restoration Hawthorn</h1><p><a href="/tile-roof-restoration-melbourne/">Melbourne</a></p></article>'
    out, cov = m.ensure_internal_links(html, LINKS)
    assert cov["missing"] == [] and cov["appended"] == 1 and cov["expected"] == 2
    assert out.count("data-matrix-links") == 1
    assert out.index("data-matrix-links") < out.index("</article>")
    # Only the missing link was appended — the writer's own link is not duplicated.
    assert out.count("roof-restoration-hawthorn/") == 1
    assert out.count("tile-roof-restoration-melbourne/") == 1
    again, cov2 = m.ensure_internal_links(out, LINKS)
    assert again == out and cov2["appended"] == 0


def test_ensure_internal_links_noop_when_all_present_and_appends_at_end_without_article():
    html = '<a href="/roof-restoration-hawthorn/">a</a><a href="/tile-roof-restoration-melbourne/">b</a>'
    out, cov = m.ensure_internal_links(html, LINKS)
    assert out == html and cov["appended"] == 0
    out2, _ = m.ensure_internal_links("<p>no links</p>", LINKS)
    assert out2.startswith("<p>no links</p>") and out2.rstrip().endswith("</section>")
    assert "Related services" in out2 and "Nearby areas" in out2


def test_render_links_block_escapes_and_groups():
    block = m.render_links_block([
        {"anchor": 'A & "B"', "url": "/x/?a=1&b=2", "relation": m.SAME_SERVICE},
    ])
    assert "Nearby areas" in block and "Related services" not in block
    assert "A &amp; &quot;B&quot;" in block and 'href="/x/?a=1&amp;b=2"' in block
    assert m.render_links_block([]) == ""


# ── estimate + gates ──────────────────────────────────────────────────────────

def test_estimate():
    assert m.estimate(12, cost_per_page_usd=1.0, minutes_per_page=11) == {
        "count": 12, "est_cost_usd": 12.0, "est_minutes": 132,
    }
    assert m.estimate(-3, cost_per_page_usd=1.0, minutes_per_page=11)["count"] == 0


def test_scale_gates():
    assert m.scale_gates(12, 12, max_per_run=50) == []
    kinds = {g["kind"] for g in m.scale_gates(250, 12, max_per_run=50)}
    assert kinds == {"matrix_signoff_required"}
    assert m.scale_gates(250, 12, max_per_run=50, signoff_acknowledged=True) == []
    kinds = {g["kind"] for g in m.scale_gates(250, 60, max_per_run=50)}
    assert kinds == {"matrix_signoff_required", "matrix_cell_limit"}
    assert all(g["blocking"] for g in m.scale_gates(250, 60, max_per_run=50))
