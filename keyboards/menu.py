"""Главное меню (reply-клавиатура)."""

from aiogram.types import ReplyKeyboardMarkup
from aiogram.utils.keyboard import ReplyKeyboardBuilder

BTN_PLAN = "📅 Мой контент-план"
BTN_PROFILE = "👤 Профиль"
BTN_NEW_PLAN = "➕ Создать новый план"


def get_main_menu() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text=BTN_PLAN)
    builder.button(text=BTN_PROFILE)
    builder.button(text=BTN_NEW_PLAN)
    builder.adjust(2, 1)
    return builder.as_markup(resize_keyboard=True)
