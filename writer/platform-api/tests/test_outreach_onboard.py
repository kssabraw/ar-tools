"""create-or-get + onboard-order placement for the "City + Business type" form.

These exercise the platform-api write side (services/outreach): that a typed city's market /
sub-area / keyword rows are CREATED once and REUSED on a repeat pick (geometry is immutable, so a
second pick must never mint a second submarket with a drifted centre), that the order carries the
business type as its ingest category, and that validation + the one-active guard hold. The outreach
client is faked — the drain that consumes the order has its own tests in the outreach service.
"""

import pytest

from services import outreach as svc


# --- a fake outreach (Supabase) client ---------------------------------------------------------


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, db, name, op="select", payload=None):
        self.db, self.name, self.op, self.payload = db, name, op, payload
        self.filters = []
        self._in = None
        self._limit = None

    def select(self, *_a, **_k):
        return self

    def insert(self, payload):
        return _Query(self.db, self.name, "insert", payload)

    def eq(self, c, v):
        self.filters.append((c, v))
        return self

    def in_(self, c, values):
        self._in = (c, [str(x) for x in values])
        return self

    def order(self, *_a, **_k):
        return self

    def range(self, *_a, **_k):
        return self

    def limit(self, n):
        self._limit = n
        return self

    def _matches(self, row):
        if not all(str(row.get(c)) == str(v) for c, v in self.filters):
            return False
        if self._in and str(row.get(self._in[0])) not in self._in[1]:
            return False
        return True

    def execute(self):
        rows = self.db.tables.setdefault(self.name, [])
        if self.op == "insert":
            payload = self.payload if isinstance(self.payload, list) else [self.payload]
            written = []
            for r in payload:
                row = dict(r)
                row.setdefault("id", f"{self.name}-{len(rows) + len(written) + 1}")
                row.setdefault("status", "pending")
                written.append(row)
            rows.extend(written)
            return _Result([dict(r) for r in written])
        found = [dict(r) for r in rows if self._matches(r)]
        if self._limit is not None:
            found = found[: self._limit]
        return _Result(found)


class _FakeClient:
    def __init__(self):
        self.tables = {}

    def table(self, name):
        return _Query(self, name)


@pytest.fixture
def fake(monkeypatch):
    client = _FakeClient()
    monkeypatch.setattr(svc, "get_outreach_client", lambda: client)
    return client


CITY = {"name": "Van Nuys, CA, USA", "region": "California, United States", "lat": 34.19, "lng": -118.45}
SUB = {"name": "Lake Balboa", "lat": 34.17, "lng": -118.50, "place_id": "sub-pid"}


# --- create-or-get + placement -----------------------------------------------------------------


def test_onboard_creates_rows_and_order_with_business_type_as_category(fake):
    order = svc.create_onboard_from_place(
        city=CITY, subarea=SUB, business_type="plumber", note="first run", actor_id="admin-1"
    )
    assert order["category"] == "plumber"
    assert order["region"] == "California, United States"
    assert order["requested_by"] == "admin-1"
    assert order["status"] == "pending"
    assert order["submarket"]["name"] == "Lake Balboa"
    assert order["keyword"]["term"] == "plumber"
    # rows were created
    assert len(fake.tables["market"]) == 1
    assert len(fake.tables["submarket"]) == 1
    assert fake.tables["keyword"][0]["is_primary"] is True  # first keyword in a fresh market
    assert len(fake.tables["onboard_request"]) == 1


def test_repeat_pick_reuses_rows_never_duplicates(fake):
    svc.create_onboard_from_place(
        city=CITY, subarea=SUB, business_type="plumber", note=None, actor_id="admin-1"
    )
    # The first order occupies the active slot; resolve it so a second can be placed.
    fake.tables["onboard_request"][0]["status"] = "done"
    svc.create_onboard_from_place(
        city=CITY, subarea=SUB, business_type="plumber", note=None, actor_id="admin-1"
    )
    # Same city/sub-area/keyword -> exactly one of each row, two orders.
    assert len(fake.tables["market"]) == 1
    assert len(fake.tables["submarket"]) == 1
    assert len(fake.tables["keyword"]) == 1
    assert len(fake.tables["onboard_request"]) == 2


def test_a_second_business_type_adds_a_keyword_not_a_market(fake):
    svc.create_onboard_from_place(
        city=CITY, subarea=SUB, business_type="plumber", note=None, actor_id="admin-1"
    )
    svc.create_onboard_from_place(
        city=CITY, subarea=SUB, business_type="roofer", note=None, actor_id="admin-1"
    )
    assert len(fake.tables["market"]) == 1
    assert len(fake.tables["submarket"]) == 1
    terms = sorted(k["term"] for k in fake.tables["keyword"])
    assert terms == ["plumber", "roofer"]
    # only the first keyword is primary
    assert sum(1 for k in fake.tables["keyword"] if k["is_primary"]) == 1


def test_already_active_onboard_is_refused(fake):
    svc.create_onboard_from_place(
        city=CITY, subarea=SUB, business_type="plumber", note=None, actor_id="admin-1"
    )
    with pytest.raises(svc.OutreachError) as exc:
        svc.create_onboard_from_place(
            city=CITY, subarea=SUB, business_type="plumber", note=None, actor_id="admin-1"
        )
    assert exc.value.code == "onboard_request_already_active"


def test_blank_business_type_is_refused(fake):
    with pytest.raises(svc.OutreachError) as exc:
        svc.create_onboard_from_place(
            city=CITY, subarea=SUB, business_type="   ", note=None, actor_id="admin-1"
        )
    assert exc.value.code == "business_type_required"


def test_incomplete_subarea_is_refused(fake):
    # A NAMED sub-area must carry coordinates (a partial pick is an error, not a whole-city scan).
    with pytest.raises(svc.OutreachError) as exc:
        svc.create_onboard_from_place(
            city=CITY, subarea={"name": "Nowhere"}, business_type="plumber",
            note=None, actor_id="admin-1",
        )
    assert exc.value.code == "subarea_incomplete"


def test_no_subarea_scans_the_whole_city_center(fake):
    # subarea=None → the submarket IS the city centre, so a small city with no sub-areas isn't a
    # dead end. The submarket is named after the city and sits at its coordinates.
    order = svc.create_onboard_from_place(
        city=CITY, subarea=None, business_type="plumber", note=None, actor_id="admin-1"
    )
    assert order["submarket"]["name"] == "Van Nuys, CA, USA"
    sub = fake.tables["submarket"][0]
    assert sub["name"] == "Van Nuys, CA, USA"
    assert sub["center_lat"] == 34.19 and sub["center_lng"] == -118.45
    assert len(fake.tables["onboard_request"]) == 1


def test_empty_subarea_dict_is_also_whole_city(fake):
    order = svc.create_onboard_from_place(
        city=CITY, subarea={}, business_type="plumber", note=None, actor_id="admin-1"
    )
    assert order["submarket"]["name"] == "Van Nuys, CA, USA"


# --- auto-seeding the whole-city AI region -----------------------------------------------------


def test_whole_city_onboard_auto_seeds_a_city_level_ai_region(fake):
    # A whole-city scan seeds a `city`-level ai_region named for the city, so the AI-visibility scan
    # resolves (prospect submarket name -> region name) without a manual seed. name_level here is the
    # level of the operator's explicit Google-city pick, not a derived judgement (I-073).
    svc.create_onboard_from_place(
        city=CITY, subarea=None, business_type="plumber", note=None, actor_id="admin-1"
    )
    regions = fake.tables.get("ai_region", [])
    assert len(regions) == 1
    assert regions[0]["name"] == "Van Nuys, CA, USA"      # matches the submarket name
    assert regions[0]["name_level"] == "city"


def test_subarea_onboard_does_not_auto_seed(fake):
    # A picked sub-area's granularity (suburb vs silent-fallback neighbourhood) is the I-073 human
    # judgement, so it is left to the manual seed modal — never auto-assigned.
    svc.create_onboard_from_place(
        city=CITY, subarea=SUB, business_type="plumber", note=None, actor_id="admin-1"
    )
    assert fake.tables.get("ai_region", []) == []


def test_auto_seed_failure_never_fails_the_onboard_order(fake, monkeypatch):
    # The AI region is a convenience; if seeding raises, the onboard order must still be placed.
    def boom(*_a, **_k):
        raise RuntimeError("ai_region insert exploded")

    monkeypatch.setattr(svc, "create_ai_region", boom)
    order = svc.create_onboard_from_place(
        city=CITY, subarea=None, business_type="plumber", note=None, actor_id="admin-1"
    )
    assert order["status"] == "pending"
    assert len(fake.tables["onboard_request"]) == 1
    assert fake.tables.get("ai_region", []) == []
