from aiogram import Bot, Dispatcher
from config.settings import settings
from bots.handlers import city, donor, pending, publish

bot = Bot(token=settings.ADMIN_BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher()
dp.include_router(city.router)
dp.include_router(donor.router)
dp.include_router(pending.router)
dp.include_router(publish.router)
