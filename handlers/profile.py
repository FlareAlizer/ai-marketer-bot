"""Профиль: просмотр, правка полей, история планов."""

import html

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import NICHE_MAX_LEN, User
from db.repo import get_owned_plan, get_plan_posts, get_user_plans
from handlers.channel import read_channel
from handlers.ui import NO_PROFILE_TEXT, read_text, send, show
from keyboards.menu import get_main_menu
from keyboards.plan import get_plan_keyboard
from keyboards.profile import (
    EditProfileCallback,
    PlanHistoryCallback,
    SetupCallback,
    get_goals_keyboard,
    get_history_list_keyboard,
    get_profile_keyboard,
    goal_title,
)
from services.prompts import ABOUT_LIMIT
from states.profile import ProfileSetupSG

router = Router(name="profile")

_EDIT_PROMPTS = {
    "niche": ("Введите новую <b>нишу</b>:", ProfileSetupSG.edit_niche),
    "about": ("Введите новое описание <b>о себе</b>:", ProfileSetupSG.edit_about),
    "goal": ("Выберите новую <b>цель</b>:", ProfileSetupSG.edit_goal),
    "channel": ("Пришлите @username канала или перешлите сообщение из него:", ProfileSetupSG.edit_channel),
}


def _value(value: object, empty: str = "не указано") -> str:
    return html.escape(str(value)) if value else empty


def render_profile(user: User) -> str:
    return (
        "👤 <b>Ваш профиль:</b>\n\n"
        f"1. <b>Ниша:</b> {_value(user.niche)}\n"
        f"2. <b>О себе:</b> {_value(user.expert_desc)}\n"
        f"3. <b>Цель:</b> {_value(user.content_goal)}\n"
        f"4. <b>Канал:</b> {_value(user.channel_id, 'не привязан')}"
    )


async def _profile_view(session: AsyncSession, user_id: int) -> tuple[str, InlineKeyboardMarkup | None]:
    user = await session.get(User, user_id)
    if user is None:
        return NO_PROFILE_TEXT, None
    return render_profile(user), get_profile_keyboard()


async def send_profile(message: Message, session: AsyncSession) -> None:
    """Отправляет профиль автора сообщения."""
    text, keyboard = await _profile_view(session, message.from_user.id)
    await message.answer(text, reply_markup=keyboard)


# --- Правка полей ---


@router.callback_query(EditProfileCallback.filter())
async def edit_profile_field(call: CallbackQuery, callback_data: EditProfileCallback, state: FSMContext) -> None:
    if callback_data.field not in _EDIT_PROMPTS:
        await call.answer()
        return
    prompt, next_state = _EDIT_PROMPTS[callback_data.field]
    keyboard = get_goals_keyboard() if callback_data.field == "goal" else None
    await call.answer()
    await show(call, prompt, keyboard)
    await state.set_state(next_state)


@router.message(ProfileSetupSG.edit_niche)
async def save_niche(message: Message, state: FSMContext, session: AsyncSession) -> None:
    niche = await read_text(message, NICHE_MAX_LEN)
    if niche is None:
        return
    await _save_field(message, state, session, "niche", niche, "✅ Ниша обновлена!")


@router.message(ProfileSetupSG.edit_about)
async def save_about(message: Message, state: FSMContext, session: AsyncSession) -> None:
    about = await read_text(message, ABOUT_LIMIT)
    if about is None:
        return
    await _save_field(message, state, session, "expert_desc", about, "✅ Описание обновлено!")


@router.message(ProfileSetupSG.edit_channel)
async def save_channel(message: Message, state: FSMContext, session: AsyncSession, bot: Bot) -> None:
    channel_id = await read_channel(message, bot)
    if channel_id is None:
        return
    await _save_field(message, state, session, "channel_id", channel_id, "✅ Канал обновлен!")


async def _save_field(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    field: str,
    value: object,
    done_text: str,
) -> None:
    user = await session.get(User, message.from_user.id)
    await state.clear()
    if user is None:
        await message.answer(NO_PROFILE_TEXT)
        return
    setattr(user, field, value)
    await session.commit()
    await message.answer(done_text, reply_markup=get_main_menu())
    await send_profile(message, session)


@router.callback_query(ProfileSetupSG.edit_goal, SetupCallback.filter(F.action == "goal"))
async def save_goal(
    call: CallbackQuery,
    callback_data: SetupCallback,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    user = await session.get(User, call.from_user.id)
    await state.clear()
    await call.answer()
    if user is None:
        await send(call, NO_PROFILE_TEXT)
        return
    user.content_goal = goal_title(callback_data.value)
    await session.commit()
    await send(call, "✅ Цель обновлена!", get_main_menu())
    await send(call, render_profile(user), get_profile_keyboard())


# --- История планов ---


@router.callback_query(F.data == "open_history_list")
async def show_history_list(call: CallbackQuery, session: AsyncSession) -> None:
    plans = await get_user_plans(session, call.from_user.id)
    if not plans:
        await call.answer("История пуста", show_alert=True)
        return
    await call.answer()
    await show(call, "📜 <b>Архив ваших планов:</b>", get_history_list_keyboard(plans))


@router.callback_query(PlanHistoryCallback.filter(F.action == "open"))
async def open_old_plan(call: CallbackQuery, callback_data: PlanHistoryCallback, session: AsyncSession) -> None:
    plan = await get_owned_plan(session, callback_data.plan_id, call.from_user.id)
    if plan is None:
        await call.answer("План не найден", show_alert=True)
        return
    posts = await get_plan_posts(session, plan.id)
    await call.answer()
    await show(call, f"📅 <b>План #{plan.id}:</b>", get_plan_keyboard(posts))


@router.callback_query(F.data == "back_to_profile")
async def back_to_profile(call: CallbackQuery, session: AsyncSession) -> None:
    text, keyboard = await _profile_view(session, call.from_user.id)
    await call.answer()
    await show(call, text, keyboard)
