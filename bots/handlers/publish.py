from aiogram import Router, types
from aiogram.filters import Command
from sqlalchemy.future import select
from core.models import Post, City
from infra.db import AsyncSessionLocal

router = Router()

@router.message(Command("publish"))
async def publish_handler(message: types.Message):
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Использование: /publish <code>&lt;post_id&gt;</code>")
        return


    post_id = int(args[1])
    async with AsyncSessionLocal() as session:
        post = await session.get(Post, post_id)
        if not post:
            await message.answer("Пост не найден.")
            return
        post.status = "published"
        await session.commit()

        # Получаем канал города
        city = await session.get(City, post.city_id)
        # Тут — логика отправки в канал города (через Telethon или через Bot)
        await message.answer(f"Пост опубликован в: {city.link}")
