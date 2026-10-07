from aiogram.fsm.state import State, StatesGroup


class ProfileSetupSG(StatesGroup):
    # Анкета регистрации
    input_niche = State()
    input_about = State()
    choose_goal = State()
    input_channel = State()

    # Генерация нового плана
    choose_goal_new_plan = State()
    input_own_goal_new_plan = State()
    choose_quantity = State()

    # Редактирование профиля
    edit_niche = State()
    edit_about = State()
    edit_goal = State()
    edit_channel = State()
