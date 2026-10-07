from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters.callback_data import CallbackData

# CallbackData для действий в редакторе
class EditorCallback(CallbackData, prefix="editor"):
    action: str 

# CallbackData для публикации
class PublishCallback(CallbackData, prefix="pub"):
    action: str 

def get_editor_main_keyboard() -> InlineKeyboardMarkup:
    """Главное меню редактора конкретного поста"""
    builder = InlineKeyboardBuilder()
    
    # Ряд 1: Основные разделы
    builder.button(text="📝 Тема", callback_data=EditorCallback(action="menu_topic"))
    builder.button(text="✍️ Текст", callback_data=EditorCallback(action="menu_text"))
    
    # Ряд 2: Медиа и Превью
    builder.button(text="📷 Медиа", callback_data=EditorCallback(action="add_media"))
    builder.button(text="👁 Предпросмотр", callback_data=EditorCallback(action="preview"))
    
    # Ряд 3: Самая важная кнопка возврата
    builder.button(text="🔙 Назад к плану", callback_data=EditorCallback(action="back"))
    
    builder.adjust(2, 2, 1)
    return builder.as_markup()

def get_topic_edit_keyboard() -> InlineKeyboardMarkup:
    """Подменю: Правка Темы"""
    builder = InlineKeyboardBuilder()
    builder.button(text="⌨️ Вручную (+ тезисы)", callback_data=EditorCallback(action="topic_manual"))
    builder.button(text="🔙 Отмена", callback_data=EditorCallback(action="back_to_main"))
    builder.adjust(1)
    return builder.as_markup()

def get_text_edit_keyboard() -> InlineKeyboardMarkup:
    """Подменю: Правка Текста"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🤖 AI-правка", callback_data=EditorCallback(action="text_ai"))
    builder.button(text="✏️ Вручную", callback_data=EditorCallback(action="text_manual"))
    builder.button(text="🔄 Переписать всё", callback_data=EditorCallback(action="text_regen"))
    builder.button(text="🔙 Отмена", callback_data=EditorCallback(action="back_to_main"))
    builder.adjust(1)
    return builder.as_markup()

def get_back_keyboard() -> InlineKeyboardMarkup:
    """Кнопка отмены действия (возврат в главное меню редактора)"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Отмена", callback_data=EditorCallback(action="back_to_main"))
    return builder.as_markup()

def get_preview_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🚀 Опубликовать СЕЙЧАС", callback_data=PublishCallback(action="now"))
    builder.button(text="🗓 Запланировать пост", callback_data=PublishCallback(action="schedule_single"))
    builder.button(text="📅 График плана", callback_data=PublishCallback(action="schedule_batch"))
    
    # ВОТ ЭТА КНОПКА (возвращает в главное меню редактора)
    builder.button(text="✏️ Редактировать", callback_data=EditorCallback(action="back_to_main"))
    
    builder.adjust(1)
    return builder.as_markup()

def get_after_publish_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📅 К списку постов", callback_data=EditorCallback(action="back"))
    
    # НОВАЯ КНОПКА: чтобы юзер не застревал в редакторе
    builder.button(text="👤 В главное меню", callback_data="go_to_main_menu")
    return builder.as_markup()

def get_compression_choice_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✂️ Сжать текст и оставить фото", callback_data=EditorCallback(action="compress_yes"))
    builder.button(text="📝 Оставить текст (без фото)", callback_data=EditorCallback(action="compress_no"))
    builder.adjust(1)
    return builder.as_markup()
