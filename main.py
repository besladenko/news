import asyncio
import uvloop
from infra.db import init_db
from infra.telethon_client import start_telethon_watcher
from bots.news_bot import bot as news_bot, dp as news_dp
from bots.admin_bot import bot as admin_bot, dp as admin_dp
from tools.logging import logger

asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

async def main():
    await init_db()
    # Запуск telethon-парсера как фоновой задачи
    telethon_task = asyncio.create_task(start_telethon_watcher())
    logger.info("Telethon client running.")

    # Стартуем оба бота как asyncio задачи!
    bot_tasks = [
        asyncio.create_task(news_dp.start_polling(news_bot)),
        asyncio.create_task(admin_dp.start_polling(admin_bot)),
    ]

    # Ожидание всех задач (боты + telethon)
    await asyncio.gather(telethon_task, *bot_tasks)

if __name__ == "__main__":
    asyncio.run(main())
