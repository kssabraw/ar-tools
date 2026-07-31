"""Supabase client for the Outreacher project (the outreach pipeline's database).

**This reaches a second Supabase PROJECT, not a second schema.** That is the difference from
`leadoff_db.py`, which this module otherwise follows: LeadOff scopes a client to the
`market_scanner` schema inside AR-Internal-Tools, whereas outreach lives in its own project
(`fkwhgvcggvsricuinuqy`) with its own URL and its own service-role key. A schema option would
achieve nothing here — the tables are not in this database at all.

Why a separate project, and why the API is here anyway (outreach/HANDOFF.md §2): the storage
projection is ~64M `grid_result` rows a year, which would eat the suite project's headroom, so
the DATA stays separate. The application does not follow it — platform-api holds the service role
and is the only client, so staff authenticate against the suite and never need an Outreacher
account.

Credentials are OUTREACH_SUPABASE_URL / OUTREACH_SUPABASE_SERVICE_ROLE_KEY, deliberately the same
variable names the outreach Railway job already uses, carrying the same values.
"""
from functools import lru_cache

from supabase import Client, create_client

from config import settings


def outreach_configured() -> bool:
    """Whether the Outreacher credentials are present on this service.

    Checked before the client is built so an unconfigured deployment answers 503 with a named
    reason rather than raising a driver error out of the first query.
    """
    return bool(settings.outreach_supabase_url and settings.outreach_supabase_service_role_key)


@lru_cache
def get_outreach_client() -> Client:
    """Service-role client for the Outreacher project (RLS bypassed).

    Service role because every outreach table has RLS enabled with zero policies — that is the
    intended posture, not an oversight (HANDOFF §2). Any other key reads nothing.
    """
    if not outreach_configured():
        raise RuntimeError("outreach_not_configured")
    return create_client(
        settings.outreach_supabase_url, settings.outreach_supabase_service_role_key
    )
