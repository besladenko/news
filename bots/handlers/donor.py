from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from infra.db import AsyncSessionLocal
from core.models import DonorChannel, City
from aiogram.filters import Command

router = Router()

class DonorFSM(StatesGroup):
    waiting_for_city = State()
    waiting_for_link = State()
    waiting_for_mask = State()
    waiting_for_donor_for_mask = State()
    waiting_for_new_mask = State()

@router.message(Command("donor"))
async def donor_menu(message: types.Message, state: FSMContext):
    builder = ReplyKeyboardBuilder()
    builder.button(text="Добавить донора")
    builder.button(text="Добавить маску для донора")
    builder.button(text="Меню")
    await message.answer(
        "Выбери действие с донорами:",
        reply_markup=builder.as_markup(resize_keyboard=True)
    )
    await state.clear()

@router.message(F.text == "Меню")
async def main_menu(message: types.Message, state: FSMContext):
    from bots.handlers.city import start_menu
    await start_menu(message, state)

@router.message(F.text == "Добавить донора")
async def add_donor_start(message: types.Message, state: FSMContext):
    async with AsyncSessionLocal() as session:
        res = await session.execute(City.__table__.select())
        cities = res.fetchall()
    if not cities:
        await message.answer("Сначала добавьте городской канал!", reply_markup=types.ReplyKeyboardRemove())
        await state.clear()
        return
    builder = ReplyKeyboardBuilder()
    for row in cities:
        city = row[0] if isinstance(row, tuple) else row
        builder.button(text=f"{city.title} ({city.channel_id})")
    builder.button(text="Меню")
    await message.answer(
        "Выберите канал, к которому привязать донора:",
        reply_markup=builder.as_markup(resize_keyboard=True)
    )
    await state.set_state(DonorFSM.waiting_for_city)

@router.message(DonorFSM.waiting_for_city)
async def add_donor_link(message: types.Message, state: FSMContext):
    if message.text == "Меню":
        await main_menu(message, state)
        return
    city_username = message.text.split("(")[-1].replace(")", "")
    await state.update_data(city_username=city_username)
    await message.answer("Пришлите ссылку на канал-донора:", reply_markup=types.ReplyKeyboardRemove())
    await state.set_state(DonorFSM.waiting_for_link)

@router.message(DonorFSM.waiting_for_link)
async def add_donor_mask(message: types.Message, state: FSMContext):
    link = message.text.strip()
    if not link.startswith("https://t.me/"):
        await message.answer("Ссылка должна начинаться с https://t.me/")
        return
    donor_channel_id = link.replace("https://t.me/", "").replace("@", "")
    data = await state.get_data()
    city_username = data.get("city_username")
    async with AsyncSessionLocal() as session:
        city_res = await session.execute(City.__table__.select().where(City.channel_id == city_username))
        city = city_res.scalar_one_or_none()
        if not city:
            await message.answer("Не найден город.", reply_markup=types.ReplyKeyboardRemove())
            await state.clear()
            return
        donor_res = await session.execute(
            DonorChannel.__table__.select().where(
                DonorChannel.channel_id == donor_channel_id, DonorChannel.city_id == city.id
            )
        )
        if donor_res.scalar_one_or_none():
            await message.answer("Такой донор уже добавлен к этому каналу!", reply_markup=types.ReplyKeyboardRemove())
            await state.clear()
            return
        await state.update_data(donor_channel_id=donor_channel_id, city_id=city.id)
    await message.answer("Пришлите маску для постов (можно с markdown):", reply_markup=types.ReplyKeyboardRemove())
    await state.set_state(DonorFSM.waiting_for_mask)

@router.message(DonorFSM.waiting_for_mask)
async def add_donor_save(message: types.Message, state: FSMContext):
    mask = message.text.strip()
    data = await state.get_data()
    donor_channel_id = data.get("donor_channel_id")
    city_id = data.get("city_id")
    link = f"https://t.me/{donor_channel_id}"
    async with AsyncSessionLocal() as session:
        donor = DonorChannel(
            title=link,
            channel_id=donor_channel_id,
            city_id=city_id,
            mask_pattern=mask
        )
        session.add(donor)
        try:
            await session.commit()
            await message.answer("Донор и маска успешно добавлены.", reply_markup=types.ReplyKeyboardRemove())
        except Exception:
            await message.answer("Такой донор уже существует!", reply_markup=types.ReplyKeyboardRemove())
        await state.clear()

# --- Маска отдельно к существующему дону ---

@router.message(F.text == "Добавить маску для донора")
async def add_mask_choose_donor(message: types.Message, state: FSMContext):
    async with AsyncSessionLocal() as session:
        res = await session.execute(DonorChannel.__table__.select())
        donors = res.fetchall()
    if not donors:
        await message.answer("Нет доноров, сначала добавьте!", reply_markup=types.ReplyKeyboardRemove())
        await state.clear()
        return
    builder = ReplyKeyboardBuilder()
    for row in donors:
        donor = row[0] if isinstance(row, tuple) else row
        builder.button(text=f"{donor.title} ({donor.channel_id})")
    builder.button(text="Меню")
    await message.answer(
        "Выберите донора для обновления маски:",
        reply_markup=builder.as_markup(resize_keyboard=True)
    )
    await state.set_state(DonorFSM.waiting_for_donor_for_mask)

@router.message(DonorFSM.waiting_for_donor_for_mask)
async def wait_for_new_mask(message: types.Message, state: FSMContext):
    if message.text == "Меню":
        await main_menu(message, state)
        return
    donor_channel_id = message.text.split("(")[-1].replace(")", "")
    await state.update_data(donor_channel_id=donor_channel_id)
    await message.answer("Пришлите новую маску для этого донора:", reply_markup=types.ReplyKeyboardRemove())
    await state.set_state(DonorFSM.waiting_for_new_mask)

@router.message(DonorFSM.waiting_for_new_mask)
async def save_new_mask(message: types.Message, state: FSMContext):
    new_mask = message.text.strip()
    data = await state.get_data()
    donor_channel_id = data.get("donor_channel_id")
    async with AsyncSessionLocal() as session:
        res = await session.execute(DonorChannel.__table__.select().where(DonorChannel.channel_id == donor_channel_id))
        donor = res.scalar_one_or_none()
        if not donor:
            await message.answer("Донор не найден!", reply_markup=types.ReplyKeyboardRemove())
            await state.clear()
            return
        donor.mask_pattern = new_mask
        session.add(donor)
        await session.commit()
        await message.answer("Маска обновлена!", reply_markup=types.ReplyKeyboardRemove())
        await state.clear()
