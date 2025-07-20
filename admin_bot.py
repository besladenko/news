# admin_bot.py

from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from config import ADMIN_BOT_TOKEN
from models import SessionLocal, City, DonorChannel, Admin

admin_bot = Bot(token=ADMIN_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

@dp.message(commands=["start"])
async def cmd_start(msg: types.Message):
    await msg.reply("Админ-панель SetiNews.\nДоступные команды: /addcity, /adddonor, /pending, /publish, ...")

@dp.message(commands=["addcity"])
async def cmd_addcity(msg: types.Message):
    # TODO: parsing and adding a city
    await msg.reply("Формат: /addcity <@username|https://t.me/...>")

@dp.message(commands=["adddonor"])
async def cmd_adddonor(msg: types.Message):
    # TODO: parsing and adding a donor
    await msg.reply("Формат: /adddonor <city_id> <@username|https://t.me/...> [маска]")

def start_admin_bot():
    import asyncio
    asyncio.run(dp.start_polling(admin_bot))
