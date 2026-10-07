"""Общий шаг привязки канала для анкеты и для правки профиля."""

from aiogram import Bot
from aiogram.types import Message

from services.channels import ChannelCheck, check_channel_rights, resolve_channel_id

_PROBLEMS = {
    ChannelCheck.NO_ACCESS: "❌ Ошибка доступа к каналу.",
    ChannelCheck.BOT_NOT_ADMIN: "⚠️ Я не администратор в этом канале.",
    ChannelCheck.BOT_CANNOT_POST: (
        "⚠️ У меня нет права публиковать сообщения в этом канале. Включите его в настройках администратора."
    ),
    ChannelCheck.USER_NOT_ADMIN: "⚠️ Вы не администратор этого канала. Привязать можно только свой канал.",
}


async def read_channel(message: Message, bot: Bot) -> int | None:
    """Возвращает ID канала, если его можно привязать. Иначе отвечает пользователю и возвращает None."""
    channel_id = await resolve_channel_id(bot, message)
    if channel_id is None:
        await message.answer("❌ Не могу найти канал. Проверь права админа и username.")
        return None

    result = await check_channel_rights(bot, channel_id, message.from_user.id)
    if result is not ChannelCheck.OK:
        await message.answer(_PROBLEMS[result])
        return None
    return channel_id
