"""Редактор: правка темы и текста поста."""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import TOPIC_MAX_LEN
from handlers.editor.common import (
    LLM_FAILED_TEXT,
    generate_text,
    post_from_state,
    render_card,
    require_post,
    send_card,
)
from handlers.ui import delete_quietly, read_text, show
from keyboards.editor import EditorCallback, get_back_keyboard, get_editor_main_keyboard
from services.html_tools import CAPTION_LIMIT, MESSAGE_LIMIT, clip, visible_length
from services.llm import LLMError, LLMService
from services.prompts import INSTRUCTION_LIMIT, THESIS_LIMIT
from services.publisher import caption_fits
from states.editor import PostEditorSG

router = Router(name="editor.text")

_CAPTION_WARNING = (
    f"⚠️ К посту прикреплено медиа, а текст длиннее {CAPTION_LIMIT} символов. Сократите его, иначе пост не опубликуется."
)


async def _start_input(
    call: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    post_id: int,
    text: str,
    next_state: State,
) -> None:
    """Показывает приглашение к вводу и запоминает, для какого поста ждём сообщение."""
    post = await require_post(call, session, post_id)
    if post is None:
        return
    await call.answer()
    await show(call, text, get_back_keyboard(post.id))
    await state.set_state(next_state)
    await state.set_data({"post_id": post.id})


# --- Тема ---


@router.callback_query(EditorCallback.filter(F.action == "topic_manual"))
async def topic_manual_start(
    call: CallbackQuery,
    callback_data: EditorCallback,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    await _start_input(
        call,
        state,
        session,
        callback_data.post_id,
        "⌨️ <b>Ввод новой темы</b>\n\n"
        "Напишите новую тему. Можно добавить тезисы.\n"
        "<i>Пример: Как я начал бизнес. Рассказать про первый провал.</i>",
        PostEditorSG.waiting_for_new_topic_manual,
    )


@router.message(PostEditorSG.waiting_for_new_topic_manual)
async def topic_manual_process(message: Message, state: FSMContext, session: AsyncSession, llm: LLMService) -> None:
    post = await post_from_state(message, state, session)
    if post is None:
        return
    new_topic = await read_text(message, THESIS_LIMIT)
    if new_topic is None:
        return

    # В колонку темы помещается 255 символов; полный ввод уходит модели как тезисы
    post.topic = clip(new_topic, TOPIC_MAX_LEN)
    await session.commit()
    await state.clear()
    await message.answer("🔄 Тема изменена. Генерирую новый текст...")

    try:
        post.text = await generate_text(session, llm, post, thesis=new_topic)
    except LLMError:
        await message.answer(
            "❌ Не удалось сгенерировать текст: тема сохранена, текст остался прежним. "
            "Нажмите «Текст» → «Переписать всё» чуть позже."
        )
    else:
        await session.commit()
    await send_card(message, post)


# --- Текст вручную ---


@router.callback_query(EditorCallback.filter(F.action == "text_manual"))
async def text_manual_start(
    call: CallbackQuery,
    callback_data: EditorCallback,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    await _start_input(
        call,
        state,
        session,
        callback_data.post_id,
        "✏️ Пришлите новый текст поста полностью:",
        PostEditorSG.waiting_for_text_manual,
    )


@router.message(PostEditorSG.waiting_for_text_manual)
async def text_manual_process(message: Message, state: FSMContext, session: AsyncSession) -> None:
    post = await post_from_state(message, state, session)
    if post is None:
        return
    # html_text сохраняет форматирование из сообщения и экранирует спецсимволы
    new_text = message.html_text.strip() if (message.text or message.caption) else ""
    if not new_text:
        await message.answer("Нужно текстовое сообщение. Пришлите текст поста.")
        return
    if visible_length(new_text) > MESSAGE_LIMIT:
        await message.answer(f"Текст длиннее {MESSAGE_LIMIT} символов. Сократите и пришлите ещё раз.")
        return

    post.text = new_text
    await session.commit()
    await state.clear()
    await message.answer("✅ Текст сохранен.")
    if post.media_file_id and not caption_fits(post.text):
        await message.answer(_CAPTION_WARNING)
    await send_card(message, post)


# --- Правка через модель ---


@router.callback_query(EditorCallback.filter(F.action == "text_ai"))
async def text_ai_start(
    call: CallbackQuery,
    callback_data: EditorCallback,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    await _start_input(
        call,
        state,
        session,
        callback_data.post_id,
        "🤖 <b>AI-правка</b>\nЧто изменить? (короче, веселее, добавить призыв...)",
        PostEditorSG.waiting_for_ai_instruction,
    )


@router.message(PostEditorSG.waiting_for_ai_instruction)
async def text_ai_process(message: Message, state: FSMContext, session: AsyncSession, llm: LLMService) -> None:
    post = await post_from_state(message, state, session)
    if post is None:
        return
    instruction = await read_text(message, INSTRUCTION_LIMIT)
    if instruction is None:
        return
    await state.clear()
    if not post.text:
        await message.answer("У поста ещё нет текста. Откройте его заново, чтобы сгенерировать.")
        return

    progress = await message.answer("🤖 Думаю...")
    current_text = post.text
    await session.commit()  # на время запроса к модели соединение с БД возвращается в пул
    try:
        new_text = await llm.refine_post_text(current_text, instruction)
    except LLMError:
        # Прежний текст не трогаем
        await delete_quietly(progress)
        await message.answer(LLM_FAILED_TEXT)
        await send_card(message, post)
        return

    post.text = new_text
    await session.commit()
    await delete_quietly(progress)
    await message.answer("✅ Текст обновлен.")
    if post.media_file_id and not caption_fits(post.text):
        await message.answer(_CAPTION_WARNING)
    await send_card(message, post)


@router.callback_query(EditorCallback.filter(F.action == "text_regen"))
async def text_regen(
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
    progress = await show(call, "⏳ Переписываю текст...")
    try:
        post.text = await generate_text(session, llm, post)
    except LLMError:
        await show(call, LLM_FAILED_TEXT, get_editor_main_keyboard(post.id), target=progress)
        return
    await session.commit()
    await show(call, render_card(post), get_editor_main_keyboard(post.id), target=progress)
