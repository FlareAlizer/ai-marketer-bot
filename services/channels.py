"""Привязка канала: поиск по пересланному сообщению или @username и проверка прав."""

import enum
import re

from aiogram import Bot
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.types import ChatMemberAdministrator, Message, MessageOriginChannel

_ADMIN_STATUSES = {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}
_USERNAME_RE = re.compile(r"^@[A-Za-z][A-Za-z0-9_]{3,31}$")


class ChannelCheck(enum.Enum):
    OK = "ok"
    NO_ACCESS = "no_access"  # бот не видит канал
    BOT_NOT_ADMIN = "bot_not_admin"
    BOT_CANNOT_POST = "bot_cannot_post"
    USER_NOT_ADMIN = "user_not_admin"


async def resolve_channel_id(bot: Bot, message: Message) -> int | None:
    """Определяет ID канала по пересланному из него сообщению или по @username."""
    origin = message.forward_origin
    if isinstance(origin, MessageOriginChannel):
        return origin.chat.id

    username = (message.text or "").strip()
    if not _USERNAME_RE.match(username):
        return None
    try:
        chat = await bot.get_chat(username)
    except TelegramAPIError:
        return None
    return chat.id if chat.type == ChatType.CHANNEL else None


async def check_channel_rights(bot: Bot, channel_id: int, user_id: int) -> ChannelCheck:
    """Проверяет, что бот может постить в канал, а пользователь — его администратор.

    Вторая проверка обязательна: без неё любой, кто знает @username чужого канала
    с этим ботом, мог бы привязать его к себе и публиковать туда посты.
    """
    try:
        bot_member = await bot.get_chat_member(channel_id, bot.id)
    except TelegramAPIError:
        return ChannelCheck.NO_ACCESS
    if bot_member.status not in _ADMIN_STATUSES:
        return ChannelCheck.BOT_NOT_ADMIN
    if isinstance(bot_member, ChatMemberAdministrator) and bot_member.can_post_messages is False:
        return ChannelCheck.BOT_CANNOT_POST

    try:
        user_member = await bot.get_chat_member(channel_id, user_id)
    except TelegramAPIError:
        return ChannelCheck.USER_NOT_ADMIN
    if user_member.status not in _ADMIN_STATUSES:
        return ChannelCheck.USER_NOT_ADMIN
    return ChannelCheck.OK
