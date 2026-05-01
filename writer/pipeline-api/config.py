from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    dataforseo_login: str = ""
    dataforseo_password: str = ""
    scrapeowl_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    google_nlp_api_key: str = ""
    sie_cache_ttl_days: int = 7
    sie_min_pages: int = 5
    log_level: str = "INFO"

    # ------------------------------------------------------------
    # Brief Generator v2.0 — threshold tuning (PRD §12.6)
    # ------------------------------------------------------------
    # All thresholds must be configurable per the PRD. Defaults match the
    # PRD's starting values; expect first-week tuning, especially on the
    # restatement ceiling.
    brief_relevance_floor: float = 0.55
    brief_restatement_ceiling: float = 0.78
    brief_inter_heading_threshold: float = 0.75
    brief_edge_threshold: float = 0.65
    brief_mmr_lambda: float = 0.7
    brief_louvain_resolution: float = 1.0
    brief_louvain_seed: int = 42

    # When true, the pipeline includes per-candidate scores in the response
    # metadata (even for discards) so operators can tune thresholds offline.
    brief_tuning_mode: bool = False

    # 7-day brief cache (keyword + location_code shared across clients).
    brief_cache_ttl_days: int = 7

    class Config:
        env_file = ".env"


settings = Settings()
