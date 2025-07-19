# main.py
# -----------------------------------------------------------------------------
# Точка входа; запускает инициализацию БД и Telegram‑ботов
# -----------------------------------------------------------------------------
import asyncio
import sys
from loguru import logger

from config import Config
from db.database import init_db
# from bots.news_bot import start_news_bot     # пример
# from bots.admin_bot import start_admin_bot   # пример

async def async_main() -> None:
    # 1. Проверяем критичные настройки ещё раз
    if not Config.DATABASE_URL:
        logger.error("Не задана DATABASE_URL — завершаем работу.")
        sys.exit(1)

    # 2. Инициализируем БД (создание таблиц при первом запуске)
    await init_db()

    # 3. Запускаем ботов / планировщики
    # await asyncio.gather(
    #     start_news_bot(),
    #     start_admin_bot(),
    # )

if __name__ == "__main__":
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        logger.info("Остановлено пользователем (Ctrl+C)")
