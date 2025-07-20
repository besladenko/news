from aiogram import Bot, Dispatcher
from config.settings import settings
from aiogram.fsm.storage.memory import MemoryStorage

bot = Bot(token=settings.ADMIN_BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher(storage=MemoryStorage())

# Импортируем роутеры FSM/handlers
from bots.handlers import city, donor, pending, publish

dp.include_router(city.router)
dp.include_router(donor.router)
dp.include_router(pending.router)
dp.include_router(publish.router)
