from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    TG_API_ID: int
    TG_API_HASH: str
    NEWS_BOT_TOKEN: str
    ADMIN_BOT_TOKEN: str
    POSTGRES_DSN: str
    SIMILARITY_THRESHOLD: float = 0.82
    MEDIA_ROOT: str = "/var/lib/setinews_media"
    DONOR_CACHE_TTL_MIN: int = 10

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

settings = Settings()
