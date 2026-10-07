import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from redis.asyncio import Redis

from config.config import config
from db.base import init_db, async_session_factory
from middlewares.db_session import DbSessionMiddleware

# Импорт роутеров
from handlers import profile, content, editor
# Импорт планировщика
from services.scheduler import scheduler_service

async def main():
    # 1. Настройка логирования
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    )

    # 2. Инициализация Redis для состояний (FSM)
    # На Ubuntu по умолчанию Redis работает на localhost:6379
    redis = Redis(
        host=config.REDIS_HOST, 
        port=config.REDIS_PORT, 
        decode_responses=False # Для aiogram важно False
    )
    storage = RedisStorage(redis=redis)

    # 3. Инициализация Бота и Диспетчера
    bot = Bot(token=config.BOT_TOKEN.get_secret_value())
    dp = Dispatcher(storage=storage)

    # 4. Регистрация Middleware (передаем сессию БД в каждый хендлер)
    dp.update.middleware(DbSessionMiddleware(session_factory=async_session_factory))

    # 5. Подключение обработчиков (Routers)
    dp.include_router(profile.router)
    dp.include_router(content.router)
    dp.include_router(editor.router)

    # 6. Инициализация БД и Планировщика
    await init_db()
    
    # Запускаем планировщик (он использует синхронный URL из config)
    scheduler_service.start(bot)

    # 7. Запуск бота
    logging.info("🚀 Бот MarketAski запущен в Production режиме (PostgreSQL + Redis)")
    
    try:
        # Удаляем вебхуки и запускаем лонг-поллинг
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        # Закрываем все соединения при выключении
        await redis.close()
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот остановлен")