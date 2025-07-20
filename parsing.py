# parsing.py

import asyncio
from telethon import TelegramClient, events, errors
from config import API_ID, API_HASH, MEDIA_ROOT
from llm import gigachat
from utils import clean_text, contains_ad, contains_danger, signature
from donor_cache import DonorCache
from models import DonorChannel, City, Post, SessionLocal

telethon_client = TelegramClient("setinews_parser", API_ID, API_HASH)
DONORS = DonorCache()

async def resolve_channel(link: str):
    ent = await telethon_client.get_entity(link)
    chan_id = int(ent.id)
    title   = getattr(ent, "title", None) or getattr(ent, "first_name", str(chan_id))
    canon = None
    if link.startswith("http"):
        canon = link
    elif link.startswith("@"):
        canon = f"https://t.me/{link.lstrip('@')}"
    elif getattr(ent, "username", None):
        canon = f"https://t.me/{ent.username}"
    try:
        await telethon_client(JoinChannelRequest(link))
    except errors.UserAlreadyParticipantError:
        pass
    except errors.InviteHashInvalidError:
        pass
    return chan_id, title, canon

@telethon_client.on(events.NewMessage())
async def on_new_message(event):
    if event.chat_id is None or event.is_private:
        return
    async with SessionLocal() as s:
        await DONORS.refresh(s)
        if event.chat_id not in DONORS.ids:
            return
        donor = (await s.execute(
            select(DonorChannel).where(DonorChannel.channel_id == event.chat_id))
        ).scalar_one_or_none()
        if donor is None:
            return
        city = donor.city
        text = event.message.message or ""
        if donor.mask_pattern:
            text = re.sub(donor.mask_pattern, "", text).strip()
        if not text:
            return
        is_ad = await gigachat.detect_ads(text) or contains_ad(text)
        processed = None
        status = "pending"
        if is_ad:
            status = "rejected"
        else:
            cleaned = clean_text(text)
            if not contains_danger(cleaned):
                cleaned = await gigachat.paraphrase(cleaned)
            processed = f"{cleaned}\n\n{signature(city.title, city.link)}"

        media_path = None
        if event.message.media:
            fname = f"{donor.channel_id}_{event.id}.jpg"
            media_path = str(MEDIA_ROOT / fname)
            await event.message.download_media(media_path)

        post = Post(
            donor_id=donor.id,
            city_id=city.id,
            original_text=text,
            processed_text=processed,
            media_path=media_path,
            source_link=f"https://t.me/c/{str(donor.channel_id)[4:]}/{event.id}",
            is_ad=is_ad,
            status=status,
        )
        s.add(post)
        await s.commit()

def start_parser():
    telethon_client.loop.run_until_complete(telethon_client.start())
    telethon_client.run_until_disconnected()
