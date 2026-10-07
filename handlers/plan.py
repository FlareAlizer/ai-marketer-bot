"""Контент-план: показ текущего плана и генерация нового."""

import html
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ContentPlan, Post, PostStatus, User
from db.repo import get_latest_plan_id, get_plan_posts
from handlers.ui import NO_PROFILE_TEXT, delete_quietly, read_text, send, show
from keyboards.menu import get_main_menu
from keyboards.plan import get_plan_keyboard
from keyboards.profile import (
    ALLOWED_QUANTITIES,
    DEFAULT_GOAL,
    OWN_GOAL_VALUE,
    SetupCallback,
    get_goals_keyboard,
    get_quantity_keyboard,
    goal_title,
)
from services.llm import LLMError, LLMService
from services.parsers import parse_plan_text
from services.prompts import GOAL_LIMIT
from states.profile import ProfileSetupSG

logger = logging.getLogger(__name__)
router = Router(name="plan")

_NEW_PLAN_TEXT = "<b>Шаг 1/2:</b> Выберите цель для ЭТОГО контент-плана\nИли напишите свою тему, нажав кнопку ниже:"


async def send_current_plan(message: Message, session: AsyncSession) -> None:
    """Показывает последний план автора сообщения."""
    plan_id = await get_latest_plan_id(session, message.from_user.id)
    if plan_id is None:
        await message.answer("У вас пока нет плана. Нажмите '➕ Создать новый план'.")
        return
    posts = await get_plan_posts(session, plan_id)
    await message.answer("📅 <b>Ваш текущий план:</b>", reply_markup=get_plan_keyboard(posts))


async def _has_profile(session: AsyncSession, user_id: int) -> bool:
    user = await session.get(User, user_id)
    return bool(user and user.niche)


async def start_new_plan(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Первый шаг создания плана по кнопке главного меню."""
    if not await _has_profile(session, message.from_user.id):
        await message.answer(NO_PROFILE_TEXT)
        return
    await message.answer(_NEW_PLAN_TEXT, reply_markup=get_goals_keyboard(is_new_plan=True))
    await state.set_state(ProfileSetupSG.choose_goal_new_plan)


@router.callback_query(F.data == "create_new_plan")
async def callback_new_plan(call: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await call.answer()
    await state.clear()
    if not await _has_profile(session, call.from_user.id):
        await send(call, NO_PROFILE_TEXT)
        return
    await show(call, _NEW_PLAN_TEXT, get_goals_keyboard(is_new_plan=True))
    await state.set_state(ProfileSetupSG.choose_goal_new_plan)


@router.callback_query(ProfileSetupSG.choose_goal_new_plan, SetupCallback.filter(F.action == "goal_new"))
async def process_goal_new_plan(call: CallbackQuery, callback_data: SetupCallback, state: FSMContext) -> None:
    await call.answer()
    if callback_data.value == OWN_GOAL_VALUE:
        await show(
            call,
            "✍️ <b>Напишите тему/цель вашего плана:</b>\n"
            "<i>(Например: Прогрев к курсу по дизайну, Неделя разбора кейсов, или просто 'Хочу поднять охваты')</i>",
        )
        await state.set_state(ProfileSetupSG.input_own_goal_new_plan)
        return

    selected_goal = goal_title(callback_data.value)
    await state.update_data(content_goal=selected_goal)
    await show(
        call,
        f"Цель: <b>{selected_goal}</b>.\n<b>Шаг 2/2:</b> Сколько постов составить?",
        get_quantity_keyboard(),
    )
    await state.set_state(ProfileSetupSG.choose_quantity)


@router.message(ProfileSetupSG.input_own_goal_new_plan)
async def process_own_goal_input(message: Message, state: FSMContext) -> None:
    custom_goal = await read_text(message, GOAL_LIMIT)
    if custom_goal is None:
        return
    await state.update_data(content_goal=custom_goal)
    await message.answer(
        f"Тема: <b>{html.escape(custom_goal)}</b>.\n<b>Шаг 2/2:</b> Сколько постов составить?",
        reply_markup=get_quantity_keyboard(),
    )
    await state.set_state(ProfileSetupSG.choose_quantity)


@router.callback_query(ProfileSetupSG.choose_quantity, SetupCallback.filter(F.action == "quantity"))
async def process_quantity_and_generate(
    call: CallbackQuery,
    callback_data: SetupCallback,
    state: FSMContext,
    session: AsyncSession,
    llm: LLMService,
) -> None:
    # Значение приходит из callback-данных, поэтому сверяем его со списком кнопок
    if not callback_data.value.isdigit() or int(callback_data.value) not in ALLOWED_QUANTITIES:
        await call.answer("Выберите количество кнопкой.", show_alert=True)
        return
    quantity = int(callback_data.value)

    user = await session.get(User, call.from_user.id)
    if user is None or not user.niche:
        await call.answer()
        await state.clear()
        await send(call, NO_PROFILE_TEXT)
        return

    data = await state.get_data()
    goal = data.get("content_goal") or user.content_goal or DEFAULT_GOAL
    niche, about, user_id = user.niche, user.expert_desc, user.id
    # На время запроса к модели соединение с БД возвращается в пул
    await session.commit()

    await call.answer()
    progress = await show(call, f"⏳ Генерирую план из {quantity} постов (Тема: {html.escape(goal)})...")

    try:
        plan_text = await llm.generate_content_plan(niche=niche, about=about, goal=goal, quantity=quantity)
        items = parse_plan_text(plan_text, limit=quantity)
    except LLMError:
        items = []

    if not items:
        # Состояние не меняем: кнопки количества остаются рабочими для повторной попытки
        await show(call, "⚠️ Ошибка генерации. Попробуйте еще раз.", get_quantity_keyboard(), target=progress)
        return

    # План создаётся только после удачной генерации — пустых планов в истории не остаётся
    plan = ContentPlan(user_id=user_id)
    plan.posts = [
        Post(user_id=user_id, day_number=item.day, topic=item.topic, status=PostStatus.GENERATED) for item in items
    ]
    session.add(plan)
    await session.commit()
    await state.clear()

    await delete_quietly(progress)
    await send(
        call,
        f"✅ <b>План готов!</b>\nТема: {html.escape(goal)}",
        get_plan_keyboard(plan.posts),
    )
    await send(call, "Ваш план сохранен. Вы можете редактировать каждый пост отдельно.", get_main_menu())
