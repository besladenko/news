# config.py
import os
from dotenv import load_dotenv
from loguru import logger

# Загружаем переменные окружения из .env файла
load_dotenv()

class Config:
    """Класс для хранения конфигурации приложения."""

    # Telegram Bot API токены
    BOT_TOKEN: str = os.getenv("BOT_TOKEN")
    ADMIN_BOT_TOKEN: str = os.getenv("ADMIN_BOT_TOKEN")

    # GigaChat API ключи (оставляем для совместимости, но не используем, если отключено)
    GIGACHAT_CLIENT_ID: str = os.getenv("GIGACHAT_CLIENT_ID")
    GIGACHAT_CLIENT_SECRET: str = os.getenv("GIGACHAT_CLIENT_SECRET")
    GIGACHAT_AUTH_KEY: str = os.getenv("GIGACHAT_AUTH_KEY") # Base64(client_id:client_secret)
    GIGACHAT_SCOPE: str = os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")
    RQUUID: str = os.getenv("RQUUID") # Уникальный идентификатор запроса (UUID4)

    # PostgreSQL URL
    POSTGRES_URL: str = os.getenv("POSTGRES_URL")

    # Telethon API ID и Hash
    TELETHON_API_ID: int = int(os.getenv("API_ID"))
    TELETHON_API_HASH: str = os.getenv("API_HASH")
    PHONE_NUMBER: str = os.getenv("PHONE_NUMBER") # <-- НОВОЕ: Добавлен номер телефона для Telethon

    # ID чата администратора для модерации
    ADMIN_CHAT_ID: int = int(os.getenv("ADMIN_CHAT_ID"))

    # Пользовательская подпись для постов
    CUSTOM_SIGNATURE: str = os.getenv("CUSTOM_SIGNATURE", "") # <-- ОБНОВЛЕНО: Пользовательская подпись

    def __init__(self):
        self._validate_config()

    def _validate_config(self):
        """Проверяет наличие всех необходимых переменных окружения."""
        required_vars = [
            "BOT_TOKEN", "ADMIN_BOT_TOKEN",
            "POSTGRES_URL",
            "TELETHON_API_ID", "TELETHON_API_HASH",
            "PHONE_NUMBER", # <-- НОВОЕ: Добавлен в обязательные переменные
            "ADMIN_CHAT_ID"
        ]
        # GigaChat переменные теперь опциональны, если GigaChat отключен
        if os.getenv("GIGACHAT_ENABLED", "true").lower() == "true": # Пример флага для включения/выключения GigaChat
             required_vars.extend(["GIGACHAT_CLIENT_ID", "GIGACHAT_CLIENT_SECRET", "GIGACHAT_AUTH_KEY", "RQUUID"])

        for var in required_vars:
            if not getattr(Config, var):
                logger.error(f"Переменная окружения {var} не установлена. Проверьте ваш .env файл.")
                raise ValueError(f"Отсутствует переменная окружения: {var}")

# Создаем глобальный экземпляр конфигурации
config = Config()

if __name__ == "__main__":
    # Пример использования и проверки конфигурации
    try:
        logger.info("Конфигурация успешно загружена и проверена.")
        logger.info(f"BOT_TOKEN (первые 5 символов): {config.BOT_TOKEN[:5]}...")
        logger.info(f"POSTGRES_URL: {config.POSTGRES_URL}")
        logger.info(f"TELETHON_API_ID: {config.TELETHON_API_ID}")
        logger.info(f"TELETHON_API_HASH: {config.TELETHON_API_HASH[:5]}...")
        logger.info(f"PHONE_NUMBER: {config.PHONE_NUMBER}")
        logger.info(f"ADMIN_CHAT_ID: {config.ADMIN_CHAT_ID}")
        logger.info(f"CUSTOM_SIGNATURE: {config.CUSTOM_SIGNATURE}")
    except ValueError as e:
        logger.error(f"Ошибка конфигурации: {e}")
