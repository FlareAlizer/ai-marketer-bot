import datetime
from sqlalchemy import BigInteger, String, Text, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship, DeclarativeBase
from sqlalchemy.ext.asyncio import AsyncAttrs

class Base(AsyncAttrs, DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str] = mapped_column(String(255))
    
    # Настройки контента
    niche: Mapped[str | None] = mapped_column(String(100))
    expert_desc: Mapped[str | None] = mapped_column(Text)
    content_goal: Mapped[str | None] = mapped_column(String(100))
    planning_period: Mapped[str | None] = mapped_column(String(50))
    
    # ! ВАЖНО: ID канала для постинга (обязательно с минусом, например -100123456789)
    channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    
    joined_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)
    plans: Mapped[list["ContentPlan"]] = relationship(back_populates="user")
class ContentPlan(Base):
    __tablename__ = "content_plans"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)
    
    # Связь с юзером и постами
    user: Mapped["User"] = relationship(back_populates="plans")
    posts: Mapped[list["Post"]] = relationship(back_populates="plan", cascade="all, delete-orphan")

class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("content_plans.id"))
    user_id: Mapped[int] = mapped_column(BigInteger) # Дублируем для быстрого поиска

    day_number: Mapped[int] = mapped_column()          # День 1, День 2...
    topic: Mapped[str] = mapped_column(String(255))    # Тема: "Экспертность", "Кейс"
    
    text: Mapped[str | None] = mapped_column(Text)     # Текст поста
    
    # Медиа
    media_file_id: Mapped[str | None] = mapped_column(String(255))
    media_type: Mapped[str | None] = mapped_column(String(50)) # photo, video
    
    # Статусы: 'generated', 'approved', 'published'
    status: Mapped[str] = mapped_column(String(50), default="generated")
    
    scheduled_time: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)

    plan: Mapped["ContentPlan"] = relationship(back_populates="posts")