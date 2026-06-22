from typing import List

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    pipeline_api_url: str = "http://ar-tools.railway.internal:8080"
    nlp_api_url: str = "http://nlp.railway.internal:8080"
    scrapeowl_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    max_concurrent_runs: int = 5
    job_worker_poll_interval_seconds: int = 10
    allowed_origins: List[str] = ["*"]
    log_level: str = "INFO"
    google_apps_script_url: str = ""
    outscraper_api_key: str = ""
    # Google Search Console — Organic Rank Tracker (Module #4).
    # The service-account key JSON (the entire downloaded key file, as a single
    # string) for the agency-owned identity that clients add as a user on their
    # Search Console property. Stored once at the app level; never per-client.
    google_service_account_key: str = ""
    # DataForSEO — GBP review enrichment (shared with pipeline-api modules)
    dataforseo_login: str = ""
    dataforseo_password: str = ""

    # SERP analysis cache (keyword_analyses): how long a cached AnalysisResponse
    # stays fresh before it's re-scraped. Shared across clients by (keyword,
    # location). Set to 0 to disable caching.
    analysis_cache_ttl_days: int = 14

    # Silo candidate management (Platform PRD v1.4 §7.7 / §8.5)
    silo_dedup_cosine_threshold: float = 0.85
    silo_frequent_threshold: int = 3
    # text-embedding-3-large supports a `dimensions` parameter (1..3072);
    # we use 1536 because pgvector's HNSW index is capped at 2000 dims.
    silo_embedding_dimensions: int = 1536
    silo_embedding_model: str = "text-embedding-3-large"

    class Config:
        env_file = ".env"


settings = Settings()
