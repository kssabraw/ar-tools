from functools import lru_cache

from .client import DataForSEOClient, DataForSEOError

__all__ = ["DataForSEOClient", "DataForSEOError", "get_dataforseo"]


@lru_cache
def get_dataforseo(
    location_code: int = 2840, language_code: str = "en"
) -> DataForSEOClient:
    # Cached per (location_code, language_code) so each market reuses one client
    # (E1 per-country locale, 2026-06-17). Callers pass the session's
    # location_code; the default 2840/"en" preserves US behaviour for any caller
    # that doesn't (and for the existing tests).
    from fanout.config import get_settings

    s = get_settings()
    return DataForSEOClient(
        base_url=s.dataforseo_base_url,
        login=s.dataforseo_login,
        password=s.dataforseo_password,
        location_code=location_code,
        language_code=language_code,
    )
