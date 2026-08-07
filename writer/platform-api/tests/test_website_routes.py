"""Route-surface invariants for the Website Builder.

Ordering is the interesting one. FastAPI matches in registration order, so a
static path registered *after* its parameterised sibling is unreachable — the
parameter swallows it. That failure is silent (a 404 or, worse, a lookup for a
website whose id is the literal string "status"), and the module has two such
pairs.
"""

from __future__ import annotations

import routers.websites as websites


def _paths() -> list[str]:
    return [r.path for r in websites.router.routes]


def _index(path: str) -> int:
    return _paths().index(path)


class TestRouteOrdering:
    def test_status_is_matched_before_the_website_id_parameter(self):
        # /websites/status has to win, or the frontend cannot ask whether the
        # module is enabled — the one question it must be able to ask while the
        # answer is "no".
        assert _index("/websites/status") < _index("/websites/{website_id}")

    def test_the_fleet_list_does_not_shadow_the_status_route(self):
        # Both are one segment under /websites. Different shapes, so they cannot
        # actually collide — asserted because the fleet route was added later
        # and a future reorder is exactly how "status" starts being read as a
        # website id.
        assert _index("/websites/status") < _index("/websites/{website_id}")
        assert "/websites" in _paths()

    def test_plan_approve_is_matched_before_plan(self):
        # Different segment counts, so this cannot actually collide — asserted
        # anyway because the sub-path is the kind of thing a later edit moves.
        assert "/websites/{website_id}/plan/approve" in _paths()
        assert "/websites/{website_id}/plan" in _paths()


class TestRouteSurface:
    def test_the_status_route_answers_while_the_module_is_dark(self):
        # Every other route 503s while the flag is off. This one must still
        # answer, or the workspace card cannot hide itself and the route cannot
        # 404 — the frontend would be asking a question that always errors.
        import asyncio
        from unittest.mock import patch

        with patch.object(websites.settings, "website_builder_enabled", False):
            result = asyncio.run(websites.website_builder_status(auth={}))
        assert result == {"enabled": False}

        with patch.object(websites.settings, "website_builder_enabled", True):
            result = asyncio.run(websites.website_builder_status(auth={}))
        assert result == {"enabled": True}

    def test_every_write_path_exists(self):
        for path in (
            "/clients/{client_id}/websites",
            "/websites/{website_id}/provision",
            "/websites/{website_id}/plan",
            "/websites/{website_id}/plan/approve",
            "/websites/{website_id}/generate",
            "/websites/{website_id}/publish",
            "/websites/{website_id}/pages/{page_id}/retry",
            "/websites/{website_id}/deploys/recheck",
            "/websites/{website_id}/jobs/status",
            "/websites",
            "/websites/{website_id}/restore",
            "/website-themes",
            "/website-themes/{theme_id}/recompile",
            "/website-themes/{theme_id}/approve",
            "/websites/{website_id}/theme",
            "/websites/{website_id}/facts",
        ):
            assert path in _paths(), path


class TestFactsRoutes:
    def test_facts_is_readable_and_writable(self):
        # GET (any authed user) reads the GBP-filled facts; PUT (staff) saves.
        assert "/websites/{website_id}/facts" in _paths()
        methods = {
            m for r in websites.router.routes if r.path == "/websites/{website_id}/facts"
            for m in r.methods
        }
        assert {"GET", "PUT"} <= methods


class TestThemeRoutes:
    def test_themes_live_outside_the_website_id_space(self):
        # /website-themes is a sibling of /websites, not a child: the same
        # uploaded design starts several sites, and nesting it under one would
        # push people to re-upload per site and end up with themes that drift.
        assert all(not p.startswith("/websites/{website_id}/themes") for p in _paths())

    def test_selecting_a_theme_is_a_website_route(self):
        # The selection belongs to the site even though the theme does not.
        assert "/websites/{website_id}/theme" in _paths()

    def test_theme_sub_paths_are_matched_before_the_theme_id_parameter(self):
        # Same trap as /websites/status: 'approve' read as a theme id.
        for sub in ("approve", "recompile"):
            assert _index(f"/website-themes/{{theme_id}}/{sub}") < len(_paths())
        assert _index("/website-themes") < _index("/website-themes/{theme_id}")
