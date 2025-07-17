# bots/admin_bot.py
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from loguru import logger
from sqlalchemy.future import select
from sqlalchemy import func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from telethon import TelegramClient
from telethon.errors import ChannelInvalidError, UsernameNotOccupiedError

from config import config
import db.database
from db.models import Admin, City, DonorChannel, Post, Duplicate, ChannelSetting
import asyncio

# Инициализация админ-бота
admin_bot = Bot(token=config.ADMIN_BOT_TOKEN)
admin_dp = Dispatcher()

# Инициализация Telethon клиента для админ-бота (для получения ID каналов)
admin_telethon_client = TelegramClient('admin_telethon_session', config.TELETHON_API_ID, config.TELETHON_API_HASH)

# Состояния для FSM админ-бота
class AdminStates(StatesGroup):
    """Состояния для диалогов админ-бота."""
    waiting_for_city_input = State()
    waiting_for_donor_input = State()
    waiting_for_city_to_assign_donor = State()
    waiting_for_city_to_toggle_mode = State()
    waiting_for_post_id_to_rephrase = State()
    waiting_for_post_id_to_replace = State()
    waiting_for_new_text_for_replacement = State()
    waiting_for_donor_to_set_mask = State() # <-- НОВОЕ СОСТОЯНИЕ
    waiting_for_mask_pattern_input = State() # <-- НОВОЕ СОСТОЯНИЕ


# --- Middleware для проверки админ-прав ---
async def check_admin(telegram_id: int) -> bool:
    """Проверяет, является ли пользователь админом."""
    async for session in db.database.get_session():
        stmt = select(Admin).where(Admin.telegram_id == telegram_id)
        result = await session.execute(stmt)
        admin = result.scalar_one_or_none()
        return admin is not None

@admin_dp.message(CommandStart())
async def cmd_admin_start(message: types.Message):
    """Обработчик команды /start для админ-бота."""
    if not await check_admin(message.from_user.id):
        await message.answer("У вас нет прав доступа к админ-панели.")
        logger.warning(f"Неавторизованный доступ к админ-боту от {message.from_user.id}")
        return

    await message.answer(
        "Добро пожаловать в админ-панель Setinews!\n"
        "Используйте команды для управления:\n"
        "/add_city - Добавить новый городской канал\n"
        "/add_donor - Назначить донора каналу\n"
        "/toggle_mode - Включить/выключить авто-режим для канала\n"
        "/list_channels - Список всех городских каналов\n"
        "/set_mask_pattern - Установить/изменить маску для донора\n" # <-- НОВАЯ КОМАНДА
        "/logs - Просмотр логов публикаций/дубликатов\n"
        "/replace_news - Заменить опубликованную новость"
    )
    logger.info(f"Админ {message.from_user.id} запустил админ-бота.")

# --- Добавление нового городского канала ---
@admin_dp.message(Command("add_city"))
async def add_city_command(message: types.Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    await message.answer("Введите юзернейм или ссылку на новый городской канал (например, @my_city_channel или https://t.me/my_city_channel):")
    await state.set_state(AdminStates.waiting_for_city_input)

@admin_dp.message(AdminStates.waiting_for_city_input)
async def process_city_input(message: types.Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    channel_input = message.text.strip()

    await message.answer("Пожалуйста, подождите, определяю ID канала...")
    try:
        if not admin_telethon_client.is_connected():
            await admin_telethon_client.start()
            logger.info("Telethon клиент для админ-бота запущен.")

        entity = await admin_telethon_client.get_entity(channel_input)
        
        if not (hasattr(entity, 'broadcast') and entity.broadcast) and \
           not (hasattr(entity, 'megagroup') and entity.megagroup):
            await message.answer("Это не канал или супергруппа Telegram. Пожалуйста, введите юзернейм или ссылку на канал/супергруппу.")
            await state.clear()
            return

        telegram_id = int(f"-100{entity.id}")
        channel_title = entity.title if entity.title else entity.username

        async for session in db.database.get_session():
            existing_city = await session.execute(select(City).where(City.telegram_id == telegram_id))
            if existing_city.scalar_one_or_none():
                await message.answer("Канал с таким Telegram ID уже существует.")
                await state.clear()
                return

            new_city = City(telegram_id=telegram_id, title=channel_title)
            session.add(new_city)
            await session.commit()
            await message.answer(f"Городской канал '{channel_title}' (ID: `{telegram_id}`) успешно добавлен!")
            logger.info(f"Админ {message.from_user.id} добавил город: {channel_title} ({telegram_id})")
    except (ValueError, ChannelInvalidError, UsernameNotOccupiedError) as e:
        logger.error(f"Ошибка при определении ID городского канала '{channel_input}': {e}")
        await message.answer(f"Не удалось определить ID канала по введенным данным. Убедитесь, что юзернейм или ссылка корректны и канал существует. Ошибка: {e}")
    except Exception as e:
        logger.error(f"Непредвиденная ошибка при добавлении городского канала: {e}")
        await message.answer(f"Произошла непредвиденная ошибка: {e}")
    finally:
        await state.clear()

# --- Назначить список доноров ---
@admin_dp.message(Command("add_donor"))
async def add_donor_command(message: types.Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    async for session in db.database.get_session():
        cities = await session.execute(select(City))
        cities = cities.scalars().all()
        if not cities:
            await message.answer("Сначала добавьте городские каналы (/add_city).")
            return

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=city.title, callback_data=f"select_city_donor_{city.id}")] for city in cities
        ])
        await message.answer("Выберите городской канал, к которому хотите привязать донора:", reply_markup=keyboard)
        await state.set_state(AdminStates.waiting_for_city_to_assign_donor)

@admin_dp.callback_query(F.data.startswith("select_city_donor_"))
async def process_select_city_donor(callback: types.CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    city_id = int(callback.data.split('_')[-1])
    await state.update_data(target_city_id=city_id)
    await callback.message.edit_text("Введите юзернейм или ссылку на канал-донор (например, @news_channel_name или https://t.me/news_channel_name):")
    await state.set_state(AdminStates.waiting_for_donor_input)
    await callback.answer()

@admin_dp.message(AdminStates.waiting_for_donor_input)
async def process_donor_input(message: types.Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    donor_input = message.text.strip()
    user_data = await state.get_data()
    target_city_id = user_data['target_city_id']

    await message.answer("Пожалуйста, подождите, определяю ID канала-донора...")
    try:
        if not admin_telethon_client.is_connected():
            await admin_telethon_client.start()
            logger.info("Telethon клиент для админ-бота запущен.")

        entity = await admin_telethon_client.get_entity(donor_input)
        
        if not (hasattr(entity, 'broadcast') and entity.broadcast) and \
           not (hasattr(entity, 'megagroup') and entity.megagroup):
            await message.answer("Это не канал или супергруппа Telegram. Пожалуйста, введите юзернейм или ссылку на канал/супергруппу.")
            await state.clear()
            return

        donor_telegram_id = int(f"-100{entity.id}")
        donor_title = entity.title if entity.title else entity.username

        async for session in db.database.get_session():
            existing_donor = await session.execute(select(DonorChannel).where(DonorChannel.telegram_id == donor_telegram_id))
            if existing_donor.scalar_one_or_none():
                await message.answer("Этот донор уже добавлен. Если вы хотите привязать его к другому городу, удалите его сначала.")
                await state.clear()
                return

            new_donor = DonorChannel(telegram_id=donor_telegram_id, title=donor_title, city_id=target_city_id)
            session.add(new_donor)
            await session.commit()

            city = await session.execute(select(City).where(City.id == target_city_id))
            city_title = city.scalar_one().title

            await message.answer(f"Донор '{donor_title}' (ID: `{donor_telegram_id}`) успешно привязан к каналу '{city_title}'!")
            logger.info(f"Админ {message.from_user.id} привязал донора {donor_telegram_id} к городу {target_city_id}")
    except (ValueError, ChannelInvalidError, UsernameNotOccupiedError) as e:
        logger.error(f"Ошибка при определении ID донорского канала '{donor_input}': {e}")
        await message.answer(f"Не удалось определить ID донора по введенным данным. Убедитесь, что юзернейм или ссылка корректны и канал существует. Ошибка: {e}")
    except Exception as e:
        logger.error(f"Непредвиденная ошибка при добавлении донора: {e}")
        await message.answer(f"Произошла непредвиденная ошибка: {e}")
    finally:
        await state.clear()

# --- Включить/выключить авто-режим ---
@admin_dp.message(Command("toggle_mode"))
async def toggle_mode_command(message: types.Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    async for session in db.database.get_session():
        cities = await session.execute(select(City))
        cities = cities.scalars().all()
        if not cities:
            await message.answer("Нет городских каналов для настройки.")
            return

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"{city.title} (Авто: {'✅' if city.auto_mode else '❌'})", callback_data=f"toggle_mode_{city.id}")] for city in cities
        ])
        await message.answer("Выберите городской канал для переключения режима публикации:", reply_markup=keyboard)
        await state.set_state(AdminStates.waiting_for_city_to_toggle_mode)

@admin_dp.callback_query(F.data.startswith("toggle_mode_"))
async def process_toggle_mode(callback: types.CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    city_id = int(callback.data.split('_')[-1])

    async for session in db.database.get_session():
        stmt = select(City).where(City.id == city_id)
        result = await session.execute(stmt)
        city = result.scalar_one_or_none()

        if city:
            city.auto_mode = not city.auto_mode
            await session.commit()
            status = "включен" if city.auto_mode else "выключен"
            await callback.message.edit_text(f"Для канала '{city.title}' автоматический режим публикации теперь {status}.")
            logger.info(f"Админ {callback.from_user.id} переключил авто-режим для {city.title} на {status}")
        else:
            await callback.message.edit_text("Канал не найден.")
    await callback.answer()
    await state.clear()

# --- Список всех городских каналов ---
@admin_dp.message(Command("list_channels"))
async def list_channels_command(message: types.Message):
    if not await check_admin(message.from_user.id): return
    async for session in db.database.get_session():
        stmt = select(City).order_by(City.title)
        cities = await session.execute(stmt)
        cities = cities.scalars().all()

        if not cities:
            await message.answer("Городские каналы пока не добавлены.")
            return

        response_text = "Список городских каналов:\n\n"
        for city in cities:
            response_text += f"*{city.title}* (ID: `{city.telegram_id}`)\n"
            response_text += f"  Режим: {'Автоматический ✅' if city.auto_mode else 'Ручной ❌'}\n"
            
            # Получаем доноров для текущего города
            stmt_donors = select(DonorChannel).where(DonorChannel.city_id == city.id).order_by(DonorChannel.title)
            donors = await session.execute(stmt_donors)
            donors = donors.scalars().all()
            
            if donors:
                response_text += "  Доноры:\n"
                for donor in donors:
                    mask_status = f"Маска: `{donor.mask_pattern}`" if donor.mask_pattern else "Маска: ❌ Не задана"
                    response_text += f"    - {donor.title} (ID: `{donor.telegram_id}`) - {mask_status}\n" # <-- Обновлено
            else:
                response_text += "  Доноры: Нет\n"
            response_text += "\n"
        
        await message.answer(response_text, parse_mode="Markdown")
    logger.info(f"Админ {message.from_user.id} запросил список каналов.")

# --- Установка/изменение маски для донорского канала ---
@admin_dp.message(Command("set_mask_pattern"))
async def set_mask_pattern_command(message: types.Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    async for session in db.database.get_session():
        donors = await session.execute(select(DonorChannel).order_by(DonorChannel.title))
        donors = donors.scalars().all()
        if not donors:
            await message.answer("Нет донорских каналов для настройки маски. Сначала добавьте доноров.")
            return

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"{donor.title} (Маска: {'✅' if donor.mask_pattern else '❌'})", callback_data=f"select_donor_mask_{donor.id}")] for donor in donors
        ])
        await message.answer("Выберите донорский канал, для которого хотите установить/изменить маску:", reply_markup=keyboard)
        await state.set_state(AdminStates.waiting_for_donor_to_set_mask)

@admin_dp.callback_query(F.data.startswith("select_donor_mask_"))
async def process_select_donor_mask(callback: types.CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    donor_id = int(callback.data.split('_')[-1])
    await state.update_data(target_donor_id_for_mask=donor_id)
    
    async for session in db.database.get_session():
        donor = await session.get(DonorChannel, donor_id)
        if donor:
            current_mask = donor.mask_pattern if donor.mask_pattern else "Не задана"
            await callback.message.edit_text(
                f"Вы выбрали донорский канал '{donor.title}'.\n"
                f"Текущая маска: `{current_mask}`\n\n"
                f"Введите новую маску (регулярное выражение) или отправьте `/clear_mask`, чтобы удалить текущую маску:"
            )
            await state.set_state(AdminStates.waiting_for_mask_pattern_input)
        else:
            await callback.message.edit_text("Донорский канал не найден.")
    await callback.answer()

@admin_dp.message(AdminStates.waiting_for_mask_pattern_input)
async def process_mask_pattern_input(message: types.Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    user_data = await state.get_data()
    target_donor_id = user_data['target_donor_id_for_mask']
    
    new_mask_pattern = message.text.strip()
    
    if new_mask_pattern.lower() == "/clear_mask":
        new_mask_pattern = None # Устанавливаем None для удаления маски
        action_message = "Маска удалена."
    else:
        try:
            re.compile(new_mask_pattern) # Проверяем, что это валидное регулярное выражение
            action_message = f"Маска установлена: `{new_mask_pattern}`"
        except re.error as e:
            await message.answer(f"Ошибка в регулярном выражении: `{e}`. Пожалуйста, попробуйте еще раз или отправьте `/clear_mask`.")
            return # Не очищаем состояние, ждем корректный ввод
    
    async for session in db.database.get_session():
        donor = await session.get(DonorChannel, target_donor_id)
        if donor:
            donor.mask_pattern = new_mask_pattern
            await session.commit()
            await message.answer(f"Для донора '{donor.title}': {action_message}")
            logger.info(f"Админ {message.from_user.id} установил/изменил маску для донора {donor.title} на: {new_mask_pattern}")
        else:
            await message.answer("Донорский канал не найден.")
    await state.clear()

# --- Просмотр логов ---
@admin_dp.message(Command("logs"))
async def logs_command(message: types.Message):
    if not await check_admin(message.from_user.id): return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="История публикаций", callback_data="show_published_logs")],
        [InlineKeyboardButton(text="Отклоненные посты", callback_data="show_rejected_logs")] # <-- Обновлено
    ])
    await message.answer("Выберите тип логов:", reply_markup=keyboard)

@admin_dp.callback_query(F.data == "show_published_logs")
async def show_published_logs(callback: types.CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    async for session in db.database.get_session():
        stmt = select(Post).where(Post.status == "published").order_by(Post.published_at.desc()).limit(10)
        published_posts = await session.execute(stmt)
        published_posts = published_posts.scalars().all()

        if not published_posts:
            await callback.message.edit_text("Нет записей об опубликованных постах.")
            return

        response_text = "Последние опубликованные посты:\n\n"
        for post in published_posts:
            city = await session.get(City, post.city_id)
            response_text += (
                f"ID: `{post.id}`\n"
                f"Канал: {city.title if city else 'Неизвестно'}\n"
                f"Текст: {post.processed_text[:100]}...\n"
                f"Опубликовано: {post.published_at.strftime('%Y-%m-%d %H:%M')}\n\n"
            )
        await callback.message.edit_text(response_text, parse_mode="Markdown")
    await callback.answer()

@admin_dp.callback_query(F.data == "show_rejected_logs") # <-- Обновлено
async def show_rejected_logs(callback: types.CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    async for session in db.database.get_session():
        # Выбираем все отклоненные посты, включая дубликаты и те, что не прошли маску
        stmt = select(Post).where(
            Post.status.in_([
                "rejected_duplicate", 
                "rejected_no_mask_defined", # <-- НОВЫЙ СТАТУС
                "rejected_no_mask_match", 
                "rejected_empty_after_clean",
                "rejected_mask_error",
                "rejected_processing_error"
            ])
        ).order_by(Post.created_at.desc()).limit(10)
        rejected_posts = await session.execute(stmt)
        rejected_posts = rejected_posts.scalars().all()

        if not rejected_posts:
            await callback.message.edit_text("Нет записей об отклоненных постах.")
            return

        response_text = "Последние отклоненные посты:\n\n"
        for post in rejected_posts:
            city = await session.get(City, post.city_id)
            donor = await session.get(DonorChannel, post.donor_channel_id)
            
            reason = "Неизвестно"
            if post.status == "rejected_duplicate":
                reason = "Дубликат"
            elif post.status == "rejected_no_mask_defined": # <-- НОВЫЙ СТАТУС
                reason = "Маска не задана"
            elif post.status == "rejected_no_mask_match":
                reason = "Не соответствует маске"
            elif post.status == "rejected_empty_after_clean":
                reason = "Пустой после очистки"
            elif post.status == "rejected_mask_error":
                reason = "Ошибка в маске"
            elif post.status == "rejected_processing_error":
                reason = "Ошибка обработки"

            response_text += (
                f"ID: `{post.id}`\n"
                f"Канал (донор): {donor.title if donor else 'Неизвестно'}\n"
                f"Канал (город): {city.title if city else 'Неизвестно'}\n"
                f"Текст: {post.original_text[:100]}...\n"
                f"Причина: {reason}\n"
                f"Обнаружено: {post.created_at.strftime('%Y-%m-%d %H:%M')}\n\n"
            )
        await callback.message.edit_text(response_text, parse_mode="Markdown")
    await callback.answer()

# --- Обработка кнопок модерации из основного бота (callback_query) ---
@admin_dp.callback_query(F.data.startswith("publish_"))
async def handle_publish_callback(callback: types.CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    post_id = int(callback.data.split('_')[1])
    async for session in db.database.get_session():
        stmt = select(Post).where(Post.id == post_id)
        result = await session.execute(stmt)
        post = result.scalar_one_or_none()

        if post and post.status == "pending":
            from bots.news_bot import publish_post
            city = await session.get(City, post.city_id)
            if city:
                current_media_paths = [post.image_url] if post.image_url else []
                await publish_post(post.id, city.telegram_id, session, current_media_paths)
                await callback.message.edit_text(f"Пост ID {post.id} опубликован в канал '{city.title}'.")
                logger.info(f"Админ {callback.from_user.id} опубликовал пост {post.id}.")
            else:
                await callback.message.edit_text(f"Ошибка: Городской канал для поста {post.id} не найден.")
        else:
            await callback.message.edit_text(f"Пост ID {post.id} уже обработан или не найден.")
    await callback.answer()

@admin_dp.callback_query(F.data.startswith("rephrase_"))
async def handle_rephrase_callback(callback: types.CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    post_id = int(callback.data.split('_')[1])
    async for session in db.database.get_session():
        stmt = select(Post).where(Post.id == post_id)
        result = await session.execute(stmt)
        post = result.scalar_one_or_none()

        if post and post.status == "pending":
            await callback.message.edit_text(f"Переформулирую пост ID {post.id}...")
            # GigaChat все еще используется здесь для переформулирования по запросу админа
            from core.gigachat import gigachat_api
            rephrased_text = await gigachat_api.rephrase_text(post.original_text) # Используем original_text для переформулирования
            if rephrased_text:
                post.processed_text = rephrased_text
                await session.commit()
                city = await session.get(City, post.city_id)
                if city:
                    await callback.message.edit_text(
                        f"Пост ID {post.id} переформулирован. Новая версия:\n{rephrased_text[:500]}...\n"
                        f"Выберите действие:",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [
                                InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"publish_{post.id}"),
                                InlineKeyboardButton(text="✍️ Редактировать", callback_data=f"edit_{post.id}"),
                                InlineKeyboardButton(text="♻️ Переформулировать", callback_data=f"rephrase_{post.id}"),
                                InlineKeyboardButton(text="❌ Удалить", callback_data=f"delete_{post.id}")
                            ]
                        ])
                    )
                    logger.info(f"Админ {callback.from_user.id} переформулировал пост {post.id}.")
                else:
                    await callback.message.edit_text(f"Ошибка: Городской канал для поста {post.id} не найден.")
            else:
                await callback.message.edit_text(f"Не удалось переформулировать пост ID {post.id}.")
        else:
            await callback.message.edit_text(f"Пост ID {post.id} уже обработан или не найден.")
    await callback.answer()

@admin_dp.callback_query(F.data.startswith("delete_"))
async def handle_delete_callback(callback: types.CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    post_id = int(callback.data.split('_')[1])
    async for session in db.database.get_session():
        stmt = select(Post).where(Post.id == post_id)
        result = await session.execute(stmt)
        post = result.scalar_one_or_none()

        if post and post.status == "pending":
            post.status = "rejected"
            await session.commit()
            await callback.message.edit_text(f"Пост ID {post.id} удален.")
            logger.info(f"Админ {callback.from_user.id} удалил пост {post.id}.")
        else:
            await callback.message.edit_text(f"Пост ID {post.id} уже обработан или не найден.")
    await callback.answer()

# --- Возможность вручную заменить опубликованную новость ---
@admin_dp.message(Command("replace_news"))
async def replace_news_command(message: types.Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    await message.answer("Введите ID поста, который вы хотите заменить:")
    await state.set_state(AdminStates.waiting_for_post_id_to_replace)

@admin_dp.message(AdminStates.waiting_for_id_to_replace)
async def process_post_id_for_replacement(message: types.Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    try:
        post_id = int(message.text.strip())
        async for session in db.database.get_session():
            stmt = select(Post).where(Post.id == post_id, Post.status == "published")
            result = await session.execute(stmt)
            post = result.scalar_one_or_none()

            if not post:
                await message.answer("Пост с таким ID не найден или не опубликован.")
                await state.clear()
                return

            await state.update_data(post_to_replace_id=post_id)
            await message.answer(
                f"Вы выбрали пост ID {post_id}. Текущий текст:\n\n"
                f"{post.processed_text}\n\n"
                f"Теперь введите новый текст для замены:"
            )
            await state.set_state(AdminStates.waiting_for_new_text_for_replacement)
    except ValueError:
        await message.answer("Некорректный ID поста. Пожалуйста, введите число.")
    except Exception as e:
        await message.answer(f"Произошла ошибка: {e}")
        logger.error(f"Ошибка при замене новости (получение ID): {e}")

@admin_dp.message(AdminStates.waiting_for_new_text_for_replacement)
async def process_new_text_for_replacement(message: types.Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    new_text = message.text.strip()
    user_data = await state.get_data()
    post_id_to_replace = user_data['post_to_replace_id']

    async for session in db.database.get_session():
        stmt = select(Post).where(Post.id == post_id_to_replace)
        result = await session.execute(stmt)
        post = result.scalar_one_or_none()

        if post:
            post.processed_text = new_text
            post.published_at = func.now() # Обновляем время публикации
            await session.commit()
            await message.answer(f"Текст поста ID {post_id_to_replace} успешно обновлен в базе данных.")
            logger.info(f"Админ {message.from_user.id} заменил текст поста {post_id_to_replace}.")
        else:
            await message.answer("Пост не найден.")
    await state.clear()


# Запуск админ-бота
async def start_admin_bot():
    logger.info("Запуск админского Telegram бота...")
    if not admin_telethon_client.is_connected():
        await admin_telethon_client.start()
        logger.info("Telethon клиент для админ-бота запущен.")

    await admin_dp.start_polling(admin_bot)
    logger.info("Админский Telegram бот остановлен.")

if __name__ == "__main__":
    async def debug_main():
        await start_admin_bot()
    asyncio.run(debug_main())
