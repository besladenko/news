from aiogram import Router, types, F
from aiogram.filters import Command
from sqlalchemy.future import select
from core.models import Post
from infra.db import AsyncSessionLocal

router = Router()

@router.message(F.text == "Показать список каналов")
async def show_channels(message: types.Message):
    # тут логика вывода списка городских каналов (реализуешь по своим нуждам)
    await message.answer("Здесь будет список каналов (реализуй по своей БД)")

@router.message(Command("pending"))
async def pending_posts_handler(message: types.Message):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Post).where(Post.status == "pending").limit(10)
        )
        posts = result.scalars().all()
        if not posts:
            await message.answer("Нет постов на модерации.")
        else:
            for post in posts:
                await message.answer(f"ID: {post.id}\n\n{post.original_text[:1000]}")
