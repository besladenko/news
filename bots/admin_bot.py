# bots/admin_bot.py
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from loguru import logger
from sqlalchemy.future import select # select остается из future
from sqlalchemy import func, delete # <-- Исправлено: delete импортируется из sqlalchemy
from sqlalchemy.ext.asyncio import AsyncSession # Импорт AsyncSession для типизации

from config import config
from db.database import get_session
from db.models import Admin, City, DonorChannel, Post, Duplicate, ChannelSetting
from core.gigachat import gigachat_api
from bots.news_bot import publish_post # Импортируем функцию публикации из основного бота
import asyncio

# Инициализация админ-бота
admin_bot = Bot(token=config.ADMIN_BOT_TOKEN)
admin_dp = Dispatcher()

# Состояния для FSM админ-бота
class AdminStates(StatesGroup):
    """Состояния для диалогов админ-бота."""
    waiting_for_city_name = State()
    waiting_for_city_id = State()
    waiting_for_donor_name = State()
    waiting_for_donor_id = State()
    waiting_for_city_to_assign_donor = State()
    waiting_for_city_to_toggle_mode = State()
    waiting_for_post_id_to_rephrase = State()
    waiting_for_post_id_to_replace = State()
    waiting_for_new_text_for_replacement = State()


# --- Middleware для проверки админ-прав ---
# Это упрощенная проверка. В реальном приложении нужна более надежная система
# Например, с использованием декораторов или более сложного middleware
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
        "/toggle_mode - Включить/выключить авто-режим для канала\n"
        "/list_channels - Список всех городских каналов\n"
        "/logs - Просмотр логов публикаций/дубликатов\n"
        "/replace_news - Заменить опубликованную новость"
    )
    logger.info(f"Админ {message.from_user.id} запустил админ-бота.")

# --- Добавление нового городского канала ---
@admin_dp.message(Command("add_city"))
async def add_city_command(message: types.Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    await message.answer("Введите Telegram ID нового городского канала (например, -1001234567890):")
    await state.set_state(AdminStates.waiting_for_city_id)

@admin_dp.message(AdminStates.waiting_for_city_id)
async def process_city_id(message: types.Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    try:
        telegram_id = int(message.text.strip())
        if not str(telegram_id).startswith('-100'):
            await message.answer("Telegram ID канала должен начинаться с -100. Попробуйте еще раз.")
            return

        await state.update_data(telegram_id=telegram_id)
        await message.answer("Теперь введите название этого канала:")
        await state.set_state(AdminStates.waiting_for_city_name)
    except ValueError:
        await message.answer("Некорректный Telegram ID. Пожалуйста, введите число.")

@admin_dp.message(AdminStates.waiting_for_city_name)
async def process_city_name(message: types.Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    city_name = message.text.strip()
    user_data = await state.get_data()
    telegram_id = user_data['telegram_id']

    async for session in get_session():
        existing_city = await session.execute(select(City).where(City.telegram_id == telegram_id))
        if existing_city.scalar_one_or_none():
            await message.answer("Канал с таким Telegram ID уже существует.")
            await state.clear()
            return

        new_city = City(telegram_id=telegram_id, title=city_name)
        session.add(new_city)
        await session.commit()
        await message.answer(f"Городской канал '{city_name}' (ID: {telegram_id}) успешно добавлен!")
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
    await callback.message.edit_text("Введите Telegram ID канала-донора (например, @news_channel_name или -1001234567890):")
    await state.set_state(AdminStates.waiting_for_donor_id)
    await callback.answer()

@admin_dp.message(AdminStates.waiting_for_donor_id)
async def process_donor_id(message: types.Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    donor_input = message.text.strip()
    user_data = await state.get_data()
    target_city_id = user_data['target_city_id']

    # Попытка определить ID канала по имени или числовому ID
    try:
        if donor_input.startswith('@'):
            # В реальном приложении здесь нужна логика Telethon для получения ID по username
            # Для простоты, пока будем считать, что пользователь вводит числовой ID
            await message.answer("Для доноров, пожалуйста, введите числовой Telegram ID (начинается с -100 или просто числовой ID публичного канала).")
            return
        else:
            donor_telegram_id = int(donor_input)

        async for session in get_session():
            # Проверим, существует ли уже такой донор
            existing_donor = await session.execute(select(DonorChannel).where(DonorChannel.telegram_id == donor_telegram_id))
            if existing_donor.scalar_one_or_none():
                await message.answer("Этот донор уже добавлен. Если вы хотите привязать его к другому городу, удалите его сначала.")
                await state.clear()
                return

            # В реальном приложении здесь можно получить название канала через Telethon
            donor_title = f"Канал ID {donor_telegram_id}" # Заглушка

            new_donor = DonorChannel(telegram_id=donor_telegram_id, title=donor_title, city_id=target_city_id)
            session.add(new_donor)
            await session.commit()

            city = await session.execute(select(City).where(City.id == target_city_id))
            city_title = city.scalar_one().title

            await message.answer(f"Донор '{donor_title}' (ID: {donor_telegram_id}) успешно привязан к каналу '{city_title}'!")
            logger.info(f"Админ {message.from_user.id} привязал донора {donor_telegram_id} к городу {target_city_id}")
        await state.clear()
    except ValueError:
        await message.answer("Некорректный Telegram ID донора. Пожалуйста, введите число.")
    except Exception as e:
        await message.answer(f"Произошла ошибка при добавлении донора: {e}")
        logger.error(f"Ошибка при добавлении донора: {e}")
    finally:
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
                # ИСПРАВЛЕНО: Передаем media_paths в publish_post
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
                        f"Пост ID {post.id} переформулирован. Новая версия:\n{rephrased_text[:500]}...\n"
                        f"Выберите действие:",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [
                                InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"publish_{post.id}"),
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


# Запуск админ-бота
async def start_admin_bot():
    logger.info("Запуск админского Telegram бота...")
    # Пропускаем все накопившиеся обновления
    await admin_dp.start_polling(admin_bot)
    logger.info("Админский Telegram бот остановлен.")

if __name__ == "__main__":
    # Этот блок не будет запускаться напрямую, так как бот запускается через main.py
    # Но для отладки можно временно запустить
    async def debug_main():
        await start_admin_bot()
    asyncio.run(debug_main())
