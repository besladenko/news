# bot.py

from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from config import NEWS_BOT_TOKEN
from utils import signature
from models import SessionLocal, City, Post

news_bot = Bot(token=NEWS_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

@dp.message(commands=["start"])
async def cmd_start(msg: types.Message):
    await msg.reply("Это городской новостной бот.")

async def publish_post(post_id: int):
    async with SessionLocal() as s:
        post = await s.get(Post, post_id)
        if not post or post.status != "pending":
            return
        city = await s.get(City, post.city_id)
        text = post.processed_text or ""
        if post.media_path:
            with open(post.media_path, "rb") as f:
                await news_bot.send_photo(city.channel_id, f, caption=text)
        else:
            await news_bot.send_message(city.channel_id, text)
        post.status = "published"
        await s.commit()

def start_bot():
    import asyncio
    asyncio.run(dp.start_polling(news_bot))
