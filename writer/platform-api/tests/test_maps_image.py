"""Unit tests for the geo-grid map-image pure helpers (Maps Module #5).

These mirror the frontend (frontend/src/components/maps/{visuals,rank}.ts) so the
saved PNG matches the in-app map exactly. Pillow render / Google fetch / Supabase
upload are I/O and not exercised here.
"""

import math

from services import maps_image as mi


def test_rank_color_bands():
    # Mirrors rankColor() in rank.ts.
    assert mi.rank_color(None) == (229, 231, 235)   # not ranked
    assert mi.rank_color(0) == (229, 231, 235)      # < 1 → grey
    assert mi.rank_color(1) == (22, 163, 74)        # 1–3 green
    assert mi.rank_color(3) == (22, 163, 74)
    assert mi.rank_color(4) == (101, 163, 13)       # 4–7
    assert mi.rank_color(7) == (101, 163, 13)
    assert mi.rank_color(8) == (202, 138, 4)        # 8–10
    assert mi.rank_color(10) == (202, 138, 4)
    assert mi.rank_color(11) == (234, 88, 22)       # 11–15
    assert mi.rank_color(15) == (234, 88, 22)
    assert mi.rank_color(16) == (220, 38, 38)       # 16+
    assert mi.rank_color(99) == (220, 38, 38)


def test_grid_cols():
    assert mi._grid_cols(None) == 0
    assert mi._grid_cols([]) == 0
    assert mi._grid_cols([[1, 2, 3]]) == 3
    assert mi._grid_cols([[1], [1, 2, 3], [1, 2]]) == 3  # widest row


def test_fit_zoom_matches_frontend_formula():
    lat, n = 40.0, 13
    target = (n * 1609.34) / (mi.LOGICAL * 0.9)
    expected = max(1, min(16, math.floor(
        math.log2((mi._MERCATOR_M_PER_PX_Z0 * math.cos(math.radians(lat))) / target)
    )))
    assert mi.fit_zoom(lat, n) == expected
    # Always an int within Google's clamp.
    for n2 in (3, 7, 9, 15, 21):
        z = mi.fit_zoom(lat, n2)
        assert isinstance(z, int) and 1 <= z <= 16


def test_cell_lat_lng_center_is_center():
    # Odd n → the exact middle cell sits on the scan center.
    n = 9
    c = (n - 1) // 2
    lat, lng = mi.cell_lat_lng(c, c, n, 40.0, -75.0)
    assert lat == 40.0
    assert abs(lng - (-75.0)) < 1e-9


def test_cell_lat_lng_north_and_east():
    n = 9
    c = (n - 1) // 2
    # row above center = further north (higher lat); col right of center = east.
    north_lat, _ = mi.cell_lat_lng(c - 1, c, n, 40.0, -75.0)
    _, east_lng = mi.cell_lat_lng(c, c + 1, n, 40.0, -75.0)
    assert north_lat > 40.0
    assert east_lng > -75.0


def test_project_to_pixel_center_is_middle():
    x, y = mi.project_to_pixel(40.0, -75.0, 40.0, -75.0, 12)
    assert abs(x - mi.LOGICAL / 2) < 1e-6
    assert abs(y - mi.LOGICAL / 2) < 1e-6


def test_project_to_pixel_north_is_higher_on_image():
    # A point north of center projects to a smaller y (higher on the image).
    _, y_center = mi.project_to_pixel(40.0, -75.0, 40.0, -75.0, 12)
    _, y_north = mi.project_to_pixel(40.05, -75.0, 40.0, -75.0, 12)
    assert y_north < y_center


def test_base_map_url_requires_key(monkeypatch):
    monkeypatch.setattr(mi.settings, "google_maps_api_key", "", raising=False)
    assert mi.base_map_url(40.0, -75.0, 12) is None

    monkeypatch.setattr(mi.settings, "google_maps_api_key", "KEY123", raising=False)
    url = mi.base_map_url(40.0, -75.0, 12)
    assert url and "staticmap" in url
    assert "center=40.0,-75.0" in url
    assert "zoom=12" in url
    assert f"size={mi.LOGICAL}x{mi.LOGICAL}" in url
    assert f"scale={mi.SCALE}" in url
    assert "key=KEY123" in url


def test_render_map_png_no_grid_returns_none():
    assert mi.render_map_png(None, 40.0, -75.0, None) is None
    assert mi.render_map_png([], 40.0, -75.0, None) is None
    assert mi.render_map_png([[1]], None, None, None) is None
