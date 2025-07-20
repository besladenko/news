# main.py

import asyncio
from threading import Thread
from models import init_db
from parsing import start_parser
from bot import start_bot
from admin_bot import start_admin_bot

def run_in_thread(fn):
    t = Thread(target=fn, daemon=True)
    t.start()
    return t

async def main():
    await init_db()
    # Запускать парсер Telegram в отдельном потоке
    run_in_thread(start_parser)
    # Запуск бота для пользователей
    run_in_thread(start_bot)
    # Запуск бота для админов
    run_in_thread(start_admin_bot)
    # Ждать бесконечно
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
