"""Import smoke test for the FastAPI application.

Importing ``main`` is exactly what uvicorn does at boot: it imports every router
module, which evaluates their route decorators and runs ``app.include_router``
for each. A whole class of mistakes fails *at import time* here — most notably a
``status_code=204`` route that also declares a response body, which trips
FastAPI's "Status code 204 must not have a response body" assertion and crash-
loops the entire service (this is what took the platform-api — and with it every
client on the dashboard — down once already).

There is no FastAPI ``TestClient`` harness in this suite, and importing ``main``
only builds the app object: the lifespan (job worker, schedulers, Guides seeding)
runs on startup, not on import, and ``get_supabase()`` is lazy, so this needs no
network, credentials, or env beyond the all-defaulted ``Settings``.
"""

from __future__ import annotations

from fastapi.routing import APIRoute

import main


def _api_routes() -> dict[tuple[str, str], APIRoute]:
    """Map (HTTP method, path) -> APIRoute for the mounted application."""
    index: dict[tuple[str, str], APIRoute] = {}
    for route in main.app.routes:
        if isinstance(route, APIRoute):
            for method in route.methods:
                index[(method, route.path)] = route
    return index


def test_app_imports_and_registers_routes():
    """The app object builds and exposes a healthy set of routes.

    A bare import that raised would never reach this assertion — that's the
    point. The count guard catches a router silently failing to mount.
    """
    routes = _api_routes()
    assert len(routes) > 50


def test_clients_list_route_registered():
    """The route whose disappearance is most visible to users stays wired up."""
    assert ("GET", "/clients") in _api_routes()


def test_204_delete_routes_have_no_response_body():
    """Regression guard for the import-time crash.

    These DELETE endpoints return 204 (no body). Declaring a body/response model
    alongside a 204 makes FastAPI assert at import and the app never boots — so
    asserting their presence here means the modules imported cleanly, and the
    status code stays the body-less 204 the pattern requires.
    """
    routes = _api_routes()
    for path in ("/guides/{guide_id}", "/sops/{sop_id}"):
        route = routes.get(("DELETE", path))
        assert route is not None, f"missing DELETE {path}"
        assert route.status_code == 204
