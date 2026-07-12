"""Supabase client scoped to the `market_scanner` schema (LeadOff's data).

Modeled on fanout/storage/supabase_client.py: a schema-scoped client can only
see its own schema, so LeadOff keeps this client for market_scanner tables and
uses the suite's db.supabase_client.get_supabase() for anything in public.

NOTE: `market_scanner` must be listed in the Supabase project's PostgREST
"Exposed schemas" (dashboard -> API settings) before REST queries work —
see HANDOFF.md "To activate". Table grants to service_role are already applied.
"""
from functools import lru_cache

from supabase import Client, ClientOptions, create_client

from config import settings

LEADOFF_SCHEMA = "market_scanner"


@lru_cache
def get_leadoff_client() -> Client:
    """Service-role client scoped to market_scanner (RLS bypassed)."""
    options = ClientOptions(schema=LEADOFF_SCHEMA)
    return create_client(
        settings.supabase_url, settings.supabase_service_role_key, options
    )
