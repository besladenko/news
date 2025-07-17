# config.py
import os
from dotenv import load_dotenv

# Загружаем переменные окружения из файла .env
load_dotenv()

class Config:
    """Класс для хранения конфигурационных данных."""
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    ADMIN_BOT_TOKEN = os.getenv("ADMIN_BOT_TOKEN")
    ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID")) # ID чата для админских уведомлений

    GIGACHAT_CLIENT_ID = os.getenv("GIGACHAT_CLIENT_ID")
    GIGACHAT_CLIENT_SECRET = os.getenv("GIGACHAT_CLIENT_SECRET")
    GIGACHAT_AUTH_KEY = os.getenv("GIGACHAT_AUTH_KEY")
    GIGACHAT_SCOPE = os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")
    RQUUID = os.getenv("RQUUID") # Уникальный идентификатор запроса (UUID4)

    POSTGRES_URL = os.getenv("POSTGRES_URL")

    _api_id = os.getenv("API_ID")
    TELETHON_API_ID = int(_api_id) if _api_id else None
    TELETHON_API_HASH = os.getenv("API_HASH")
    PHONE_NUMBER = os.getenv("PHONE_NUMBER")

    # Путь для скачивания медиафайлов
    MEDIA_DOWNLOAD_DIR = os.getenv("MEDIA_DOWNLOAD_DIR", "media_downloads") # <-- ДОБАВЛЕНО

# Проверка наличия всех необходимых переменных после определения класса Config
REQUIRED_VARS = [
    "BOT_TOKEN", "ADMIN_BOT_TOKEN", "ADMIN_CHAT_ID",
    "GIGACHAT_CLIENT_ID", "GIGACHAT_CLIENT_SECRET", "GIGACHAT_AUTH_KEY", "RQUUID",
    "POSTGRES_URL", "TELETHON_API_ID", "TELETHON_API_HASH", "PHONE_NUMBER",
    "MEDIA_DOWNLOAD_DIR" # <-- ДОБАВЛЕНО
]

for var_name in REQUIRED_VARS:
    if not getattr(Config, var_name):
        raise ValueError(f"Переменная окружения '{var_name}' не найдена или пуста в .env файле.")

# Создаем экземпляр конфигурации
config = Config()

if __name__ == "__main__":
    # Пример использования и проверки
    print(f"BOT_TOKEN: {config.BOT_TOKEN[:5]}...")
    print(f"ADMIN_BOT_TOKEN: {config.ADMIN_BOT_TOKEN[:5]}...")
    print(f"ADMIN_CHAT_ID: {config.ADMIN_CHAT_ID}")
    print(f"GIGACHAT_CLIENT_ID: {config.GIGACHAT_CLIENT_ID[:5]}...")
    print(f"POSTGRES_URL: {config.POSTGRES_URL[:10]}...")
    print(f"TELETHON_API_ID: {config.TELETHON_API_ID}")
    print(f"PHONE_NUMBER: {config.PHONE_NUMBER}")
    print(f"MEDIA_DOWNLOAD_DIR: {config.MEDIA_DOWNLOAD_DIR}") # <-- ДОБАВЛЕНО
