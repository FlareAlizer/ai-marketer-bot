"""Точка входа: собирает зависимости и запускает long polling."""

import asyncio
import logging
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import SimpleEventIsolation
from aiogram.fsm.storage.redis import RedisStorage
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config.config import get_settings
from db.base import create_engine, create_session_factory, init_db
from handlers import build_router
from middlewares.db_session import DbSessionMiddleware
from services.llm import LLMService
from services.scheduler import PostScheduler

logger = logging.getLogger(__name__)


def create_dispatcher(
    storage: BaseStorage,
    session_factory: async_sessionmaker[AsyncSession],
    llm: LLMService,
    tz: ZoneInfo,
) -> Dispatcher:
    # SimpleEventIsolation обрабатывает апдейты одного пользователя по очереди:
    # двойное нажатие не запустит две генерации и не опубликует пост дважды
    dp = Dispatcher(storage=storage, events_isolation=SimpleEventIsolation())
    # Зависимости, которые хендлеры получают по имени аргумента
    dp["llm"] = llm
    dp["tz"] = tz
    dp.update.middleware(DbSessionMiddleware(session_factory=session_factory))
    dp.include_router(build_router())
    return dp


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.LOG_LEVEL.upper(),
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    )

    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    await init_db(engine)

    redis = Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        db=settings.REDIS_DB,
        password=settings.REDIS_PASSWORD.get_secret_value() if settings.REDIS_PASSWORD else None,
    )
    bot = Bot(
        token=settings.BOT_TOKEN.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    llm = LLMService.from_settings(settings)
    dp = create_dispatcher(RedisStorage(redis=redis), session_factory, llm, settings.tz)

    scheduler = PostScheduler(
        bot=bot,
        session_factory=session_factory,
        tz=settings.tz,
        poll_interval=settings.SCHEDULER_POLL_INTERVAL,
        misfire_grace=settings.SCHEDULER_MISFIRE_GRACE,
    )

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        scheduler.start()
        logger.info("Бот MarketAski запущен (PostgreSQL + Redis)")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await scheduler.stop()
        await llm.close()
        await dp.storage.close()
        await engine.dispose()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.getLogger(__name__).info("Бот остановлен")
