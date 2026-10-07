from aiogram.fsm.state import State, StatesGroup


class PostEditorSG(StatesGroup):
    """Шаги редактора, где бот ждёт сообщение. ID поста лежит в данных состояния (post_id)."""

    # Правка темы
    waiting_for_new_topic_manual = State()

    # Правка текста
    waiting_for_text_manual = State()
    waiting_for_ai_instruction = State()

    # Медиа
    waiting_for_media = State()
    waiting_for_media_compression_decision = State()

    # Планирование
    waiting_for_single_date = State()  # один пост на конкретную дату
    waiting_for_batch_schedule = State()  # весь план по дням недели
