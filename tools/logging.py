from loguru import logger

logger.add("setinews.log", rotation="1 week", encoding="utf-8")
