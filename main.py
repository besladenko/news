import asyncio
import uvloop
import threading
from infra.db import init_db
from config.settings import settings
from infra.telethon_client import tg_client, start_telethon
from bots.news_bot import bot as news_bot, dp as news_dp
from bots.admin_bot import bot as admin_bot, dp as admin_dp
from tools.logging import logger

asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

def start_bot(bot, dp):
    import aiogram
    async def _run():
        logger.info(f"Starting bot {bot.token[:10]}...")
        await dp.start_polling(bot)
    asyncio.run(_run())

async def main():
    await init_db()
    await start_telethon()
    logger.info("Telethon client running.")

    # Запуск ботов в отдельных потоках
    threading.Thread(target=start_bot, args=(news_bot, news_dp), daemon=True).start()
    threading.Thread(target=start_bot, args=(admin_bot, admin_dp), daemon=True).start()

    # Бесконечный цикл — фоновые задачи, кеш, обновления токенов и т.п.
    while True:
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
