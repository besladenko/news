# config.py
import os
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()

class Config:
    """
    Класс для хранения конфигурационных настроек приложения.
    Все настройки загружаются из переменных окружения.
    """
    # Настройки базы данных PostgreSQL
    DB_USER = os.getenv("DB_USER", "user")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "password")
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = os.getenv("DB_PORT", "5432")
    DB_NAME = os.getenv("DB_NAME", "setinews_db")
    DATABASE_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

    # Токены Telegram ботов
    BOT_TOKEN = os.getenv("BOT_TOKEN") # Основной бот
    ADMIN_BOT_TOKEN = os.getenv("ADMIN_BOT_TOKEN") # Админский бот

    # ID чата администратора (для уведомлений и модерации)
    ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

    # Настройки Telethon (парсера)
    API_ID = os.getenv("API_ID")
    API_HASH = os.getenv("API_HASH")
    SESSION_NAME = os.getenv("SESSION_NAME", "telethon_session") # Имя сессии Telethon

    # Настройки GigaChat API
    GIGACHAT_CLIENT_ID = os.getenv("GIGACHAT_CLIENT_ID")
    GIGACHAT_CLIENT_SECRET = os.getenv("GIGACHAT_CLIENT_SECRET")
    GIGACHAT_SCOPE = os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")
    GIGACHAT_MODEL_NAME = os.getenv("GIGACHAT_MODEL_NAME", "GigaChat")

    # Путь для сохранения загруженных медиафайлов
    MEDIA_DOWNLOADS_DIR = os.getenv("MEDIA_DOWNLOADS_DIR", "media_downloads")
    
    # Максимальное количество ссылок в посте (новое поле)
    MAX_LINKS_IN_POST = int(os.getenv("MAX_LINKS_IN_POST", "3")) # По умолчанию 3 ссылки

    # Кастомная подпись для постов
    CUSTOM_SIGNATURE = os.getenv("CUSTOM_SIGNATURE", "Setinews")

    def __init__(self):
        self._validate_config()

    def _validate_config(self):
        """Проверяет наличие обязательных переменных окружения."""
        required_vars = [
            "BOT_TOKEN", "ADMIN_BOT_TOKEN", "ADMIN_CHAT_ID",
            "API_ID", "API_HASH",
            "GIGACHAT_CLIENT_ID", "GIGACHAT_CLIENT_SECRET"
        ]
        for var in required_vars:
            if not getattr(self, var):
                raise ValueError(f"Отсутствует обязательная переменная окружения: {var}. Пожалуйста, убедитесь, что она установлена в файле .env или в окружении.")

# Создаем единственный экземпляр конфигурации
config = Config()

