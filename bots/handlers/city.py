from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from infra.db import AsyncSessionLocal
from core.models import City
from aiogram.filters import Command

router = Router()

class AddCityFSM(StatesGroup):
    waiting_for_link = State()

@router.message(Command("start"))
async def start_menu(message: types.Message, state: FSMContext):
    kb = [
        [types.KeyboardButton(text="Показать список каналов")],
        [types.KeyboardButton(text="Добавить канал")],
    ]
    markup = types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
    await message.answer("Привет! Я бот для работы с каналами.\nВыбери действие:", reply_markup=markup)
    await state.clear()

@router.message(F.text == "Добавить канал")
async def add_city_start(message: types.Message, state: FSMContext):
    await message.answer("Пришли ссылку на новый городской канал:", reply_markup=types.ReplyKeyboardRemove())
    await state.set_state(AddCityFSM.waiting_for_link)

@router.message(AddCityFSM.waiting_for_link)
async def add_city_link(message: types.Message, state: FSMContext):
    link = message.text.strip()
    if not link.startswith("https://t.me/"):
        await message.answer("Ссылка должна начинаться с https://t.me/")
        return
    username = link.replace("https://t.me/", "").replace("@", "")
    async with AsyncSessionLocal() as session:
        # Проверка на дубликат
        res = await session.execute(City.__table__.select().where(City.channel_id == username))
        if res.scalar_one_or_none():
            await message.answer("Такой канал уже есть!", reply_markup=types.ReplyKeyboardRemove())
            await state.clear()
            return
        city = City(title=link, channel_id=username, link=link, auto_mode=False)
        session.add(city)
        await session.commit()
    await message.answer(f"Канал {link} добавлен.", reply_markup=types.ReplyKeyboardRemove())
    await state.clear()
