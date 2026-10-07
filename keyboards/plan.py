"""Клавиатура со списком постов плана."""

import re
from collections.abc import Iterable

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from db.models import Post, PostStatus
from services.html_tools import strip_tags

HEADLINE_MAX_LEN = 22
_STATUS_EMOJI = {
    PostStatus.PUBLISHED: "✅",
    PostStatus.SCHEDULED: "🕒",
    PostStatus.FAILED: "⚠️",
}


class PostSelectCallback(CallbackData, prefix="select_post"):
    post_id: int
    action: str


def short_headline(topic: str) -> str:
    """Короткий заголовок для кнопки: часть темы до тире, без кавычек, не длиннее 22 символов."""
    raw_topic = strip_tags(topic).strip()
    headline = re.split(r" [-—] ", raw_topic, maxsplit=1)[0].strip(' "')
    if len(headline) > HEADLINE_MAX_LEN:
        return headline[: HEADLINE_MAX_LEN - 2] + ".."
    return headline


def get_plan_keyboard(posts: Iterable[Post]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for post in posts:
        status_emoji = _STATUS_EMOJI.get(post.status, "📝")
        builder.button(
            text=f"{status_emoji} #{post.day_number}: {short_headline(post.topic)}",
            callback_data=PostSelectCallback(post_id=post.id, action="edit"),
        )
    builder.button(text="➕ Новый план", callback_data="create_new_plan")
    builder.adjust(1)
    return builder.as_markup()
