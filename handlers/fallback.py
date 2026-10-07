"""Обработчики «на всё остальное». Роутер подключается последним."""

import logging
from contextlib import suppress

from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, ErrorEvent, Message

logger = logging.getLogger(__name__)
router = Router(name="fallback")


@router.callback_query()
async def stale_callback(call: CallbackQuery) -> None:
    """Кнопка из старого сообщения или шаг, который уже завершён."""
    await call.answer("Кнопка устарела. Откройте раздел заново через меню.", show_alert=True)


@router.message()
async def unknown_message(message: Message) -> None:
    await message.answer("Не понял сообщение. Воспользуйтесь меню или командой /start.")


@router.errors()
async def on_error(event: ErrorEvent, bot: Bot) -> bool:
    """Логирует необработанное исключение и сообщает пользователю, что действие не выполнено."""
    update = event.update
    logger.error("Ошибка при обработке апдейта %s", update.update_id, exc_info=event.exception)

    chat_id = None
    if update.message:
        chat_id = update.message.chat.id
    elif update.callback_query:
        chat_id = update.callback_query.from_user.id
        with suppress(TelegramAPIError):
            await update.callback_query.answer()
    if chat_id is not None:
        with suppress(TelegramAPIError):
            await bot.send_message(chat_id, "⚠️ Что-то пошло не так. Попробуйте ещё раз или нажмите /start.")
    return True
