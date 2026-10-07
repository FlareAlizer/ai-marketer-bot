"""Планировщик: один проход по отложенным постам на базе в памяти."""

from datetime import datetime, timedelta

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.methods import SendMessage, SendPhoto
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.models import ContentPlan, Post, PostStatus, User
from services.scheduler import PostScheduler
from tests.conftest import CHANNEL_ID, TZ, USER_ID, FakeTelegram

NOW = datetime(2026, 10, 7, 12, 0)


@pytest.fixture
def scheduler(bot: Bot, session_factory: async_sessionmaker[AsyncSession]) -> PostScheduler:
    return PostScheduler(bot, session_factory, TZ, poll_interval=1, misfire_grace=3600)


async def add_post(session_factory: async_sessionmaker[AsyncSession], channel_id: int | None = CHANNEL_ID, **kw) -> int:
    values = {"text": "<b>Текст</b>", "status": PostStatus.SCHEDULED, "scheduled_time": NOW - timedelta(minutes=1)}
    values.update(kw)
    async with session_factory() as session:
        if await session.get(User, USER_ID) is None:
            session.add(User(id=USER_ID, full_name="Аня", niche="Дизайн", channel_id=channel_id))
        plan = ContentPlan(user_id=USER_ID)
        post = Post(user_id=USER_ID, day_number=1, topic="Тема", **values)
        plan.posts = [post]
        session.add(plan)
        await session.commit()
        return post.id


async def status_of(session_factory: async_sessionmaker[AsyncSession], post_id: int) -> str:
    async with session_factory() as session:
        return (await session.get(Post, post_id)).status


async def test_due_post_is_published_once(scheduler, session_factory, telegram: FakeTelegram) -> None:
    post_id = await add_post(session_factory)

    assert await scheduler.tick(NOW) == 1
    assert await status_of(session_factory, post_id) == PostStatus.PUBLISHED
    (sent,) = telegram.sent(SendMessage)
    assert sent.chat_id == CHANNEL_ID
    assert sent.text == "<b>Текст</b>"

    # Повторный проход ничего не отправляет
    assert await scheduler.tick(NOW) == 0
    assert len(telegram.sent(SendMessage)) == 1


async def test_future_and_unscheduled_posts_are_left_alone(scheduler, session_factory, telegram) -> None:
    future = await add_post(session_factory, scheduled_time=NOW + timedelta(hours=1))
    draft = await add_post(session_factory, status=PostStatus.GENERATED)

    assert await scheduler.tick(NOW) == 0
    assert telegram.requests == []
    assert await status_of(session_factory, future) == PostStatus.SCHEDULED
    assert await status_of(session_factory, draft) == PostStatus.GENERATED


async def test_post_with_photo_goes_as_photo(scheduler, session_factory, telegram) -> None:
    await add_post(session_factory, media_file_id="photo-id", media_type="photo")
    assert await scheduler.tick(NOW) == 1
    (sent,) = telegram.sent(SendPhoto)
    assert sent.caption == "<b>Текст</b>"


async def test_missed_post_is_not_published_late(scheduler, session_factory, telegram) -> None:
    post_id = await add_post(session_factory, scheduled_time=NOW - timedelta(hours=5))

    assert await scheduler.tick(NOW) == 0
    assert await status_of(session_factory, post_id) == PostStatus.FAILED
    # В канал ничего не ушло, автор получил уведомление в личку
    (notice,) = telegram.sent(SendMessage)
    assert notice.chat_id == USER_ID
    assert "не опубликован по расписанию" in notice.text


@pytest.mark.parametrize(
    ("kwargs", "channel_id"),
    [
        ({"text": None}, CHANNEL_ID),  # текст так и не сгенерировали
        ({}, None),  # канал отвязан
    ],
)
async def test_unpublishable_post_is_marked_failed(scheduler, session_factory, telegram, kwargs, channel_id) -> None:
    post_id = await add_post(session_factory, channel_id=channel_id, **kwargs)

    assert await scheduler.tick(NOW) == 0
    assert await status_of(session_factory, post_id) == PostStatus.FAILED
    assert [request.chat_id for request in telegram.sent(SendMessage)] == [USER_ID]


async def test_telegram_rejection_marks_post_failed(scheduler, session_factory, telegram) -> None:
    post_id = await add_post(session_factory)
    telegram.errors[SendMessage] = TelegramBadRequest(method=SendMessage(chat_id=1, text="x"), message="chat not found")

    assert await scheduler.tick(NOW) == 0
    assert await status_of(session_factory, post_id) == PostStatus.FAILED


async def test_network_error_keeps_post_for_retry(scheduler, session_factory, telegram) -> None:
    post_id = await add_post(session_factory)
    telegram.errors[SendMessage] = TelegramNetworkError(method=SendMessage(chat_id=1, text="x"), message="timeout")

    assert await scheduler.tick(NOW) == 0
    assert await status_of(session_factory, post_id) == PostStatus.SCHEDULED

    # Сеть вернулась — пост уходит на следующем проходе
    telegram.errors.clear()
    assert await scheduler.tick(NOW) == 1
    assert await status_of(session_factory, post_id) == PostStatus.PUBLISHED


async def test_start_and_stop(scheduler) -> None:
    scheduler.start()
    scheduler.start()  # повторный запуск не создаёт вторую задачу
    await scheduler.stop()
    await scheduler.stop()
