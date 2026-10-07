import re
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters.callback_data import CallbackData
from db.models import Post

class PostSelectCallback(CallbackData, prefix="select_post"):
    post_id: int
    action: str

def get_plan_keyboard(posts: list[Post]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    
    for post in posts:
        # 1. Убираем HTML теги
        raw_topic = re.sub(r'<[^>]+>', '', post.topic).strip()
        
        # 2. Пытаемся отделить Заголовок от Описания (если есть тире)
        parts = re.split(r' [-—] ', raw_topic, maxsplit=1)
        short_headline = parts[0]
        
        # 3. Чистим от лишних кавычек
        short_headline = short_headline.strip(' "')
        
        # 4. Обрезаем до 22 символов
        if len(short_headline) > 22:
            display_text = short_headline[:20] + ".."
        else:
            display_text = short_headline
        
        status_emoji = "✅" if post.status == "published" else "📝"
        
        # ИСПРАВЛЕНО: Убрали "Д", добавили "#" или просто номер
        button_text = f"{status_emoji} #{post.day_number}: {display_text}"
        
        builder.button(
            text=button_text,
            callback_data=PostSelectCallback(post_id=post.id, action="edit")
        )
    
    builder.button(text="➕ Новый план", callback_data="create_new_plan")
    builder.adjust(1)
    return builder.as_markup()