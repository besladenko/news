from telethon import TelegramClient, events
from config.settings import settings
from infra.db import AsyncSessionLocal
from core.models import DonorChannel, City
from core.processor import process_post
from bots.news_bot import bot as news_bot
from loguru import logger
import asyncio

async def start_telethon_watcher():
    client = TelegramClient('parser', settings.TG_API_ID, settings.TG_API_HASH)
    await client.start()
    logger.info("Telethon client started.")

    # Получаем все донорские каналы
    async with AsyncSessionLocal() as session:
        donors = (await session.execute(DonorChannel.__table__.select())).scalars().all()
    donor_ids = [donor.channel_id for donor in donors]

    # Переводим channel_id к username для Telethon (важно, если channel_id = username, иначе нужен peer id!)
    @client.on(events.NewMessage(chats=donor_ids))
    async def handler(event):
        # event.chat.username не всегда гарантирован!
        donor_id = event.chat.username or event.chat.id or str(event.chat)
        text = event.text or ""
        async with AsyncSessionLocal() as session:
            # Ищем донора по username или channel_id (важно для приватных/публичных каналов)
            donor = (await session.execute(
                DonorChannel.__table__.select().where(
                    (DonorChannel.channel_id == donor_id) | (DonorChannel.channel_id == str(event.chat.id))
                )
            )).scalar_one_or_none()
            if not donor:
                logger.warning(f"Unknown donor: {donor_id}")
                return
            city = (await session.execute(
                City.__table__.select().where(City.id == donor.city_id)
            )).scalar_one_or_none()
            if not city:
                logger.warning(f"Unknown city for donor: {donor_id}")
                return

            # Обработка текста (чистка подписи и т.п.)
            clean_text = process_post(text, donor, city_title=city.title)
            if city.auto_mode:
                logger.info(f"Publishing post from {donor.channel_id} to {city.channel_id}")
                try:
                    await news_bot.send_message(chat_id=city.channel_id, text=clean_text)
                except Exception as e:
                    logger.error(f"Error sending message: {e}")

    await client.run_until_disconnected()
