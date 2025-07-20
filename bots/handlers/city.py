from aiogram import Router, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from sqlalchemy.ext.asyncio import AsyncSession
from core.models import City
from infra.db import AsyncSessionLocal

router = Router()

# Главное меню (ReplyKeyboard)
admin_main_kb = types.ReplyKeyboardMarkup(
    keyboard=[
        [types.KeyboardButton(text="Добавить канал")],
        [types.KeyboardButton(text="Добавить донора")],
        [types.KeyboardButton(text="Показать список каналов")],
        [types.KeyboardButton(text="Модерация: вкл")],
    ],
    resize_keyboard=True
)

# Состояния FSM
class AddChannelState(StatesGroup):
    waiting_for_link = State()

@router.message(Command("start"))
async def start_menu(message: types.Message):
    await message.answer(
        "Привет! Я бот для работы с каналами в Telegram.",
        reply_markup=admin_main_kb
    )

# Запуск сценария добавления канала
@router.message(F.text == "Добавить канал")
async def fsm_add_channel_start(message: types.Message, state: FSMContext):
    await message.answer(
        "Пришли ссылку на канал:",
        reply_markup=types.ReplyKeyboardRemove()
    )
    await state.set_state(AddChannelState.waiting_for_link)

# Приём ссылки и добавление в БД
@router.message(StateFilter(AddChannelState.waiting_for_link))
async def fsm_add_channel_link(message: types.Message, state: FSMContext):
    link = message.text.strip()
    # Быстрая проверка на валидность ссылки (упрощённо)
    if not link.startswith("https://t.me/"):
        await message.answer(
            "Ошибка! Пришли ссылку на канал в формате https://t.me/...",
            reply_markup=admin_main_kb
        )
        await state.clear()
        return

    channel_id = link.split("/")[-1]
    city = City(title=link, channel_id=channel_id, link=link)
    async with AsyncSessionLocal() as session:
        session.add(city)
        await session.commit()
        await message.answer(
            f"Городской канал добавлен!\ncity_id: {city.id}",
            reply_markup=admin_main_kb
        )
    await state.clear()
