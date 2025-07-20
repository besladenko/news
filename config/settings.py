from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    TG_API_ID: int
    TG_API_HASH: str
    NEWS_BOT_TOKEN: str
    ADMIN_BOT_TOKEN: str
    POSTGRES_DSN: str
    GIGACHAT_CLIENT_ID: str
    GIGACHAT_CLIENT_SECRET: str
    SIMILARITY_THRESHOLD: float = 0.82
    MEDIA_ROOT: str = "/var/lib/setinews_media"
    DONOR_CACHE_TTL_MIN: int = 10

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()
