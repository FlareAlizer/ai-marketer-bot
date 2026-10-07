from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters.callback_data import CallbackData
from db.models import ContentPlan

class SetupCallback(CallbackData, prefix="setup"):
    action: str
    value: str

class PlanHistoryCallback(CallbackData, prefix="history"):
    plan_id: int
    action: str

class EditProfileCallback(CallbackData, prefix="edit_prof"):
    field: str 

# --- ЦЕЛИ ---
def get_goals_keyboard(is_new_plan: bool = False) -> InlineKeyboardMarkup:
    """
    is_new_plan=True -> action="goal_new"
    is_new_plan=False -> action="goal"
    """
    builder = InlineKeyboardBuilder()
    
    # Стандартные цели
    goals = [
        ("💰 Продажи", "sales"),
        ("🔥 Прогрев / Вовлечение", "engagement"),
        ("🎓 Экспертность / Доверие", "expert"),
        ("🚀 Личный бренд", "brand")
    ]
    
    action_key = "goal_new" if is_new_plan else "goal"
    
    for text, val in goals:
        builder.button(text=text, callback_data=SetupCallback(action=action_key, value=val))
    
    # --- НОВАЯ КНОПКА: Своя тема ---
    # Добавляем её только при создании НОВОГО плана, чтобы не усложнять регистрацию (или можно везде)
    if is_new_plan:
        builder.button(text="✍️ Своя тема/цель", callback_data=SetupCallback(action=action_key, value="own_input"))
    
    builder.adjust(1)
    return builder.as_markup()

# --- КОЛИЧЕСТВО ---
def get_quantity_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    quantities = [
        ("5 постов", "5"),
        ("7 постов (Неделя)", "7"),
        ("10 постов", "10"),
        ("14 постов (2 недели)", "14"),
        ("30 постов (Месяц)", "30")
    ]
    for text, val in quantities:
        builder.button(text=text, callback_data=SetupCallback(action="quantity", value=val))
    builder.adjust(1)
    return builder.as_markup()

# --- ПРОФИЛЬ ---
def get_profile_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🎯 Ниша", callback_data=EditProfileCallback(field="niche"))
    builder.button(text="📝 О себе", callback_data=EditProfileCallback(field="about"))
    builder.button(text="🏆 Цель", callback_data=EditProfileCallback(field="goal"))
    builder.button(text="📢 Канал", callback_data=EditProfileCallback(field="channel"))
    builder.button(text="📜 История планов", callback_data="open_history_list")
    builder.adjust(2, 2, 1)
    return builder.as_markup()

# --- ИСТОРИЯ ---
def get_history_list_keyboard(plans: list[ContentPlan]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for plan in plans:
        date_str = plan.created_at.strftime("%d.%m.%Y")
        builder.button(
            text=f"📅 План от {date_str}", 
            callback_data=PlanHistoryCallback(plan_id=plan.id, action="open")
        )
    builder.button(text="🔙 Назад", callback_data="back_to_profile")
    builder.adjust(1)
    return builder.as_markup()