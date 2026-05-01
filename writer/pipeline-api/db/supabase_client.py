"""Supabase client for pipeline-api (uses service role key)."""

from __future__ import annotations

from typing import Optional

from supabase import Client, create_client

from config import settings

_client: Optional[Client] = None


def get_supabase() -> Client:
    """Lazy-init the Supabase service-role client."""
    global _client
    if _client is None:
        _client = create_client(settings.supabase_url, settings.supabase_service_role_key)
    return _client
