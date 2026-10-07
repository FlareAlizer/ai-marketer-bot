"""Редактор: публикация сейчас, отложенная публикация одного поста и график для всего плана."""

import html
from datetime import timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Post, PostStatus, User
from db.repo import get_plan_posts
from handlers.editor.common import post_from_state, require_post
from handlers.ui import send
from keyboards.editor import PublishCallback, get_after_publish_keyboard, get_back_keyboard
from services.publisher import PublishError, check_post_ready, send_post
from services.schedule import (
    DATETIME_FORMAT,
    build_schedule,
    local_now,
    parse_batch_schedule,
    parse_single_datetime,
)
from states.editor import PostEditorSG

router = Router(name="editor.publish")

_NO_CHANNEL_TEXT = "❌ Канал не привязан. Настройте профиль."


async def _has_channel(session: AsyncSession, user_id: int) -> bool:
    user = await session.get(User, user_id)
    return bool(user and user.channel_id)


# --- Публикация сейчас ---


@router.callback_query(PublishCallback.filter(F.action == "now"))
async def process_publish_now(
    call: CallbackQuery,
    callback_data: PublishCallback,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
    tz: ZoneInfo,
) -> None:
    post = await require_post(call, session, callback_data.post_id)
    if post is None:
        return
    if post.status == PostStatus.PUBLISHED:
        # Защита от повторной отправки в канал по второму нажатию
        await call.answer("Этот пост уже опубликован.", show_alert=True)
        return
    await call.answer()

    user = await session.get(User, post.user_id)
    if user is None or not user.channel_id:
        await send(call, _NO_CHANNEL_TEXT)
        return

    try:
        await send_post(bot, user.channel_id, post)
    except PublishError as exc:
        await send(call, f"❌ Ошибка публикации: {html.escape(exc.reason)}")
        return

    post.status = PostStatus.PUBLISHED
    post.scheduled_time = local_now(tz)
    await session.commit()
    await state.clear()
    await send(call, "🚀 Опубликовано!", get_after_publish_keyboard(post.id))


# --- Один пост на дату ---


@router.callback_query(PublishCallback.filter(F.action == "schedule_single"))
async def start_single_schedule(
    call: CallbackQuery,
    callback_data: PublishCallback,
    state: FSMContext,
    session: AsyncSession,
    tz: ZoneInfo,
) -> None:
    post = await require_post(call, session, callback_data.post_id)
    if post is None:
        return
    await call.answer()
    example = (local_now(tz) + timedelta(days=1)).replace(hour=14, minute=0).strftime(DATETIME_FORMAT)
    await send(
        call,
        f"Введите дату и время публикации в формате:\n<code>ДД.ММ.ГГГГ ЧЧ:ММ</code>\n\nПример: <code>{example}</code>",
        get_back_keyboard(post.id),
    )
    await state.set_state(PostEditorSG.waiting_for_single_date)
    await state.set_data({"post_id": post.id})


@router.message(PostEditorSG.waiting_for_single_date)
async def process_single_schedule(message: Message, state: FSMContext, session: AsyncSession, tz: ZoneInfo) -> None:
    post = await post_from_state(message, state, session)
    if post is None:
        return

    run_date = parse_single_datetime(message.text or "")
    if run_date is None:
        await message.answer("❌ Неверный формат даты. Используй: ДД.ММ.ГГГГ ЧЧ:ММ")
        return
    if run_date <= local_now(tz):
        await message.answer("⚠️ Дата не может быть в прошлом!")
        return

    await state.clear()
    if not await _has_channel(session, post.user_id):
        await message.answer(_NO_CHANNEL_TEXT)
        return
    problem = check_post_ready(post)
    if problem:
        await message.answer(f"❌ Пост нельзя запланировать: {html.escape(problem)}")
        return

    post.status = PostStatus.SCHEDULED
    post.scheduled_time = run_date
    await session.commit()
    await message.answer(
        f"✅ Пост #{post.day_number} запланирован на {run_date.strftime(DATETIME_FORMAT)}",
        reply_markup=get_after_publish_keyboard(post.id),
    )


# --- График для всего плана ---


@router.callback_query(PublishCallback.filter(F.action == "schedule_batch"))
async def start_batch_schedule(
    call: CallbackQuery,
    callback_data: PublishCallback,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    post = await require_post(call, session, callback_data.post_id)
    if post is None:
        return
    await call.answer()
    await send(
        call,
        "🗓 <b>Гибкая настройка графика</b>\n"
        "Напишите дни и время для публикации (начиная с завтра).\n"
        "Примеры:\n<code>Пн Ср Пт 10:00</code>\n<code>Каждый день 18:30</code>",
        get_back_keyboard(post.id),
    )
    await state.set_state(PostEditorSG.waiting_for_batch_schedule)
    await state.set_data({"post_id": post.id})


def split_for_batch(posts: list[Post]) -> tuple[list[Post], list[Post]]:
    """Делит посты плана на те, что можно поставить в график, и те, что пока нельзя.

    Опубликованные посты в график не попадают вовсе. Нельзя запланировать пост
    без текста или с текстом, который не пройдёт лимиты Telegram.
    """
    ready, skipped = [], []
    for post in posts:
        if post.status == PostStatus.PUBLISHED:
            continue
        (skipped if check_post_ready(post) else ready).append(post)
    return ready, skipped


@router.message(PostEditorSG.waiting_for_batch_schedule)
async def process_batch_schedule(message: Message, state: FSMContext, session: AsyncSession, tz: ZoneInfo) -> None:
    post = await post_from_state(message, state, session)
    if post is None:
        return

    parsed = parse_batch_schedule(message.text or "")
    if parsed is None:
        await message.answer("⚠️ Не понял формат. Попробуйте: <code>Пн Вт 15:00</code>")
        return
    weekdays, at = parsed

    await state.clear()
    if not await _has_channel(session, post.user_id):
        await message.answer(_NO_CHANNEL_TEXT)
        return

    ready, skipped = split_for_batch(list(await get_plan_posts(session, post.plan_id)))
    slots = build_schedule(local_now(tz), weekdays, at, len(ready))
    for item, slot in zip(ready, slots, strict=True):
        item.status = PostStatus.SCHEDULED
        item.scheduled_time = slot
    await session.commit()

    text = f"✅ Запланировано {len(ready)} постов по графику!"
    if slots:
        text += f"\nПервый: {slots[0].strftime(DATETIME_FORMAT)}, последний: {slots[-1].strftime(DATETIME_FORMAT)}."
    if skipped:
        numbers = ", ".join(f"#{item.day_number}" for item in skipped)
        text += (
            f"\n\n⚠️ Не попали в график: {numbers}. У них ещё нет текста или он не проходит лимиты Telegram. "
            "Откройте эти посты в редакторе и запустите график ещё раз."
        )
    await message.answer(text, reply_markup=get_after_publish_keyboard(post.id))
