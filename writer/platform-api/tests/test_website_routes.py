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
        ):
            assert path in _paths(), path
