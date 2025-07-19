# config.py
# -----------------------------------------------------------------------------
# Централизованное чтение переменных окружения + безопасные алиасы
# -----------------------------------------------------------------------------

import os
from dotenv import load_dotenv

# грузим .env раньше всего
load_dotenv()

class Config:
    """
    Собирает все секреты и настройки приложения.
    Искусственно дублируем DATABASE_URL → POSTGRES_URL,
    чтобы старый код не падал, если где‑то ещё осталось POSTGRES_URL.
    """
    # ---------------------------------------------------------------------
    # База данных
    # ---------------------------------------------------------------------
    DATABASE_URL: str | None = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL")
    # Alias на случай, если где‑то в проекте ещё осталось старое имя
    POSTGRES_URL: str | None = DATABASE_URL

    # ---------------------------------------------------------------------
    # Telegram боты
    # ---------------------------------------------------------------------
    BOT_TOKEN: str | None         = os.getenv("BOT_TOKEN")
    ADMIN_BOT_TOKEN: str | None   = os.getenv("ADMIN_BOT_TOKEN")
    ADMIN_CHAT_ID: str | None     = os.getenv("ADMIN_CHAT_ID")

    # ---------------------------------------------------------------------
    # Telethon
    # ---------------------------------------------------------------------
    API_ID: int | None            = os.getenv("API_ID")
    API_HASH: str | None          = os.getenv("API_HASH")
    PHONE_NUMBER: str | None      = os.getenv("PHONE_NUMBER")

    # ---------------------------------------------------------------------
    # GigaChat
    # ---------------------------------------------------------------------
    GIGACHAT_CLIENT_ID: str | None     = os.getenv("GIGACHAT_CLIENT_ID")
    GIGACHAT_CLIENT_SECRET: str | None = os.getenv("GIGACHAT_CLIENT_SECRET")
    GIGACHAT_AUTH_KEY: str | None      = os.getenv("GIGACHAT_AUTH_KEY")
    GIGACHAT_SCOPE: str | None         = os.getenv("GIGACHAT_SCOPE")
    RQUUID: str | None                 = os.getenv("RQUUID")
