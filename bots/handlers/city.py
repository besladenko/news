from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from core.models import City
from infra.db import AsyncSessionLocal
from sqlalchemy.future import select

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

class AddCityState(StatesGroup):
    waiting_for_link = State()

@router.message(Command("start"))
async def start_menu(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(".", reply_markup=types.ReplyKeyboardRemove())
    await message.answer(
        "Привет! Я бот для работы с каналами в Telegram.\nВыбери действие:",
        reply_markup=admin_main_kb
    )

@router.message(F.text == "Добавить канал")
async def add_city_handler(message: types.Message, state: FSMContext):
    await state.set_state(AddCityState.waiting_for_link)
    await message.answer(".", reply_markup=types.ReplyKeyboardRemove())
    await message.answer(
        "Пришли ссылку на канал (например, https://t.me/your_channel):",
        reply_markup=types.ReplyKeyboardRemove()
    )

@router.message(AddCityState.waiting_for_link)
async def process_city_link(message: types.Message, state: FSMContext):
    link = message.text.strip()
    if not link.startswith("https://t.me/"):
        await message.answer(".", reply_markup=types.ReplyKeyboardRemove())
        await message.answer(
            "Ошибка! Пришли ссылку на канал в формате https://t.me/...",
            reply_markup=admin_main_kb
        )
        await state.clear()
        return

    channel_id = link.split("/")[-1]
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(City).where(City.channel_id == channel_id))
        exists = result.scalar_one_or_none()
        if exists:
            await message.answer(".", reply_markup=types.ReplyKeyboardRemove())
            await message.answer(
                "Канал уже есть в базе!",
                reply_markup=admin_main_kb
            )
            await state.clear()
            return

        city = City(
            title=link,
            channel_id=channel_id,
            link=link,
            auto_mode=False
        )
        session.add(city)
        await session.commit()
        await message.answer(".", reply_markup=types.ReplyKeyboardRemove())
        await message.answer(
            f"Канал <b>{link}</b> добавлен!",
            parse_mode="HTML",
            reply_markup=admin_main_kb
        )
    await state.clear()
