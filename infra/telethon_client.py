from telethon import TelegramClient, events
from config.settings import settings

tg_client = TelegramClient(
    'setinews_session',
    settings.TG_API_ID,
    settings.TG_API_HASH
)

async def start_telethon():
    await tg_client.start()
    print("Telethon client started")
