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
    def __init__(self, account_ids):
        self._ids = account_ids
        self.calls = 0

    def list_integrations(self, profile_id=None):
        self.calls += 1
        assert profile_id, "adapter must be called scoped to a profile"
        return [_Integ(i) for i in self._ids]


@pytest.fixture(autouse=True)
def _enabled(monkeypatch):
    monkeypatch.setattr(publish.settings, "social_enabled", True)


def _wire(monkeypatch, *, profile, account_ids):
    adapter = _Adapter(account_ids)
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
