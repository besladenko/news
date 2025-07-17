# core/parser.py
from telethon import TelegramClient, events
from telethon.tl.types import Channel, User, Chat, MessageMediaPhoto, MessageMediaDocument
from loguru import logger
import asyncio
import os
import datetime

from config import config
import db.database # <-- ИСПРАВЛЕНО: Импорт модуля вместо прямой функции
from db.models import DonorChannel, City, Post

class TelegramParser:
    def __init__(self, api_id, api_hash):
        self.client = TelegramClient('telegram_parser_session', api_id, api_hash)
        self.message_handlers = []
        self._is_running = False

    def add_message_handler(self, handler_func):
        """
        Добавляет функцию-обработчик для новых сообщений.
        Эта функция будет вызываться для каждого нового сообщения.
        """
        self.message_handlers.append(handler_func)
        logger.info(f"Добавлен обработчик сообщений: {handler_func.__name__}")

    async def _new_message_handler(self, event):
        """
        Обработчик новых сообщений Telethon.
        Извлекает текст, медиафайлы и вызывает зарегистрированные обработчики.
        """
        logger.info(f"Новое сообщение от {event.peer_id.channel_id if event.is_channel else event.peer_id.user_id} (ID: {event.id}): {event.message.text[:50]}...")

        # Проверяем, что сообщение пришло из канала
        if not event.is_channel:
            logger.debug(f"Сообщение {event.id} не из канала. Пропускаем.")
            return

        # Получаем ID канала Telethon.
        # Telethon возвращает ID канала без префикса -100.
        # Мы будем использовать этот "сырой" ID для поиска донора в БД,
        # а news_bot.py будет обрабатывать оба формата ID.
        channel_id = event.peer_id.channel_id if event.is_channel else None
        if not channel_id:
            logger.warning(f"Не удалось определить ID канала для сообщения {event.id}. Пропускаем.")
            return

        text = event.message.text
        media_paths = []

        # Обработка медиафайлов
        if event.message.media:
            try:
                # Создаем директорию для медиа, если ее нет
                media_dir = "media_downloads"
                os.makedirs(media_dir, exist_ok=True)

                # Скачиваем медиа
                # Telethon автоматически определяет тип медиа (фото/видео)
                # Если это альбом, event.message.media будет содержать MediaGroup
                # Но events.NewMessage обрабатывает каждый элемент альбома как отдельное событие
                # Для упрощения, мы будем скачивать только первое медиа, если это не альбом.
                # Если это альбом, Telethon отправляет каждое фото/видео как отдельное сообщение,
                # но с тем же album_id. Для корректной обработки альбомов,
                # нужно собирать сообщения по album_id и обрабатывать их вместе.
                # Пока что мы просто скачиваем каждое медиа, как оно приходит.
                
                # Получаем путь к файлу
                file_name = f"{event.id}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
                if isinstance(event.message.media, MessageMediaPhoto):
                    file_name += ".jpg"
                elif isinstance(event.message.media, MessageMediaDocument):
                    # Пытаемся получить расширение из документа
                    if event.message.media.document.mime_type:
                        mime_type = event.message.media.document.mime_type
                        if 'image/' in mime_type:
                            file_name += "." + mime_type.split('/')[-1]
                        elif 'video/' in mime_type:
                            file_name += "." + mime_type.split('/')[-1]
                        else:
                            file_name += ".bin" # Запасной вариант
                    else:
                        file_name += ".bin"

                download_path = os.path.join(media_dir, file_name)
                
                # Скачиваем файл
                downloaded_file = await self.client.download_media(event.message, file=download_path)
                if downloaded_file:
                    media_paths.append(downloaded_file)
                    logger.info(f"Медиафайл скачан: {downloaded_file}")
                else:
                    logger.warning(f"Не удалось скачать медиа для сообщения {event.id}.")

            except Exception as e:
                logger.error(f"Ошибка при обработке медиа для сообщения {event.id}: {e}")

        # Формируем ссылку на источник
        source_link = f"https://t.me/c/{channel_id}/{event.message.id}"

        # Вызываем все зарегистрированные обработчики
        for handler in self.message_handlers:
            await handler(
                channel_id,
                event.message.id,
                text,
                media_paths,
                source_link
            )

    async def start(self):
        """Запускает Telethon клиент и регистрирует обработчик сообщений."""
        if self._is_running:
            logger.warning("Парсер Telethon уже запущен.")
            return

        logger.info("Запуск парсера Telethon...")
        try:
            await self.client.start()
            logger.info("Парсер Telethon успешно подключен.")
            # Регистрируем обработчик для всех входящих новых сообщений
            self.client.add_event_handler(self._new_message_handler, events.NewMessage(incoming=True, func=lambda e: e.is_channel or e.is_private))
            self._is_running = True
        except Exception as e:
            logger.error(f"Ошибка при запуске парсера Telethon: {e}")
            self._is_running = False

    async def stop(self):
        """Останавливает Telethon клиент."""
        if self._is_running:
            logger.info("Остановка парсера Telethon...")
            await self.client.disconnect()
            self._is_running = False
            logger.info("Парсер Telethon остановлен.")

# Создаем глобальный экземпляр парсера
telegram_parser = TelegramParser(config.TELETHON_API_ID, config.TELETHON_API_HASH)

if __name__ == "__main__":
    async def debug_main():
        # Этот блок предназначен только для отладки parser.py отдельно
        # В основном приложении он запускается через main.py
        logger.info("Запуск отладочного режима parser.py...")
        await telegram_parser.start()
        try:
            # Держим клиент запущенным, чтобы он мог получать сообщения
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            logger.info("Остановка отладочного режима parser.py.")
        finally:
            await telegram_parser.stop()

    asyncio.run(debug_main())
