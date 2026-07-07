"""Supabase client wrappers.

Two access paths (PRD §13: "the FastAPI service uses the user's JWT to drive the
policy"):

- service client  — built with the service-role key, bypasses RLS. Used for
  admin writes the backend fully controls (provisioning a profile, the Scratch
  project).
- user client     — built with the anon key plus the caller's JWT in the
  Authorization header, so PostgREST enforces RLS as that user. Used for all
  scoped reads.

Both default to the `fanout` schema, which must be added to the project's
PostgREST "Exposed schemas" (Supabase dashboard → API settings).
"""

import logging
from functools import lru_cache

from supabase import Client, ClientOptions, create_client

from fanout.config import get_settings

logger = logging.getLogger(__name__)


def _host_role(user_id: str) -> str | None:
    """Read the caller's AR Tools suite role (public.profiles.role) via the
    public-schema service client (the fanout client is scoped to the fanout
    schema, so it can't see public.profiles). Best-effort — any failure returns
    None so the fanout role stands and login is never blocked."""
    try:
        from db.supabase_client import get_supabase

        resp = (
            get_supabase()
            .table("profiles")
            .select("role")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        return resp.data[0].get("role") if resp.data else None
    except Exception as exc:  # noqa: BLE001 - bridge is advisory, never fatal
        logger.warning(
            "host_role_bridge_failed",
            extra={"event": "host_role_bridge_failed", "reason": repr(exc)},
        )
        return None


def _host_is_elevated(user_id: str) -> bool:
    """Role bridge: an AR Tools suite senior operator (public.profiles.role in
    {'admin', 'staff'}) is treated as a Topic Fanout 'owner'."""
    return _host_role(user_id) in ("admin", "staff")


def host_is_read_only(user_id: str) -> bool:
    """True when the suite role is a read-only tier ('client'). Used by the
    fanout auth layer to reject write requests — the suite's read-only
    enforcement lives in the suite's require_auth, which never runs for /fanout
    routes."""
    return _host_role(user_id) == "client"


@lru_cache
def get_service_client() -> Client:
    settings = get_settings()
    options = ClientOptions(schema=settings.fanout_schema)
    return create_client(
        settings.supabase_url,
        settings.supabase_service_role_key,
        options,
    )


def get_user_client(access_token: str) -> Client:
    settings = get_settings()
    options = ClientOptions(
        schema=settings.fanout_schema,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    return create_client(settings.supabase_url, settings.supabase_anon_key, options)


def ensure_user_profile(user_id: str, email: str | None) -> dict:
    """Return the caller's profile row, creating a default `va` profile on first
    login. The Owner (Kyle) is seeded by the M1 migration; everyone else defaults
    to `va` until an Owner promotes them.
    """
    service = get_service_client()
    existing = (
        service.table("user_profiles")
        .select("user_id, display_name, role")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if existing.data:
        profile = existing.data[0]
        # Keep a suite senior operator (admin/staff) promoted to owner even if
        # they were provisioned as a va on an earlier Fanout-only login.
        if profile.get("role") != "owner" and _host_is_elevated(user_id):
            updated = (
                service.table("user_profiles")
                .update({"role": "owner"})
                .eq("user_id", user_id)
                .execute()
            )
            if updated.data:
                return updated.data[0]
            profile["role"] = "owner"
        return profile

    display_name = (email or "").split("@")[0] or None
    # New Fanout user: a suite senior operator (admin/staff) lands as owner,
    # everyone else as va.
    role = "owner" if _host_is_elevated(user_id) else "va"
    inserted = (
        service.table("user_profiles")
        .insert({"user_id": user_id, "display_name": display_name, "role": role})
        .execute()
    )
    return inserted.data[0]


def ensure_scratch_project(user_id: str) -> dict:
    """Return the caller's Scratch project, auto-creating it on first login
    (PRD §15.1, §9.4)."""
    service = get_service_client()
    existing = (
        service.table("projects")
        .select("id, name, is_scratch, created_at")
        .eq("user_id", user_id)
        .eq("is_scratch", True)
        .limit(1)
        .execute()
    )
    if existing.data:
        return existing.data[0]

    inserted = (
        service.table("projects")
        .insert({"user_id": user_id, "name": "Scratch", "is_scratch": True})
        .execute()
    )
    return inserted.data[0]
