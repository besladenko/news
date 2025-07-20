from aiogram import Router, types
from aiogram.filters import Command
from core.models import DonorChannel
from infra.db import AsyncSessionLocal

router = Router()

@router.message(Command("adddonor"))
async def add_donor_handler(message: types.Message):
    # Пример: /adddonor 1 https://t.me/source_channel "(?i)❤️.*$"
    args = message.text.split(maxsplit=3)
    if len(args) < 3:
        await message.answer("Использование: /adddonor <code>&lt;city_id&gt; &lt;ссылка&gt; [маска]</code>")
        return


    city_id = int(args[1])
    link = args[2]
    mask = args[3] if len(args) > 3 else None
    channel_id = link.split("/")[-1]
    donor = DonorChannel(title=link, channel_id=channel_id, city_id=city_id, mask_pattern=mask)
    async with AsyncSessionLocal() as session:
        session.add(donor)
        await session.commit()
        await message.answer("Канал-доnor добавлен!")
