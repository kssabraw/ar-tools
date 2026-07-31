"""Supabase client for the outreach pipeline.

This is a SEPARATE Supabase project from AR Tools (DECISIONS.md). Do not point it at
AR-Internal-Tools — the storage spec projects ~64M grid_result rows/year and that headroom
belongs to this project alone.

Service role key, as with the rest of the estate: RLS would block service operations.
"""

from __future__ import annotations

from functools import lru_cache

from supabase import Client, create_client

from .config import get_settings, missing_supabase_vars


@lru_cache
def get_client() -> Client:
    settings = get_settings()

    missing = missing_supabase_vars(settings)
    if missing:
        raise RuntimeError(f"not set: {', '.join(missing)}")

    return create_client(settings.supabase_url, settings.supabase_service_role_key)
