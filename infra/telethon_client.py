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

    async with AsyncSessionLocal() as session:
        result = await session.execute(DonorChannel.__table__.select())
        donors = result.fetchall()

    donor_ids = []
    for row in donors:
        donor = row[0] if isinstance(row, tuple) else row
        channel_id = donor.channel_id
        # Преобразуем @username или ссылку в id, если надо
        if channel_id.startswith('-100') or channel_id.isdigit():
            donor_ids.append(int(channel_id))
        else:
            donor_ids.append(channel_id)

    @client.on(events.NewMessage(chats=donor_ids))
    async def handler(event):
        donor_username = event.chat.username or str(event.chat_id)
        text = event.text or ""
        async with AsyncSessionLocal() as session:
            donor_result = await session.execute(
                DonorChannel.__table__.select().where(
                    (DonorChannel.channel_id == donor_username) | (DonorChannel.channel_id == str(event.chat_id))
                )
            )
            donor = donor_result.scalar_one_or_none()
            if not donor:
                logger.warning(f"Unknown donor: {donor_username}")
                return
            city_result = await session.execute(
                City.__table__.select().where(City.id == donor.city_id)
            )
            city = city_result.scalar_one_or_none()
            if not city:
                logger.warning(f"Unknown city for donor: {donor_username}")
                return
            clean_text = process_post(text, donor)
            if city.auto_mode:
                logger.info(f"Publishing post from {donor.channel_id} to {city.channel_id}")
                # Публикуем текст и медиа
                if event.media:
                    file = await event.download_media()
                    await news_bot.send_document(chat_id=city.channel_id, document=file, caption=clean_text)
                else:
                    await news_bot.send_message(chat_id=city.channel_id, text=clean_text)
            # Здесь можно сохранять в базу если надо

    await client.run_until_disconnected()
