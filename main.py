import asyncio
import uvloop
from loguru import logger
from infra.db import init_db
from infra.telethon_client import start_telethon_watcher
from bots.admin_bot import bot as admin_bot, dp as admin_dp
from bots.news_bot import bot as news_bot, dp as news_dp

async def start_bot(dp, bot):
    await dp.start_polling(bot)

async def main():
    uvloop.install()
    await init_db()
    logger.info("Telethon client running.")
    telethon_task = asyncio.create_task(start_telethon_watcher())
    bot_tasks = [
        asyncio.create_task(start_bot(admin_dp, admin_bot)),
        asyncio.create_task(start_bot(news_dp, news_bot)),
    ]
    await asyncio.gather(telethon_task, *bot_tasks)

if __name__ == "__main__":
    asyncio.run(main())
