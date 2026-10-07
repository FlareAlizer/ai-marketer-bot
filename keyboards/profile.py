"""Клавиатуры анкеты, профиля и истории планов."""

from collections.abc import Iterable

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from db.models import ContentPlan

# Код цели в callback -> (текст кнопки, значение, которое сохраняется в профиль и уходит в промпт)
GOALS: dict[str, tuple[str, str]] = {
    "sales": ("💰 Продажи", "Продажи"),
    "engagement": ("🔥 Прогрев / Вовлечение", "Вовлечение"),
    "expert": ("🎓 Экспертность / Доверие", "Экспертность"),
    "brand": ("🚀 Личный бренд", "Личный бренд"),
}
DEFAULT_GOAL = "Продажи"
OWN_GOAL_VALUE = "own_input"

QUANTITIES: list[tuple[str, int]] = [
    ("5 постов", 5),
    ("7 постов (Неделя)", 7),
    ("10 постов", 10),
    ("14 постов (2 недели)", 14),
    ("30 постов (Месяц)", 30),
]
ALLOWED_QUANTITIES = frozenset(quantity for _, quantity in QUANTITIES)


class SetupCallback(CallbackData, prefix="setup"):
    action: str
    value: str


class PlanHistoryCallback(CallbackData, prefix="history"):
    plan_id: int
    action: str


class EditProfileCallback(CallbackData, prefix="edit_prof"):
    field: str


def goal_title(code: str) -> str:
    """Название цели по коду из кнопки. Неизвестный код — цель по умолчанию."""
    return GOALS[code][1] if code in GOALS else DEFAULT_GOAL


def get_goals_keyboard(is_new_plan: bool = False) -> InlineKeyboardMarkup:
    """Выбор цели. Для нового плана action="goal_new" и есть кнопка «Своя тема», в анкете — action="goal"."""
    builder = InlineKeyboardBuilder()
    action_key = "goal_new" if is_new_plan else "goal"
    for code, (text, _) in GOALS.items():
        builder.button(text=text, callback_data=SetupCallback(action=action_key, value=code))
    if is_new_plan:
        builder.button(text="✍️ Своя тема/цель", callback_data=SetupCallback(action=action_key, value=OWN_GOAL_VALUE))
    builder.adjust(1)
    return builder.as_markup()


def get_quantity_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for text, quantity in QUANTITIES:
        builder.button(text=text, callback_data=SetupCallback(action="quantity", value=str(quantity)))
    builder.adjust(1)
    return builder.as_markup()


def get_profile_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🎯 Ниша", callback_data=EditProfileCallback(field="niche"))
    builder.button(text="📝 О себе", callback_data=EditProfileCallback(field="about"))
    builder.button(text="🏆 Цель", callback_data=EditProfileCallback(field="goal"))
    builder.button(text="📢 Канал", callback_data=EditProfileCallback(field="channel"))
    builder.button(text="📜 История планов", callback_data="open_history_list")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def get_history_list_keyboard(plans: Iterable[ContentPlan]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for plan in plans:
        date_str = plan.created_at.strftime("%d.%m.%Y")
        builder.button(
            text=f"📅 План от {date_str}",
            callback_data=PlanHistoryCallback(plan_id=plan.id, action="open"),
        )
    builder.button(text="🔙 Назад", callback_data="back_to_profile")
    builder.adjust(1)
    return builder.as_markup()
