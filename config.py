# … начало файла без изменений …

class Config:
    # -----------------------------------------------------------------
    # База данных (как было)
    DATABASE_URL: str | None = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL")
    POSTGRES_URL: str | None = DATABASE_URL

    # -----------------------------------------------------------------
    # Telegram боты (как было)
    BOT_TOKEN: str | None       = os.getenv("BOT_TOKEN")
    ADMIN_BOT_TOKEN: str | None = os.getenv("ADMIN_BOT_TOKEN")
    ADMIN_CHAT_ID: str | None   = os.getenv("ADMIN_CHAT_ID")

    # -----------------------------------------------------------------
    # Telethon
    API_ID: int | None   = os.getenv("API_ID")
    API_HASH: str | None = os.getenv("API_HASH")
    PHONE_NUMBER: str | None = os.getenv("PHONE_NUMBER")

    # 🔽  Новый блок‑алиас, чтобы старый код не падал
    TELETHON_API_ID: int | None   = API_ID
    TELETHON_API_HASH: str | None = API_HASH

    # -----------------------------------------------------------------
    # GigaChat (как было)
    GIGACHAT_CLIENT_ID: str | None     = os.getenv("GIGACHAT_CLIENT_ID")
    GIGACHAT_CLIENT_SECRET: str | None = os.getenv("GIGACHAT_CLIENT_SECRET")
    GIGACHAT_AUTH_KEY: str | None      = os.getenv("GIGACHAT_AUTH_KEY")
    GIGACHAT_SCOPE: str | None         = os.getenv("GIGACHAT_SCOPE")
    RQUUID: str | None                 = os.getenv("RQUUID")
