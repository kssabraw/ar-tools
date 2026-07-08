"""Unit tests for the suite role model (middleware.auth)."""

from __future__ import annotations

import pytest

from middleware import auth


def test_role_rank_is_strictly_ordered():
    assert (
        auth.role_rank("client")
        < auth.role_rank("team_member")
        < auth.role_rank("staff")
        < auth.role_rank("admin")
    )


def test_unknown_role_sorts_below_everything():
    assert auth.role_rank("bogus") < auth.role_rank("client")
    assert auth.role_rank(None) < auth.role_rank("client")


@pytest.mark.parametrize(
    "role,expected",
    [("admin", True), ("staff", True), ("team_member", False), ("client", False), (None, False)],
)
def test_is_staff_or_above(role, expected):
    assert auth.is_staff_or_above(role) is expected


def test_client_is_the_only_read_only_role():
    assert auth.READ_ONLY_ROLES == {"client"}
    # The other three tiers are all writers.
    for role in ("admin", "staff", "team_member"):
        assert role not in auth.READ_ONLY_ROLES


def test_require_gates_thresholds():
    # require_staff clears staff+, require_admin clears admin only.
    assert auth.role_rank("staff") >= auth.ROLE_RANK["staff"]
    assert auth.role_rank("team_member") < auth.ROLE_RANK["staff"]
    assert auth.role_rank("admin") >= auth.ROLE_RANK["admin"]
    assert auth.role_rank("staff") < auth.ROLE_RANK["admin"]
