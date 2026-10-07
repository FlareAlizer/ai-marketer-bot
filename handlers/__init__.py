"""Сборка роутеров бота."""

from aiogram import F, Router
from aiogram.enums import ChatType

from . import editor, fallback, menu, onboarding, plan, profile


def build_router() -> Router:
    """Корневой роутер. Порядок важен: меню — первым, обработчики «на всё остальное» — последними.

    Модули хранят роутеры на уровне модуля, поэтому функцию можно вызвать один раз за процесс.
    """
    root = Router(name="root")
    # Бот рассчитан на личные чаты: в группах и каналах он на сообщения не отвечает
    root.message.filter(F.chat.type == ChatType.PRIVATE)
    root.include_routers(
        menu.router,
        onboarding.router,
        profile.router,
        plan.router,
        editor.router,
        fallback.router,
    )
    return root
