# models.py

import os
from datetime import datetime
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy import Column, Integer, BigInteger, String, Boolean, Text, DateTime, ForeignKey, select

POSTGRES_DSN = os.getenv("POSTGRES_DSN", "postgresql+asyncpg://user:pass@localhost/db")

Base = declarative_base()
engine = create_async_engine(POSTGRES_DSN, echo=False)
SessionLocal = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

class City(Base):
    __tablename__ = "cities"
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    channel_id = Column(BigInteger, unique=True, nullable=False)
    link = Column(String)
    auto_mode = Column(Boolean, default=True)
    donors = relationship("DonorChannel", back_populates="city", cascade="all,delete")

class DonorChannel(Base):
    __tablename__ = "donor_channels"
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    channel_id = Column(BigInteger, unique=True, nullable=False)
    city_id = Column(Integer, ForeignKey("cities.id"), nullable=False)
    mask_pattern = Column(Text)
    city = relationship("City", back_populates="donors")
    posts = relationship("Post", back_populates="donor", cascade="all,delete")

class Post(Base):
    __tablename__ = "posts"
    id = Column(Integer, primary_key=True)
    donor_id = Column(Integer, ForeignKey("donor_channels.id"), nullable=False)
    city_id = Column(Integer, ForeignKey("cities.id"), nullable=False)
    original_text = Column(Text)
    processed_text = Column(Text)
    media_path = Column(String)
    source_link = Column(String)
    is_ad = Column(Boolean, default=False)
    status = Column(String, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)
    donor = relationship("DonorChannel", back_populates="posts")

class Admin(Base):
    __tablename__ = "admins"
    tg_id = Column(BigInteger, primary_key=True)
    username = Column(String)
    is_super = Column(Boolean, default=False)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("DB schema ready ✅")
