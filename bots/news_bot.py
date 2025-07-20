from aiogram import Bot, Dispatcher

from config.settings import settings

bot = Bot(token=settings.NEWS_BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher()
