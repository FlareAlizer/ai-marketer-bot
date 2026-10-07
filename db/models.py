"""Модели: пользователь, контент-план и посты плана."""

import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Ограничения длины совпадают с размерами колонок
NICHE_MAX_LEN = 100
GOAL_MAX_LEN = 100
TOPIC_MAX_LEN = 255


def utcnow() -> datetime.datetime:
    """Текущее время UTC без tzinfo: колонки объявлены как TIMESTAMP WITHOUT TIME ZONE."""
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


class PostStatus:
    GENERATED = "generated"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    FAILED = "failed"  # не удалось опубликовать по расписанию


class Base(AsyncAttrs, DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Telegram ID
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str] = mapped_column(String(255))

    # Настройки контента
    niche: Mapped[str | None] = mapped_column(String(NICHE_MAX_LEN))
    expert_desc: Mapped[str | None] = mapped_column(Text)
    content_goal: Mapped[str | None] = mapped_column(String(GOAL_MAX_LEN))
    planning_period: Mapped[str | None] = mapped_column(String(50))

    # ID канала для постинга (у каналов отрицательный, вида -100...)
    channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    joined_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)
    plans: Mapped[list["ContentPlan"]] = relationship(back_populates="user")


class ContentPlan(Base):
    __tablename__ = "content_plans"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped["User"] = relationship(back_populates="plans")
    posts: Mapped[list["Post"]] = relationship(back_populates="plan", cascade="all, delete-orphan")


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("content_plans.id"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)  # дублируем для проверки владельца

    day_number: Mapped[int] = mapped_column()  # порядковый номер поста в плане
    topic: Mapped[str] = mapped_column(String(TOPIC_MAX_LEN))

    text: Mapped[str | None] = mapped_column(Text)  # HTML-разметка Telegram

    media_file_id: Mapped[str | None] = mapped_column(String(255))
    media_type: Mapped[str | None] = mapped_column(String(50))  # photo, video

    status: Mapped[str] = mapped_column(String(50), default=PostStatus.GENERATED)

    # Время в часовом поясе из настроек (TIMEZONE), без tzinfo.
    # Для отложенного поста — когда публиковать, для опубликованного — когда вышел.
    scheduled_time: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)

    plan: Mapped["ContentPlan"] = relationship(back_populates="posts")
