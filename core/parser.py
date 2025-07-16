# core/parser.py
from telethon import TelegramClient, events
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument, MessageMediaWebPage, MessageMediaUnsupported
from config import config
from loguru import logger
import asyncio
import os

class TelegramParser:
    """
    Класс для парсинга сообщений из Telegram каналов-доноров с использованием Telethon.
    """
    def __init__(self, api_id: int, api_hash: str, session_name: str = 'telethon_session'):
        self.client = TelegramClient(session_name, api_id, api_hash)
        self.running = False
        self.message_handlers = [] # Список функций-обработчиков для новых сообщений

    async def start(self):
        """Запускает клиент Telethon и авторизуется."""
        logger.info("Запуск Telethon клиента...")
        try:
            await self.client.start()
            self.running = True
            logger.info("Telethon клиент запущен.")
            # Добавляем обработчик для новых сообщений
            # incoming=True: только сообщения, приходящие в наши диалоги/каналы
            # forwards=False: игнорируем пересланные сообщения, т.к. нас интересует оригинал
            self.client.add_event_handler(self._new_message_handler, events.NewMessage(incoming=True, forwards=False))
        except Exception as e:
            logger.error(f"Ошибка при запуске Telethon клиента: {e}")
            self.running = False
            # Если ошибка SessionPasswordNeededError, она будет поймана выше в main.py
            # Здесь ловим общие ошибки, чтобы не упасть

    async def stop(self):
        """Останавливает клиент Telethon."""
        if self.running:
            logger.info("Остановка Telethon клиента...")
            await self.client.disconnect()
            self.running = False
            logger.info("Telethon клиент остановлен.")

    def add_message_handler(self, handler_func):
        """Добавляет функцию-обработчик для новых сообщений."""
        self.message_handlers.append(handler_func)
        logger.info(f"Добавлен обработчик сообщений: {handler_func.__name__}")

    async def _new_message_handler(self, event):
        """
        Внутренний обработчик новых сообщений.
        Передает сообщение всем зарегистрированным обработчикам.
        Обрабатывает одиночные медиа и медиа-альбомы.
        """
        # Проверяем, является ли отправитель каналом (не личным сообщением)
        if hasattr(event.peer_id, 'channel_id'):
            channel_id = event.peer_id.channel_id
            message_text = event.message.message
            message_id = event.message.id
            sender_chat = await event.get_chat()
            sender_title = sender_chat.title if sender_chat else f"Канал {channel_id}"

            media_paths = [] # Список для хранения путей ко всем скачанным медиафайлам
            media_dir = "downloads"
            os.makedirs(media_dir, exist_ok=True) # Создаем директорию, если ее нет

            if event.message.media:
                # Проверяем, является ли это медиа-альбомом
                if event.message.grouped_id:
                    # Это часть медиа-альбома. Telethon обрабатывает альбомы как отдельные события
                    # с одинаковым grouped_id. Мы должны собрать все части альбома.
                    # Для простоты текущей реализации, мы будем скачивать каждое медиа по отдельности
                    # при получении его события. deduplicator должен будет учесть, что это части одного поста.
                    # В более сложной системе, нужно было бы ждать все части альбома, прежде чем обрабатывать.
                    # Но для NewMessage события, каждое медиа в альбоме приходит как отдельное событие.
                    # Поэтому просто обрабатываем его как одиночное медиа.
                    pass # Пройдет в блок ниже, как одиночное медиа

                # Обработка одиночного медиафайла
                if isinstance(event.message.media, MessageMediaPhoto):
                    file_extension = "jpg"
                    path = os.path.join(media_dir, f"photo_{event.message.id}.{file_extension}")
                    try:
                        await self.client.download_media(event.message.media, file=path)
                        media_paths.append(path)
                        logger.info(f"Фото сохранено: {path}")
                    except Exception as e:
                        logger.warning(f"Не удалось загрузить фото для сообщения {message_id}: {e}")
                elif isinstance(event.message.media, MessageMediaDocument):
                    # Проверяем, является ли документ видео
                    if event.message.media.document.mime_type and event.message.media.document.mime_type.startswith('video/'):
                        file_extension = event.message.media.document.mime_type.split('/')[-1]
                        path = os.path.join(media_dir, f"video_{event.message.id}.{file_extension}")
                        try:
                            await self.client.download_media(event.message.media, file=path)
                            media_paths.append(path)
                            logger.info(f"Видео сохранено: {path}")
                        except Exception as e:
                            logger.warning(f"Не удалось загрузить видео для сообщения {message_id}: {e}")
                    else:
                        logger.info(f"Обнаружен документ (не фото/видео) в сообщении {message_id} из {sender_title}. Пропускаем.")
                elif isinstance(event.message.media, MessageMediaWebPage):
                    # Это предварительный просмотр ссылки, обычно не нужно скачивать как медиа
                    logger.info(f"Обнаружен предпросмотр ссылки в сообщении {message_id} из {sender_title}. Пропускаем как медиа.")
                elif isinstance(event.message.media, MessageMediaUnsupported):
                    logger.warning(f"Обнаружен неподдерживаемый тип медиа в сообщении {message_id} из {sender_title}. Пропускаем.")
                else:
                    logger.info(f"Обнаружен неизвестный тип медиа {type(event.message.media)} в сообщении {message_id} из {sender_title}. Пропускаем.")

            logger.info(f"Новое сообщение от {sender_title} (ID: {channel_id}): {message_text[:50]}...")

            for handler in self.message_handlers:
                await handler(
                    channel_id=channel_id,
                    message_id=message_id,
                    text=message_text,
                    media_paths=media_paths, # Передаем список путей ко всем медиафайлам
                    source_link=f"https://t.me/c/{channel_id}/{message_id}" # Ссылка на оригинальный пост
                )

# Создаем глобальный экземпляр парсера
telegram_parser = TelegramParser(api_id=config.TELETHON_API_ID, api_hash=config.TELETHON_API_HASH)

if __name__ == "__main__":
    # Пример использования парсера
    async def my_message_processor(channel_id, message_id, text, media_paths, source_link):
        logger.info(f"Обработчик получил сообщение: Канал ID={channel_id}, Сообщение ID={message_id}")
        logger.info(f"Текст: {text[:100]}...")
        if media_paths:
            logger.info(f"Медиа: {media_paths}")
        logger.info(f"Ссылка: {source_link}")

    async def main():
        telegram_parser.add_message_handler(my_message_processor)
        await telegram_parser.start()
        logger.info("Парсер запущен. Ожидание сообщений (нажмите Ctrl+C для выхода)...")
        try:
            while True:
                await asyncio.sleep(1) # Небольшая задержка, чтобы не нагружать CPU
        except KeyboardInterrupt:
            logger.info("Остановка парсера по запросу пользователя.")
        finally:
            await telegram_parser.stop()

    # Запускаем основной цикл
    asyncio.run(main())
