"""Планировщик отложенных постов.

Раз в несколько секунд выбирает из базы посты со статусом scheduled, время которых
наступило, и публикует их. Отдельного хранилища задач нет: расписание живёт в таблице
posts, поэтому оно переживает перезапуск бота и не может разойтись с данными.
"""

import asyncio
import html
import logging
from contextlib import suppress
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.models import Post, PostStatus, User
from db.repo import get_due_post_ids
from services.publisher import PublishError, send_post
from services.schedule import DATETIME_FORMAT, is_missed, local_now

logger = logging.getLogger(__name__)


class PostScheduler:
    def __init__(
        self,
        bot: Bot,
        session_factory: async_sessionmaker[AsyncSession],
        tz: ZoneInfo,
        poll_interval: int = 30,
        misfire_grace: int = 3600,
    ) -> None:
        self._bot = bot
        self._session_factory = session_factory
        self._tz = tz
        self._poll_interval = poll_interval
        self._misfire_grace = misfire_grace
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="post-scheduler")
            logger.info("Планировщик запущен, интервал опроса %s с", self._poll_interval)

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                # Сбой одной итерации (например, база недоступна) не должен останавливать планировщик
                logger.exception("Ошибка в цикле планировщика")
            await asyncio.sleep(self._poll_interval)

    async def tick(self, now: datetime | None = None) -> int:
        """Обрабатывает все посты, время которых наступило. Возвращает число опубликованных."""
        now = now or local_now(self._tz)
        async with self._session_factory() as session:
            post_ids = await get_due_post_ids(session, now)

        published = 0
        for post_id in post_ids:
            try:
                published += await self._process(post_id, now)
            except Exception:
                logger.exception("Не удалось обработать отложенный пост %s", post_id)
        return published

    async def _process(self, post_id: int, now: datetime) -> int:
        async with self._session_factory() as session:
            # Блокировка строки: пост не уйдёт дважды, даже если запущено два экземпляра бота
            post = await session.get(Post, post_id, with_for_update=True)
            if post is None or post.status != PostStatus.SCHEDULED or post.scheduled_time is None:
                return 0

            if is_missed(post.scheduled_time, now, self._misfire_grace):
                planned = post.scheduled_time.strftime(DATETIME_FORMAT)
                await self._fail(session, post, f"время публикации ({planned}) прошло, пока бот был выключен.")
                return 0

            user = await session.get(User, post.user_id)
            if user is None or not user.channel_id:
                await self._fail(session, post, "канал не привязан. Настройте профиль.")
                return 0

            try:
                await send_post(self._bot, user.channel_id, post)
            except PublishError as exc:
                if exc.retryable:
                    logger.warning("Пост %s не отправлен, повторим на следующем цикле", post.id)
                    return 0
                await self._fail(session, post, exc.reason)
                return 0

            post.status = PostStatus.PUBLISHED
            await session.commit()
            logger.info("Пост %s опубликован по расписанию", post.id)
            return 1

    async def _fail(self, session: AsyncSession, post: Post, reason: str) -> None:
        """Помечает пост как неопубликованный и сообщает об этом автору."""
        post.status = PostStatus.FAILED
        await session.commit()
        logger.warning("Пост %s не опубликован по расписанию", post.id)
        with suppress(TelegramAPIError):
            await self._bot.send_message(
                chat_id=post.user_id,
                text=(
                    f"⚠️ Пост #{post.day_number} не опубликован по расписанию: {html.escape(reason)}\n"
                    "Откройте его через «📅 Мой контент-план» и запланируйте заново."
                ),
            )
