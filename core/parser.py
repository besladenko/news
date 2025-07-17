# core/parser.py
import asyncio
import os
from telethon import TelegramClient, events
from loguru import logger
from db.database import get_session
from db.models import DonorChannel
from sqlalchemy.future import select

# Импортируем функцию обработки сообщений из news_bot
from bots.news_bot import process_new_donor_message, set_telegram_parser_instance_for_news_bot
from config import config

class TelegramParser:
    """
    Класс для парсинга сообщений из Telegram каналов с использованием Telethon.
    """
    def __init__(self, api_id: int, api_hash: str, phone_number: str):
        self.client = TelegramClient(phone_number, api_id, api_hash)
        self.donor_channels_ids = set() # Множество для быстрого поиска ID доноров
        logger.info("Telethon клиент инициализирован.")

    async def _load_donor_channels(self):
        """Загружает ID всех донорских каналов из базы данных."""
        async for session in get_session():
            stmt = select(DonorChannel.telegram_id)
            result = await session.execute(stmt)
            self.donor_channels_ids = set(result.scalars().all())
        logger.info(f"Загружено {len(self.donor_channels_ids)} донорских каналов из БД.")

    async def _new_message_handler(self, event):
        """
        Обработчик новых сообщений.
        Фильтрует сообщения только от зарегистрированных донорских каналов.
        """
        chat_id = event.chat_id
        # Проверяем, является ли отправитель донорским каналом
        if chat_id in self.donor_channels_ids:
            logger.info(f"Новое сообщение от {chat_id} (ID: {event.id}): {event.text[:50]}...")
            
            # Скачиваем медиафайл, если он есть
            image_url = None # Это будет локальный путь к скачанному файлу
            if event.photo:
                try:
                    # Telethon возвращает список размеров фото, берем самый большой
                    photo_path = os.path.join(config.MEDIA_DOWNLOAD_DIR, f"{event.id}_{event.date.strftime('%Y%m%d%H%M%S')}.jpg")
                    await event.download_media(file=photo_path)
                    image_url = photo_path # Сохраняем локальный путь
                    logger.info(f"Медиафайл скачан: {image_url}")
                except Exception as e:
                    logger.error(f"Ошибка при скачивании фото для сообщения {event.id}: {e}")
                    image_url = None # Сбрасываем, если не удалось скачать
            elif event.video:
                try:
                    video_path = os.path.join(config.MEDIA_DOWNLOAD_DIR, f"{event.id}_{event.date.strftime('%Y%m%d%H%M%S')}.mp4")
                    await event.download_media(file=video_path)
                    image_url = video_path # Сохраняем локальный путь к видео как image_url для обработки в news_bot
                    logger.info(f"Медиафайл скачан: {image_url}")
                except Exception as e:
                    logger.error(f"Ошибка при скачивании видео для сообщения {event.id}: {e}")
                    image_url = None # Сбрасываем, если не удалось скачать

            # Определяем source_link (если есть)
            source_link = None
            if event.fwd_from and event.fwd_from.channel_post:
                # Если это пересланное сообщение из канала, можно попытаться сформировать ссылку
                # Это упрощенный вариант, может потребоваться доработка для разных типов пересылки
                source_link = f"https://t.me/c/{abs(event.fwd_from.channel_id)}/{event.fwd_from.channel_post}"

            # Передаем данные в news_bot.process_new_donor_message
            # Теперь передаем явные аргументы, как ожидает функция в news_bot.py
            await process_new_donor_message(
                channel_id=chat_id,
                message_id=event.id,
                text=event.text,
                media_paths=[image_url] if image_url else [], # Передаем список путей к медиафайлам
                source_link=source_link
            )
        else:
            # logger.debug(f"Сообщение от незарегистрированного канала {chat_id}. Пропускаем.")
            pass # Не логируем каждый пропущенный канал, чтобы не засорять логи

    async def start(self):
        """Запускает парсер Telethon и начинает слушать новые сообщения."""
        logger.info("Запуск Telethon парсера...")
        
        # Создаем директорию для медиафайлов, если ее нет
        os.makedirs(config.MEDIA_DOWNLOAD_DIR, exist_ok=True)

        await self.client.start(phone=lambda: config.PHONE_NUMBER) # Используем лямбда-функцию для номера телефона
        logger.info("Telethon клиент подключен.")

        # Загружаем донорские каналы после подключения клиента
        await self._load_donor_channels()

        # Устанавливаем экземпляр парсера в news_bot
        await set_telegram_parser_instance_for_news_bot(self)

        # Добавляем обработчик для новых сообщений
        self.client.add_event_handler(self._new_message_handler, events.NewMessage)
        logger.info("Telethon парсер начал слушать новые сообщения.")

        # Держим клиент активным
        await self.client.run_until_disconnected()
        logger.info("Telethon парсер остановлен.")

    async def stop(self):
        """Останавливает парсер Telethon."""
        if self.client.is_connected():
            logger.info("Остановка Telethon парсера...")
            await self.client.disconnect()
            logger.info("Telethon парсер отключен.")

# Глобальный экземпляр парсера
telegram_parser = TelegramParser(
    api_id=config.TELETHON_API_ID,
    api_hash=config.TELETHON_API_HASH,
    phone_number=config.PHONE_NUMBER
)

if __name__ == "__main__":
    async def debug_parser():
        # Это для отладки самого парсера, обычно запускается через main.py
        await telegram_parser.start()

    asyncio.run(debug_parser())
