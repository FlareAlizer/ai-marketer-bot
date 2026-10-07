"""Отправка поста в канал. Используется и кнопкой «Опубликовать сейчас», и планировщиком."""

import logging

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)

from db.models import Post
from services.html_tools import CAPTION_LIMIT, MESSAGE_LIMIT, sanitize_html, visible_length

logger = logging.getLogger(__name__)


class PublishError(Exception):
    """Пост не отправлен. reason можно показать пользователю; retryable — есть смысл повторить позже."""

    def __init__(self, reason: str, retryable: bool = False) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retryable = retryable


def caption_fits(text: str | None) -> bool:
    return visible_length(text or "") <= CAPTION_LIMIT


def check_post_ready(post: Post) -> str | None:
    """Проверяет, что пост можно отправить. Возвращает описание проблемы или None."""
    if not post.text or not post.text.strip():
        return "у поста нет текста."
    length = visible_length(post.text)
    if post.media_file_id and length > CAPTION_LIMIT:
        return (
            f"в тексте {length} символов, а подпись к медиа вмещает {CAPTION_LIMIT}. "
            "Сократите текст через «AI-правка» или «Вручную»."
        )
    if length > MESSAGE_LIMIT:
        return f"в тексте {length} символов, а сообщение Telegram вмещает {MESSAGE_LIMIT}. Сократите текст."
    return None


async def send_post(bot: Bot, chat_id: int, post: Post) -> None:
    """Отправляет пост в чат. Бросает PublishError с понятной причиной."""
    problem = check_post_ready(post)
    if problem:
        raise PublishError(problem)

    text = sanitize_html(post.text or "")
    try:
        if not post.media_file_id:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
        elif post.media_type == "photo":
            await bot.send_photo(chat_id=chat_id, photo=post.media_file_id, caption=text, parse_mode="HTML")
        else:
            await bot.send_video(chat_id=chat_id, video=post.media_file_id, caption=text, parse_mode="HTML")
    except (TelegramRetryAfter, TelegramNetworkError, TelegramServerError) as exc:
        raise PublishError("Telegram временно недоступен, попробуйте чуть позже.", retryable=True) from exc
    except TelegramForbiddenError as exc:
        raise PublishError("у бота нет доступа к каналу. Проверьте, что он остался администратором.") from exc
    except TelegramBadRequest as exc:
        raise PublishError(f"Telegram отклонил пост ({exc.message}).") from exc
    except TelegramAPIError as exc:
        logger.error("Пост %s не отправлен: %s", post.id, type(exc).__name__)
        raise PublishError("не удалось отправить пост в канал.") from exc
