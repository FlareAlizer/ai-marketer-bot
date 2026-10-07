from aiogram import Router, types
from aiogram.filters import Command
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Post
from keyboards.plan import get_plan_keyboard

router = Router()

@router.message(Command("plan"))
async def cmd_plan(message: types.Message, session: AsyncSession):
    """
    Показывает текущий контент-план пользователя.
    """
    user_id = message.from_user.id
    
    # Берем посты пользователя, сортируем по дням
    # Можно добавить фильтр .where(Post.status != 'published'), если хотим скрывать опубликованные
    stmt = select(Post).where(Post.user_id == user_id).order_by(Post.day_number)
    result = await session.execute(stmt)
    posts = result.scalars().all()
    
    if not posts:
        await message.answer("⚠️ У вас пока нет активного контент-плана.\nНажмите /start для создания.")
        return

    await message.answer(
        "📅 <b>Ваш контент-план:</b>\n"
        "Нажмите на день, чтобы редактировать или опубликовать пост.",
        reply_markup=get_plan_keyboard(posts),
        parse_mode="HTML"
    )