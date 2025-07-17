# bots/news_bot.py
import asyncio
import os
import re # Добавляем импорт re для функции remove_advertisement_links
from aiogram import Bot, Dispatcher, types
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError # Import specific exceptions
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from loguru import logger
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from config import config
from db.database import get_session
from db.models import City, DonorChannel, Post, Admin # Ensure Admin is imported for check_admin

# Инициализация бота
bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()

# Глобальная переменная для хранения экземпляра TelethonParser
# Это будет установлено из main.py
telegram_parser_instance = None

async def set_telegram_parser_instance_for_news_bot(parser_instance):
    """Устанавливает экземпляр TelethonParser для использования в news_bot."""
    global telegram_parser_instance
    telegram_parser_instance = parser_instance
    logger.info("Экземпляр TelethonParser установлен в news_bot.")


async def process_new_donor_message(event):
    """
    Обрабатывает новые сообщения от донорских каналов.
    Проверяет на дубликаты, рекламный контент и переформулирует текст.
    """
    # Импортируем Deduplicator и GigaChatAPI здесь, чтобы избежать циклических зависимостей
    # если они импортируют news_bot.
    from core.deduplicator import deduplicator
    from core.gigachat import gigachat_api
    from bots.admin_bot import admin_bot # Импортируем админ-бота для отправки уведомлений

    channel_id = event.chat_id
    message_id = event.id
    original_text = event.text
    image_url = None
    if event.photo:
        # Telethon возвращает список размеров фото, берем самый большой
        image_url = event.photo.sizes[-1].url
    elif event.video:
        image_url = event.video.thumbs[-1].url if event.video.thumbs else None # Берем превью видео

    logger.info(f"Начало обработки нового сообщения от донора {channel_id}, ID: {message_id}")

    async for session in get_session():
        # Находим донорский канал по его Telegram ID
        stmt_donor = select(DonorChannel).where(DonorChannel.telegram_id == channel_id)
        donor_channel = (await session.execute(stmt_donor)).scalar_one_or_none()

        if not donor_channel:
            logger.warning(f"Сообщение от неизвестного донора (ID: {channel_id}). Пропускаем.")
            return

        city = await session.get(City, donor_channel.city_id)
        if not city:
            logger.error(f"Город для донора {donor_channel.title} (ID: {donor_channel.id}) не найден. Пропускаем сообщение.")
            return

        # 1. Проверка на дубликаты
        is_duplicate = await deduplicator.check_for_duplicates(original_text, city.id, session)
        if is_duplicate:
            new_post = Post(
                original_text=original_text,
                processed_text=original_text, # Сохраняем оригинал для логов
                image_url=image_url,
                is_duplicate=True,
                status="rejected", # Помечаем как отклоненный дубликат
                city_id=city.id,
                donor_channel_id=donor_channel.id
            )
            session.add(new_post)
            await session.commit()
            logger.info(f"Сообщение от донора {channel_id}, ID: {message_id} является дубликатом. Пропускаем.")
            return

        # 2. Проверка на рекламный контент
        is_advertisement = await gigachat_api.check_advertisement(original_text)
        if is_advertisement:
            new_post = Post(
                original_text=original_text,
                processed_text=original_text, # Сохраняем оригинал для модерации
                image_url=image_url,
                is_duplicate=False,
                status="pending", # Отправляем на ручную модерацию
                city_id=city.id,
                donor_channel_id=donor_channel.id
            )
            session.add(new_post)
            await session.commit()
            logger.info(f"Сообщение '{original_text[:50]}...' является рекламным. Отправляем на ручную модерацию.")
            await send_post_to_admin_panel(new_post, city.title, admin_bot)
            return

        # 3. Удаление рекламных ссылок (если есть)
        processed_text = remove_advertisement_links(original_text)
        if not processed_text.strip(): # Если текст стал пустым после удаления ссылок
            logger.warning(f"Текст поста (ID: {message_id}) стал пустым после удаления рекламных ссылок. Пропускаем.")
            return

        # 4. Переформулирование текста (если не содержит ключевых слов)
        # Ключевые слова, при наличии которых переформулирование пропускается
        keywords = ["бпла", "ракетная опасность", "обстрел", "взрыв", "атака"]
        if any(keyword in processed_text.lower() for keyword in keywords):
            logger.info(f"Сообщение '{processed_text[:50]}...' содержит ключевые слова ({' или '.join(keywords)}). Переформулирование пропущено.")
            final_text = processed_text
        else:
            final_text = await gigachat_api.rephrase_text(processed_text)
            if not final_text:
                logger.warning(f"Не удалось переформулировать текст для '{processed_text[:50]}...'. Используем оригинал.")
                final_text = processed_text

        # 5. Сохранение поста в БД
        new_post = Post(
            original_text=original_text,
            processed_text=final_text,
            image_url=image_url,
            is_duplicate=False,
            status="pending", # Всегда отправляем на модерацию после обработки
            city_id=city.id,
            donor_channel_id=donor_channel.id
        )
        session.add(new_post)
        await session.commit()
        logger.info(f"Новый пост (ID: {new_post.id}) сохранен в БД со статусом 'pending'.")

        # 6. Публикация или отправка на модерацию
        if city.auto_mode:
            await publish_post(new_post.id, city.telegram_id, session, [image_url] if image_url else [])
        else:
            await send_post_to_admin_panel(new_post, city.title, admin_bot)

def remove_advertisement_links(text: str) -> str:
    """Удаляет потенциальные рекламные ссылки из текста."""
    # Пример: удаление ссылок t.me, vk.com, instagram.com, а также других URL
    # Это очень базовая реализация. Для более сложного парсинга потребуется regex
    # или специализированные библиотеки.
    cleaned_text = re.sub(r'https?://\S+|t\.me/\S+|vk\.com/\S+|instagram\.com/\S+', '', text)
    # Удаляем хештеги, которые часто используются в рекламе
    cleaned_text = re.sub(r'#\w+', '', cleaned_text)
    # Удаляем @username, которые могут быть ссылками на каналы/пользователей
    cleaned_text = re.sub(r'@\w+', '', cleaned_text)
    return cleaned_text

async def publish_post(post_id: int, target_telegram_channel_id: int, session: AsyncSession, media_paths: list = None):
    """
    Публикует пост в указанный Telegram канал.
    Обновляет статус поста в БД.
    """
    from bots.admin_bot import admin_bot # Импортируем админ-бота здесь

    post = await session.get(Post, post_id)
    if not post:
        logger.error(f"Пост ID {post_id} не найден для публикации.")
        return

    try:
        if media_paths and media_paths[0]:
            media_file_path = media_paths[0]
            if os.path.exists(media_file_path):
                # Отправка фото или видео
                if media_file_path.lower().endswith(('.png', '.jpg', '.jpeg')):
                    await bot.send_photo(chat_id=target_telegram_channel_id, photo=types.FSInputFile(media_file_path), caption=post.processed_text, parse_mode="Markdown")
                elif media_file_path.lower().endswith(('.mp4', '.mov', '.avi')):
                    await bot.send_video(chat_id=target_telegram_channel_id, video=types.FSInputFile(media_file_path), caption=post.processed_text, parse_mode="Markdown")
                else:
                    logger.warning(f"Неподдерживаемый тип медиафайла для поста {post_id}: {media_file_path}. Отправляем только текст.")
                    await bot.send_message(chat_id=target_telegram_channel_id, text=post.processed_text, parse_mode="Markdown")
            else:
                logger.warning(f"Медиафайл не найден по пути {media_file_path} для поста {post_id}. Отправляем только текст.")
                await bot.send_message(chat_id=target_telegram_channel_id, text=post.processed_text, parse_mode="Markdown")
        else:
            logger.info(f"Медиафайлы для поста {post_id} отсутствуют. Отправляем только текст.")
            await bot.send_message(chat_id=target_telegram_channel_id, text=post.processed_text, parse_mode="Markdown")
        
        post.status = "published"
        post.published_at = func.now()
        await session.commit()
        logger.info(f"Пост ID {post_id} успешно опубликован в канал {target_telegram_channel_id}.")

    except TelegramBadRequest as e:
        # Это включает ошибки типа "chat not found", "bot is not a member", "caption too long" и т.д.
        logger.error(f"Ошибка при публикации поста ID {post_id} в канал {target_telegram_channel_id}: {e}")
        post.status = "failed_publication"
        await session.commit()
        await admin_bot.send_message(
            chat_id=config.ADMIN_CHAT_ID,
            text=f"⚠️ **Ошибка публикации поста ID {post.id}** в канал `{target_telegram_channel_id}`:\n`{e}`\n"
                 f"Возможно, канал не существует, бот не является его администратором, или есть другая проблема с запросом. Пост помечен как 'failed_publication'.",
            parse_mode="Markdown"
        )
    except TelegramForbiddenError as e:
        # Это происходит, когда бот был заблокирован пользователем или исключен из чата
        logger.error(f"Бот был заблокирован или исключен из канала {target_telegram_channel_id} при публикации поста ID {post_id}: {e}")
        post.status = "failed_publication"
        await session.commit()
        await admin_bot.send_message(
            chat_id=config.ADMIN_CHAT_ID,
            text=f"🚫 **Бот был заблокирован или исключен из канала `{target_telegram_channel_id}`** при попытке публикации поста ID {post.id}:\n`{e}`\n"
                 f"Пост помечен как 'failed_publication'.",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Неизвестная ошибка при публикации поста ID {post_id} в канал {target_telegram_channel_id}: {e}")
        post.status = "error" # Общий статус для необработанных ошибок
        await session.commit()
        await admin_bot.send_message(
            chat_id=config.ADMIN_CHAT_ID,
            text=f"❌ **Неизвестная ошибка при публикации поста ID {post.id}** в канал `{target_telegram_channel_id}`:\n`{e}`\n"
                 f"Пост помечен как 'error'.",
            parse_mode="Markdown"
        )
    finally:
        # Удаляем медиафайл после попытки публикации, независимо от успеха
        if media_paths and media_paths[0] and os.path.exists(media_paths[0]):
            os.remove(media_paths[0])
            logger.info(f"Медиафайл {media_paths[0]} удален после публикации.")


async def send_post_to_admin_panel(post: Post, city_title: str, admin_bot_instance: Bot):
    """
    Отправляет пост на ручную модерацию в админ-чат.
    """
    caption_text = (
        f"**Новый пост для модерации в канале '{city_title}':**\n\n"
        f"ID поста: `{post.id}`\n"
        f"Исходный текст:\n```\n{post.original_text[:1000]}\n```\n\n"
        f"Обработанный текст (для публикации):\n```\n{post.processed_text[:1000]}\n```\n\n"
        f"Выберите действие:"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"publish_{post.id}"),
            InlineKeyboardButton(text="✍️ Редактировать", callback_data=f"edit_{post.id}"),
            InlineKeyboardButton(text="♻️ Переформулировать", callback_data=f"rephrase_{post.id}"),
            InlineKeyboardButton(text="❌ Удалить", callback_data=f"delete_{post.id}")
        ]
    ])

    try:
        if post.image_url and os.path.exists(post.image_url):
            # Отправка фото или видео
            if post.image_url.lower().endswith(('.png', '.jpg', '.jpeg')):
                await admin_bot_instance.send_photo(
                    chat_id=config.ADMIN_CHAT_ID,
                    photo=types.FSInputFile(post.image_url),
                    caption=caption_text,
                    parse_mode="Markdown",
                    reply_markup=keyboard
                )
                logger.info(f"Фото для поста {post.id} отправлено в админ-чат (первое из альбома).")
            elif post.image_url.lower().endswith(('.mp4', '.mov', '.avi')):
                await admin_bot_instance.send_video(
                    chat_id=config.ADMIN_CHAT_ID,
                    video=types.FSInputFile(post.image_url),
                    caption=caption_text,
                    parse_mode="Markdown",
                    reply_markup=keyboard
                )
                logger.info(f"Видео для поста {post.id} отправлено в админ-чат.")
            else:
                logger.warning(f"Неподдерживаемый тип медиафайла для поста {post.id} в админ-панель: {post.image_url}. Отправляем только текст.")
                await admin_bot_instance.send_message(
                    chat_id=config.ADMIN_CHAT_ID,
                    text=caption_text,
                    parse_mode="Markdown",
                    reply_markup=keyboard
                )
        else:
            await admin_bot_instance.send_message(
                chat_id=config.ADMIN_CHAT_ID,
                text=caption_text,
                parse_mode="Markdown",
                reply_markup=keyboard
            )
        logger.info(f"Пост ID {post.id} успешно отправлен в админ-панель для модерации.")
    except Exception as e:
        logger.error(f"Ошибка при отправке поста ID {post.id} в админ-панель: {e}")

async def start_news_bot():
    """Запускает основного Telegram бота."""
    logger.info("Запуск основного Telegram бота...")
    # Пропускаем все накопившиеся обновления
    await dp.start_polling(bot)
    logger.info("Основной Telegram бот остановлен.")

if __name__ == "__main__":
    # Этот блок не будет запускаться напрямую, так как бот запускается через main.py
    # Но для отладки можно временно запустить
    async def debug_main():
        # Для отладки здесь нужен фиктивный parser_instance или реальный, если Telethon запущен
        class MockTelethonClient:
            def __init__(self):
                self._connected = False
            async def start(self): self._connected = True
            async def disconnect(self): self._connected = False
            def is_connected(self): return self._connected
            async def get_entity(self, identifier):
                if identifier == "@test_channel" or identifier == "-1001234567890":
                    class MockChannel:
                        id = 1234567890 # Telethon возвращает без -100 для публичных
                        title = "Тестовый Канал"
                    return MockChannel()
                raise UsernameNotOccupiedError("Test error")

        class MockTelegramParser:
            def __init__(self):
                self.client = MockTelethonClient()
            def add_message_handler(self, handler_func): pass
            async def start(self): await self.client.start()
            async def stop(self): await self.client.disconnect()

        mock_parser = MockTelegramParser()
        await mock_parser.start() # Убедимся, что клиент подключен для resolve_channel_id
        await set_telegram_parser_instance_for_news_bot(mock_parser)

        # Инициализация БД для отладки
        from db.database import init_db
        await init_db()

        # Добавление тестового города и донора для отладки
        async for session in get_session():
            test_city = await session.execute(select(City).where(City.telegram_id == -1002705093365))
            test_city = test_city.scalar_one_or_none()
            if not test_city:
                test_city = City(telegram_id=-1002705093365, title="Тестовый Город", auto_mode=True)
                session.add(test_city)
                await session.commit()
                logger.info("Добавлен тестовый город для отладки.")
            
            test_donor = await session.execute(select(DonorChannel).where(DonorChannel.telegram_id == 1481151436))
            test_donor = test_donor.scalar_one_or_none()
            if not test_donor:
                test_donor = DonorChannel(telegram_id=1481151436, title="Тестовый Донор", city_id=test_city.id)
                session.add(test_donor)
                await session.commit()
                logger.info("Добавлен тестовый донор для отладки.")

        await start_news_bot()
    asyncio.run(debug_main())
