from aiogram import Router, types
from aiogram.filters import Command
from sqlalchemy.ext.asyncio import AsyncSession
from core.models import City
from infra.db import AsyncSessionLocal

router = Router()

@router.message(Command("addcity"))
async def add_city_handler(message: types.Message):
    # Пример: /addcity https://t.me/+abcd
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /addcity <code>&lt;ссылка&gt;</code>")
        return


    link = args[1].strip()
    channel_id = link.split("/")[-1]
    city = City(title=link, channel_id=channel_id, link=link)
    async with AsyncSessionLocal() as session:
        session.add(city)
        await session.commit()
        await message.answer(f"Городской канал добавлен!\ncity_id: {city.id}")
