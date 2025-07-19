# bots/news_bot.py
import asyncio
import os
import re
from aiogram import Bot, Dispatcher, types
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from loguru import logger
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from config import config
from db.database import get_session
from db.models import City, DonorChannel, Post, Admin

# Инициализация бота
bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()

# Глобальная переменная для хранения экземпляра TelethonParser
telegram_parser_instance = None

async def set_telegram_parser_instance_for_news_bot(parser_instance):
    """Устанавливает экземпляр TelethonParser для использования в news_bot."""
    global telegram_parser_instance
    telegram_parser_instance = parser_instance
    logger.info("Экземпляр TelethonParser установлен в news_bot.")

def remove_advertisement_links(text: str) -> str:
    """Удаляет потенциальные рекламные ссылки и @упоминания из текста."""
    # Удаляем URL-ссылки (http/https), t.me, vk.com, instagram.com
    cleaned_text = re.sub(r'https?://\S+|t\.me/\S+|vk\.com/\S+|instagram\.com/\S+', '', text, flags=re.IGNORECASE)
    # Удаляем @username, которые могут быть ссылками на каналы/пользователей
    cleaned_text = re.sub(r'@\w+', '', cleaned_text)
    # Удаляем хештеги
    cleaned_text = re.sub(r'#\w+', '', cleaned_text)
    return cleaned_text.strip()

def remove_call_to_action_paragraphs(text: str) -> str:
    """
    Удаляет последние абзацы текста, если они содержат призывы к действию
    или типичные рекламные фразы. Удаляет весь контент, начиная с первого
    найденного абзаца-призыва до конца сообщения.
    """
    paragraphs = text.split('\n\n') # Разбиваем текст на абзацы по двойному переносу строки
    
    # Ключевые слова и фразы для определения призыва к действию (регистронезависимо)
    call_to_action_keywords = [
        r'подпишись', r'подписывайтесь', r'переходи', r'переходите',
        r'наш канал', r'на нашем канале', r'ссылка в профиле', r'читайте также',
        r'больше новостей', r'все подробности', r'узнать подробнее',
        r'присоединяйтесь', r'вступайте', r'наш сайт', r'наша группа',
        r'активная ссылка', r'в шапке профиля', r'в описании канала',
        r'для связи', r'по всем вопросам', r'пишите нам', r'звоните',
        r'успей', r'скидки', r'акция', r'предложение', r'специальное предложение',
        r'перейти по ссылке', r'жми', r'кликни', r'подробнее здесь',
        r'источник', r'первоисточник', r'канал', r'группа', r'паблик',
        r'наш телеграм', r'наш тг', r'наш тг-канал', r'наш телеграм-канал',
        r'подробнее в нашем канале', r'подробнее по ссылке',
        r'все самое интересное', r'не пропусти', r'будь в курсе', r'узнай первым',
        r'реклама', r'на правах рекламы', r'по вопросам сотрудничества'
    ]
    
    # Компилируем regex для быстрого поиска
    regex_pattern = r'\b(?:' + '|'.join(call_to_action_keywords) + r')\b'
    call_to_action_regex = re.compile(regex_pattern, re.IGNORECASE)

    # Ищем первый абзац с конца, который является призывом к действию
    cut_index = len(paragraphs)
    for i in range(len(paragraphs) - 1, -1, -1):
        paragraph = paragraphs[i].strip()
        
        # Если абзац содержит ключевые слова призыва к действию
        # ИЛИ короткий и содержит ссылки/хештеги (часто признак CTA)
        if (call_to_action_regex.search(paragraph) or 
            (len(paragraph.split()) < 15 and re.search(r'https?://\S+|t\.me/\S+|vk\.com/\S+|instagram\.com/\S+|@\w+|#\w+', paragraph, re.IGNORECASE))):
            
            # Проверяем, не является ли этот абзац частью основной новости
            # путем поиска "безопасных" ключевых слов, которые обычно не встречаются в CTA
            safe_keywords = [r'\d{2}\.\d{2}\.\d{4}', r'\d{1,2}:\d{2}', r'\bулица\b', r'\bрайон\b', r'\bгород\b', r'\bместо\b', r'\bпроисшествие\b', r'\bсобытие\b']
            safe_regex = re.compile(r'\b(?:' + '|'.join(safe_keywords) + r')\b', re.IGNORECASE)

            if not safe_regex.search(paragraph):
                cut_index = i # Нашли точку обрезки
                logger.info(f"Обнаружен абзац-призыв к действию: '{paragraph[:50]}...'")
            else:
                # Если абзац содержит безопасные слова, это, вероятно, не CTA,
                # и мы не должны удалять его или предшествующие абзацы.
                break 
        else:
            # Если текущий абзац не является призывом к действию, то и предыдущие абзацы,
            # скорее всего, тоже не являются, так как призывы обычно идут в конце.
            break
            
    # Обрезаем список абзацев до найденного индекса
    cleaned_paragraphs = paragraphs[:cut_index]
            
    return '\n\n'.join(cleaned_paragraphs).strip()

def count_links(text: str) -> int:
    """Подсчитывает количество URL-ссылок в тексте."""
    # Более широкий regex для ссылок, включая t.me, vk.com, instagram.com и общие URL
    url_pattern = r'https?://\S+|t\.me/\S+|vk\.com/\S+|instagram\.com/\S+|@\w+'
    return len(re.findall(url_pattern, text, re.IGNORECASE))

async def process_new_donor_message(event):
    """
    Обрабатывает новые сообщения от донорских каналов.
    Проверяет на дубликаты, рекламный контент и переформулирует текст.
    """
    from core.deduplicator import deduplicator
    from core.gigachat import gigachat_api
    from bots.admin_bot import admin_bot

    channel_id = event.chat_id
    message_id = event.id
    original_text = event.text
    image_url = None
    if event.photo:
        image_url = event.photo.sizes[-1].url
    elif event.video:
        image_url = event.video.thumbs[-1].url if event.video.thumbs else None

    logger.info(f"Начало обработки нового сообщения от донора {channel_id}, ID: {message_id}")

    async for session in get_session():
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
                processed_text=original_text,
                image_url=image_url,
                is_duplicate=True,
                status="rejected",
                city_id=city.id,
                donor_channel_id=donor_channel.id
            )
            session.add(new_post)
            await session.commit()
            logger.info(f"Сообщение от донора {channel_id}, ID: {message_id} является дубликатом. Пропускаем.")
            return

        # 2. Проверка на количество ссылок
        link_count = count_links(original_text)
        if link_count > config.MAX_LINKS_IN_POST:
            new_post = Post(
                original_text=original_text,
                processed_text=original_text,
                image_url=image_url,
                is_duplicate=False,
                status="rejected", # Отклоняем из-за большого количества ссылок
                city_id=city.id,
                donor_channel_id=donor_channel.id
            )
            session.add(new_post)
            await session.commit()
            logger.info(f"Сообщение '{original_text[:50]}...' содержит {link_count} ссылок, что превышает лимит {config.MAX_LINKS_IN_POST}. Отклонено.")
            await admin_bot.send_message(
                chat_id=config.ADMIN_CHAT_ID,
                text=f"🚫 **Пост отклонен из-за большого количества ссылок** в канале '{city.title}':\n\n"
                     f"ID поста: `{new_post.id}`\n"
                     f"Количество ссылок: {link_count} (лимит: {config.MAX_LINKS_IN_POST})\n"
                     f"Текст:\n```\n{original_text[:1000]}\n```",
                parse_mode="Markdown"
            )
            return

        # 3. Проверка на рекламный контент
        is_advertisement = await gigachat_api.check_advertisement(original_text)
        if is_advertisement:
            new_post = Post(
                original_text=original_text,
                processed_text=original_text,
                image_url=image_url,
                is_duplicate=False,
                status="pending",
                city_id=city.id,
                donor_channel_id=donor_channel.id
            )
            session.add(new_post)
            await session.commit()
            logger.info(f"Сообщение '{original_text[:50]}...' является рекламным. Отправляем на ручную модерацию.")
            await send_post_to_admin_panel(new_post, city.title, admin_bot)
            return

        # 4. Удаление рекламных ссылок
        processed_text = remove_advertisement_links(original_text)
        if not processed_text.strip():
            logger.warning(f"Текст поста (ID: {message_id}) стал пустым после удаления рекламных ссылок. Пропускаем.")
            return

        # 5. Удаление призывов к действию в последних абзацах
        processed_text = remove_call_to_action_paragraphs(processed_text)
        if not processed_text.strip():
            logger.warning(f"Текст поста (ID: {message_id}) стал пустым после удаления призывов к действию. Пропускаем.")
            return

        # 6. Переформулирование текста (если не содержит ключевых слов)
        keywords = ["бпла", "ракетная опасность", "обстрел", "взрыв", "атака"]
        if any(keyword in processed_text.lower() for keyword in keywords):
            logger.info(f"Сообщение '{processed_text[:50]}...' содержит ключевые слова ({' или '.join(keywords)}). Переформулирование пропущено.")
            final_text = processed_text
        else:
            final_text = await gigachat_api.rephrase_text(processed_text)
            if not final_text:
                logger.warning(f"Не удалось переформулировать текст для '{processed_text[:50]}...'. Используем оригинал.")
                final_text = processed_text

        # 7. Сохранение поста в БД
        new_post = Post(
            original_text=original_text,
            processed_text=final_text,
            image_url=image_url,
            is_duplicate=False,
            status="pending",
            city_id=city.id,
            donor_channel_id=donor_channel.id
        )
        session.add(new_post)
        await session.commit()
        logger.info(f"Новый пост (ID: {new_post.id}) сохранен в БД со статусом 'pending'.")

        # 8. Публикация или отправка на модерацию
        if city.auto_mode:
            await publish_post(new_post.id, city.telegram_id, session, [image_url] if image_url else [])
        else:
            await send_post_to_admin_panel(new_post, city.title, admin_bot)

async def publish_post(post_id: int, target_telegram_channel_id: int, session: AsyncSession, media_paths: list = None):
    """
    Публикует пост в указанный Telegram канал.
    Обновляет статус поста в БД.
    """
    from bots.admin_bot import admin_bot

    post = await session.get(Post, post_id)
    if not post:
        logger.error(f"Пост ID {post_id} не найден для публикации.")
        return

    try:
        if media_paths and media_paths[0]:
            media_file_path = media_paths[0]
            if os.path.exists(media_file_path):
                if post.processed_text: # Убедимся, что текст не пустой
                    if media_file_path.lower().endswith(('.png', '.jpg', '.jpeg')):
                        await bot.send_photo(chat_id=target_telegram_channel_id, photo=types.FSInputFile(media_file_path), caption=post.processed_text, parse_mode="Markdown")
                    elif media_file_path.lower().endswith(('.mp4', '.mov', '.avi')):
                        await bot.send_video(chat_id=target_telegram_channel_id, video=types.FSInputFile(media_file_path), caption=post.processed_text, parse_mode="Markdown")
                    else:
                        logger.warning(f"Неподдерживаемый тип медиафайла для поста {post_id}: {media_file_path}. Отправляем только текст.")
                        await bot.send_message(chat_id=target_telegram_channel_id, text=post.processed_text, parse_mode="Markdown")
                else: # Если текст пустой, отправляем только медиа
                    if media_file_path.lower().endswith(('.png', '.jpg', '.jpeg')):
                        await bot.send_photo(chat_id=target_telegram_channel_id, photo=types.FSInputFile(media_file_path))
                    elif media_file_path.lower().endswith(('.mp4', '.mov', '.avi')):
                        await bot.send_video(chat_id=target_telegram_channel_id, video=types.FSInputFile(media_file_path))
                    logger.warning(f"Текст поста {post_id} пустой. Отправлен только медиафайл.")
            else:
                logger.warning(f"Медиафайл не найден по пути {media_file_path} для поста {post_id}. Отправляем только текст.")
                if post.processed_text:
                    await bot.send_message(chat_id=target_telegram_channel_id, text=post.processed_text, parse_mode="Markdown")
                else:
                    logger.warning(f"Пост {post_id} не имеет ни медиа, ни текста. Пропускаем публикацию.")
                    return # Ничего не отправляем
        else:
            logger.info(f"Медиафайлы для поста {post_id} отсутствуют. Отправляем только текст.")
            if post.processed_text:
                await bot.send_message(chat_id=target_telegram_channel_id, text=post.processed_text, parse_mode="Markdown")
            else:
                logger.warning(f"Пост {post_id} не имеет ни медиа, ни текста. Пропускаем публикацию.")
                return # Ничего не отправляем
        
        post.status = "published"
        post.published_at = func.now()
        await session.commit()
        logger.info(f"Пост ID {post_id} успешно опубликован в канал {target_telegram_channel_id}.")

    except TelegramBadRequest as e:
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
        post.status = "error"
        await session.commit()
        await admin_bot.send_message(
            chat_id=config.ADMIN_CHAT_ID,
            text=f"❌ **Неизвестная ошибка при публикации поста ID {post.id}** в канал `{target_telegram_channel_id}`:\n`{e}`\n"
                 f"Пост помечен как 'error'.",
            parse_mode="Markdown"
        )
    finally:
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
            if post.processed_text:
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
            else: # Если текст пустой, отправляем только медиа
                if post.image_url.lower().endswith(('.png', '.jpg', '.jpeg')):
                    await admin_bot_instance.send_photo(
                        chat_id=config.ADMIN_CHAT_ID,
                        photo=types.FSInputFile(post.image_url),
                        reply_markup=keyboard
                    )
                elif post.image_url.lower().endswith(('.mp4', '.mov', '.avi')):
                    await admin_bot_instance.send_video(
                        chat_id=config.ADMIN_CHAT_ID,
                        video=types.FSInputFile(post.image_url),
                        reply_markup=keyboard
                    )
                logger.warning(f"Текст поста {post.id} пустой для админ-панели. Отправлен только медиафайл.")
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
    # Удаляем вебхук перед запуском long polling
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Вебхук основного бота успешно удален.")
    except Exception as e:
        logger.warning(f"Не удалось удалить вебхук основного бота: {e}")
    await dp.start_polling(bot)
    logger.info("Основной Telegram бот остановлен.")

if __name__ == "__main__":
    async def debug_main():
        class MockTelethonClient:
            def __init__(self):
                self._connected = False
            async def start(self): self._connected = True
            async def disconnect(self): self._connected = False
            def is_connected(self): return self._connected
            async def get_entity(self, identifier):
                if identifier == "@test_channel" or identifier == "-1001234567890":
                    class MockChannel:
                        id = 1234567890
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
        await mock_parser.start()
        await set_telegram_parser_instance_for_news_bot(mock_parser)

        from db.database import init_db
        await init_db()

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
