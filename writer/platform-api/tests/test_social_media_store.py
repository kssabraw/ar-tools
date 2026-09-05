"""Unit tests for the social media store's pure helpers (no SDK / network)."""

import pytest

from services.social import media_store


def test_resolve_media_type():
    assert media_store.resolve_media_type("image/jpeg") == ("jpg", "image")
    assert media_store.resolve_media_type("image/png") == ("png", "image")
    assert media_store.resolve_media_type("video/mp4") == ("mp4", "video")
    assert media_store.resolve_media_type("video/quicktime") == ("mov", "video")
    # content-type with charset suffix + case
    assert media_store.resolve_media_type("IMAGE/WEBP; charset=x") == ("webp", "image")
    with pytest.raises(ValueError):
        media_store.resolve_media_type("application/pdf")


def test_media_key_shape():
    k = media_store.media_key("mp4", "upload")
    assert k.startswith("social/upload/") and k.endswith(".mp4")
    kg = media_store.media_key("png", "generated")
    assert kg.startswith("social/generated/") and kg.endswith(".png")
    # unknown kind falls back to upload; keys are unique
    assert media_store.media_key("jpg", "weird").startswith("social/upload/")
    assert media_store.media_key("jpg") != media_store.media_key("jpg")


def test_r2_configured_and_select_store(monkeypatch):
    from config import settings
    for attr in ("r2_account_id", "r2_access_key_id", "r2_secret_access_key",
                 "r2_bucket", "r2_public_base_url"):
        monkeypatch.setattr(settings, attr, "")
    assert media_store.r2_configured() is False
    assert media_store.select_store() == "supabase"

    for attr in ("r2_account_id", "r2_access_key_id", "r2_secret_access_key", "r2_bucket"):
        monkeypatch.setattr(settings, attr, "x")
    assert media_store.r2_configured() is False  # public base still missing
    monkeypatch.setattr(settings, "r2_public_base_url", "https://media.example.com")
    assert media_store.r2_configured() is True
    assert media_store.select_store() == "r2"
    assert media_store.select_store(prefer_r2=False) == "supabase"


def test_r2_public_url_construction(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "r2_bucket", "b")
    monkeypatch.setattr(settings, "r2_public_base_url", "https://media.example.com/")
    store = media_store.R2Store()
    assert store.public_url("social/upload/x.mp4") == "https://media.example.com/social/upload/x.mp4"
    assert store.public_url("/social/upload/y.jpg") == "https://media.example.com/social/upload/y.jpg"
