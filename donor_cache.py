# donor_cache.py

from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from models import DonorChannel

class DonorCache:
    def __init__(self):
        self.ids = set()
        self.expires = datetime.min

    async def refresh(self, session: AsyncSession, ttl_min: int = 10):
        if datetime.utcnow() < self.expires:
            return
        rows = await session.execute(select(DonorChannel.channel_id))
        self.ids = set(rows.scalars())
        self.expires = datetime.utcnow() + timedelta(minutes=ttl_min)
