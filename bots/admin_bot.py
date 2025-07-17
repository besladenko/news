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
from telethon import TelegramClient # Импортируем TelegramClient для разрешения юзернеймов
from telethon.tl.types import Channel, User, Chat # Импортируем типы для работы с сущностями Telethon
from telethon.errors import UsernameNotOccupiedError, ChannelPrivateError, ChatAdminRequiredError # Импортируем ошибки Telethon

from config import config
from db.database import get_session
from db.models import Admin, City, DonorChannel, Post, Duplicate, ChannelSetting
from core.gigachat import gigachat_api
from bots.news_bot import publish_post # Импортируем функцию публикации из основного бота
import asyncio
import re # Для обработки списка ссылок

# Инициализация админ-бота
admin_bot = Bot(token=config.ADMIN_BOT_TOKEN)
admin_dp = Dispatcher()

# Глобальная переменная для хранения экземпляра TelethonParser
telegram_parser_instance = None

# Состояния для FSM админ-бота
class AdminStates(StatesGroup):
    """Состояния для диалогов админ-бота."""
    waiting_for_city_input = State() # Для add_city (ID или юзернейм/ссылка)
    waiting_for_city_name = State() # Для add_city (название, если не получено автоматически)
    waiting_for_donor_input = State() # Для add_donor (ID или юзернейм/ссылка)
    waiting_for_donor_name = State() # Для add_donor (название, если не получено автоматически)
    waiting_for_city_to_assign_donor = State()
    waiting_for_city_to_toggle_mode = State()
    waiting_for_post_id_to_rephrase = State()
    waiting_for_post_id_to_replace = State()
    waiting_for_new_text_for_replacement = State()
    
    # НОВЫЕ СОСТОЯНИЯ
    waiting_for_city_to_send_test_message = State()
    waiting_for_test_message_text = State()
    waiting_for_edited_text = State() # Для редактирования поста
    waiting_for_city_to_delete = State() # Для удаления города
    waiting_for_city_for_bulk_donors = State() # Для массового добавления доноров
    waiting_for_bulk_donor_list = State() # Для ввода списка доноров

async def set_telegram_parser_instance(parser_instance):
    """Устанавливает экземпляр TelethonParser для использования в admin_bot."""
    global telegram_parser_instance
    telegram_parser_instance = parser_instance
    logger.info("Экземпляр TelethonParser установлен в admin_bot.")

async def resolve_channel_id(channel_identifier: str) -> tuple[int | None, str | None]:
    """
    Разрешает Telegram ID канала по его юзернейму или ссылке.
    Возвращает (ID, Название) или (None, None) в случае ошибки.
    """
    if not telegram_parser_instance or not telegram_parser_instance.client.is_connected():
        logger.error("Telethon клиент не запущен или не подключен для разрешения канала.")
        return None, None

    # Если уже числовой ID, возвращаем его
    try:
        # Проверяем, является ли это числовым ID канала (может быть без -100)
        # Или уже с -100
        if channel_identifier.lstrip('-').isdigit():
            num_id = int(channel_identifier)
            # Если ID положительный (для публичных каналов Telethon), добавляем -100
            # Telethon для публичных каналов возвращает положительный ID, который нужно преобразовать в -100xxxx
            if num_id > 0 and not str(num_id).startswith('100'): # Избегаем двойного -100
                return int(f"-100{num_id}"), None # Название пока неизвестно
            return num_id, None # Название пока неизвестно
    except ValueError:
        pass # Не числовой ID, продолжаем попытку разрешения

    # Удаляем префикс ссылки, если есть
    channel_identifier = channel_identifier.replace("https://t.me/", "").replace("t.me/", "").replace("@", "")

    try:
        entity = await telegram_parser_instance.client.get_entity(channel_identifier)
        if isinstance(entity, (Channel, Chat)):
            # Telethon возвращает ID канала без -100 для публичных каналов.
            # Для согласованности с БД, всегда приводим к формату с -100.
            resolved_id = entity.id
            if not str(resolved_id).startswith('100'): # Если ID не начинается с 100 (т.е. это raw ID)
                 resolved_id = int(f"-100{resolved_id}")
            return resolved_id, entity.title
        elif isinstance(entity, User):
            logger.warning(f"'{channel_identifier}' является пользователем, а не каналом/группой.")
            return None, None
        else:
            logger.warning(f"Неизвестный тип сущности для '{channel_identifier}': {type(entity)}")
            return None, None
    except UsernameNotOccupiedError:
        logger.warning(f"Канал/юзернейм '{channel_identifier}' не найден.")
        return None, None
    except ChannelPrivateError:
        logger.warning(f"Канал '{channel_identifier}' приватный, нет доступа.")
        return None, None
    except ChatAdminRequiredError:
        logger.warning(f"Бот не является админом в чате '{channel_identifier}'.")
        return None, None
    except Exception as e:
        logger.error(f"Ошибка при разрешении ID канала '{channel_identifier}': {e}")
        return None, None


# --- Middleware для проверки админ-прав ---
async def check_admin(telegram_id: int) -> bool:
    """Проверяет, является ли пользователь админом."""
    async for session in get_session():
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
        "/add_bulk_donors - Массово добавить доноров к каналу\n" # НОВОЕ
        "/delete_city - Удалить городской канал и его доноров\n" # НОВОЕ
        "/toggle_mode - Включить/выключить авто-режим для канала\n"
        "/list_channels - Список всех городских каналов\n"
        "/logs - Просмотр логов публикаций/дубликатов\n"
        "/replace_news - Заменить опубликованную новость\n"
        "/send_test_message - Отправить тестовое сообщение в канал"
    )
    logger.info(f"Админ {message.from_user.id} запустил админ-бота.")

# --- Добавление нового городского канала ---
@admin_dp.message(Command("add_city"))
async def add_city_command(message: types.Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    await message.answer("Введите Telegram ID или юзернейм/ссылку нового городского канала (например, -1001234567890 или @my_city_news):")
    await state.set_state(AdminStates.waiting_for_city_input)

@admin_dp.message(AdminStates.waiting_for_city_input)
async def process_city_input(message: types.Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    channel_identifier = message.text.strip()

    telegram_id, channel_title = await resolve_channel_id(channel_identifier)

    if telegram_id is None:
        await message.answer(f"Не удалось определить Telegram ID для '{channel_identifier}'. Убедитесь, что это корректный ID или публичный юзернейм/ссылка, и бот имеет доступ к каналу.")
        await state.clear()
        return

    async for session in get_session():
        existing_city = await session.execute(select(City).where(City.telegram_id == telegram_id))
        if existing_city.scalar_one_or_none():
            await message.answer("Канал с таким Telegram ID уже существует.")
            await state.clear()
            return

        # Если название не было получено из Telethon, просим пользователя ввести его
        if not channel_title:
            await state.update_data(telegram_id=telegram_id)
            await message.answer("Не удалось автоматически получить название канала. Пожалуйста, введите название этого канала:")
            await state.set_state(AdminStates.waiting_for_city_name)
        else:
            new_city = City(telegram_id=telegram_id, title=channel_title)
            session.add(new_city)
            await session.commit()
            await message.answer(f"Городской канал '{channel_title}' (ID: `{telegram_id}`) успешно добавлен!")
            logger.info(f"Админ {message.from_user.id} добавил город: {channel_title} ({telegram_id})")
            await state.clear()

@admin_dp.message(AdminStates.waiting_for_city_name)
async def process_city_name(message: types.Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    city_name = message.text.strip()
    user_data = await state.get_data()
    telegram_id = user_data['telegram_id']

    async for session in get_session():
        new_city = City(telegram_id=telegram_id, title=city_name)
        session.add(new_city)
        await session.commit()
        await message.answer(f"Городской канал '{city_name}' (ID: `{telegram_id}`) успешно добавлен!")
        logger.info(f"Админ {message.from_user.id} добавил город: {city_name} ({telegram_id})")
    await state.clear()


# --- Назначить список доноров ---
@admin_dp.message(Command("add_donor"))
async def add_donor_command(message: types.Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    async for session in get_session():
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
    await callback.message.edit_text("Введите Telegram ID или юзернейм/ссылку канала-донора (например, @donor_news или -1001234567890):")
    await state.set_state(AdminStates.waiting_for_donor_input)
    await callback.answer()

@admin_dp.message(AdminStates.waiting_for_donor_input)
async def process_donor_input(message: types.Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    channel_identifier = message.text.strip()
    user_data = await state.get_data()
    target_city_id = user_data['target_city_id']

    donor_telegram_id, donor_title = await resolve_channel_id(channel_identifier)

    if donor_telegram_id is None:
        await message.answer(f"Не удалось определить Telegram ID для '{channel_identifier}'. Убедитесь, что это корректный ID или публичный юзернейм/ссылка, и бот имеет доступ к каналу.")
        await state.clear()
        return

    async for session in get_session():
        existing_donor = await session.execute(select(DonorChannel).where(DonorChannel.telegram_id == donor_telegram_id))
        if existing_donor.scalar_one_or_none():
            await message.answer("Этот донор уже добавлен. Если вы хотите привязать его к другому городу, удалите его сначала.")
            await state.clear()
            return

        # Если название не было получено из Telethon, используем заглушку или просим пользователя ввести
        if not donor_title:
            donor_title = f"Канал ID {donor_telegram_id}" # Заглушка, если Telethon не вернул название
            await message.answer(f"Не удалось автоматически получить название канала-донора. Используем '{donor_title}'.")

        new_donor = DonorChannel(telegram_id=donor_telegram_id, title=donor_title, city_id=target_city_id)
        session.add(new_donor)
        await session.commit()

        city = await session.execute(select(City).where(City.id == target_city_id))
        city_title = city.scalar_one().title

        await message.answer(f"Донор '{donor_title}' (ID: `{donor_telegram_id}`) успешно привязан к каналу '{city_title}'!")
        logger.info(f"Админ {message.from_user.id} привязал донора {donor_telegram_id} к городу {target_city_id}")
    await state.clear()

# --- Массовое добавление доноров ---
@admin_dp.message(Command("add_bulk_donors"))
async def add_bulk_donors_command(message: types.Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    async for session in get_session():
        cities = await session.execute(select(City))
        cities = cities.scalars().all()
        if not cities:
            await message.answer("Сначала добавьте городские каналы (/add_city).")
            return

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=city.title, callback_data=f"select_city_bulk_donor_{city.id}")] for city in cities
        ])
        await message.answer("Выберите городской канал, к которому хотите массово привязать доноров:", reply_markup=keyboard)
        await state.set_state(AdminStates.waiting_for_city_for_bulk_donors)

@admin_dp.callback_query(F.data.startswith("select_city_bulk_donor_"))
async def process_select_city_bulk_donor(callback: types.CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    city_id = int(callback.data.split('_')[-1])
    await state.update_data(target_city_id=city_id)
    await callback.message.edit_text("Теперь отправьте список юзернеймов или ссылок на каналы-доноры, каждый с новой строки (например, @donor_news или https://t.me/donor_channel):")
    await state.set_state(AdminStates.waiting_for_bulk_donor_list)
    await callback.answer()

@admin_dp.message(AdminStates.waiting_for_bulk_donor_list)
async def process_bulk_donor_list(message: types.Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    donor_identifiers = message.text.strip().split('\n')
    user_data = await state.get_data()
    target_city_id = user_data['target_city_id']
    
    results = []
    async for session in get_session():
        city = await session.get(City, target_city_id)
        if not city:
            await message.answer("Выбранный городской канал не найден.")
            await state.clear()
            return

        for identifier in donor_identifiers:
            identifier = identifier.strip()
            if not identifier:
                continue

            donor_telegram_id, donor_title = await resolve_channel_id(identifier)

            if donor_telegram_id is None:
                results.append(f"❌ Не удалось определить ID для '{identifier}'")
                continue

            existing_donor = await session.execute(select(DonorChannel).where(DonorChannel.telegram_id == donor_telegram_id))
            if existing_donor.scalar_one_or_none():
                results.append(f"⚠️ Донор '{identifier}' (ID: `{donor_telegram_id}`) уже существует. Пропущен.")
                continue
            
            if not donor_title:
                donor_title = f"Канал ID {donor_telegram_id}"

            new_donor = DonorChannel(telegram_id=donor_telegram_id, title=donor_title, city_id=target_city_id)
            session.add(new_donor)
            await session.commit() # Коммитим каждую запись, чтобы видеть прогресс и избежать больших транзакций
            results.append(f"✅ Донор '{donor_title}' (ID: `{donor_telegram_id}`) успешно привязан к '{city.title}'.")
            logger.info(f"Админ {message.from_user.id} массово добавил донора {donor_telegram_id} к городу {target_city_id}")
    
    response_text = "Результаты массового добавления доноров:\n\n" + "\n".join(results)
    await message.answer(response_text, parse_mode="Markdown")
    await state.clear()


# --- Удаление городского канала ---
@admin_dp.message(Command("delete_city"))
async def delete_city_command(message: types.Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    async for session in get_session():
        cities = await session.execute(select(City))
        cities = cities.scalars().all()
        if not cities:
            await message.answer("Нет городских каналов для удаления.")
            return

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=city.title, callback_data=f"delete_city_{city.id}")] for city in cities
        ])
        await message.answer("Выберите городской канал, который хотите удалить (вместе со всеми его донорами):", reply_markup=keyboard)
        await state.set_state(AdminStates.waiting_for_city_to_delete)

@admin_dp.callback_query(F.data.startswith("delete_city_"))
async def process_delete_city(callback: types.CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    city_id = int(callback.data.split('_')[-1])

    async for session in get_session():
        city_stmt = select(City).where(City.id == city_id)
        city_result = await session.execute(city_stmt)
        city_to_delete = city_result.scalar_one_or_none()

        if city_to_delete:
            city_title = city_to_delete.title

            # Получаем все донорские каналы, связанные с этим городом
            stmt_donors = select(DonorChannel).where(DonorChannel.city_id == city_id)
            result_donors = await session.execute(stmt_donors)
            donors_of_city = result_donors.scalars().all()
            
            # Собираем ID доноров для удаления связанных постов
            donor_ids_to_delete = [donor.id for donor in donors_of_city]
            logger.info(f"DEBUG: Donor IDs to delete for city {city_id}: {donor_ids_to_delete}")

            # 1. Удаляем все посты, связанные с этими донорами ИЛИ напрямую связанные с городом
            # Это гарантирует, что все посты, которые должны быть удалены вместе с городом, будут удалены.
            if donor_ids_to_delete:
                delete_posts_stmt = delete(Post).where(
                    (Post.donor_channel_id.in_(donor_ids_to_delete)) | (Post.city_id == city_id)
                )
            else:
                # Если доноров нет, удаляем посты только по city_id
                delete_posts_stmt = delete(Post).where(Post.city_id == city_id)

            deleted_posts_result = await session.execute(delete_posts_stmt)
            logger.info(f"Удалено {deleted_posts_result.rowcount} постов, связанных с донорами или напрямую с городом {city_title} (ID: {city_id}).")


            # 2. Удаляем все донорские каналы, привязанные к этому городу
            delete_donors_stmt = delete(DonorChannel).where(DonorChannel.city_id == city_id)
            deleted_donors_result = await session.execute(delete_donors_stmt)
            logger.info(f"Удалено {deleted_donors_result.rowcount} доноров для города {city_title} (ID: {city_id}).")

            # 3. Удаляем сам городской канал
            await session.delete(city_to_delete)
            await session.commit()
            await callback.message.edit_text(f"Городской канал '{city_title}' и все его доноры успешно удалены.")
            logger.info(f"Админ {callback.from_user.id} удалил город: {city_title} ({city_id}) и его доноров.")
        else:
            await callback.message.edit_text("Городской канал не найден.")
    await callback.answer()
    await state.clear()


# --- Включить/выключить авто-режим ---
@admin_dp.message(Command("toggle_mode"))
async def toggle_mode_command(message: types.Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    async for session in get_session():
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

    async for session in get_session():
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
    async for session in get_session():
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
                    response_text += f"    - {donor.title} (ID: `{donor.telegram_id}`)\n"
            else:
                response_text += "  Доноры: Нет\n"
            response_text += "\n"
        
        await message.answer(response_text, parse_mode="Markdown")
    logger.info(f"Админ {message.from_user.id} запросил список каналов.")

# --- Просмотр логов ---
@admin_dp.message(Command("logs"))
async def logs_command(message: types.Message):
    if not await check_admin(message.from_user.id): return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="История публикаций", callback_data="show_published_logs")],
        [InlineKeyboardButton(text="Удаленные дубликаты", callback_data="show_duplicate_logs")]
    ])
    await message.answer("Выберите тип логов:", reply_markup=keyboard)

@admin_dp.callback_query(F.data == "show_published_logs")
async def show_published_logs(callback: types.CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    async for session in get_session():
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

@admin_dp.callback_query(F.data == "show_duplicate_logs")
async def show_duplicate_logs(callback: types.CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    async for session in get_session():
        stmt = select(Post).where(Post.is_duplicate == True).order_by(Post.created_at.desc()).limit(10)
        duplicate_posts = await session.execute(stmt)
        duplicate_posts = duplicate_posts.scalars().all()

        if not duplicate_posts:
            await callback.message.edit_text("Нет записей об удаленных дубликатах.")
            return

        response_text = "Последние удаленные дубликаты:\n\n"
        for post in duplicate_posts:
            city = await session.get(City, post.city_id)
            response_text += (
                f"ID: `{post.id}`\n"
                f"Канал: {city.title if city else 'Неизвестно'}\n"
                f"Текст: {post.original_text[:100]}...\n"
                f"Причина: Дубликат\n" # Здесь можно получить более точную причину из таблицы duplicates
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
    async for session in get_session():
        stmt = select(Post).where(Post.id == post_id)
        result = await session.execute(stmt)
        post = result.scalar_one_or_none()

        if post and post.status == "pending":
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

@admin_dp.callback_query(F.data.startswith("edit_")) # Обработчик кнопки редактирования
async def handle_edit_callback(callback: types.CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    post_id = int(callback.data.split('_')[1])
    async for session in get_session():
        stmt = select(Post).where(Post.id == post_id)
        result = await session.execute(stmt)
        post = result.scalar_one_or_none()

        if post and post.status == "pending":
            await state.update_data(post_id_to_edit=post.id)
            await callback.message.edit_text(
                f"Вы выбрали пост ID {post.id} для редактирования.\n\n"
                f"Текущий текст:\n```\n{post.processed_text[:1000]}\n```\n\n"
                f"Пожалуйста, отправьте новый текст поста. Я заменю им текущий."
            )
            await state.set_state(AdminStates.waiting_for_edited_text)
        else:
            await callback.message.edit_text(f"Пост ID {post.id} уже обработан или не найден для редактирования.")
    await callback.answer()

@admin_dp.message(AdminStates.waiting_for_edited_text) # Обработчик нового текста
async def process_edited_text(message: types.Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    user_data = await state.get_data()
    post_id = user_data.get('post_id_to_edit')
    new_text = message.text.strip()

    if not post_id:
        await message.answer("Ошибка: ID поста для редактирования не найден. Пожалуйста, попробуйте снова.")
        await state.clear()
        return

    async for session in get_session():
        stmt = select(Post).where(Post.id == post_id)
        result = await session.execute(stmt)
        post = result.scalar_one_or_none()

        if post:
            post.processed_text = new_text
            await session.commit()
            await message.answer(f"Пост ID {post.id} успешно обновлен новым текстом.")
            logger.info(f"Админ {message.from_user.id} отредактировал пост {post.id}.")
            # После редактирования можно предложить опубликовать или переформулировать снова
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"publish_{post.id}"),
                    InlineKeyboardButton(text="♻️ Переформулировать", callback_data=f"rephrase_{post.id}"),
                    InlineKeyboardButton(text="❌ Удалить", callback_data=f"delete_{post.id}")
                ]
            ])
            await message.answer("Выберите следующее действие:", reply_markup=keyboard)
        else:
            await message.answer(f"Пост ID {post.id} не найден.")
    await state.clear()


@admin_dp.callback_query(F.data.startswith("rephrase_"))
async def handle_rephrase_callback(callback: types.CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    post_id = int(callback.data.split('_')[1])
    async for session in get_session():
        stmt = select(Post).where(Post.id == post_id)
        result = await session.execute(stmt)
        post = result.scalar_one_or_none()

        if post and post.status == "pending":
            await callback.message.edit_text(f"Переформулирую пост ID {post.id}...")
            rephrased_text = await gigachat_api.rephrase_text(post.original_text)
            if rephrased_text:
                post.processed_text = rephrased_text
                await session.commit()
                # Отправляем обновленный пост на повторную модерацию
                city = await session.get(City, post.city_id)
                if city:
                    await callback.message.edit_text(
                        f"Пост ID {post.id} переформулирован. Новая версия:\n```\n{rephrased_text[:1000]}\n```\n"
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
    async for session in get_session():
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

@admin_dp.message(AdminStates.waiting_for_post_id_to_replace)
async def process_post_id_for_replacement(message: types.Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    try:
        post_id = int(message.text.strip())
        async for session in get_session():
            stmt = select(Post).where(Post.id == post_id, Post.status == "published")
            result = await session.execute(stmt)
            post = result.scalar_one_or_none()

            if not post:
                await message.answer("Пост с таким ID не найден или не опубликован.")
                await state.clear()
                return

            await state.update_data(post_to_replace_id=post_id)
            await message.answer(
                f"Вы выбрали пост ID {post.id}. Текущий текст:\n\n"
                f"```\n{post.processed_text}\n```\n\n"
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

    async for session in get_session():
        stmt = select(Post).where(Post.id == post_id_to_replace)
        result = await session.execute(stmt)
        post = result.scalar_one_or_none()

        if post:
            # В реальном Telegram API нет прямого метода "заменить сообщение" в канале.
            # Обычно это делается так:
            # 1. Удаляется старое сообщение (если есть его message_id в Telegram)
            # 2. Отправляется новое сообщение
            # Для простоты, мы просто обновим processed_text в БД.
            # Если нужно реальное обновление в Telegram, потребуется хранить telegram_message_id в Post
            # и использовать bot.edit_message_text или bot.delete_message + bot.send_message
            post.processed_text = new_text
            post.published_at = func.now() # Обновляем время публикации
            await session.commit()
            await message.answer(f"Текст поста ID {post_id_to_replace} успешно обновлен в базе данных.")
            logger.info(f"Админ {message.from_user.id} заменил текст поста {post_id_to_replace}.")
            # TODO: Если нужно, отправить обновленный пост в Telegram канал
            # Для этого потребуется сохранить telegram_message_id при первой публикации
            # и использовать admin_bot.edit_message_text(chat_id=post.city.telegram_id, message_id=post.telegram_message_id, text=new_text)
        else:
            await message.answer("Пост не найден.")
    await state.clear()

# --- Отправка тестового сообщения ---
@admin_dp.message(Command("send_test_message"))
async def send_test_message_command(message: types.Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    async for session in get_session():
        cities = await session.execute(select(City))
        cities = cities.scalars().all()
        if not cities:
            await message.answer("Нет городских каналов для отправки тестового сообщения.")
            return

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=city.title, callback_data=f"select_city_test_message_{city.id}")] for city in cities
        ])
        await message.answer("Выберите городской канал, в который хотите отправить тестовое сообщение:", reply_markup=keyboard)
        await state.set_state(AdminStates.waiting_for_city_to_send_test_message)

@admin_dp.callback_query(F.data.startswith("select_city_test_message_"))
async def process_select_city_test_message(callback: types.CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    city_id = int(callback.data.split('_')[-1])
    async for session in get_session():
        city = await session.get(City, city_id)
        if city:
            await state.update_data(target_city_telegram_id=city.telegram_id, target_city_title=city.title)
            await callback.message.edit_text(f"Вы выбрали канал '{city.title}' (ID: `{city.telegram_id}`).\n\nТеперь введите текст тестового сообщения:")
            await state.set_state(AdminStates.waiting_for_test_message_text)
        else:
            await callback.message.edit_text("Канал не найден.")
    await callback.answer()

@admin_dp.message(AdminStates.waiting_for_test_message_text)
async def process_test_message_text(message: types.Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    user_data = await state.get_data()
    target_telegram_channel_id = user_data.get('target_city_telegram_id')
    target_city_title = user_data.get('target_city_title')
    test_text = message.text.strip()

    if not target_telegram_channel_id:
        await message.answer("Ошибка: Целевой канал не определен. Пожалуйста, попробуйте снова.")
        await state.clear()
        return

    try:
        await admin_bot.send_message(chat_id=target_telegram_channel_id, text=f"Тестовое сообщение от админа:\n\n{test_text}")
        await message.answer(f"Тестовое сообщение успешно отправлено в канал '{target_city_title}' (ID: `{target_telegram_channel_id}`).")
        logger.info(f"Админ {message.from_user.id} отправил тестовое сообщение в канал {target_telegram_channel_id}.")
    except Exception as e:
        await message.answer(f"Ошибка при отправке тестового сообщения: {e}")
        logger.error(f"Ошибка при отправке тестового сообщения в канал {target_telegram_channel_id}: {e}")
    finally:
        await state.clear()


# Запуск админ-бота
async def start_admin_bot(parser_instance): # <-- ИСПРАВЛЕНО: Принимаем parser_instance
    logger.info("Запуск админского Telegram бота...")
    await set_telegram_parser_instance(parser_instance) # Устанавливаем экземпляр парсера
    # Пропускаем все накопившиеся обновления
    await admin_dp.start_polling(admin_bot)
    logger.info("Админский Telegram бот остановлен.")

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
        await start_admin_bot(mock_parser) # Передаем фиктивный парсер
    asyncio.run(debug_main())
