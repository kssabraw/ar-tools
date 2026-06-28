"""Unit tests for the Drive folder resolver (per-content-type publishing)."""

from services.google_docs import resolve_drive_folder


def test_type_specific_folder_wins():
    client = {
        "drive_folders": {"blog_post": "folder-blog", "service_page": "folder-svc"},
        "google_drive_folder_id": "folder-default",
    }
    assert resolve_drive_folder(client, "blog_post") == "folder-blog"
    assert resolve_drive_folder(client, "service_page") == "folder-svc"


def test_falls_back_to_default_when_type_unset():
    client = {
        "drive_folders": {"blog_post": "folder-blog"},
        "google_drive_folder_id": "folder-default",
    }
    # location_page has no entry → default
    assert resolve_drive_folder(client, "location_page") == "folder-default"


def test_falls_back_when_no_map_at_all():
    client = {"google_drive_folder_id": "folder-default"}
    assert resolve_drive_folder(client, "blog_post") == "folder-default"


def test_empty_string_entry_falls_through_to_default():
    client = {
        "drive_folders": {"blog_post": ""},
        "google_drive_folder_id": "folder-default",
    }
    assert resolve_drive_folder(client, "blog_post") == "folder-default"


def test_whitespace_entry_falls_through_to_default():
    client = {
        "drive_folders": {"blog_post": "   "},
        "google_drive_folder_id": "folder-default",
    }
    assert resolve_drive_folder(client, "blog_post") == "folder-default"


def test_non_string_entry_falls_through_to_default():
    client = {
        "drive_folders": {"blog_post": 12345},
        "google_drive_folder_id": "folder-default",
    }
    assert resolve_drive_folder(client, "blog_post") == "folder-default"


def test_values_are_stripped():
    client = {"drive_folders": {"blog_post": "  folder-blog  "}, "google_drive_folder_id": "d"}
    assert resolve_drive_folder(client, "blog_post") == "folder-blog"
    assert resolve_drive_folder({"google_drive_folder_id": "  d  "}, "blog_post") == "d"


def test_returns_none_when_nothing_configured():
    assert resolve_drive_folder({"drive_folders": {}}, "use_case") is None
    assert resolve_drive_folder({}, "blog_post") is None
    # whitespace-only default → None (not a bogus "   " folder id)
    assert resolve_drive_folder({"google_drive_folder_id": "   "}, "blog_post") is None
    # non-dict drive_folders → ignored, falls to default
    assert resolve_drive_folder({"drive_folders": "oops", "google_drive_folder_id": "d"}, "blog_post") == "d"


def test_none_content_type_uses_default():
    client = {"drive_folders": {"blog_post": "x"}, "google_drive_folder_id": "d"}
    assert resolve_drive_folder(client, None) == "d"
