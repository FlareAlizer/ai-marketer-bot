"""Редактор: прикрепление фото или видео к посту."""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from handlers.editor.common import post_from_state, render_card, require_post, send_card
from handlers.ui import send, show
from keyboards.editor import (
    EditorCallback,
    get_back_keyboard,
    get_compression_choice_keyboard,
    get_editor_main_keyboard,
)
from services.html_tools import visible_length
from services.llm import LLMError, LLMService
from services.publisher import caption_fits
from states.editor import PostEditorSG

router = Router(name="editor.media")


@router.callback_query(EditorCallback.filter(F.action == "add_media"))
async def add_media_start(
    call: CallbackQuery,
    callback_data: EditorCallback,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    post = await require_post(call, session, callback_data.post_id)
    if post is None:
        return
    await call.answer()
    await show(
        call,
        "📷 <b>Добавление медиа</b>\n\n"
        "Пришлите <b>ОДНО</b> фото или видео.\n"
        "<i>(Отправка альбомов из нескольких фото пока не поддерживается, бот сохранит только последний файл)</i>",
        get_back_keyboard(post.id),
    )
    await state.set_state(PostEditorSG.waiting_for_media)
    await state.set_data({"post_id": post.id})


@router.message(PostEditorSG.waiting_for_media, F.photo | F.video)
async def add_media_process(message: Message, state: FSMContext, session: AsyncSession) -> None:
    post = await post_from_state(message, state, session)
    if post is None:
        return

    media_file_id = message.photo[-1].file_id if message.photo else message.video.file_id
    media_type = "photo" if message.photo else "video"

    if not caption_fits(post.text):
        # Медиа пока держим в состоянии: в базу оно попадёт только после решения пользователя
        await state.update_data(temp_media_id=media_file_id, temp_media_type=media_type)
        await message.answer(
            "⚠️ <b>Текст слишком длинный для медиа-поста!</b>\n\n"
            f"В вашем посте сейчас {visible_length(post.text or '')} символов. "
            "Лимит Telegram для подписи к фото — 1024 символа.\n\n"
            "Что мы сделаем?",
            reply_markup=get_compression_choice_keyboard(post.id),
        )
        await state.set_state(PostEditorSG.waiting_for_media_compression_decision)
        return

    post.media_file_id = media_file_id
    post.media_type = media_type
    await session.commit()
    await state.clear()
    await message.answer("✅ Медиа успешно добавлено.")
    await send_card(message, post)


@router.message(PostEditorSG.waiting_for_media)
async def add_media_wrong_content(message: Message) -> None:
    await message.answer("Пришлите одно фото или видео. Чтобы выйти, нажмите «Отмена» под сообщением выше.")


@router.callback_query(
    PostEditorSG.waiting_for_media_compression_decision,
    EditorCallback.filter(F.action.in_({"compress_yes", "compress_no"})),
)
async def process_compression_choice(
    call: CallbackQuery,
    callback_data: EditorCallback,
    state: FSMContext,
    session: AsyncSession,
    llm: LLMService,
) -> None:
    data = await state.get_data()
    post = await require_post(call, session, callback_data.post_id)
    if post is None:
        return
    await call.answer()
    await state.clear()
    keyboard = get_editor_main_keyboard(post.id)

    if data.get("post_id") != post.id or not data.get("temp_media_id"):
        await show(call, render_card(post), keyboard)
        return

    if callback_data.action == "compress_no":
        # Текст остаётся как есть; медиа к такому длинному тексту не прикрепить
        post.media_file_id = None
        post.media_type = None
        await session.commit()
        await show(call, "🚫 Фото отклонено. Текст оставлен в оригинальном виде.")
        await send(call, render_card(post), keyboard)
        return

    progress = await show(call, "⏳ Нейросеть сжимает текст, чтобы он поместился под фото...")
    current_text = post.text or ""
    await session.commit()  # на время запроса к модели соединение с БД возвращается в пул
    try:
        compressed_text = await llm.shorten_post_for_caption(current_text)
    except LLMError:
        compressed_text = None

    if not compressed_text or not caption_fits(compressed_text):
        # Сбой модели или текст всё ещё не влезает — ничего не меняем
        await show(
            call,
            "❌ Не получилось сократить текст до лимита подписи. Медиа не прикреплено, текст остался прежним.",
            target=progress,
        )
        await send(call, render_card(post), keyboard)
        return

    post.text = compressed_text
    post.media_file_id = data["temp_media_id"]
    post.media_type = data.get("temp_media_type")
    await session.commit()
    await show(call, "✅ Текст оптимизирован, фото прикреплено.", target=progress)
    await send(call, render_card(post), keyboard)
