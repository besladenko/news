# bots/news_bot.py
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from loguru import logger

from config import config
from db.database import get_session
from db.models import Post, City, DonorChannel # <-- УДАЛЕНО: ChannelSetting
from core.gigachat import gigachat_api
from core.deduplicator import deduplicator
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
import asyncio
import datetime
import re
import os

# Инициализация бота
bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()

# Состояния для FSM (Finite State Machine)
class NewsBotStates(StatesGroup):
    # Здесь можно определить состояния, если основной бот будет иметь диалоги с пользователями
    # Например, для подписки на новости или настройки уведомлений
    pass

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    """Обработчик команды /start."""
    await message.answer(
        "Привет! Я бот городской новостной сети. Я буду автоматически публиковать новости в городские каналы."
    )
    logger.info(f"Получена команда /start от пользователя {message.from_user.id}")

def _normalize_text(text: str) -> str:
    """
    Нормализует текст: заменяет различные пробелы и переносы строк на стандартные,
    чтобы обеспечить консистентность при сравнении и удалении масок.
    """
    if not text:
        return ""
    # Заменяем все виды пробелов (включая неразрывные) на обычные пробелы
    normalized_text = re.sub(r'\s+', ' ', text).strip()
    # Заменяем все виды переносов строк на '\n'
    normalized_text = normalized_text.replace('\r\n', '\n').replace('\r', '\n')
    # Удаляем множественные переносы строк, оставляя только один
    normalized_text = re.sub(r'\n+', '\n', normalized_text)
    return normalized_text.strip()

async def _remove_promotional_links(text: str, literal_mask: str = None) -> str:
    """
    Удаляет из текста ссылки типа "Подписаться" и схожие рекламные подписи,
    особенно в конце поста.
    :param text: Исходный текст поста.
    :param literal_mask: Буквальная строка маски, которую нужно удалить из текста.
    """
    if not text:
        return ""

    original_text_normalized = _normalize_text(text) # Нормализуем текст поста
    
    # 1. Удаление буквальной маски, если она задана
    if literal_mask:
        normalized_literal_mask = _normalize_text(literal_mask) # Нормализуем маску
        # Используем re.escape, чтобы специальные символы в маске обрабатывались как буквальные
        # и re.DOTALL для обработки маски, которая может содержать несколько строк.
        escaped_mask = re.escape(normalized_literal_mask)
        
        # Используем re.sub с флагом re.DOTALL, чтобы '.' соответствовал переносам строк
        # и re.IGNORECASE для игнорирования регистра.
        # Добавляем \s* вокруг, чтобы учесть возможные пробелы/переносы строк вокруг маски
        original_text_normalized = re.sub(rf'\s*{escaped_mask}\s*', '', original_text_normalized, flags=re.IGNORECASE | re.DOTALL)
        logger.info(f"Буквальная маска '{literal_mask[:50]}...' удалена из текста (после нормализации).")


    # 2. Удаление Telegram-ссылок в скобках (https://t.me/...)
    # Улучшено для обработки t.me/+ и других символов в пути ссылки
    original_text_normalized = re.sub(r'\s*\([^)]*https?://t\.me/[^\s)]*\)', '', original_text_normalized, flags=re.IGNORECASE)

    # Улучшенные паттерны для удаления строк, которые являются рекламными подписями или ссылками.
    # Используем re.fullmatch для точного совпадения всей строки.
    promotional_line_patterns = [
        # Паттерн для Markdown ссылок, например [Текст](URL)
        r'^\s*[\U0001F000-\U0001FFFF\U00002000-\U00002BFF\W_]*\[.*?\]\s*\(https?://[^\s)]+\)[\U0001F000-\U0001FFFF\U00002000-\U00002BFF\W_]*\s*$',
        # Линии, которые являются только URL-адресами или содержат URL с минимальным окружающим текстом/символами
        r'^\s*[\W_]*https?://[^\s)]+[\W_]*\s*$',
        # Общие рекламные фразы, с ссылкой или без, с учетом ведущих/завершающих символов/пробелов
        # Добавлены новые ключевые слова для лучшего распознавания
        r'^\s*[\U0001F000-\U0001FFFF\U00002000-\U00002BFF\W_]*\b(?:подписаться|наш канал|прислать новость|новости|канал|наш|подпишись|вступай|переходи|наш чат|наша группа|источник|подробнее|смотрите также|наш сайт|наш телеграм|наш telegram|наш тг|наш tg|наш паблик|проголосовать|голос|вконтакте|наш вк|наш youtube|наш инстаграм|наш facebook|наш twitter|наш дзен|наш рутуб|наш rutube|наш vk)\b.*?(?:https?://[^\s)]+)?[\W_]*\s*$',
        # Линии, которые очень короткие и содержат ссылку, например, "Источник: ссылка"
        r'^\s*(?:источник|source|подробнее|details|link|ссылка|читать|read|join|присоединяйтесь|перейти|go)\s*[\W_]*https?://[^\s)]+[\W_]*\s*$',
        # Линии, которые являются просто короткими призывами к действию или ссылками на социальные сети
        r'^\s*[\U0001F000-\U0001FFFF\U00002000-\U00002BFF\W_]*(?:@[\w_]+|t\.me/[\w_]+|vk\.com/[\w_]+|youtube\.com/[\w_]+|instagram\.com/[\w_]+|facebook\.com/[\w_]+)[\U0001F000-\U0001FFFF\U00002000-\U00002BFF\W_]*\s*$'
    ]

    lines = original_text_normalized.split('\n') # Работаем с нормализованным текстом
    cleaned_lines = []
    
    # Идем с конца, удаляя рекламные строки.
    # Это позволяет удалить блоки рекламных строк в конце поста.
    i = len(lines) - 1
    while i >= 0:
        line = lines[i].strip()
        is_promotional = False
        for pattern in promotional_line_patterns:
            # Используем re.fullmatch для проверки, является ли вся строка рекламной
            if re.fullmatch(pattern, line, flags=re.IGNORECASE | re.DOTALL):
                is_promotional = True
                break
        
        if is_promotional:
            i -= 1 # Если строка рекламная, удаляем ее и проверяем предыдущую
        else:
            # Если строка не рекламная, то все предыдущие строки оставляем
            cleaned_lines = lines[:i+1]
            break
    else: # Если весь текст состоял из рекламных строк
        cleaned_lines = []

    return "\n".join(cleaned_lines).strip()


async def process_new_donor_message(
    channel_id: int,
    message_id: int,
    text: str,
    media_paths: list[str],
    source_link: str
):
    """
    Обрабатывает новое сообщение, спарсенное из канала-донора.
    Эта функция будет вызываться из `core/parser.py`.
    """
    logger.info(f"Начало обработки нового сообщения от донора {channel_id}, ID: {message_id}")

    async for session in get_session(): # <-- Используем get_session напрямую
        # --- Начало костыля для обработки ID канала ---
        # Telethon часто возвращает ID без префикса -100.
        # Проверяем оба варианта: raw ID и ID с префиксом -100.
        possible_donor_ids = [channel_id]
        if channel_id > 0: # Если ID положительный, добавляем вариант с -100
            possible_donor_ids.append(int(f"-100{channel_id}"))
        elif str(channel_id).startswith('-100'): # Если уже с -100, добавляем raw ID
            try:
                possible_donor_ids.append(int(str(channel_id)[4:]))
            except ValueError:
                pass # Если не удалось преобразовать, игнорируем

        # Находим донорский канал по любому из возможных ID
        stmt_donor = select(DonorChannel).where(DonorChannel.telegram_id.in_(possible_donor_ids))
        result_donor = await session.execute(stmt_donor)
        donor_channel = result_donor.scalar_one_or_none()
        # --- Конец костыля ---

        if not donor_channel:
            logger.warning(f"Сообщение от неизвестного донора (ID: {channel_id}). Пропускаем.")
            return

        stmt_city = select(City).where(City.id == donor_channel.city_id)
        result_city = await session.execute(stmt_city)
        city = result_city.scalar_one_or_none()

        if not city:
            logger.error(f"Городской канал для донора {donor_channel.title} (ID: {donor_channel.city_id}) не найден. Пропускаем.")
            return

        # 1. Проверка на дубликат
        is_duplicate, reason = await deduplicator.check_for_duplicates(session, text, city.id)

        if is_duplicate:
            logger.info(f"Сообщение '{text[:50]}...' является дубликатом. Причина: {reason}. Не публикуем.")
            new_post = Post(
                original_text=text,
                image_url=media_paths[0] if media_paths else None, # Сохраняем только первый путь для БД
                source_link=source_link,
                is_duplicate=True,
                status="rejected_duplicate",
                donor_channel_id=donor_channel.id,
                city_id=city.id,
                original_message_id=message_id
            )
            session.add(new_post)
            await session.commit()
            return

        # 2. Проверка на рекламный характер
        is_advertisement = await gigachat_api.check_advertisement(text)
        if is_advertisement:
            logger.info(f"Сообщение '{text[:50]}...' является рекламным. Отправляем на ручную модерацию.")
            new_post = Post(
                original_text=text,
                processed_text=text, # Для рекламных постов processed_text равен original_text
                image_url=media_paths[0] if media_paths else None, # Сохраняем только первый путь для БД
                source_link=source_link,
                is_advertisement=True,
                is_duplicate=False,
                status="pending",
                donor_channel_id=donor_channel.id,
                city_id=city.id,
                original_message_id=message_id
            )
            session.add(new_post)
            await session.commit()
            await send_post_to_admin_panel(new_post.id, city.telegram_id, session, media_paths)
            return

        # 3. Проверка на ключевые слова для пропуска переформулирования
        skip_rephrasing_keywords = ["бпла", "ракетная опасность"]
        should_skip_rephrasing = False
        for keyword in text.lower().split(): # Разделяем текст на слова для более точного поиска
            if keyword in skip_rephrasing_keywords:
                should_skip_rephrasing = True
                break
        
        if should_skip_rephrasing:
            processed_text = text # Используем оригинальный текст
            logger.info(f"Сообщение '{text[:50]}...' содержит ключевые слова ({' или '.join(skip_rephrasing_keywords)}). Переформулирование пропущено.")
        else:
            # 4. Переформулирование текста
            processed_text = await gigachat_api.rephrase_text(text)
            if not processed_text:
                logger.warning(f"Не удалось переформулировать текст для '{text[:50]}...'. Используем оригинал.")
                processed_text = text

        # 5. Удаление рекламных ссылок и подписей (применяется всегда)
        # Передаем literal_mask из donor_channel.mask_pattern
        processed_text = await _remove_promotional_links(processed_text, donor_channel.mask_pattern)
        if not processed_text.strip(): # Если после очистки текст стал пустым
            logger.warning(f"Текст поста (ID: {message_id}) стал пустым после удаления рекламных ссылок. Пропускаем.")
            new_post = Post(
                original_text=text,
                image_url=media_paths[0] if media_paths else None,
                source_link=source_link,
                is_advertisement=False,
                is_duplicate=False,
                status="rejected_empty_after_clean",
                donor_channel_id=donor_channel.id,
                city_id=city.id,
                original_message_id=message_id
            )
            session.add(new_post)
            await session.commit()
            return


        # 6. Сохранение поста в БД
        new_post = Post(
            original_text=text,
            processed_text=processed_text,
            image_url=media_paths[0] if media_paths else None, # Сохраняем только первый путь для БД
            source_link=source_link,
            is_advertisement=False,
            is_duplicate=False,
            status="pending",
            donor_channel_id=donor_channel.id,
            city_id=city.id,
            original_message_id=message_id
        )
        session.add(new_post)
        await session.commit()
        logger.info(f"Новый пост (ID: {new_post.id}) сохранен в БД со статусом 'pending'.")

        # 7. Публикация или отправка на модерацию
        if city.auto_mode:
            await publish_post(new_post.id, city.telegram_id, session, media_paths)
        else:
            await send_post_to_admin_panel(new_post.id, city.telegram_id, session, media_paths)

async def publish_post(post_id: int, target_telegram_channel_id: int, session: AsyncSession, media_paths: list[str]):
    """
    Публикует пост в целевой Telegram канал.
    :param post_id: ID поста в БД.
    :param target_telegram_channel_id: Telegram ID канала, куда нужно отправить пост.
    :param session: Сессия базы данных.
    :param media_paths: Список путей к медиафайлам для публикации.
    """
    stmt = select(Post).where(Post.id == post_id)
    result = await session.execute(stmt)
    post = result.scalar_one_or_none()

    if not post:
        logger.error(f"Пост с ID {post_id} не найден для публикации.")
        return

    try:
        # Формируем текст для публикации (без ссылки на источник)
        message_to_send = post.processed_text

        # Отправка медиафайлов (если есть)
        if media_paths:
            # Отправляем первое медиа с подписью
            first_media_path = media_paths[0]
            if os.path.exists(first_media_path):
                file_to_send = FSInputFile(first_media_path)
                file_extension = os.path.splitext(first_media_path)[1].lower()

                if file_extension in ['.jpg', '.jpeg', '.png', '.gif']:
                    await bot.send_photo(chat_id=target_telegram_channel_id, photo=file_to_send, caption=message_to_send)
                    logger.info(f"Фото для поста {post_id} успешно отправлено (первое из альбома).")
                elif file_extension in ['.mp4', '.mov', '.avi', '.mkv', '.webm']:
                    await bot.send_video(chat_id=target_telegram_channel_id, video=file_to_send, caption=message_to_send)
                    logger.info(f"Видео для поста {post_id} успешно отправлено (первое из альбома).")
                else:
                    logger.warning(f"Неизвестный тип первого медиафайла '{file_extension}' для поста {post.id}. Отправляем только текст.")
                    await bot.send_message(chat_id=target_telegram_channel_id, text=message_to_send)
            else:
                logger.warning(f"Первый медиафайл '{first_media_path}' для поста {post.id} не найден. Отправляем только текст.")
                await bot.send_message(chat_id=target_telegram_channel_id, text=message_to_send)

            # Отправляем остальные медиа без подписи
            for i, media_path in enumerate(media_paths[1:]):
                if os.path.exists(media_path):
                    file_to_send = FSInputFile(media_path)
                    file_extension = os.path.splitext(media_path)[1].lower()
                    try:
                        if file_extension in ['.jpg', '.jpeg', '.png', '.gif']:
                            await bot.send_photo(chat_id=target_telegram_channel_id, photo=file_to_send)
                            logger.info(f"Дополнительное фото для поста {post_id} успешно отправлено.")
                        elif file_extension in ['.mp4', '.mov', '.avi', '.mkv', '.webm']:
                            await bot.send_video(chat_id=target_telegram_channel_id, video=file_to_send)
                            logger.info(f"Дополнительное видео для поста {post_id} успешно отправлено.")
                        else:
                            logger.warning(f"Неизвестный тип дополнительного медиафайла '{file_extension}' для поста {post.id}. Пропускаем.")
                    except Exception as e:
                        logger.warning(f"Ошибка при отправке дополнительного медиафайла {media_path} для поста {post.id}: {e}")
                else:
                    logger.warning(f"Дополнительный медиафайл '{media_path}' для поста {post.id} не найден. Пропускаем.")
        else:
            # Если медиафайлов нет, отправляем только текст
            logger.info(f"Медиафайлы для поста {post.id} отсутствуют. Отправляем только текст.")
            await bot.send_message(chat_id=target_telegram_channel_id, text=message_to_send)

        post.status = "published"
        post.published_at = datetime.datetime.now()
        await session.commit()
        logger.info(f"Пост ID {post.id} успешно опубликован в канал {target_telegram_channel_id}.")
    except Exception as e:
        logger.error(f"Ошибка при публикации поста ID {post.id} в канал {target_telegram_channel_id}: {e}")
        post.status = "publish_error"
        await session.commit()
    finally:
        # Очистка всех медиафайлов после отправки
        for media_path in media_paths:
            if os.path.exists(media_path):
                try:
                    os.remove(media_path)
                    logger.info(f"Медиафайл {media_path} удален после публикации.")
                except Exception as e:
                    logger.warning(f"Не удалось удалить медиафайл {media_path}: {e}")


async def send_post_to_admin_panel(post_id: int, target_telegram_channel_id: int, session: AsyncSession, media_paths: list[str]):
    """
    Отправляет пост в админ-панель для ручной модерации.
    Админ-бот должен быть настроен на получение этих сообщений.
    """
    stmt = select(Post).where(Post.id == post_id)
    result = await session.execute(stmt)
    post = result.scalar_one_or_none()

    if not post:
        logger.error(f"Пост с ID {post.id} не найден для отправки в админ-панель.")
        return

    # Импортируем admin_bot здесь, чтобы избежать циклического импорта
    from bots.admin_bot import admin_bot

    # Формируем сообщение для админ-панели (без ссылки на источник)
    message_for_admin = (
        f"🚨 *Новый пост для модерации* (ID: `{post.id}`)\n"
        f"Канал назначения: `{target_telegram_channel_id}`\n"
        f"Статус: {'Реклама' if post.is_advertisement else 'Ожидает'}\n\n"
        f"Оригинал:\n```\n{post.original_text[:1000]}\n```\n\n" # Форматирование в code block
        f"Предложено:\n```\n{post.processed_text[:1000]}\n```\n" # Форматирование в code block
    )
    if post.is_advertisement:
        message_for_admin += "\n_GigaChat пометил как рекламное._"

    # Создаем инлайн-кнопки
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"publish_{post.id}"),
            InlineKeyboardButton(text="✍️ Редактировать", callback_data=f"edit_{post.id}"), # НОВОЕ: Кнопка редактирования
            InlineKeyboardButton(text="♻️ Переформулировать", callback_data=f"rephrase_{post.id}"),
            InlineKeyboardButton(text="❌ Удалить", callback_data=f"delete_{post.id}")
        ]
    ])

    try:
        # Отправка медиафайлов в админ-чат (если есть)
        if media_paths:
            # Отправляем первое медиа с подписью
            first_media_path = media_paths[0]
            if os.path.exists(first_media_path):
                file_to_send = FSInputFile(first_media_path)
                file_extension = os.path.splitext(first_media_path)[1].lower()

                if file_extension in ['.jpg', '.jpeg', '.png', '.gif']:
                    await admin_bot.send_photo(chat_id=config.ADMIN_CHAT_ID, photo=file_to_send, caption=message_for_admin, parse_mode="Markdown")
                    logger.info(f"Фото для поста {post.id} отправлено в админ-чат (первое из альбома).")
                elif file_extension in ['.mp4', '.mov', '.avi', '.mkv', '.webm']:
                    await admin_bot.send_video(chat_id=config.ADMIN_CHAT_ID, video=file_to_send, caption=message_for_admin, parse_mode="Markdown")
                    logger.info(f"Видео для поста {post.id} отправлено в админ-чат (первое из альбома).")
                else:
                    logger.warning(f"Неизвестный тип первого медиафайла '{file_extension}' для поста {post.id}. Отправляем только текст в админ-чат.")
                    await admin_bot.send_message(chat_id=config.ADMIN_CHAT_ID, text=message_for_admin, reply_markup=keyboard, parse_mode="Markdown")
            else:
                logger.warning(f"Первый медиафайл '{first_media_path}' для поста {post.id} не найден. Отправляем только текст в админ-чат.")
                await admin_bot.send_message(chat_id=config.ADMIN_CHAT_ID, text=message_for_admin, reply_markup=keyboard, parse_mode="Markdown")

            # Отправляем остальные медиа без подписи
            for i, media_path in enumerate(media_paths[1:]):
                if os.path.exists(media_path):
                    file_to_send = FSInputFile(media_path)
                    file_extension = os.path.splitext(media_path)[1].lower()
                    try:
                        if file_extension in ['.jpg', '.jpeg', '.png', '.gif']:
                            await admin_bot.send_photo(chat_id=config.ADMIN_CHAT_ID, photo=file_to_send)
                            logger.info(f"Дополнительное фото для поста {post.id} отправлено в админ-чат.")
                        elif file_extension in ['.mp4', '.mov', '.avi', '.mkv', '.webm']:
                            await admin_bot.send_video(chat_id=config.ADMIN_CHAT_ID, video=file_to_send)
                            logger.info(f"Дополнительное видео для поста {post.id} отправлено в админ-чат.")
                        else:
                            logger.warning(f"Неизвестный тип дополнительного медиафайла '{file_extension}' для поста {post.id}. Пропускаем при отправке в админ-чат.")
                    except Exception as e:
                        logger.warning(f"Ошибка при отправке дополнительного медиафайла {media_path} для поста {post.id} в админ-чат: {e}")
                else:
                    logger.warning(f"Дополнительный медиафайл '{media_path}' для поста {post.id} не найден. Пропускаем при отправке в админ-чат.")
            
            # Отправляем кнопки после всех медиа, если их было несколько, чтобы они были в конце
            await admin_bot.send_message(chat_id=config.ADMIN_CHAT_ID, text="Выберите действие:", reply_markup=keyboard)


        else:
            # Если медиафайлов нет, отправляем только текст с кнопками
            logger.info(f"Медиафайлы для поста {post.id} отсутствуют. Отправляем только текст в админ-чат.")
            await admin_bot.send_message(chat_id=config.ADMIN_CHAT_ID, text=message_for_admin, reply_markup=keyboard, parse_mode="Markdown")

        logger.info(f"Пост ID {post.id} успешно отправлен в админ-панель для модерации.")
    except Exception as e:
        logger.error(f"Ошибка при отправке поста ID {post.id} в админ-панель: {e}")


# Запуск бота
async def start_news_bot():
    logger.info("Запуск основного Telegram бота...")
    # Пропускаем все накопившиеся обновления
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
        # await set_telegram_parser_instance_for_news_bot(mock_parser) # Не используется в этом контексте

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
