import logging
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from config.config import config
from .models import Base

logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)

pool_pre_ping=True 

engine = create_async_engine(
    config.database_url, 
    echo=False,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20
)

# Фабрика асинхронных сессий
async_session_factory = async_sessionmaker(
    bind=engine, 
    expire_on_commit=False, 
    class_=AsyncSession
)

async def init_db():
    """
    Создает таблицы в PostgreSQL, если их еще нет.
    """
    async with engine.begin() as conn:
        # В продакшене лучше использовать Alembic, но для первого запуска этого достаточно
        await conn.run_sync(Base.metadata.create_all)
    logging.info("--- База данных PostgreSQL инициализирована ---")

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Зависимость для получения сессии (если понадобится вне мидлвари)
    """
    async with async_session_factory() as session:
        yield session