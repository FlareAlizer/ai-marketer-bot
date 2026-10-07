"""Общее для редактора: поиск поста с проверкой владельца, карточка поста, генерация текста."""

import html

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Post, PostStatus, User
from db.repo import get_owned_post
from handlers.ui import show
from keyboards.editor import get_editor_main_keyboard, get_generation_failed_keyboard
from services.html_tools import clip, strip_tags
from services.llm import LLMError, LLMService
from services.schedule import DATETIME_FORMAT

POST_LOST_TEXT = "❌ Ошибка: пост не найден в памяти. Вернитесь в /plan"
LLM_FAILED_TEXT = "❌ Ошибка нейросети. Попробуйте ещё раз чуть позже."
_GENERATING_TEXT = "⏳ <b>Подождите, я создаю текст поста...</b>\nЭто займет около 10-15 секунд."

CARD_TEXT_PREVIEW_LEN = 250
CARD_TOPIC_LEN = 60


async def require_post(call: CallbackQuery, session: AsyncSession, post_id: int) -> Post | None:
    """Пост из callback-данных. Чужой или удалённый пост не отдаётся."""
    post = await get_owned_post(session, post_id, call.from_user.id)
    if post is None:
        await call.answer("Пост не найден. Откройте план заново.", show_alert=True)
    return post


async def post_from_state(message: Message, state: FSMContext, session: AsyncSession) -> Post | None:
    """Пост, для которого бот ждёт ввод (ID лежит в данных состояния)."""
    post_id = (await state.get_data()).get("post_id")
    post = await get_owned_post(session, post_id, message.from_user.id) if isinstance(post_id, int) else None
    if post is None:
        await state.clear()
        await message.answer(POST_LOST_TEXT)
    return post


def render_card(post: Post) -> str:
    """Текст карточки поста в редакторе. Все значения экранируются."""
    preview = html.escape(clip(strip_tags(post.text or ""), CARD_TEXT_PREVIEW_LEN))
    topic = html.escape(clip(strip_tags(post.topic), CARD_TOPIC_LEN))

    status_line = ""
    if post.status == PostStatus.SCHEDULED and post.scheduled_time:
        status_line = f"<b>Публикация:</b> 🕒 {post.scheduled_time.strftime(DATETIME_FORMAT)}\n"
    elif post.status == PostStatus.PUBLISHED:
        status_line = "<b>Статус:</b> ✅ Опубликован\n"
    elif post.status == PostStatus.FAILED:
        status_line = "<b>Статус:</b> ⚠️ Не опубликован по расписанию\n"

    return (
        f"🛠 <b>Редактор поста #{post.day_number}</b>\n\n"
        f"<b>Тема:</b> {topic}\n"
        f"<b>Медиа:</b> {'✅ Прикреплено' if post.media_file_id else '❌ Отсутствует'}\n"
        f"{status_line}"
        f"➖➖➖➖➖➖➖➖\n\n"
        f"{preview}\n\n"
        f"<i>Нажмите «Предпросмотр», чтобы увидеть пост целиком.</i>"
    )


async def generate_text(session: AsyncSession, llm: LLMService, post: Post, thesis: str | None = None) -> str:
    """Запрашивает у модели текст поста. В базу ничего не пишет; при сбое бросает LLMError."""
    user = await session.get(User, post.user_id)
    niche, about = (user.niche, user.expert_desc) if user else (None, None)
    # На время запроса к модели соединение с БД возвращается в пул
    await session.commit()
    return await llm.generate_post_text(
        niche=niche,
        about=about,
        topic=post.topic,
        post_number=post.day_number,
        thesis=thesis,
    )


async def show_card(call: CallbackQuery, session: AsyncSession, llm: LLMService, post: Post) -> None:
    """Открывает карточку поста вместо сообщения под кнопкой. Если текста ещё нет — сначала генерирует его."""
    target = None
    if not post.text:
        target = await show(call, _GENERATING_TEXT)
        try:
            post.text = await generate_text(session, llm, post)
        except LLMError:
            await show(call, LLM_FAILED_TEXT, get_generation_failed_keyboard(post.id), target=target)
            return
        await session.commit()
    await show(call, render_card(post), get_editor_main_keyboard(post.id), target=target)


async def send_card(message: Message, post: Post) -> None:
    """Отправляет карточку поста новым сообщением (после ввода текста пользователем)."""
    await message.answer(render_card(post), reply_markup=get_editor_main_keyboard(post.id))
