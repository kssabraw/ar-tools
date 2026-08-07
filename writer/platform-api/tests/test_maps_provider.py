"""Unit tests for the per-client Maps data-source resolution.

`resolve_scan_provider` is the single place that decides whether a NEW geo-grid
scan runs on Local Dominator or DataForSEO: the per-client
maps_scan_configs.provider when set, otherwise the global MAPS_SCAN_PROVIDER.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import settings  # noqa: E402
from services import local_dominator as ld  # noqa: E402


@pytest.fixture
def default_local(monkeypatch):
    monkeypatch.setattr(settings, "maps_scan_provider", "local_dominator")


def test_per_client_dataforseo_overrides_global_default(default_local):
    assert ld.resolve_scan_provider({"provider": "dataforseo"}) == "dataforseo"


def test_per_client_local_dominator_overrides_global_default(monkeypatch):
    monkeypatch.setattr(settings, "maps_scan_provider", "dataforseo")
    assert ld.resolve_scan_provider({"provider": "local_dominator"}) == "local_dominator"


def test_unset_provider_inherits_global_default(default_local):
    assert ld.resolve_scan_provider({"provider": None}) == "local_dominator"
    assert ld.resolve_scan_provider({}) == "local_dominator"


def test_unset_provider_inherits_global_dataforseo(monkeypatch):
    monkeypatch.setattr(settings, "maps_scan_provider", "dataforseo")
    assert ld.resolve_scan_provider({}) == "dataforseo"


def test_none_config_falls_back_to_global(default_local):
    assert ld.resolve_scan_provider(None) == "local_dominator"
