from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import sessionmaker
from config.settings import settings

engine = create_async_engine(
    settings.POSTGRES_DSN,
    echo=False,  # True для дебага SQL
    future=True
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)

async def get_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session

# Функция для инициализации БД (создание таблиц)
async def init_db():
    from core.models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
