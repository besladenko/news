from sqlalchemy import (
    Column, Integer, String, Boolean, ForeignKey, DateTime, Text
)
from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base, relationship
import datetime

Base = declarative_base()

class City(Base):
    __tablename__ = "city"
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    channel_id = Column(String, unique=True, nullable=False)
    link = Column(String, nullable=False)
    auto_mode = Column(Boolean, default=False)

    donors = relationship("DonorChannel", back_populates="city")
    posts = relationship("Post", back_populates="city")

class DonorChannel(Base):
    __tablename__ = "donor_channel"
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    channel_id = Column(String, unique=True, nullable=False)
    city_id = Column(Integer, ForeignKey("city.id"), nullable=False)
    mask_pattern = Column(String, nullable=True)

    city = relationship("City", back_populates="donors")
    posts = relationship("Post", back_populates="donor")

class Post(Base):
    __tablename__ = "post"
    id = Column(Integer, primary_key=True)
    donor_id = Column(Integer, ForeignKey("donor_channel.id"))
    city_id = Column(Integer, ForeignKey("city.id"))
    original_text = Column(Text, nullable=False)
    processed_text = Column(Text, nullable=True)
    media_path = Column(String, nullable=True)
    source_link = Column(String, nullable=True)
    is_ad = Column(Boolean, default=False)
    is_duplicate = Column(Boolean, default=False)
    status = Column(String, default="pending")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    published_at = Column(DateTime, nullable=True)

    donor = relationship("DonorChannel", back_populates="posts")
    city = relationship("City", back_populates="posts")

class Admin(Base):
    __tablename__ = "admin"
    tg_id = Column(Integer, primary_key=True)
    username = Column(String, nullable=True)
    is_super = Column(Boolean, default=False)
