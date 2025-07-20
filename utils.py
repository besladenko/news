# utils.py

import re

LINK_RE    = re.compile(r"https?://\S+|t\.me/\S+|@\w+|#[\wА-Яа-я_]+")
AD_PHRASES = ["подпишись", "жми", "переходи", "смотри канал"]
DANGER     = ["бпла", "ракетн", "тревог"]

def clean_text(text: str) -> str:
    return LINK_RE.sub("", text).strip()

def contains_ad(text: str) -> bool:
    return any(p in text.lower() for p in AD_PHRASES)

def contains_danger(text: str) -> bool:
    return any(k in text.lower() for k in DANGER)

def signature(city_title, city_link) -> str:
    return f"❤️ Подпишись на {city_title} ({city_link})" if city_link else f"❤️ Подпишись на {city_title}"
