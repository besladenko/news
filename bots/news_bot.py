from aiogram import Bot, Dispatcher
from aiogram.types import Message
from config.settings import settings
from bots.handlers import city, donor, pending, publish

bot = Bot(token=settings.NEWS_BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher()

# Подключаем нужные хендлеры (у news_bot только публикация, pending)
dp.include_router(city.router)
dp.include_router(donor.router)
dp.include_router(pending.router)
dp.include_router(publish.router)
