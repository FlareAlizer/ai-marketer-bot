"""Запросы к базе. Доступ к планам и постам — только с проверкой владельца."""

import datetime
from collections.abc import Sequence

from aiogram.types import User as TgUser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ContentPlan, Post, PostStatus, User

# Больше планов в «Истории» не показываем: у клавиатуры Telegram лимит 100 кнопок
HISTORY_LIMIT = 30


async def get_or_create_user(session: AsyncSession, tg_user: TgUser) -> User:
    user = await session.get(User, tg_user.id)
    if user is None:
        user = User(id=tg_user.id, username=tg_user.username, full_name=tg_user.full_name[:255])
        session.add(user)
        await session.commit()
    return user


async def get_owned_post(session: AsyncSession, post_id: int, user_id: int) -> Post | None:
    post = await session.get(Post, post_id)
    if post is None or post.user_id != user_id:
        return None
    return post


async def get_owned_plan(session: AsyncSession, plan_id: int, user_id: int) -> ContentPlan | None:
    plan = await session.get(ContentPlan, plan_id)
    if plan is None or plan.user_id != user_id:
        return None
    return plan


async def get_plan_posts(session: AsyncSession, plan_id: int) -> Sequence[Post]:
    stmt = select(Post).where(Post.plan_id == plan_id).order_by(Post.day_number)
    return (await session.scalars(stmt)).all()


async def get_latest_plan_id(session: AsyncSession, user_id: int) -> int | None:
    stmt = (
        select(ContentPlan.id)
        .where(ContentPlan.user_id == user_id)
        .order_by(ContentPlan.created_at.desc(), ContentPlan.id.desc())
        .limit(1)
    )
    return await session.scalar(stmt)


async def get_user_plans(session: AsyncSession, user_id: int) -> Sequence[ContentPlan]:
    stmt = (
        select(ContentPlan)
        .where(ContentPlan.user_id == user_id)
        .order_by(ContentPlan.created_at.desc(), ContentPlan.id.desc())
        .limit(HISTORY_LIMIT)
    )
    return (await session.scalars(stmt)).all()


async def get_due_post_ids(session: AsyncSession, now: datetime.datetime, limit: int = 20) -> Sequence[int]:
    """ID отложенных постов, время публикации которых уже наступило."""
    stmt = (
        select(Post.id)
        .where(Post.status == PostStatus.SCHEDULED, Post.scheduled_time <= now)
        .order_by(Post.scheduled_time)
        .limit(limit)
    )
    return (await session.scalars(stmt)).all()
