# bots/news_bot.py
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from loguru import logger

from config import config
import db.database
from db.models import Post, City, DonorChannel, ChannelSetting
from core.gigachat import gigachat_api # Оставляем импорт на случай, если GigaChat понадобится позже
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

# Глобальная переменная для хранения экземпляра TelethonParser
telegram_parser_instance = None

async def set_telegram_parser_instance_for_news_bot(parser_instance):
    """Устанавливает экземпляр TelethonParser для использования в news_bot."""
    global telegram_parser_instance
    telegram_parser_instance = parser_instance
    logger.info("Экземпляр TelethonParser установлен в news_bot.")

# Состояния для FSM (Finite State Machine)
class NewsBotStates(StatesGroup):
    pass

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    """Обработчик команды /start."""
    await message.answer(
        "Привет! Я бот городской новостной сети. Я буду автоматически публиковать новости в городские каналы."
    )
    logger.info(f"Получена команда /start от пользователя {message.from_user.id}")

async def _remove_promotional_links(text: str) -> str:
    """
    Удаляет из текста ссылки типа "Подписаться" и схожие рекламные подписи,
    особенно в конце поста.
    """
    if not text:
        return ""

    # 1. Удаление Telegram-ссылок в скобках (https://t.me/...)
    # Пример: "Текст новости (https://t.me/channel)" -> "Текст новости"
    text = re.sub(r'\s*\([^)]*https?://t\.me/[^)]*\)', '', text, flags=re.IGNORECASE)

    # Паттерны для удаления строк, которые являются рекламными подписями.
    # Используем re.fullmatch для точного совпадения всей строки.
    promotional_line_patterns = [
        # Фразы типа "Подписаться на наш канал" с эмодзи или без, с/без ссылки
        r'^\s*[\U0001F000-\U0001FFFF\U00002000-\U00002BFF\W_]*\b(?:подписаться|наш канал|прислать новость|новости|канал|наш|подпишись|вступай|переходи|наш чат|наша группа)\b.*?(?:https?://[^\s)]+)?\s*$',
        # Просто URL в строке
        r'^\s*https?://[^\s)]+\s*$'
    ]

    lines = text.split('\n')
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

    async for session in db.database.get_session():
        # --- Начало костыля для обработки ID канала ---
        possible_donor_ids = [channel_id]
        if channel_id > 0:
            possible_donor_ids.append(int(f"-100{channel_id}"))
        elif str(channel_id).startswith('-100'):
            try:
                possible_donor_ids.append(int(str(channel_id)[4:]))
            except ValueError:
                pass

        stmt_donor = select(DonorChannel).where(DonorChannel.telegram_id.in_(possible_donor_ids))
        result_donor = await session.execute(stmt_donor)
        donor_channel = result_donor.scalar_one_or_none()

        if not donor_channel:
            logger.warning(f"Сообщение от неизвестного донора (ID: {channel_id}). Пропускаем.")
            return

        stmt_city = select(City).where(City.id == donor_channel.city_id)
        result_city = await session.execute(stmt_city)
        city = result_city.scalar_one_or_none()

        if not city:
            logger.error(f"Городской канал для донора {donor_channel.title} (ID: {donor_channel.city_id}) не найден. Пропускаем.")
            return

        original_text = text # Сохраняем оригинальный текст для логирования и БД

        # --- НОВАЯ ЛОГИКА ОБРАБОТКИ С МАСКОЙ ---
        processed_text = original_text
        
        if not donor_channel.mask_pattern:
            logger.info(f"Для донора '{donor_channel.title}' (ID: {donor_channel.telegram_id}) не задана маска. Пост отклонен.")
            new_post = Post(
                original_text=original_text,
                processed_text=None,
                image_url=media_paths[0] if media_paths else None,
                source_link=source_link,
                is_advertisement=False,
                is_duplicate=False,
                status="rejected_no_mask_defined", # Новый статус
                donor_channel_id=donor_channel.id,
                city_id=city.id,
                original_message_id=message_id
            )
            session.add(new_post)
            await session.commit()
            return

        try:
            # Ищем совпадения с маской
            match = re.search(donor_channel.mask_pattern, original_text, re.DOTALL | re.IGNORECASE)
            
            if not match:
                logger.info(f"Пост от донора '{donor_channel.title}' (ID: {donor_channel.telegram_id}) не соответствует маске. Пост отклонен.")
                new_post = Post(
                    original_text=original_text,
                    processed_text=None,
                    image_url=media_paths[0] if media_paths else None,
                    source_link=source_link,
                    is_advertisement=False,
                    is_duplicate=False,
                    status="rejected_no_mask_match", # Новый статус
                    donor_channel_id=donor_channel.id,
                    city_id=city.id,
                    original_message_id=message_id
                )
                session.add(new_post)
                await session.commit()
                return
            
            # Если маска совпала, удаляем найденный текст
            processed_text = re.sub(donor_channel.mask_pattern, '', original_text, flags=re.DOTALL | re.IGNORECASE).strip()

            if not processed_text:
                logger.warning(f"Текст поста (ID: {message_id}) стал пустым после применения маски. Пост отклонен.")
                new_post = Post(
                    original_text=original_text,
                    processed_text=None,
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

            # Добавляем кастомную подпись
            # Формируем адрес канала: если есть username, используем его, иначе - t.me/c/ID
            channel_address = f"https://t.me/{donor_channel.title.replace('@', '')}" if donor_channel.title.startswith('@') else f"https://t.me/c/{abs(donor_channel.telegram_id)}"
            custom_signature = f"\n\n\t\t**❤️** **[Подпишись на {donor_channel.title.replace('@', '')}]({channel_address})**"
            processed_text += custom_signature

        except re.error as e:
            logger.error(f"Ошибка регулярного выражения в маске для донора '{donor_channel.title}' (ID: {donor_channel.telegram_id}): {e}. Пост отклонен.")
            new_post = Post(
                original_text=original_text,
                processed_text=None,
                image_url=media_paths[0] if media_paths else None,
                source_link=source_link,
                is_advertisement=False,
                is_duplicate=False,
                status="rejected_mask_error", # Новый статус
                donor_channel_id=donor_channel.id,
                city_id=city.id,
                original_message_id=message_id
            )
            session.add(new_post)
            await session.commit()
            return
        except Exception as e:
            logger.error(f"Неизвестная ошибка при обработке маски для донора '{donor_channel.title}': {e}. Пост отклонен.")
            new_post = Post(
                original_text=original_text,
                processed_text=None,
                image_url=media_paths[0] if media_paths else None,
                source_link=source_link,
                is_advertisement=False,
                is_duplicate=False,
                status="rejected_processing_error", # Новый статус
                donor_channel_id=donor_channel.id,
                city_id=city.id,
                original_message_id=message_id
            )
            session.add(new_post)
            await session.commit()
            return
        # --- КОНЕЦ НОВОЙ ЛОГИКИ С МАСКОЙ ---

        # 1. Проверка на дубликат (теперь после обработки маской)
        is_duplicate, reason = await deduplicator.check_for_duplicates(session, processed_text, city.id)

        if is_duplicate:
            logger.info(f"Сообщение '{processed_text[:50]}...' является дубликатом. Причина: {reason}. Не публикуем.")
            new_post = Post(
                original_text=original_text,
                processed_text=processed_text,
                image_url=media_paths[0] if media_paths else None,
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

        # 2. Сохранение поста в БД
        new_post = Post(
            original_text=original_text,
            processed_text=processed_text,
            image_url=media_paths[0] if media_paths else None,
            source_link=source_link,
            is_advertisement=False, # Теперь рекламность определяется маской
            is_duplicate=False,
            status="pending",
            donor_channel_id=donor_channel.id,
            city_id=city.id,
            original_message_id=message_id
        )
        session.add(new_post)
        await session.commit()
        logger.info(f"Новый пост (ID: {new_post.id}) сохранен в БД со статусом 'pending'.")

        # 3. Публикация или отправка на модерацию
        if city.auto_mode:
            await publish_post(new_post.id, city.telegram_id, session, media_paths)
        else:
            from bots.admin_bot import admin_bot
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
        message_to_send = post.processed_text

        if media_paths:
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

    from bots.admin_bot import admin_bot

    message_for_admin = (
        f"🚨 *Новый пост для модерации* (ID: `{post.id}`)\n"
        f"Канал назначения: `{target_telegram_channel_id}`\n"
        f"Статус: {'Реклама' if post.is_advertisement else 'Ожидает'}\n\n"
        f"Оригинал:\n`{post.original_text[:1000]}`\n\n" # Ограничиваем длину для удобства
        f"Предложено:\n`{post.processed_text[:1000]}`\n" # Ограничиваем длину для удобства
    )
    if post.is_advertisement:
        message_for_admin += "\n_GigaChat пометил как рекламное._"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"publish_{post.id}"),
            InlineKeyboardButton(text="✍️ Редактировать", callback_data=f"edit_{post.id}"), # Добавлена кнопка редактирования
            InlineKeyboardButton(text="♻️ Переформулировать", callback_data=f"rephrase_{post.id}"),
            InlineKeyboardButton(text="❌ Удалить", callback_data=f"delete_{post.id}")
        ]
    ])

    try:
        if media_paths:
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
            
            await admin_bot.send_message(chat_id=config.ADMIN_CHAT_ID, text="Выберите действие:", reply_markup=keyboard)


        else:
            logger.info(f"Медиафайлы для поста {post.id} отсутствуют. Отправляем только текст в админ-чат.")
            await admin_bot.send_message(chat_id=config.ADMIN_CHAT_ID, text=message_for_admin, reply_markup=keyboard, parse_mode="Markdown")

        logger.info(f"Пост ID {post.id} успешно отправлен в админ-панель для модерации.")
    except Exception as e:
        logger.error(f"Ошибка при отправке поста ID {post.id} в админ-панель: {e}")


# Запуск бота
async def start_news_bot():
    logger.info("Запуск основного Telegram бота...")
    await dp.start_polling(bot)
    logger.info("Основной Telegram бот остановлен.")

if __name__ == "__main__":
    async def debug_main():
        await start_news_bot()
    asyncio.run(debug_main())
