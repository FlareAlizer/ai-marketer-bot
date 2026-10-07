"""Общие помощники для хендлеров: показать экран, прочитать текстовый ответ."""

from contextlib import suppress

from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, ReplyKeyboardMarkup

Markup = InlineKeyboardMarkup | ReplyKeyboardMarkup | None

NO_PROFILE_TEXT = "Сначала заполните профиль (/start)."


async def send(call: CallbackQuery, text: str, reply_markup: Markup = None, **kwargs) -> Message:
    """Отправляет новое сообщение в чат, из которого пришло нажатие (бот работает только в личке)."""
    return await call.bot.send_message(call.from_user.id, text, reply_markup=reply_markup, **kwargs)


async def delete_quietly(message: object) -> None:
    if isinstance(message, Message):
        with suppress(TelegramAPIError):
            await message.delete()


async def show(
    call: CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    target: Message | None = None,
) -> Message | None:
    """Заменяет содержимое сообщения под кнопкой.

    Сообщение с фото/видео или слишком старое отредактировать как текст нельзя —
    тогда оно удаляется и отправляется новое. Возвращает сообщение, которое сейчас
    на экране: его можно передать как target при следующем вызове.
    """
    message = target or call.message
    if isinstance(message, Message) and message.text is not None:
        try:
            edited = await message.edit_text(text, reply_markup=reply_markup)
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc):
                return message
        else:
            return edited if isinstance(edited, Message) else message
    await delete_quietly(message)
    return await send(call, text, reply_markup)


async def read_text(message: Message, limit: int) -> str | None:
    """Возвращает текст сообщения или None, предварительно объяснив пользователю, что не так."""
    text = (message.text or "").strip()
    if not text:
        await message.answer("Нужно текстовое сообщение. Напишите ответ словами.")
        return None
    if len(text) > limit:
        await message.answer(f"Слишком длинно: {len(text)} символов при лимите {limit}. Сократите и пришлите ещё раз.")
        return None
    return text
