import asyncio
from loguru import logger

from config import config
from db.database import init_db
from core.parser import telegram_parser # Импортируем глобальный экземпляр парсера
from bots.news_bot import start_news_bot
from bots.admin_bot import start_admin_bot
from core.gigachat import gigachat_api
from core.scheduler import scheduler

async def main():
    logger.info("Запуск приложения Setinews...")

    # Инициализация базы данных
    await init_db()

    # Инициализация GigaChat API (получение первого токена)
    # Это важно сделать до запуска планировщика, чтобы токен был доступен сразу
    await gigachat_api.get_token()

    # Добавление задачи обновления токена GigaChat в планировщик
    # Передаем саму корутину gigachat_api.get_token без вызова ()
    scheduler.add_task(gigachat_api.get_token, 3000, "Обновление токена GigaChat") # Обновляем токен каждые 50 минут (3000 секунд)

    # Запуск планировщика
    await scheduler.start()

    # Запуск Telethon парсера
    # Метод start() в TelegramParser уже содержит логику для добавления обработчика сообщений.
    # Нет необходимости вызывать add_message_handler() здесь напрямую.
    await telegram_parser.start()

    # Запуск ботов (они используют dp.start_polling, который блокирует выполнение,
    # поэтому их нужно запускать асинхронно с asyncio.gather)
    await asyncio.gather(
        start_news_bot(),
        start_admin_bot()
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Приложение остановлено вручную.")
    except Exception as e:
        logger.error(f"Критическая ошибка в основном приложении: {e}")
        # Убедимся, что планировщик останавливается даже при критических ошибках
        asyncio.run(scheduler.stop())
