"""Клавиатуры редактора поста.

ID поста передаётся в каждой кнопке: кнопки под старыми сообщениями продолжают
относиться к своему посту, даже если пользователь уже открыл другой.
"""

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from keyboards.plan import PostSelectCallback


class EditorCallback(CallbackData, prefix="editor"):
    action: str
    post_id: int


class PublishCallback(CallbackData, prefix="pub"):
    action: str
    post_id: int


def get_editor_main_keyboard(post_id: int) -> InlineKeyboardMarkup:
    """Главное меню редактора конкретного поста."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Тема", callback_data=EditorCallback(action="menu_topic", post_id=post_id))
    builder.button(text="✍️ Текст", callback_data=EditorCallback(action="menu_text", post_id=post_id))
    builder.button(text="📷 Медиа", callback_data=EditorCallback(action="add_media", post_id=post_id))
    builder.button(text="👁 Предпросмотр", callback_data=EditorCallback(action="preview", post_id=post_id))
    builder.button(text="🔙 Назад к плану", callback_data=EditorCallback(action="back", post_id=post_id))
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def get_topic_edit_keyboard(post_id: int) -> InlineKeyboardMarkup:
    """Подменю: правка темы."""
    builder = InlineKeyboardBuilder()
    builder.button(text="⌨️ Вручную (+ тезисы)", callback_data=EditorCallback(action="topic_manual", post_id=post_id))
    builder.button(text="🔙 Отмена", callback_data=EditorCallback(action="back_to_main", post_id=post_id))
    builder.adjust(1)
    return builder.as_markup()


def get_text_edit_keyboard(post_id: int) -> InlineKeyboardMarkup:
    """Подменю: правка текста."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🤖 AI-правка", callback_data=EditorCallback(action="text_ai", post_id=post_id))
    builder.button(text="✏️ Вручную", callback_data=EditorCallback(action="text_manual", post_id=post_id))
    builder.button(text="🔄 Переписать всё", callback_data=EditorCallback(action="text_regen", post_id=post_id))
    builder.button(text="🔙 Отмена", callback_data=EditorCallback(action="back_to_main", post_id=post_id))
    builder.adjust(1)
    return builder.as_markup()


def get_back_keyboard(post_id: int) -> InlineKeyboardMarkup:
    """Отмена ввода: возврат к карточке поста."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Отмена", callback_data=EditorCallback(action="back_to_main", post_id=post_id))
    return builder.as_markup()


def get_preview_keyboard(post_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🚀 Опубликовать СЕЙЧАС", callback_data=PublishCallback(action="now", post_id=post_id))
    builder.button(
        text="🗓 Запланировать пост", callback_data=PublishCallback(action="schedule_single", post_id=post_id)
    )
    builder.button(text="📅 График плана", callback_data=PublishCallback(action="schedule_batch", post_id=post_id))
    builder.button(text="✏️ Редактировать", callback_data=EditorCallback(action="back_to_main", post_id=post_id))
    builder.adjust(1)
    return builder.as_markup()


def get_after_publish_keyboard(post_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📅 К списку постов", callback_data=EditorCallback(action="back", post_id=post_id))
    builder.button(text="👤 В главное меню", callback_data="go_to_main_menu")
    return builder.as_markup()


def get_compression_choice_keyboard(post_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✂️ Сжать текст и оставить фото", callback_data=EditorCallback(action="compress_yes", post_id=post_id)
    )
    builder.button(
        text="📝 Оставить текст (без фото)", callback_data=EditorCallback(action="compress_no", post_id=post_id)
    )
    builder.adjust(1)
    return builder.as_markup()


def get_generation_failed_keyboard(post_id: int) -> InlineKeyboardMarkup:
    """Показывается, когда текст поста не удалось сгенерировать."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Попробовать снова", callback_data=PostSelectCallback(post_id=post_id, action="edit"))
    builder.button(text="🔙 Назад к плану", callback_data=EditorCallback(action="back", post_id=post_id))
    builder.adjust(1)
    return builder.as_markup()
