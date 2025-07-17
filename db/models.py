# db/models.py
from sqlalchemy import Column, BigInteger, String, Boolean, DateTime, ForeignKey, Text, Integer
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func
import datetime

# Базовый класс для декларативного определения моделей
Base = declarative_base()

class City(Base):
    """Модель для хранения информации о городских каналах (группах)."""
    __tablename__ = 'cities'

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, comment="ID Telegram канала/группы")
    title = Column(String, nullable=False, comment="Название городского канала")
    auto_mode = Column(Boolean, default=True, comment="Режим публикации: True - авто, False - ручной")
    created_at = Column(DateTime, default=func.now(), comment="Время создания записи")

    # Связь с донорами (один-ко-многим)
    donor_channels = relationship("DonorChannel", back_populates="city")
    # Связь с настройками (один-к-одному)
    settings = relationship("ChannelSetting", uselist=False, back_populates="city")

    def __repr__(self):
        return f"<City(id={self.id}, title='{self.title}', telegram_id={self.telegram_id})>"

class DonorChannel(Base):
    """Модель для хранения информации о каналах-источниках новостей."""
    __tablename__ = 'donor_channels'

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, comment="ID Telegram канала-донора")
    title = Column(String, nullable=False, comment="Название канала-донора")
    city_id = Column(Integer, ForeignKey('cities.id'), nullable=False, comment="ID городского канала, к которому привязан донор")
    mask_pattern = Column(Text, nullable=True, comment="Регулярное выражение для фильтрации и очистки постов") # <-- НОВОЕ ПОЛЕ
    created_at = Column(DateTime, default=func.now(), comment="Время создания записи")

    # Связь с городом (многие-к-одному)
    city = relationship("City", back_populates="donor_channels")
    # Связь с постами (один-ко-многим)
    posts = relationship("Post", back_populates="donor_channel")

    def __repr__(self):
        return f"<DonorChannel(id={self.id}, title='{self.title}', telegram_id={self.telegram_id})>"

class Post(Base):
    """Модель для хранения спарсенных и обработанных новостей."""
    __tablename__ = 'posts'

    id = Column(Integer, primary_key=True, autoincrement=True)
    original_text = Column(Text, nullable=False, comment="Оригинальный текст новости")
    processed_text = Column(Text, nullable=True, comment="Переформулированный текст новости")
    image_url = Column(String, nullable=True, comment="URL изображения, если есть")
    source_link = Column(String, nullable=True, comment="Ссылка на оригинальный пост/источник")
    is_advertisement = Column(Boolean, default=False, comment="Признак рекламного характера")
    is_duplicate = Column(Boolean, default=False, comment="Признак дубликата")
    status = Column(String, default="pending", comment="Статус поста: pending, approved, rejected, published, rejected_no_mask_defined, rejected_no_mask_match, rejected_empty_after_clean, rejected_mask_error, rejected_processing_error") # <-- Обновлен комментарий
    published_at = Column(DateTime, nullable=True, comment="Время публикации в городском канале")
    created_at = Column(DateTime, default=func.now(), comment="Время создания записи")
    donor_channel_id = Column(Integer, ForeignKey('donor_channels.id'), nullable=False, comment="ID канала-донора")
    city_id = Column(Integer, ForeignKey('cities.id'), nullable=False, comment="ID городского канала, куда предназначается пост")
    original_message_id = Column(BigInteger, nullable=True, comment="ID оригинального сообщения в доноре")

    # Связь с донором (многие-к-одному)
    donor_channel = relationship("DonorChannel", back_populates="posts")
    # Связь с городом (многие-к-одному)
    city = relationship("City") # Нет обратной связи, так как City уже имеет связь с DonorChannel

    def __repr__(self):
        return f"<Post(id={self.id}, status='{self.status}', is_duplicate={self.is_duplicate})>"

class Duplicate(Base):
    """Модель для хранения информации о найденных дубликатах."""
    __tablename__ = 'duplicates'

    id = Column(Integer, primary_key=True, autoincrement=True)
    original_post_id = Column(Integer, ForeignKey('posts.id'), nullable=False, comment="ID оригинального поста")
    duplicate_post_id = Column(Integer, ForeignKey('posts.id'), nullable=True, comment="ID дублирующего поста")
    reason = Column(String, nullable=True, comment="Причина дублирования (текст/смысл)")
    created_at = Column(DateTime, default=func.now(), comment="Время обнаружения дубликата")

    # Связи с постами (многие-к-одному)
    original_post = relationship("Post", foreign_keys=[original_post_id], backref="original_duplicates")
    duplicate_post = relationship("Post", foreign_keys=[duplicate_post_id], backref="as_duplicate")

    def __repr__(self):
        return f"<Duplicate(id={self.id}, original_post_id={self.original_post_id}, duplicate_post_id={self.duplicate_post_id})>"

class Admin(Base):
    """Модель для хранения списка администраторов с правами."""
    __tablename__ = 'admins'

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, comment="ID Telegram пользователя-админа")
    username = Column(String, nullable=True, comment="Никнейм админа")
    is_super_admin = Column(Boolean, default=False, comment="Признак супер-админа")
    created_at = Column(DateTime, default=func.now(), comment="Время добавления админа")

    def __repr__(self):
        return f"<Admin(id={self.id}, telegram_id={self.telegram_id}, username='{self.username}')>"

class ChannelSetting(Base):
    """Модель для хранения настроек по каждому каналу."""
    __tablename__ = 'channel_settings'

    id = Column(Integer, primary_key=True, autoincrement=True)
    city_id = Column(Integer, ForeignKey('cities.id'), unique=True, nullable=False, comment="ID городского канала")
    # Дополнительные настройки могут быть добавлены здесь
    min_words_for_deduplication = Column(Integer, default=10, comment="Минимальное количество слов для дедупликации")
    # ... другие настройки

    # Связь с городом (один-к-одному)
    city = relationship("City", back_populates="settings")

    def __repr__(self):
        return f"<ChannelSetting(id={self.id}, city_id={self.city_id})>"
