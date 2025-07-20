# config.py

import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

API_ID               = int(os.getenv("TG_API_ID", 0))
API_HASH             = os.getenv("TG_API_HASH", "")
NEWS_BOT_TOKEN       = os.getenv("NEWS_BOT_TOKEN", "")
ADMIN_BOT_TOKEN      = os.getenv("ADMIN_BOT_TOKEN", "")
POSTGRES_DSN         = os.getenv("POSTGRES_DSN", "postgresql+asyncpg://user:pass@localhost/db")
SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "0.82"))
MEDIA_ROOT           = Path(os.getenv("MEDIA_ROOT", "media"))
DONOR_CACHE_TTL_MIN  = int(os.getenv("DONOR_CACHE_TTL_MIN", "10"))

MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
