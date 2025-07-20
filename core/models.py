from sqlalchemy.orm import DeclarativeBase, mapped_column, Mapped, relationship
from sqlalchemy import Integer, String, Boolean, ForeignKey

class Base(DeclarativeBase):
    pass

class City(Base):
    __tablename__ = "city"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    channel_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    link: Mapped[str] = mapped_column(String, nullable=False)
    auto_mode: Mapped[bool] = mapped_column(Boolean, default=False)

class DonorChannel(Base):
    __tablename__ = "donor_channel"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    channel_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    city_id: Mapped[int] = mapped_column(Integer, ForeignKey("city.id"))
    mask_pattern: Mapped[str] = mapped_column(String, nullable=True)

class Post(Base):
    __tablename__ = "post"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    donor_id: Mapped[int] = mapped_column(Integer, ForeignKey("donor_channel.id"))
    city_id: Mapped[int] = mapped_column(Integer, ForeignKey("city.id"))
    original_text: Mapped[str] = mapped_column(String)
    processed_text: Mapped[str] = mapped_column(String)
    media_path: Mapped[str] = mapped_column(String)
    source_link: Mapped[str] = mapped_column(String)
    is_ad: Mapped[bool] = mapped_column(Boolean, default=False)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String)
    published_at: Mapped[str] = mapped_column(String)

class Admin(Base):
    __tablename__ = "admin"
    tg_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String)
    is_super: Mapped[bool] = mapped_column(Boolean, default=False)
