import asyncio
from loguru import logger

from config import config
from db.database import init_db # <-- Оставляем импорт init_db, но не вызываем ее в main()
from core.parser import telegram_parser
from bots.news_bot import start_news_bot, set_telegram_parser_instance_for_news_bot, process_new_donor_message
from bots.admin_bot import start_admin_bot, admin_dp # Импортируем admin_dp для регистрации обработчиков
from core.gigachat import gigachat_api
from core.scheduler import scheduler

async def main():
    logger.info("Запуск приложения Setinews...")

    # Инициализация базы данных должна выполняться ОДИН РАЗ вручную
    # (например, через python3 -c "import asyncio; from db.database import init_db; asyncio.run(init_db())")
    # Убираем вызов init_db() отсюда, чтобы она не очищалась при каждом запуске бота.
    # await init_db() # <-- УДАЛЕНО: НЕ ВЫЗЫВАЕМ init_db() ЗДЕСЬ!

    # Инициализация GigaChat API (получение первого токена)
    await gigachat_api.get_token()

    # Добавление задачи обновления токена GigaChat в планировщик
    scheduler.add_task(gigachat_api.get_token, 3000, "Обновление токена GigaChat")

    # Запуск планировщика
    await scheduler.start()

    # Устанавливаем экземпляр парсера в news_bot
    # Это нужно сделать до того, как парсер начнет слушать сообщения
    await set_telegram_parser_instance_for_news_bot(telegram_parser)

    # Регистрируем обработчик сообщений парсера в news_bot
    telegram_parser.add_message_handler(process_new_donor_message)

    # Запуск Telethon парсера
    await telegram_parser.start()

    # Запуск ботов
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
        asyncio.run(scheduler.stop()) # Убедимся, что планировщик останавливается
