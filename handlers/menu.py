"""Команды и кнопки главного меню.

Роутер подключается первым: /start и кнопки меню работают из любого шага
и сбрасывают незавершённый ввод, чтобы следующий текст не ушёл в чужой шаг.
"""

import html

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from db.repo import get_or_create_user
from handlers.plan import send_current_plan, start_new_plan
from handlers.profile import send_profile
from handlers.ui import send
from keyboards.menu import BTN_NEW_PLAN, BTN_PLAN, BTN_PROFILE, get_main_menu
from states.profile import ProfileSetupSG

router = Router(name="menu")


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext, session: AsyncSession) -> None:
    user = await get_or_create_user(session, message.from_user)
    await state.clear()
    first_name = html.escape(message.from_user.first_name)

    if user.niche and user.expert_desc:
        await message.answer(
            f"Рад тебя видеть снова, {first_name}! ✨\nТвой ИИ-маркетолог на связи. Готов создавать новый контент?",
            reply_markup=get_main_menu(),
        )
        return

    await message.answer(
        f"Привет, {first_name}! 🚀\n\n"
        "Я помогу тебе вести Telegram-канал на уровне топовых медиа. "
        "Я умею составлять стратегии, писать вовлекающие тексты и планировать посты.\n\n"
        "Давай познакомимся! <b>В какой нише ты развиваешься?</b>\n"
        "<i>Например: Криптовалюты, Психология отношений, Дизайн интерьеров...</i>"
    )
    await state.set_state(ProfileSetupSG.input_niche)


@router.message(Command("plan"))
@router.message(F.text == BTN_PLAN)
async def menu_my_plan(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    await send_current_plan(message, session)


@router.message(F.text == BTN_PROFILE)
async def menu_profile(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    await send_profile(message, session)


@router.message(F.text == BTN_NEW_PLAN)
async def menu_new_plan(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    await start_new_plan(message, state, session)


@router.callback_query(F.data == "go_to_main_menu")
async def go_to_main_menu(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.answer()
    await send(call, "Вы вернулись в главное меню. Что делаем дальше?", get_main_menu())
