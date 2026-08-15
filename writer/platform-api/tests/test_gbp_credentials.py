"""Guard the GBP discovery-client credential source.

The ingest/verify/resolve clients must authenticate with the OAuth-preferred
credentials (``gbp_auth.credentials()`` — the connected agency account, SA
fallback), NOT the service-account-only ``_credentials()``. GBP is OAuth-first:
a bare service account is usually not a listing Manager, so the SA path returns
404 ``location_not_recognized`` and no metrics ingest. This was a live bug —
``build_performance_client()`` defaulted to the SA while ``diagnose_performance``
used OAuth, so the diagnostic passed but every ingest 404'd.

No Google libraries needed: ``googleapiclient.discovery.build`` is stubbed to
capture the ``credentials`` kwarg.
"""

from __future__ import annotations

import sys
import types

from services import gbp_performance_service as gbp


def _stub_discovery(monkeypatch) -> dict:
    captured: dict = {}

    def fake_build(*args, **kwargs):
        captured.update(kwargs)
        return object()

    disc = types.ModuleType("googleapiclient.discovery")
    disc.build = fake_build
    pkg = sys.modules.get("googleapiclient") or types.ModuleType("googleapiclient")
    monkeypatch.setitem(sys.modules, "googleapiclient", pkg)
    monkeypatch.setitem(sys.modules, "googleapiclient.discovery", disc)
    return captured


def test_build_default_uses_oauth_preferred_credentials(monkeypatch):
    captured = _stub_discovery(monkeypatch)

    sentinel = object()
    from services import gbp_auth

    monkeypatch.setattr(gbp_auth, "credentials", lambda: sentinel)

    def _sa_boom():
        raise AssertionError("service-account _credentials() must not be the default path")

    monkeypatch.setattr(gbp, "_credentials", _sa_boom)

    gbp.build_performance_client()
    assert captured.get("credentials") is sentinel
    assert captured.get("cache_discovery") is False


def test_build_respects_explicit_creds(monkeypatch):
    """A caller-supplied client (e.g. diagnose_performance) is honored verbatim."""
    captured = _stub_discovery(monkeypatch)

    from services import gbp_auth

    def _auth_boom():
        raise AssertionError("explicit creds must not be overridden")

    monkeypatch.setattr(gbp_auth, "credentials", _auth_boom)

    explicit = object()
    gbp._build("businessprofileperformance", "v1", explicit)
    assert captured.get("credentials") is explicit
