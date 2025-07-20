from aiogram import Router, types, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from core.models import DonorChannel, City
from infra.db import AsyncSessionLocal
from sqlalchemy.future import select

router = Router()

# --- FSM состояния для добавления донора ---
class AddDonorState(StatesGroup):
    waiting_for_city = State()
    waiting_for_donor_link = State()
    waiting_for_mask = State()

# --- FSM состояния для изменения маски ---
class EditMaskState(StatesGroup):
    waiting_for_city = State()
    waiting_for_donor = State()
    waiting_for_new_mask = State()

# --- Добавить донора (через меню) ---
@router.message(F.text == "Добавить донора")
async def start_add_donor(message: types.Message, state: FSMContext):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(City))
        cities = result.scalars().all()

    if not cities:
        await message.answer("Нет добавленных городов. Сначала добавьте хотя бы один канал.")
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
    await callback.message.answer("Пришлите ссылку на канал-донора:")
    await state.set_state(AddDonorState.waiting_for_donor_link)
    await callback.answer()

@router.message(StateFilter(AddDonorState.waiting_for_donor_link))
async def donor_link_received(message: types.Message, state: FSMContext):
    link = message.text.strip()
    if not link.startswith("https://t.me/"):
        await message.answer("Ошибка! Пришлите ссылку на канал-донора в формате https://t.me/...")
        await state.clear()
        return

    await state.update_data(donor_link=link)
    await message.answer(
        "Пришлите маску для обработки постов из этого донора (можно с markdown):"
    )
    await state.set_state(AddDonorState.waiting_for_mask)

@router.message(StateFilter(AddDonorState.waiting_for_mask))
async def donor_mask_received(message: types.Message, state: FSMContext):
    data = await state.get_data()
    city_id = data["city_id"]
    link = data["donor_link"]
    mask = message.text.strip()
    channel_id = link.split("/")[-1]

    async with AsyncSessionLocal() as session:
        # Проверка на дубликат по channel_id+city_id
        result = await session.execute(
            select(DonorChannel).where(
                DonorChannel.channel_id == channel_id,
                DonorChannel.city_id == city_id
            )
        )
        existing_donor = result.scalar_one_or_none()
        if existing_donor:
            await message.answer(
                "Такой донор уже добавлен к этому каналу!",
                parse_mode="HTML"
            )
            await state.clear()
            return

        # --- Добавление нового донора ---
        donor = DonorChannel(
            title=link,
            channel_id=channel_id,
            city_id=city_id,
            mask_pattern=mask
        )
        session.add(donor)
        await session.commit()
        await message.answer(
            f"Донор <b>{link}</b> добавлен к городу с маской:\n<code>{mask}</code>",
            parse_mode="HTML"
        )
    await state.clear()

# --- Изменить маску донора (отдельное меню) ---
@router.message(F.text == "Изменить маску донора")
async def start_edit_mask(message: types.Message, state: FSMContext):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(City))
        cities = result.scalars().all()
    if not cities:
        await message.answer("Нет городов.")
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
        await callback.message.answer("В этом городе нет доноров.")
        await state.clear()
        await callback.answer()
        return

    buttons = [
        [types.InlineKeyboardButton(text=donor.title, callback_data=f"editmask_donor_{donor.id}")]
        for donor in donors
    ]
    kb = types.InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.answer("Выберите донора:", reply_markup=kb)
    await state.set_state(EditMaskState.waiting_for_donor)
    await callback.answer()

@router.callback_query(StateFilter(EditMaskState.waiting_for_donor), F.data.startswith("editmask_donor_"))
async def prompt_new_mask(callback: types.CallbackQuery, state: FSMContext):
    donor_id = int(callback.data.replace("editmask_donor_", ""))
    await state.update_data(donor_id=donor_id)
    async with AsyncSessionLocal() as session:
        donor = await session.get(DonorChannel, donor_id)
    await callback.message.answer(
        f"Текущая маска:\n<code>{donor.mask_pattern}</code>\n\nВведите новую маску:",
        parse_mode="HTML"
    )
    await state.set_state(EditMaskState.waiting_for_new_mask)
    await callback.answer()

@router.message(StateFilter(EditMaskState.waiting_for_new_mask))
async def update_mask(message: types.Message, state: FSMContext):
    data = await state.get_data()
    donor_id = data["donor_id"]
    new_mask = message.text.strip()
    async with AsyncSessionLocal() as session:
        donor = await session.get(DonorChannel, donor_id)
        donor.mask_pattern = new_mask
        await session.commit()
    # Возвращаем главное меню (если используешь admin_main_kb — импортируй)
    await message.answer(
        f"Маска донора обновлена:\n<code>{new_mask}</code>",
        parse_mode="HTML"
    )
    await state.clear()
