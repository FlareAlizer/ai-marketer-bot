"""Редактор: открытие поста, навигация по меню, предпросмотр."""

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Post
from db.repo import get_plan_posts
from handlers.editor.common import require_post, show_card
from handlers.ui import delete_quietly, send, show
from keyboards.editor import (
    EditorCallback,
    get_preview_keyboard,
    get_text_edit_keyboard,
    get_topic_edit_keyboard,
)
from keyboards.plan import PostSelectCallback, get_plan_keyboard
from services.html_tools import CAPTION_LIMIT, clip, sanitize_html, strip_tags
from services.llm import LLMService
from services.publisher import caption_fits

router = Router(name="editor.view")

# Запас под служебную строку в сообщении без разметки
_PLAIN_FALLBACK_LEN = 3900


@router.callback_query(PostSelectCallback.filter(F.action == "edit"))
async def open_post_editor(
    call: CallbackQuery,
    callback_data: PostSelectCallback,
    state: FSMContext,
    session: AsyncSession,
    llm: LLMService,
) -> None:
    post = await require_post(call, session, callback_data.post_id)
    if post is None:
        return
    # Отвечаем сразу: генерация текста может занять десятки секунд
    await call.answer("Открываю редактор...")
    await state.clear()
    await show_card(call, session, llm, post)


@router.callback_query(EditorCallback.filter(F.action == "back_to_main"))
async def back_to_main(
    call: CallbackQuery,
    callback_data: EditorCallback,
    state: FSMContext,
    session: AsyncSession,
    llm: LLMService,
) -> None:
    post = await require_post(call, session, callback_data.post_id)
    if post is None:
        return
    await call.answer()
    await state.clear()
    await show_card(call, session, llm, post)


@router.callback_query(EditorCallback.filter(F.action == "back"))
async def back_to_plan_list(
    call: CallbackQuery,
    callback_data: EditorCallback,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    post = await require_post(call, session, callback_data.post_id)
    if post is None:
        return
    posts = await get_plan_posts(session, post.plan_id)
    await call.answer()
    await state.clear()
    await show(call, "📅 <b>Ваш контент-план:</b>", get_plan_keyboard(posts))


@router.callback_query(EditorCallback.filter(F.action == "menu_topic"))
async def menu_topic(call: CallbackQuery, callback_data: EditorCallback, session: AsyncSession) -> None:
    post = await require_post(call, session, callback_data.post_id)
    if post is None:
        return
    await call.answer()
    await show(call, "⚙️ <b>Правка ТЕМЫ</b>\nВыберите действие:", get_topic_edit_keyboard(post.id))


@router.callback_query(EditorCallback.filter(F.action == "menu_text"))
async def menu_text(call: CallbackQuery, callback_data: EditorCallback, session: AsyncSession) -> None:
    post = await require_post(call, session, callback_data.post_id)
    if post is None:
        return
    await call.answer()
    await show(call, "⚙️ <b>Правка ТЕКСТА</b>\nВыберите действие:", get_text_edit_keyboard(post.id))


@router.callback_query(EditorCallback.filter(F.action == "preview"))
async def show_preview(
    call: CallbackQuery,
    callback_data: EditorCallback,
    session: AsyncSession,
    llm: LLMService,
) -> None:
    post = await require_post(call, session, callback_data.post_id)
    if post is None:
        return
    await call.answer()
    if not post.text:
        # Текста ещё нет (прошлая генерация не удалась) — карточка запустит её заново
        await show_card(call, session, llm, post)
        return
    await delete_quietly(call.message)
    await send_preview(call, post)


async def send_preview(call: CallbackQuery, post: Post) -> None:
    """Показывает пост так, как он будет выглядеть в канале."""
    keyboard = get_preview_keyboard(post.id)
    text = sanitize_html(post.text or "")
    chat_id = call.from_user.id
    try:
        if post.media_file_id and not caption_fits(text):
            await send(call, text)
            await send(
                call,
                f"⚠️ Текст длиннее {CAPTION_LIMIT} символов и не поместится в подпись к медиа. "
                "Сократите его, иначе пост не опубликуется.",
                keyboard,
            )
        elif post.media_file_id and post.media_type == "photo":
            await call.bot.send_photo(chat_id, photo=post.media_file_id, caption=text, reply_markup=keyboard)
        elif post.media_file_id:
            await call.bot.send_video(chat_id, video=post.media_file_id, caption=text, reply_markup=keyboard)
        else:
            await send(call, text, keyboard)
    except TelegramBadRequest:
        plain = clip(strip_tags(text), _PLAIN_FALLBACK_LEN)
        await send(
            call,
            f"⚠️ Ошибка разметки. Текст без оформления:\n\n{plain}",
            keyboard,
            parse_mode=None,
        )
