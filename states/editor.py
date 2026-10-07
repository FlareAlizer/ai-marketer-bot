from aiogram.fsm.state import State, StatesGroup

class PostEditorSG(StatesGroup):
    viewing = State()            # Главное меню редактора
    
    # Ветка: Правка Темы
    waiting_for_new_topic_manual = State() # Ввод новой темы вручную
    
    # Ветка: Правка Текста
    waiting_for_text_manual = State()      # Ввод всего текста вручную
    waiting_for_ai_instruction = State()   # Инструкция для AI
    
    # Медиа
    waiting_for_media = State()
    
    # Планирование
    waiting_for_single_date = State() # Обычное планирование одного поста
    waiting_for_batch_schedule = State() # Пакетное планирование (гибкие сроки)

    waiting_for_media_compression_decision = State()