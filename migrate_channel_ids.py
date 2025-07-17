# migrate_channel_ids.py
import asyncio
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from config import config
from db.database import get_session
from db.models import City, DonorChannel

async def migrate_channel_ids():
    """
    Мигрирует Telegram ID в таблицах City и DonorChannel.
    Если ID канала или донора положительный, он будет преобразован в формат -100XXXXXX.
    Это обеспечивает консистентность с Telegram Bot API, где ID каналов обычно отрицательные.
    """
    logger.info("Начало миграции Telegram ID каналов в базе данных...")
    async for session in get_session():
        cities_updated = 0
        donors_updated = 0

        # --- Миграция городских каналов ---
        stmt_cities = select(City)
        result_cities = await session.execute(stmt_cities)
        cities = result_cities.scalars().all()

        for city in cities:
            # Если Telegram ID положительный, добавляем префикс -100
            # (Телеграм ID каналов и супергрупп всегда отрицательные и начинаются с -100)
            if city.telegram_id > 0:
                old_id = city.telegram_id
                new_id = int(f"-100{old_id}")
                city.telegram_id = new_id
                cities_updated += 1
                logger.info(f"Обновлен ID городского канала '{city.title}': {old_id} -> {new_id}")
        
        # --- Миграция донорских каналов ---
        stmt_donors = select(DonorChannel)
        result_donors = await session.execute(stmt_donors)
        donors = result_donors.scalars().all()

        for donor in donors:
            # Если Telegram ID положительный, добавляем префикс -100
            if donor.telegram_id > 0:
                old_id = donor.telegram_id
                new_id = int(f"-100{old_id}")
                donor.telegram_id = new_id
                donors_updated += 1
                logger.info(f"Обновлен ID донорского канала '{donor.title}': {old_id} -> {new_id}")

        if cities_updated > 0 or donors_updated > 0:
            await session.commit()
            logger.info(f"Миграция завершена. Обновлено {cities_updated} городских каналов и {donors_updated} донорских каналов.")
        else:
            logger.info("Миграция не требовалась: все ID каналов уже в правильном формате (отрицательные).")

if __name__ == "__main__":
    asyncio.run(migrate_channel_ids())
