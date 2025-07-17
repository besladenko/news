# main.py
import asyncio
from loguru import logger

from config import config # <-- Moved to the top

# import db.database # <-- Удалена эта строка

from core.parser import telegram_parser, TelegramParser
from core.scheduler import scheduler
from core.gigachat import gigachat_api
from bots.news_bot import dp as news_dp, bot as news_bot, process_new_donor_message, start_news_bot
from bots.admin_bot import admin_dp, admin_bot, start_admin_bot
from sqlalchemy.future import select
from db.models import DonorChannel, City

# Импортируем init_db и get_session здесь, после всех остальных импортов модулей
from db.database import init_db, get_session # <-- Перенесено сюда

async def run_parser_and_process_messages():
    """
    Функция, которая будет запускаться планировщиком для парсинга
    и обработки новых сообщений.
    """
    logger.info("Запуск задачи: Проверка новых сообщений от доноров.")
    # Telethon уже имеет внутренний обработчик events.NewMessage
    # Нам просто нужно убедиться, что Telethon клиент запущен.
    # Функция process_new_donor_message уже зарегистрирована как обработчик в parser.py
    # при вызове telegram_parser.add_message_handler
    pass # Логика парсинга и обработки уже встроена в Telethon и его обработчики

async def main():
    """Основная функция для запуска всех компонентов проекта."""
    logger.add("file.log", rotation="500 MB") # Настройка логирования в файл
    logger.info("Запуск приложения Setinews...")

    # 1. Инициализация базы данных
    await init_db() # <-- Вызываем напрямую

    # 2. Инициализация и запуск Telethon парсера
    # Добавляем обработчик сообщений из парсера в наш процессор
    telegram_parser.add_message_handler(process_new_donor_message)
    await telegram_parser.start()

    # 3. Запуск планировщика
    # Добавляем задачу для периодического обновления токена GigaChat
    scheduler.add_task(gigachat_api.get_token(), 15 * 60, "Обновление токена GigaChat") # Каждые 15 минут
    # TODO: Добавить задачу для периодической проверки каналов на наличие новых постов
    # (если Telethon.events.NewMessage недостаточно для всех сценариев)
    # scheduler.add_task(run_parser_and_process_messages(), 60, "Парсинг новых сообщений") # Каждую минуту

    await scheduler.start()

    # 4. Запуск Telegram ботов
    # Запускаем ботов в отдельных корутинах
    bot_tasks = [
        start_news_bot(),
        start_admin_bot()
    ]
    
    # Запускаем ботов параллельно
    await asyncio.gather(*bot_tasks)

    logger.info("Приложение Setinews завершено.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Приложение остановлено пользователем.")
    except Exception as e:
        logger.error(f"Критическая ошибка в основном приложении: {e}")
    finally:
        # Остановка Telethon клиента при завершении
        asyncio.run(telegram_parser.stop())
        # Остановка планировщика
        asyncio.run(scheduler.stop())
