"""Client-isolation tests for the Social module (the account→client boundary).

PostPeer has one account-wide key with no per-profile access control, so the
suite must scope every read/write to the client's own profile. These pin the two
guarantees: list_accounts FAILS CLOSED when a client has no Social group (never
leaks other clients' accounts), and the publish path REFUSES an account that
isn't in the client's profile.
"""

import pytest
from fastapi import HTTPException

from services.social import publish


class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    """Chainable no-op query returning a fixed row set on execute()."""
    def __init__(self, rows):
        self._rows = rows

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def update(self, *a, **k):
        return self

    def execute(self):
        return _Resp(self._rows)


class _SB:
    def __init__(self, client_row):
        self._rows = [client_row] if client_row is not None else []

    def table(self, _name):
        return _Query(self._rows)


class _Integ:
    def __init__(self, account_id):
        self.account_id = account_id
        self.platform = "facebook"
        self.handle = "acct"
        self.reconnect_required = False


class _Adapter:
    def __init__(self, account_ids, raises=None, created_profile="prof-new"):
        self._ids = account_ids
        self._raises = raises
        self._created_profile = created_profile
        self.calls = 0
        self.created = 0

    def list_integrations(self, profile_id=None):
        self.calls += 1
        assert profile_id, "adapter must be called scoped to a profile"
        if self._raises is not None:
            raise self._raises
        return [_Integ(i) for i in self._ids]

    def create_profile(self, name, description=None):
        self.created += 1
        return self._created_profile


@pytest.fixture(autouse=True)
def _enabled(monkeypatch):
    monkeypatch.setattr(publish.settings, "social_enabled", True)


def _wire(monkeypatch, *, profile, account_ids, raises=None):
    adapter = _Adapter(account_ids, raises=raises)
    monkeypatch.setattr(
        publish, "_sb", lambda: _SB({"social_profile_id": profile, "name": "Acme"})
    )
    monkeypatch.setattr(publish, "get_adapter", lambda *a, **k: adapter)
    return adapter


def test_list_accounts_fails_closed_without_profile(monkeypatch):
    adapter = _wire(monkeypatch, profile=None, account_ids=["a1"])
    assert publish.list_accounts("client-x") == []
    # The boundary: the adapter is NEVER called for an unmapped client, so an
    # unscoped account list can't leak.
    assert adapter.calls == 0


def test_list_accounts_scopes_to_profile(monkeypatch):
    adapter = _wire(monkeypatch, profile="prof-1", account_ids=["a1", "a2"])
    got = {a["account_id"] for a in publish.list_accounts("client-x")}
    assert got == {"a1", "a2"}
    assert adapter.calls == 1


def test_assert_account_allowed_no_profile_409(monkeypatch):
    _wire(monkeypatch, profile=None, account_ids=["a1"])
    with pytest.raises(HTTPException) as ei:
        publish._assert_account_allowed("client-x", "a1")
    assert ei.value.status_code == 409
    assert ei.value.detail == "social_profile_not_set"


def test_assert_account_allowed_foreign_account_403(monkeypatch):
    _wire(monkeypatch, profile="prof-1", account_ids=["a1", "a2"])
    with pytest.raises(HTTPException) as ei:
        publish._assert_account_allowed("client-x", "other-client-acct")
    assert ei.value.status_code == 403
    assert ei.value.detail == "social_account_not_in_client_profile"


def test_assert_account_allowed_ok(monkeypatch):
    _wire(monkeypatch, profile="prof-1", account_ids=["a1", "a2"])
    # In-profile account passes (no exception).
    publish._assert_account_allowed("client-x", "a2")


def test_assert_account_allowed_deferred_swallows_postpeer_outage(monkeypatch):
    # A PostPeer outage at compose time (require_live=False) must NOT block
    # composing/scheduling — the membership check is deferred to the publish job.
    _wire(
        monkeypatch, profile="prof-1", account_ids=["a1"],
        raises=HTTPException(status_code=502, detail="postpeer_unreachable"),
    )
    publish._assert_account_allowed("client-x", "a2", require_live=False)  # no raise


def test_assert_account_allowed_deferred_still_requires_profile(monkeypatch):
    # Even with require_live=False, the DB-only "profile is set" rung is enforced.
    _wire(monkeypatch, profile=None, account_ids=["a1"])
    with pytest.raises(HTTPException) as ei:
        publish._assert_account_allowed("client-x", "a1", require_live=False)
    assert ei.value.status_code == 409
    assert ei.value.detail == "social_profile_not_set"


def test_assert_account_allowed_authoritative_reraises_on_outage(monkeypatch):
    # The publish job (require_live=True) never publishes to an account whose
    # membership it couldn't confirm — a PostPeer error propagates.
    _wire(
        monkeypatch, profile="prof-1", account_ids=["a1"],
        raises=HTTPException(status_code=502, detail="postpeer_unreachable"),
    )
    with pytest.raises(HTTPException) as ei:
        publish._assert_account_allowed("client-x", "a2", require_live=True)
    assert ei.value.status_code == 502


def test_ensure_profile_race_keeps_existing_never_clobbers(monkeypatch):
    # Two callers race: our read sees no profile, we create one at PostPeer, but by
    # the time we re-read another caller has stored theirs. We must honour the stored
    # one and never overwrite the mapping.
    reads = iter([None, "prof-winner"])  # pre-create read, then post-create re-read

    monkeypatch.setattr(publish, "_client_profile_id", lambda cid: next(reads))
    adapter = _Adapter([], created_profile="prof-mine")
    monkeypatch.setattr(publish, "get_adapter", lambda *a, **k: adapter)
    updated = {"count": 0}

    class _SBNoUpdate:
        def table(self, _name):
            outer = self

            class _Q:
                def update(self, *a, **k):
                    outer_updated = updated
                    outer_updated["count"] += 1
                    return self

                def eq(self, *a, **k):
                    return self

                def execute(self):
                    return _Resp([])

            return _Q()

    monkeypatch.setattr(publish, "_sb", lambda: _SBNoUpdate())
    got = publish.ensure_profile_for_client("client-x", "Acme")
    assert got == "prof-winner"        # honoured the stored mapping
    assert adapter.created == 1        # we did create (then discovered the race)
    assert updated["count"] == 0       # never wrote over the winner's mapping


def test_enqueue_profile_provision_noops_when_profile_set(monkeypatch):
    monkeypatch.setattr(publish.settings, "postpeer_api_key", "k")
    monkeypatch.setattr(publish, "_client_profile_id", lambda cid: "prof-1")
    inserted = {"count": 0}

    class _SBInsert:
        def table(self, _name):
            class _Q:
                def insert(self, *a, **k):
                    inserted["count"] += 1
                    return self

                def execute(self):
                    return _Resp([])

            return _Q()

    monkeypatch.setattr(publish, "_sb", lambda: _SBInsert())
    publish.enqueue_profile_provision("client-x", "Acme")
    assert inserted["count"] == 0  # already has a profile → no job enqueued


def test_enqueue_profile_provision_enqueues_when_absent(monkeypatch):
    monkeypatch.setattr(publish.settings, "postpeer_api_key", "k")
    monkeypatch.setattr(publish, "_client_profile_id", lambda cid: None)
    inserted = {"rows": []}

    class _SBInsert:
        def table(self, _name):
            class _Q:
                def insert(self, row):
                    inserted["rows"].append(row)
                    return self

                def execute(self):
                    return _Resp([])

            return _Q()

    monkeypatch.setattr(publish, "_sb", lambda: _SBInsert())
    publish.enqueue_profile_provision("client-x", "Acme")
    assert len(inserted["rows"]) == 1
    assert inserted["rows"][0]["job_type"] == "social_profile_provision"
    assert inserted["rows"][0]["payload"]["client_id"] == "client-x"
