# db/database.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from db.models import Base
from config import config
import asyncio
from loguru import logger

# Создаем асинхронный движок SQLAlchemy
engine = create_async_engine(config.POSTGRES_URL, echo=False) # echo=True для вывода SQL-запросов

# Создаем фабрику асинхронных сессий
AsyncSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False # Важно, чтобы объекты не "истекали" после коммита
)

async def init_db():
    """
    Инициализирует базу данных:
    УДАЛЯЕТ ВСЕ ТАБЛИЦЫ и создает их заново.
    ИСПОЛЬЗУЙТЕ С ОСТОРОЖНОСТЬЮ: ЭТО ПРИВЕДЕТ К ПОЛНОЙ ПОТЕРЕ ДАННЫХ.
    Подходит для разработки и начальной настройки.
    """
    logger.info("Инициализация базы данных: удаление и пересоздание всех таблиц...")
    async with engine.begin() as conn:
        # !!! ВНИМАНИЕ: ЭТА СТРОКА УДАЛЯЕТ ВСЕ ТАБЛИЦЫ В БАЗЕ ДАННЫХ !!!
        await conn.run_sync(Base.metadata.drop_all)
        # Создание всех таблиц
        await conn.run_sync(Base.metadata.create_all)
    logger.info("База данных успешно пересоздана.")

async def get_session():
    """Асинхронный генератор для получения сессии базы данных."""
    async with AsyncSessionLocal() as session:
        yield session

# Пример использования (для тестирования)
async def main():
    await init_db()
    logger.info("База данных готова к работе.")

if __name__ == "__main__":
    asyncio.run(main())
