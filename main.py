# main.py

import asyncio
from threading import Thread
from models import init_db
from parse import start_parser
from bot import start_bot
from admin_bot import start_admin_bot

def run_in_thread(fn):
    """Запускает функцию в отдельном потоке-демоне."""
    t = Thread(target=fn, daemon=True)
    t.start()
    return t

async def main():
    # 1. Инициализация базы данных
    await init_db()
    # 2. Запуск парсера Telegram в отдельном потоке
    run_in_thread(start_parser)
    # 3. Запуск бота для пользователей (публикатора)
    run_in_thread(start_bot)
    # 4. Запуск бота для админов
    run_in_thread(start_admin_bot)
    # 5. Ждать бесконечно (чтобы main не завершился)
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
