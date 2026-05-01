from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    dataforseo_login: str = ""
    dataforseo_password: str = ""
    scrapeowl_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    sie_cache_ttl_days: int = 7
    log_level: str = "INFO"

    class Config:
        env_file = ".env"


settings = Settings()
