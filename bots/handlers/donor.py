from aiogram import Router, types, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from core.models import DonorChannel, City
from infra.db import AsyncSessionLocal
from sqlalchemy.future import select
import re

router = Router()

admin_main_kb = types.ReplyKeyboardMarkup(
    keyboard=[
        [types.KeyboardButton(text="Добавить канал")],
        [types.KeyboardButton(text="Добавить донора")],
        [types.KeyboardButton(text="Изменить маску донора")],
        [types.KeyboardButton(text="Найти по маске и опубликовать")],
        [types.KeyboardButton(text="Показать список каналов")],
        [types.KeyboardButton(text="Модерация: вкл")],
    ],
    resize_keyboard=True
)

# ================================
# Вспомогательные функции

def normalize_text(text: str) -> str:
    """Нормализация перевода строк и невидимых символов."""
    if not text:
        return ""
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = re.sub(r"[\u200b\u200c\u200d\uFEFF]", "", text)
    return text.strip()

def remove_signature_from_end(post_text: str, signature: str) -> str:
    """
    Удаляет подпись (маску) с конца поста, даже если между ними 1-2 таба или пустые строки.
    """
    norm_text = normalize_text(post_text)
    norm_sign = normalize_text(signature)
    if not norm_sign:
        return norm_text
    # Разрешаем в конце до 3 любых whitespace перед маской (включая табы и \n)
    # и до 3 любых whitespace после маски до конца строки
    # Маска в re.escape, чтобы не было багов на спецсимволах
    pattern = rf"((\s|\t|\n){{0,3}}{re.escape(norm_sign)}(\s|\t|\n){{0,3}})$"
    cleaned = re.sub(pattern, "", norm_text, flags=re.DOTALL)
    return cleaned.strip()

def clean_mask(mask: str) -> str:
    # Убираем невидимые символы и неразрывные пробелы
    mask = re.sub(r"[\u200b\u200c\u200d\uFEFF]", "", mask or "")
    return mask.strip()

# ================================
# Состояния FSM

class AddDonorState(StatesGroup):
    waiting_for_city = State()
    waiting_for_donor_link = State()
    waiting_for_mask = State()

class EditMaskState(StatesGroup):
    waiting_for_city = State()
    waiting_for_donor = State()
    waiting_for_new_mask = State()

class FindByMaskState(StatesGroup):
    waiting_for_city = State()
    waiting_for_donor = State()

# ================================
# Добавить донора

@router.message(F.text == "Добавить донора")
async def start_add_donor(message: types.Message, state: FSMContext):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(City))
        cities = result.scalars().all()
    if not cities:
        await message.answer("Нет добавленных городов. Сначала добавьте хотя бы один канал.",
                            reply_markup=admin_main_kb)
        return
    buttons = [
        [types.InlineKeyboardButton(text=city.title, callback_data=f"adddonor_city_{city.id}")]
        for city in cities
    ]
    kb = types.InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer("Выберите канал, к которому добавить донора:", reply_markup=kb)
    await state.set_state(AddDonorState.waiting_for_city)

@router.callback_query(StateFilter(AddDonorState.waiting_for_city), F.data.startswith("adddonor_city_"))
async def city_chosen(callback: types.CallbackQuery, state: FSMContext):
    city_id = int(callback.data.replace("adddonor_city_", ""))
    await state.update_data(city_id=city_id)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Пришлите ссылку на канал-донора:")
    await state.set_state(AddDonorState.waiting_for_donor_link)
    await callback.answer()

@router.message(StateFilter(AddDonorState.waiting_for_donor_link))
async def donor_link_received(message: types.Message, state: FSMContext):
    link = message.text.strip()
    if not link.startswith("https://t.me/"):
        await message.answer("Ошибка! Пришлите ссылку на канал-донора в формате https://t.me/...",
                            reply_markup=admin_main_kb)
        await state.clear()
        return

    await state.update_data(donor_link=link)
    await message.answer("Пришлите маску для обработки постов из этого донора (можно с markdown):")
    await state.set_state(AddDonorState.waiting_for_mask)

@router.message(StateFilter(AddDonorState.waiting_for_mask))
async def donor_mask_received(message: types.Message, state: FSMContext):
    data = await state.get_data()
    city_id = data["city_id"]
    link = data["donor_link"]
    mask_raw = message.text.strip()
    mask = clean_mask(mask_raw)
    channel_id = link.split("/")[-1]

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(DonorChannel).where(
                DonorChannel.channel_id == channel_id,
                DonorChannel.city_id == city_id
            )
        )
        existing_donor = result.scalar_one_or_none()
        if existing_donor:
            await message.answer("Такой донор уже добавлен к этому каналу!",
                                reply_markup=admin_main_kb)
            await state.clear()
            return

        donor = DonorChannel(
            title=link,
            channel_id=channel_id,
            city_id=city_id,
            mask_pattern=mask
        )
        session.add(donor)
        await session.commit()
        await message.answer(
            f"Донор <b>{link}</b> добавлен к городу с маской:\n<pre>{repr(mask)}</pre>\nHEX: <code>{mask.encode().hex()}</code>",
            parse_mode="HTML",
            reply_markup=admin_main_kb
        )
    await state.clear()

# ================================
# Изменить маску донора

@router.message(F.text == "Изменить маску донора")
async def start_edit_mask(message: types.Message, state: FSMContext):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(City))
        cities = result.scalars().all()
    if not cities:
        await message.answer("Нет городов.", reply_markup=admin_main_kb)
        return

    buttons = [
        [types.InlineKeyboardButton(text=city.title, callback_data=f"editmask_city_{city.id}")]
        for city in cities
    ]
    kb = types.InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer("Выберите город:", reply_markup=kb)
    await state.set_state(EditMaskState.waiting_for_city)

@router.callback_query(StateFilter(EditMaskState.waiting_for_city), F.data.startswith("editmask_city_"))
async def choose_donor_city(callback: types.CallbackQuery, state: FSMContext):
    city_id = int(callback.data.replace("editmask_city_", ""))
    await state.update_data(city_id=city_id)
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(DonorChannel).where(DonorChannel.city_id == city_id))
        donors = result.scalars().all()
    if not donors:
        await callback.message.answer("В этом городе нет доноров.", reply_markup=admin_main_kb)
        await state.clear()
        await callback.answer()
        return

    buttons = [
        [types.InlineKeyboardButton(text=donor.title, callback_data=f"editmask_donor_{donor.id}")]
        for donor in donors
    ]
    kb = types.InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Выберите донора:", reply_markup=kb)
    await state.set_state(EditMaskState.waiting_for_donor)
    await callback.answer()

@router.callback_query(StateFilter(EditMaskState.waiting_for_donor), F.data.startswith("editmask_donor_"))
async def prompt_new_mask(callback: types.CallbackQuery, state: FSMContext):
    donor_id = int(callback.data.replace("editmask_donor_", ""))
    await state.update_data(donor_id=donor_id)
    async with AsyncSessionLocal() as session:
        donor = await session.get(DonorChannel, donor_id)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"Текущая маска:\n<pre>{repr(donor.mask_pattern)}</pre>\nHEX: <code>{donor.mask_pattern.encode().hex()}</code>\n\nВведите новую маску:",
        parse_mode="HTML"
    )
    await state.set_state(EditMaskState.waiting_for_new_mask)
    await callback.answer()

@router.message(StateFilter(EditMaskState.waiting_for_new_mask))
async def update_mask(message: types.Message, state: FSMContext):
    data = await state.get_data()
    donor_id = data["donor_id"]
    new_mask_raw = message.text.strip()
    new_mask = clean_mask(new_mask_raw)
    async with AsyncSessionLocal() as session:
        donor = await session.get(DonorChannel, donor_id)
        donor.mask_pattern = new_mask
        await session.commit()
    await message.answer(
        f"Маска донора обновлена:\n<pre>{repr(new_mask)}</pre>\nHEX: <code>{new_mask.encode().hex()}</code>",
        parse_mode="HTML",
        reply_markup=admin_main_kb
    )
    await state.clear()

# ================================
# Найти по маске и опубликовать (тест)

@router.message(F.text == "Найти по маске и опубликовать")
async def start_find_by_mask(message: types.Message, state: FSMContext):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(City))
        cities = result.scalars().all()
    if not cities:
        await message.answer("Нет городов.", reply_markup=admin_main_kb)
        return
    buttons = [
        [types.InlineKeyboardButton(text=city.title, callback_data=f"findbymask_city_{city.id}")]
        for city in cities
    ]
    kb = types.InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer("Выберите город:", reply_markup=kb)
    await state.set_state(FindByMaskState.waiting_for_city)

@router.callback_query(StateFilter(FindByMaskState.waiting_for_city), F.data.startswith("findbymask_city_"))
async def find_by_mask_choose_donor(callback: types.CallbackQuery, state: FSMContext):
    city_id = int(callback.data.replace("findbymask_city_", ""))
    await state.update_data(city_id=city_id)
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(DonorChannel).where(DonorChannel.city_id == city_id))
        donors = result.scalars().all()
    if not donors:
        await callback.message.answer("В этом городе нет доноров.", reply_markup=admin_main_kb)
        await state.clear()
        await callback.answer()
        return
    buttons = [
        [types.InlineKeyboardButton(text=donor.title, callback_data=f"findbymask_donor_{donor.id}")]
        for donor in donors
    ]
    kb = types.InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Выберите донора:", reply_markup=kb)
    await state.set_state(FindByMaskState.waiting_for_donor)
    await callback.answer()

@router.callback_query(StateFilter(FindByMaskState.waiting_for_donor), F.data.startswith("findbymask_donor_"))
async def find_and_publish(callback: types.CallbackQuery, state: FSMContext):
    donor_id = int(callback.data.replace("findbymask_donor_", ""))
    data = await state.get_data()
    city_id = data["city_id"]

    async with AsyncSessionLocal() as session:
        donor = await session.get(DonorChannel, donor_id)
        city = await session.get(City, city_id)

    mask_pattern = donor.mask_pattern
    donor_channel_id = donor.channel_id

    from telethon import TelegramClient
    from config.settings import settings

    async with TelegramClient("anon", settings.TG_API_ID, settings.TG_API_HASH) as client:
        await client.start()
        messages = await client.get_messages(donor_channel_id, limit=50)
        found = None
        for msg in messages:
            if not msg.text:
                continue
            # Очищаем подпись
            cleaned_text = remove_signature_from_end(msg.text, mask_pattern)
            # Если исходный текст != очищенному, значит нашли подпись
            if cleaned_text != normalize_text(msg.text):
                found = (msg, cleaned_text)
                break

    if found:
        from bots.news_bot import bot as news_bot
        # Публикуем уже очищенный текст!
        await news_bot.send_message(
            city.channel_id, found[1]
        )
        await callback.message.answer(
            f"Новость найдена и опубликована:\n\n{found[1][:2000]}",
            parse_mode="HTML",
            reply_markup=admin_main_kb
        )
    else:
        await callback.message.answer("Новость по маске не найдена в последних 50 постах.", reply_markup=admin_main_kb)
    await state.clear()
    await callback.answer()
