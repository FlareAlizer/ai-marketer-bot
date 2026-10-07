"""Анкета при первом запуске: ниша -> о себе -> цель -> канал -> количество постов."""

import html

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import NICHE_MAX_LEN
from db.repo import get_or_create_user
from handlers.channel import read_channel
from handlers.ui import read_text, show
from keyboards.profile import SetupCallback, get_goals_keyboard, get_quantity_keyboard, goal_title
from services.prompts import ABOUT_LIMIT
from states.profile import ProfileSetupSG

router = Router(name="onboarding")


@router.message(ProfileSetupSG.input_niche)
async def process_niche(message: Message, state: FSMContext) -> None:
    niche = await read_text(message, NICHE_MAX_LEN)
    if niche is None:
        return
    await state.update_data(niche=niche)
    await message.answer(
        f"🔥 {html.escape(niche)} — отличная ниша!\n\n"
        "Теперь расскажи немного <b>о себе</b>. Это поможет мне писать тексты в твоем стиле.\n"
        "Кто ты? Какой у тебя опыт? О чем твой проект?"
    )
    await state.set_state(ProfileSetupSG.input_about)


@router.message(ProfileSetupSG.input_about)
async def process_about(message: Message, state: FSMContext) -> None:
    about = await read_text(message, ABOUT_LIMIT)
    if about is None:
        return
    await state.update_data(expert_desc=about)
    await message.answer("Какая <b>цель</b> у этого контент-плана?", reply_markup=get_goals_keyboard())
    await state.set_state(ProfileSetupSG.choose_goal)


@router.callback_query(ProfileSetupSG.choose_goal, SetupCallback.filter(F.action == "goal"))
async def process_goal(call: CallbackQuery, callback_data: SetupCallback, state: FSMContext) -> None:
    selected_goal = goal_title(callback_data.value)
    await state.update_data(content_goal=selected_goal)
    await call.answer()
    await show(
        call,
        f"Цель: <b>{selected_goal}</b>.\n\n"
        "📢 <b>Теперь привяжем твой Telegram-канал.</b>\n\n"
        "1. Добавь меня в администраторы своего канала.\n"
        "2. Перешли мне любое сообщение из этого канала (или напиши @username канала).",
    )
    await state.set_state(ProfileSetupSG.input_channel)


@router.message(ProfileSetupSG.input_channel)
async def process_channel_link(message: Message, state: FSMContext, session: AsyncSession, bot: Bot) -> None:
    channel_id = await read_channel(message, bot)
    if channel_id is None:
        return

    data = await state.get_data()
    if not data.get("niche") or not data.get("expert_desc"):
        # Данные анкеты потерялись (например, очищен Redis) — начинаем заново
        await state.clear()
        await message.answer("Анкета сбросилась. Нажмите /start, чтобы пройти её заново.")
        return

    # Профиль сохраняется сразу: он не должен зависеть от того, получится ли сгенерировать план
    user = await get_or_create_user(session, message.from_user)
    user.niche = data["niche"]
    user.expert_desc = data["expert_desc"]
    user.content_goal = data.get("content_goal")
    user.channel_id = channel_id
    await session.commit()

    await state.set_data({"content_goal": user.content_goal})
    await message.answer(
        "✅ Канал привязан!\nДавай составим твой первый план. <b>Сколько постов нужно?</b>",
        reply_markup=get_quantity_keyboard(),
    )
    await state.set_state(ProfileSetupSG.choose_quantity)
