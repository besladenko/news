# db/models.py
from sqlalchemy import Column, Integer, String, BigInteger, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class City(Base):
    __tablename__ = 'cities'
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False)
    title = Column(String, nullable=False)
    auto_mode = Column(Boolean, default=False)

    # При удалении города, автоматически удалять связанные донорские каналы и посты.
    # Это самое надежное решение для поддержания целостности данных.
    donor_channels = relationship("DonorChannel", back_populates="city", cascade="all, delete-orphan")
    posts = relationship("Post", back_populates="city", cascade="all, delete-orphan")


class DonorChannel(Base):
    __tablename__ = 'donor_channels'
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False)
    title = Column(String, nullable=False)
    # ondelete='CASCADE' означает, что при удалении связанного City, этот DonorChannel также будет удален.
    city_id = Column(Integer, ForeignKey('cities.id', ondelete='CASCADE'), nullable=False) 
    
    city = relationship("City", back_populates="donor_channels")
    posts = relationship("Post", back_populates="donor_channel")

class Post(Base):
    __tablename__ = 'posts'
    id = Column(Integer, primary_key=True)
    original_text = Column(Text, nullable=False)
    processed_text = Column(Text, nullable=True)
    image_url = Column(String, nullable=True)
    is_duplicate = Column(Boolean, default=False)
    status = Column(String, default="pending") # pending, published, rejected
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    published_at = Column(DateTime(timezone=True), nullable=True)

    # ondelete='CASCADE' означает, что при удалении связанного City, этот Post также будет удален.
    city_id = Column(Integer, ForeignKey('cities.id', ondelete='CASCADE'), nullable=False) 
    # ondelete='CASCADE' означает, что при удалении связанного DonorChannel, этот Post также будет удален.
    # Если Post.donor_channel_id может быть NULL, и вы хотите сохранить пост при удалении донора,
    # используйте ondelete='SET NULL'. Но для вашей задачи, кажется, лучше CASCADE.
    donor_channel_id = Column(Integer, ForeignKey('donor_channels.id', ondelete='CASCADE'), nullable=True) 

    city = relationship("City", back_populates="posts")
    donor_channel = relationship("DonorChannel", back_populates="posts")

class Admin(Base):
    __tablename__ = 'admins'
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False)
    username = Column(String, nullable=True)
    is_super_admin = Column(Boolean, default=False)
