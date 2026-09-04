"""Unit tests for the GBP Profile Editor module.

Pure builders/validators/parsers (no Google, no DB) plus flow tests for the
apply job (re-read-and-diff), the reconciler backoff, and the draft mapping —
driven by a fake Supabase + monkeypatched live get/patch.
"""

from __future__ import annotations

import asyncio

import pytest

from services import gbp_profile_api as api
from services import gbp_profile_service as svc


# ═══════════════════════════════════════════════════════════════════════════
# Pure: description validation + linter
# ═══════════════════════════════════════════════════════════════════════════
def test_validate_description_ok():
    assert api.validate_description("  We fix roofs in Tampa.  ") == "We fix roofs in Tampa."


def test_validate_description_too_long():
    with pytest.raises(ValueError, match="description_too_long"):
        api.validate_description("x" * 751, 750)


def test_validate_description_rejects_url_and_phone():
    with pytest.raises(ValueError, match="description_contains_url"):
        api.validate_description("Visit www.example.com today")
    with pytest.raises(ValueError, match="description_contains_phone"):
        api.validate_description("Call us at (813) 555-1212 now")
    with pytest.raises(ValueError, match="description_contains_phone"):
        api.validate_description("Reach us on 813-555-1212 anytime")


def test_lint_description_flags_advisory_only():
    hits = {w["code"] for w in api.lint_description("BEST ROOFER!!! visit www.x.com 813-555-1212")}
    assert {"url", "phone", "all_caps", "promotional", "punctuation"} <= hits


def test_lint_clean_description_has_no_warnings():
    assert api.lint_description("We repair and restore roofs across the Tampa Bay area.") == []


def test_build_description_patch():
    body, mask = api.build_description_patch("Hello there")
    assert body == {"profile": {"description": "Hello there"}}
    assert mask == "profile.description"


# ═══════════════════════════════════════════════════════════════════════════
# Pure: hours mapping (TimeOfDay, closed, 24h, cross-midnight)
# ═══════════════════════════════════════════════════════════════════════════
def test_parse_time_of_day():
    assert api.parse_time_of_day("09:30") == {"hours": 9, "minutes": 30}
    assert api.parse_time_of_day("00:00") == {}
    assert api.parse_time_of_day("24:00") == {"hours": 24}


def test_parse_time_of_day_rejects_bad():
    for bad in ["9:5", "25:00", "12:60", "abc", "24:30"]:
        with pytest.raises(ValueError):
            api.parse_time_of_day(bad)


def test_format_time_of_day():
    assert api.format_time_of_day({"hours": 9, "minutes": 5}) == "09:05"
    assert api.format_time_of_day({}) == "00:00"
    assert api.format_time_of_day(None) == "00:00"


def test_build_hours_patch_normal_and_closed():
    body, mask = api.build_hours_patch([
        {"day": 0, "open_24": False, "periods": [{"open": "09:00", "close": "17:00"}]},
        # Tuesday absent → closed → no period emitted.
    ])
    assert mask == "regularHours"
    periods = body["regularHours"]["periods"]
    assert periods == [{
        "openDay": "MONDAY", "openTime": {"hours": 9},
        "closeDay": "MONDAY", "closeTime": {"hours": 17},
    }]


def test_build_hours_patch_open_24():
    body, _ = api.build_hours_patch([{"day": 2, "open_24": True, "periods": []}])
    assert body["regularHours"]["periods"] == [{
        "openDay": "WEDNESDAY", "openTime": {}, "closeDay": "WEDNESDAY", "closeTime": {"hours": 24},
    }]


def test_build_hours_patch_cross_midnight():
    body, _ = api.build_hours_patch([{"day": 4, "open_24": False, "periods": [{"open": "18:00", "close": "02:00"}]}])
    p = body["regularHours"]["periods"][0]
    assert p["openDay"] == "FRIDAY" and p["closeDay"] == "SATURDAY"


def test_build_hours_patch_special_included_only_when_given():
    body, mask = api.build_hours_patch([], special_rows=None)
    assert mask == "regularHours" and "specialHours" not in body
    body, mask = api.build_hours_patch([], special_rows=[])
    assert mask == "regularHours,specialHours"
    assert body["specialHours"] == {"specialHourPeriods": []}


def test_build_hours_patch_special_period():
    body, _ = api.build_hours_patch([], special_rows=[
        {"start": {"year": 2026, "month": 12, "day": 25}, "closed": True},
    ])
    sp = body["specialHours"]["specialHourPeriods"][0]
    assert sp["startDate"] == {"year": 2026, "month": 12, "day": 25}
    assert sp["endDate"] == {"year": 2026, "month": 12, "day": 25} and sp["closed"] is True


# ═══════════════════════════════════════════════════════════════════════════
# Pure: services mapping (free-form, dedup, category attach, structured passthrough)
# ═══════════════════════════════════════════════════════════════════════════
def test_build_services_patch_free_form_and_dedup():
    body, mask = api.build_services_patch(
        [
            {"kind": "free_form", "label": "Roof Repair", "category_id": "gcid:roofing_contractor", "description": "fix leaks"},
            {"kind": "free_form", "label": "roof repair", "category_id": "gcid:roofing_contractor"},  # dup label
        ],
        allowed_categories={"gcid:roofing_contractor"},
    )
    assert mask == "serviceItems"
    assert body["serviceItems"] == [{
        "freeFormServiceItem": {
            "category": "gcid:roofing_contractor",
            "label": {"displayName": "Roof Repair", "languageCode": "en", "description": "fix leaks"},
        }
    }]


def test_build_services_patch_requires_label_and_category():
    with pytest.raises(ValueError, match="service_label_required"):
        api.build_services_patch([{"kind": "free_form", "label": "  "}])
    with pytest.raises(ValueError, match="service_category_required"):
        api.build_services_patch([{"kind": "free_form", "label": "X"}])


def test_build_services_patch_validates_category_against_listing():
    with pytest.raises(ValueError, match="invalid_service_category:Bad"):
        api.build_services_patch(
            [{"kind": "free_form", "label": "Bad", "category_id": "gcid:not_on_listing"}],
            allowed_categories={"gcid:roofing_contractor"},
        )


def test_build_services_patch_preserves_structured():
    raw = {"structuredServiceItem": {"serviceTypeId": "job_type_id:x", "description": "d"}}
    body, _ = api.build_services_patch([{"kind": "structured", "raw": raw}])
    assert body["serviceItems"] == [raw]


def test_build_services_patch_structured_pick():
    body, mask = api.build_services_patch([
        {"kind": "structured", "service_type_id": "job_type_id:flex_office_rentals"},
        {"kind": "structured", "service_type_id": "job_type_id:coworking", "description": "hot desks"},
    ])
    assert mask == "serviceItems"
    assert body["serviceItems"] == [
        {"structuredServiceItem": {"serviceTypeId": "job_type_id:flex_office_rentals"}},
        {"structuredServiceItem": {"serviceTypeId": "job_type_id:coworking", "description": "hot desks"}},
    ]


def test_build_services_patch_structured_pick_requires_id():
    with pytest.raises(ValueError, match="service_type_id_required"):
        api.build_services_patch([{"kind": "structured"}])


def test_build_services_patch_structured_dedup_across_pick_and_passthrough():
    # A picked id + a passthrough raw for the SAME serviceTypeId collapse to one.
    raw = {"structuredServiceItem": {"serviceTypeId": "job_type_id:x", "description": "d"}}
    body, _ = api.build_services_patch([
        {"kind": "structured", "raw": raw},
        {"kind": "structured", "service_type_id": "job_type_id:x"},
    ])
    assert body["serviceItems"] == [raw]


def test_build_services_patch_structured_uses_row_description_over_raw():
    # Editing an existing structured service's description takes effect (the
    # row's service_type_id + edited description win over the stored raw).
    raw = {"structuredServiceItem": {"serviceTypeId": "job_type_id:x", "description": "old"}}
    body, _ = api.build_services_patch([
        {"kind": "structured", "service_type_id": "job_type_id:x", "description": "new desc", "raw": raw},
    ])
    assert body["serviceItems"] == [
        {"structuredServiceItem": {"serviceTypeId": "job_type_id:x", "description": "new desc"}},
    ]


def test_diff_services_structured_description_change_detected():
    a = [{"kind": "structured", "service_type_id": "job_type_id:x", "label": "X", "description": "d1"}]
    b = [{"kind": "structured", "service_type_id": "job_type_id:x", "label": "X", "description": "d2"}]
    assert api.diff_field("services", a, b) is True


def test_build_services_patch_mixes_structured_and_kept_free_form():
    body, _ = api.build_services_patch(
        [
            {"kind": "structured", "service_type_id": "job_type_id:x"},
            {"kind": "free_form", "label": "Legacy Custom", "category_id": "gcid:roofing_contractor"},
        ],
        allowed_categories={"gcid:roofing_contractor"},
    )
    kinds = [next(iter(i)) for i in body["serviceItems"]]
    assert kinds == ["structuredServiceItem", "freeFormServiceItem"]


# ═══════════════════════════════════════════════════════════════════════════
# Pure: service-type picker (categories.batchGet view=FULL → picker shape)
# ═══════════════════════════════════════════════════════════════════════════
def test_humanize_service_type_id():
    assert api.humanize_service_type_id("job_type_id:flex_office_rentals") == "Flex Office Rentals"
    assert api.humanize_service_type_id("gcid:coworking_space") == "Coworking Space"
    assert api.humanize_service_type_id("") == ""


_BATCHGET = {
    "categories": [
        {
            "name": "gcid:roofing_contractor", "displayName": "Roofing contractor",
            "serviceTypes": [
                {"serviceTypeId": "job_type_id:roof_repair", "displayName": "Roof repair"},
                {"serviceTypeId": "job_type_id:roof_repair", "displayName": "dup"},  # dup id dropped
                {"serviceTypeId": "job_type_id:roof_inspection"},  # no displayName → humanized
            ],
        },
        {"name": "gcid:gutter", "displayName": "Gutter service", "serviceTypes": []},
    ]
}


def test_parse_service_types_groups_and_orders():
    cats = [{"id": "gcid:gutter", "name": "Gutter service"},
            {"id": "gcid:roofing_contractor", "name": "Roofing contractor"}]
    out = api.parse_service_types(_BATCHGET, cats)
    # Ordered to match the listing's category order (gutter first).
    assert [c["id"] for c in out] == ["gcid:gutter", "gcid:roofing_contractor"]
    roofing = next(c for c in out if c["id"] == "gcid:roofing_contractor")
    assert roofing["service_types"] == [
        {"service_type_id": "job_type_id:roof_repair", "display_name": "Roof repair"},
        {"service_type_id": "job_type_id:roof_inspection", "display_name": "Roof Inspection"},
    ]


def test_parse_service_types_empty_response():
    assert api.parse_service_types({}, []) == []
    assert api.parse_service_types(None, None) == []


def test_parse_services_carries_structured_service_type_id():
    svcs = api.parse_services(_LIVE)
    structured = next(s for s in svcs if s["kind"] == "structured")
    assert structured["service_type_id"] == "job_type_id:x"


# ═══════════════════════════════════════════════════════════════════════════
# Pure: parse a v1 Location into the internal shape
# ═══════════════════════════════════════════════════════════════════════════
_LIVE = {
    "name": "locations/123",
    "title": "First Class Roofing",
    "profile": {"description": "We restore roofs."},
    "regularHours": {"periods": [
        {"openDay": "MONDAY", "openTime": {"hours": 9}, "closeDay": "MONDAY", "closeTime": {"hours": 17}},
        {"openDay": "SUNDAY", "openTime": {}, "closeDay": "SUNDAY", "closeTime": {"hours": 24}},
    ]},
    "serviceItems": [
        {"freeFormServiceItem": {"category": "gcid:roofing_contractor",
                                 "label": {"displayName": "Roof Repair", "description": "fix"}}},
        {"structuredServiceItem": {"serviceTypeId": "job_type_id:x", "description": "d"}},
    ],
    "categories": {
        "primaryCategory": {"name": "gcid:roofing_contractor", "displayName": "Roofing contractor"},
        "additionalCategories": [{"name": "gcid:gutter", "displayName": "Gutter service"}],
    },
    "metadata": {"hasPendingEdits": True, "canModifyServiceList": True, "placeId": "PID"},
}


def test_parse_location_fields():
    p = api.parse_location_fields(_LIVE)
    assert p["description"] == "We restore roofs."
    assert p["categories"] == [
        {"id": "gcid:roofing_contractor", "name": "Roofing contractor"},
        {"id": "gcid:gutter", "name": "Gutter service"},
    ]
    # Hours: Monday period + Sunday open-24.
    reg = {r["day"]: r for r in p["hours"]["regular"]}
    assert reg[0]["periods"] == [{"open": "09:00", "close": "17:00"}]
    assert reg[6]["open_24"] is True
    # Services: free-form editable + structured preserved.
    kinds = [s["kind"] for s in p["services"]]
    assert kinds == ["free_form", "structured"]
    assert p["services"][0]["category_id"] == "gcid:roofing_contractor"
    assert p["metadata"]["has_pending_edits"] is True
    assert p["metadata"]["can_modify_service_list"] is True


# ═══════════════════════════════════════════════════════════════════════════
# Pure: re-read-and-diff
# ═══════════════════════════════════════════════════════════════════════════
def test_diff_description_whitespace_insensitive():
    assert api.diff_field("description", "hello ", "hello") is False
    assert api.diff_field("description", "hello", "world") is True


def test_diff_services_order_insensitive():
    a = [{"kind": "free_form", "label": "A", "category_id": "c", "description": ""},
         {"kind": "free_form", "label": "B", "category_id": "c", "description": ""}]
    b = list(reversed(a))
    assert api.diff_field("services", a, b) is False
    c = [{"kind": "free_form", "label": "A", "category_id": "c2", "description": ""}]
    assert api.diff_field("services", a, c) is True


def test_diff_services_structured_pick_matches_live_read_back():
    # A fresh pick (human label + service_type_id) and its live read-back
    # (label == service_type_id) must compare equal, so apply records 'applied'.
    picked = [{"kind": "structured", "service_type_id": "job_type_id:x", "label": "Flex Office"}]
    live = [{"kind": "structured", "service_type_id": "job_type_id:x", "label": "job_type_id:x",
             "raw": {"structuredServiceItem": {"serviceTypeId": "job_type_id:x"}}}]
    assert api.diff_field("services", picked, live) is False
    other = [{"kind": "structured", "service_type_id": "job_type_id:y", "label": "Other"}]
    assert api.diff_field("services", picked, other) is True


def test_diff_hours():
    a = {"regular": [{"day": 0, "open_24": False, "periods": [{"open": "09:00", "close": "17:00"}]}]}
    assert api.diff_field("hours", a, dict(a)) is False
    b = {"regular": [{"day": 0, "open_24": True, "periods": []}]}
    assert api.diff_field("hours", a, b) is True


# ═══════════════════════════════════════════════════════════════════════════
# Pure: error classification
# ═══════════════════════════════════════════════════════════════════════════
def test_classify_profile_error():
    assert api.classify_profile_error(403, "canModifyServiceList false", "services") == "cannot_modify_services"
    assert api.classify_profile_error(403, "listing is unverified") == "gbp_listing_unverified"
    assert api.classify_profile_error(403, "no permission") == "gbp_listing_read_only"
    assert api.classify_profile_error(404, "") == "gbp_location_not_found"
    assert api.classify_profile_error(400, "description exceeds 750 length", "description") == "description_too_long"
    assert api.classify_profile_error(400, "description contains a url", "description") == "description_contains_url"
    assert api.classify_profile_error(400, "category not valid", "services") == "invalid_service_category"
    assert api.classify_profile_error(429, "quota exceeded") == "gbp_quota_not_granted"


# ═══════════════════════════════════════════════════════════════════════════
# Pure: draft-service mapping + backoff ladder + outcome decision
# ═══════════════════════════════════════════════════════════════════════════
def test_map_drafted_services_maps_category_and_falls_back():
    cats = [{"id": "gcid:roofing_contractor", "name": "Roofing contractor"}, {"id": "gcid:gutter", "name": "Gutter service"}]
    out = svc.map_drafted_services(
        'Here you go: [{"label":"Roof Repair","category":"Roofing contractor","description":"x"},'
        '{"label":"Gutter Cleaning","category":"Nonexistent"}]',
        cats,
    )
    assert out[0]["category_id"] == "gcid:roofing_contractor"
    assert out[1]["category_id"] == "gcid:roofing_contractor"  # fallback = primary/first


def test_map_drafted_services_bad_json_degrades():
    assert svc.map_drafted_services("not json at all", [{"id": "c", "name": "n"}]) == []


_SVC_TYPES = [
    {"id": "gcid:roofing_contractor", "name": "Roofing contractor", "service_types": [
        {"service_type_id": "job_type_id:roof_repair", "display_name": "Roof repair"},
        {"service_type_id": "job_type_id:roof_inspection", "display_name": "Roof inspection"},
    ]},
]


def test_map_drafted_service_types_maps_and_drops_unknown():
    out = svc.map_drafted_service_types(
        'ok: ["job_type_id:roof_repair", "job_type_id:not_real", "job_type_id:roof_repair"]',
        _SVC_TYPES,
    )
    # Unknown id dropped, duplicate collapsed, mapped to display + category.
    assert out == [{
        "kind": "structured", "service_type_id": "job_type_id:roof_repair",
        "label": "Roof repair", "category_id": "gcid:roofing_contractor",
    }]


def test_map_drafted_service_types_accepts_objects():
    out = svc.map_drafted_service_types(
        '[{"service_type_id": "job_type_id:roof_inspection"}]', _SVC_TYPES,
    )
    assert out[0]["service_type_id"] == "job_type_id:roof_inspection"
    assert out[0]["label"] == "Roof inspection"


def test_map_drafted_service_types_bad_json_degrades():
    assert svc.map_drafted_service_types("not json", _SVC_TYPES) == []


def test_next_backoff_ladder():
    ladder = svc.settings.gbp_profile_sync_backoff
    assert [svc.next_backoff(i) for i in range(len(ladder))] == ladder
    assert svc.next_backoff(len(ladder)) is None


def test_pending_or_terminal():
    assert svc._pending_or_terminal("description", "new", "new", {})["status"] == "applied"
    assert svc._pending_or_terminal("description", "new", "old", {"has_pending_edits": True})["status"] == "pending_review"
    assert svc._pending_or_terminal("description", "new", "old", {"has_pending_edits": False})["status"] == "rejected"


# ═══════════════════════════════════════════════════════════════════════════
# Flow tests: apply job + reconciler (fake Supabase + monkeypatched get/patch)
# ═══════════════════════════════════════════════════════════════════════════
class _Query:
    def __init__(self, table, rows):
        self.table, self.rows = table, rows
        self._filters, self._limit = [], None
        self._insert = self._update = None
        self._delete = False

    def select(self, *_a, **_k):
        return self

    def eq(self, k, v):
        self._filters.append(lambda r: r.get(k) == v); return self

    def in_(self, k, vs):
        self._filters.append(lambda r: r.get(k) in vs); return self

    def lte(self, k, v):
        self._filters.append(lambda r: (r.get(k) or "") <= v); return self

    def is_(self, k, _null):
        self._filters.append(lambda r: r.get(k) is None); return self

    @property
    def not_(self):
        outer = self

        class _Not:
            def is_(self, k, _null):
                outer._filters.append(lambda r: r.get(k) is not None); return outer
        return _Not()

    def order(self, *_a, **_k):
        return self

    def limit(self, n):
        self._limit = n; return self

    def insert(self, row):
        self._insert = row; return self

    def update(self, upd):
        self._update = upd; return self

    def delete(self):
        self._delete = True; return self

    def _matching(self):
        out = [r for r in self.rows if all(f(r) for f in self._filters)]
        return out[: self._limit] if self._limit else out

    def execute(self):
        if self._insert is not None:
            rows = self._insert if isinstance(self._insert, list) else [self._insert]
            for r in rows:
                r.setdefault("id", f"{self.table}-{len(self.rows) + 1}")
                if self.table == "async_jobs":
                    r.setdefault("status", "pending")  # DB default
            self.rows.extend(rows)
            return type("R", (), {"data": [dict(r) for r in rows]})()
        if self._update is not None:
            hit = self._matching()
            for r in hit:
                # Mirror the DB's now() default → a concrete timestamp.
                r.update({k: ("t" if v == "now()" else v) for k, v in self._update.items()})
            return type("R", (), {"data": [dict(r) for r in hit]})()
        if self._delete:
            hit = self._matching()
            for r in hit:
                self.rows.remove(r)
            return type("R", (), {"data": [dict(r) for r in hit]})()
        return type("R", (), {"data": [dict(r) for r in self._matching()]})()


class _FakeSupabase:
    def __init__(self):
        self.tables = {"gbp_profile_edits": [], "gbp_locations": [], "async_jobs": [], "clients": []}

    def table(self, name):
        return _Query(name, self.tables.setdefault(name, []))


@pytest.fixture
def fake(monkeypatch):
    sb = _FakeSupabase()
    sb.tables["gbp_locations"].append(
        {"id": "loc-1", "client_id": "c-1", "location_id": "locations/123", "account_id": "accounts/9",
         "title": "FCR", "access_status": "ok"}
    )
    sb.tables["clients"].append({"id": "c-1", "name": "FCR"})
    monkeypatch.setattr(svc, "get_supabase", lambda: sb)
    return sb


def _edit(sb, **over):
    row = {
        "id": "e-1", "client_id": "c-1", "location_row_id": "loc-1", "field": "description",
        "source": "manual", "current_value": "old", "proposed_value": "new", "status": "applying",
        "google_pending": False, "sync_attempts": 0, "next_sync_at": None,
    }
    row.update(over)
    sb.tables["gbp_profile_edits"].append(row)
    return row


def _stub_live(monkeypatch, description="old", pending=False):
    loc = {"name": "locations/123", "profile": {"description": description},
           "metadata": {"hasPendingEdits": pending}}
    monkeypatch.setattr(svc.api, "get_location", lambda *a, **k: dict(loc))
    return loc


def test_apply_job_applies_when_live_matches_after_patch(fake, monkeypatch):
    _edit(fake, status="applying", current_value="old", proposed_value="new")
    _stub_live(monkeypatch, description="old")  # baseline unchanged → no drift
    # The patch returns the new value live, not pending.
    monkeypatch.setattr(svc.api, "patch_location",
                        lambda *a, **k: {"profile": {"description": "new"}, "metadata": {}})
    job = {"id": "j1", "payload": {"edit_id": "e-1", "client_id": "c-1"}}
    asyncio.run(svc.run_apply_job(job))
    edit = fake.tables["gbp_profile_edits"][0]
    assert edit["status"] == "applied" and edit.get("applied_at")


def test_apply_job_aborts_on_out_of_band_drift(fake, monkeypatch):
    _edit(fake, status="applying", current_value="old", proposed_value="new")
    _stub_live(monkeypatch, description="someone_else_edited_this")  # live != snapshot
    called = {"patched": False}
    monkeypatch.setattr(svc.api, "patch_location", lambda *a, **k: called.__setitem__("patched", True) or {})
    job = {"id": "j1", "payload": {"edit_id": "e-1", "client_id": "c-1"}}
    asyncio.run(svc.run_apply_job(job))
    edit = fake.tables["gbp_profile_edits"][0]
    assert edit["status"] == "live_changed"
    assert called["patched"] is False  # never clobbered the dashboard edit


def test_apply_job_pending_review_sets_sync_clock(fake, monkeypatch):
    _edit(fake, status="applying", current_value="old", proposed_value="new")
    _stub_live(monkeypatch, description="old")
    monkeypatch.setattr(svc.api, "patch_location",
                        lambda *a, **k: {"profile": {"description": "old"}, "metadata": {"hasPendingEdits": True}})
    job = {"id": "j1", "payload": {"edit_id": "e-1", "client_id": "c-1"}}
    asyncio.run(svc.run_apply_job(job))
    edit = fake.tables["gbp_profile_edits"][0]
    assert edit["status"] == "pending_review" and edit["google_pending"] is True
    assert edit["next_sync_at"] is not None


def test_apply_job_idempotent_when_already_applied(fake, monkeypatch):
    _edit(fake, status="applied", proposed_value="new")
    monkeypatch.setattr(svc.api, "get_location", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not read")))
    job = {"id": "j1", "payload": {"edit_id": "e-1", "client_id": "c-1"}}
    asyncio.run(svc.run_apply_job(job))
    assert fake.tables["async_jobs"] == []  # settle updates the job row; none created here
    assert fake.tables["gbp_profile_edits"][0]["status"] == "applied"


def test_sync_job_resolves_applied(fake, monkeypatch):
    _edit(fake, status="pending_review", proposed_value="new", next_sync_at="2020-01-01T00:00:00+00:00")
    _stub_live(monkeypatch, description="new")  # live now matches proposed
    job = {"id": "j1", "payload": {"edit_id": "e-1", "client_id": "c-1"}}
    asyncio.run(svc.run_sync_job(job))
    edit = fake.tables["gbp_profile_edits"][0]
    assert edit["status"] == "applied" and edit["next_sync_at"] is None


def test_sync_job_rejects_when_settled_and_unchanged(fake, monkeypatch):
    _edit(fake, status="pending_review", proposed_value="new")
    _stub_live(monkeypatch, description="old", pending=False)  # settled, value didn't take
    job = {"id": "j1", "payload": {"edit_id": "e-1", "client_id": "c-1"}}
    asyncio.run(svc.run_sync_job(job))
    assert fake.tables["gbp_profile_edits"][0]["status"] == "rejected"


def test_sync_job_advances_backoff_then_gives_up(fake, monkeypatch):
    _edit(fake, status="pending_review", proposed_value="new", sync_attempts=0)
    _stub_live(monkeypatch, description="old", pending=True)  # still pending
    job = {"id": "j1", "payload": {"edit_id": "e-1", "client_id": "c-1"}}
    asyncio.run(svc.run_sync_job(job))
    edit = fake.tables["gbp_profile_edits"][0]
    assert edit["status"] == "pending_review" and edit["sync_attempts"] == 1
    assert edit["next_sync_at"] is not None
    # Exhaust the ladder → give up (stays pending_review, clock cleared).
    edit["sync_attempts"] = len(svc.settings.gbp_profile_sync_backoff)
    asyncio.run(svc.run_sync_job(job))
    assert edit["status"] == "pending_review" and edit["next_sync_at"] is None


def test_enqueue_due_syncs_selects_due_and_skips_active(fake, monkeypatch):
    monkeypatch.setattr(svc.settings, "gbp_api_enabled", True)
    monkeypatch.setattr(svc.settings, "gbp_profile_enabled", True)
    _edit(fake, id="due-1", status="pending_review", next_sync_at="2000-01-01T00:00:00+00:00")
    _edit(fake, id="future-1", status="pending_review", next_sync_at="2999-01-01T00:00:00+00:00")
    n = svc.enqueue_due_gbp_profile_syncs()
    assert n == 1
    jobs = fake.tables["async_jobs"]
    assert len(jobs) == 1 and jobs[0]["payload"]["edit_id"] == "due-1"
    # A second sweep with an active job for the same edit enqueues nothing more.
    assert svc.enqueue_due_gbp_profile_syncs() == 0


def test_enqueue_due_syncs_noop_when_disabled(fake):
    assert svc.enqueue_due_gbp_profile_syncs() == 0  # flags default off in the fixture
