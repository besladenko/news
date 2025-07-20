from aiogram import Router, types, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from core.models import DonorChannel, City
from infra.db import AsyncSessionLocal
from sqlalchemy.future import select

router = Router()

# FSM для добавления донора
class AddDonorState(StatesGroup):
    waiting_for_city = State()
    waiting_for_donor_link = State()
    waiting_for_mask = State()

# Старт: пользователь нажал "Добавить донора" в меню
@router.message(F.text == "Добавить донора")
async def start_add_donor(message: types.Message, state: FSMContext):
    # Подгружаем список городов из БД для выбора
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(City))
        cities = result.scalars().all()

    if not cities:
        await message.answer("Нет добавленных городов. Сначала добавьте хотя бы один канал.")
        return

    # Делаем инлайн-клавиатуру для выбора города
    buttons = [
        [types.InlineKeyboardButton(text=city.title, callback_data=f"adddonor_city_{city.id}")]
        for city in cities
    ]
    kb = types.InlineKeyboardMarkup(inline_keyboard=buttons)

    await message.answer("Выберите канал, к которому добавить донора:", reply_markup=kb)
    await state.set_state(AddDonorState.waiting_for_city)

# Пользователь выбрал канал (callback)
@router.callback_query(StateFilter(AddDonorState.waiting_for_city), F.data.startswith("adddonor_city_"))
async def city_chosen(callback: types.CallbackQuery, state: FSMContext):
    city_id = int(callback.data.replace("adddonor_city_", ""))
    await state.update_data(city_id=city_id)
    await callback.message.answer("Пришлите ссылку на канал-донора:")
    await state.set_state(AddDonorState.waiting_for_donor_link)
    await callback.answer()  # убираем "часики" в Telegram

# Пользователь прислал ссылку на донора
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

# Пользователь прислал маску (она сохраняется как есть)
@router.message(StateFilter(AddDonorState.waiting_for_mask))
async def donor_mask_received(message: types.Message, state: FSMContext):
    data = await state.get_data()
    city_id = data["city_id"]
    link = data["donor_link"]
    mask = message.text.strip()

    channel_id = link.split("/")[-1]

    donor = DonorChannel(
        title=link,
        channel_id=channel_id,
        city_id=city_id,
        mask_pattern=mask
    )
    async with AsyncSessionLocal() as session:
        session.add(donor)
        await session.commit()

    await message.answer(
        f"Донор <b>{link}</b> добавлен к городу с маской:\n<code>{mask}</code>",
        parse_mode="HTML"
    )
    await state.clear()
