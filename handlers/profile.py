from aiogram import Router, F, types, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User, ContentPlan, Post
from states.profile import ProfileSetupSG
from keyboards.profile import (
    get_goals_keyboard, 
    get_quantity_keyboard, 
    SetupCallback, 
    get_profile_keyboard, 
    get_history_list_keyboard, 
    PlanHistoryCallback,
    EditProfileCallback
)
from keyboards.plan import get_plan_keyboard 
from services.llm import llm_client
from services.parsers import parse_plan_text

router = Router()

# --- ВСПОМОГАТЕЛЬНАЯ: Главное меню ---
def get_main_menu():
    builder = ReplyKeyboardBuilder()
    builder.button(text="📅 Мой контент-план")
    builder.button(text="👤 Профиль")
    builder.button(text="➕ Создать новый план")
    builder.adjust(2, 1)
    return builder.as_markup(resize_keyboard=True)

# --- 1. СТАРТ (Умная логика) ---
@router.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext, session: AsyncSession):
    user_id = message.from_user.id
    user = await session.get(User, user_id)
    
    if not user:
        user = User(id=user_id, username=message.from_user.username, full_name=message.from_user.full_name)
        session.add(user)
        await session.commit()

    if user.niche and user.expert_desc:
        await message.answer(
            f"Рад тебя видеть снова, {message.from_user.first_name}! ✨\n"
            "Твой ИИ-маркетолог на связи. Готов создавать новый контент?",
            reply_markup=get_main_menu()
        )
        return

    await message.answer(
        f"Привет, {message.from_user.first_name}! 🚀\n\n"
        "Я помогу тебе вести Telegram-канал на уровне топовых медиа. "
        "Я умею составлять стратегии, писать вовлекающие тексты и планировать посты.\n\n"
        "Давай познакомимся! <b>В какой нише ты развиваешься?</b>\n"
        "<i>Например: Криптовалюты, Психология отношений, Дизайн интерьеров...</i>",
        parse_mode="HTML"
    )
    await state.set_state(ProfileSetupSG.input_niche)

# --- 2. АНКЕТА РЕГИСТРАЦИИ ---

@router.message(ProfileSetupSG.input_niche)
async def process_niche(message: types.Message, state: FSMContext):
    await state.update_data(niche=message.text)
    await message.answer(
        f"🔥 {message.text} — отличная ниша!\n\n"
        "Теперь расскажи немного <b>о себе</b>. Это поможет мне писать тексты в твоем стиле.\n"
        "Кто ты? Какой у тебя опыт? О чем твой проект?",
        parse_mode="HTML"
    )
    await state.set_state(ProfileSetupSG.input_about)

@router.message(ProfileSetupSG.input_about)
async def process_about(message: types.Message, state: FSMContext):
    await state.update_data(expert_desc=message.text)
    await message.answer(
        "Какая <b>цель</b> у этого контент-плана?",
        reply_markup=get_goals_keyboard(),
        parse_mode="HTML"
    )
    await state.set_state(ProfileSetupSG.choose_goal)

@router.callback_query(ProfileSetupSG.choose_goal, SetupCallback.filter(F.action == "goal"))
async def process_goal(call: types.CallbackQuery, callback_data: SetupCallback, state: FSMContext):
    goals_map = {"sales": "Продажи", "engagement": "Вовлечение", "expert": "Экспертность", "brand": "Личный бренд"}
    selected_goal = goals_map.get(callback_data.value, "Продажи")
    
    await state.update_data(content_goal=selected_goal)
    
    await call.message.edit_text(
        f"Цель: <b>{selected_goal}</b>.\n\n"
        "📢 <b>Теперь привяжем твой Telegram-канал.</b>\n\n"
        "1. Добавь меня в администраторы своего канала.\n"
        "2. Перешли мне любое сообщение из этого канала (или напиши @username канала).",
        parse_mode="HTML"
    )
    await state.set_state(ProfileSetupSG.input_channel)

@router.message(ProfileSetupSG.input_channel)
async def process_channel_link(message: types.Message, state: FSMContext, bot: Bot):
    channel_id = None
    if message.forward_from_chat and message.forward_from_chat.type == 'channel':
        channel_id = message.forward_from_chat.id
    elif message.text and message.text.startswith('@'):
        try:
            chat = await bot.get_chat(message.text)
            if chat.type == 'channel':
                channel_id = chat.id
        except Exception: pass

    if not channel_id:
        await message.answer("❌ Не могу найти канал. Проверь права админа и username.")
        return

    try:
        member = await bot.get_chat_member(channel_id, bot.id)
        if member.status not in ('administrator', 'creator'):
            await message.answer("⚠️ Я не администратор в этом канале.")
            return
    except Exception:
        await message.answer("❌ Ошибка доступа к каналу.")
        return

    await state.update_data(channel_id=channel_id)
    
    await message.answer(
        "✅ Канал привязан!\nДавай составим твой первый план. <b>Сколько постов нужно?</b>",
        reply_markup=get_quantity_keyboard(),
        parse_mode="HTML"
    )
    await state.set_state(ProfileSetupSG.choose_quantity)


# --- 3. МЕНЮ: ПРОФИЛЬ И РЕДАКТИРОВАНИЕ ---

@router.message(F.text == "👤 Профиль")
async def menu_profile(message: types.Message, session: AsyncSession):
    user = await session.get(User, message.from_user.id)
    txt = (
        f"👤 <b>Ваш профиль:</b>\n\n"
        f"1. <b>Ниша:</b> {user.niche}\n"
        f"2. <b>О себе:</b> {user.expert_desc}\n"
        f"3. <b>Цель:</b> {user.content_goal}\n"
        f"4. <b>Канал:</b> {user.channel_id}"
    )
    await message.answer(txt, parse_mode="HTML", reply_markup=get_profile_keyboard())

@router.callback_query(EditProfileCallback.filter())
async def edit_profile_field(call: types.CallbackQuery, callback_data: EditProfileCallback, state: FSMContext):
    field = callback_data.field
    await state.update_data(editing_field=field)
    
    prompts = {
        "niche": "Введите новую <b>нишу</b>:",
        "about": "Введите новое описание <b>о себе</b>:",
        "goal": "Выберите новую <b>цель</b>:",
        "channel": "Пришлите @username канала или перешлите сообщение из него:"
    }
    
    if field == "goal":
        await call.message.edit_text(prompts[field], reply_markup=get_goals_keyboard(), parse_mode="HTML")
        await state.set_state(ProfileSetupSG.edit_goal)
    elif field == "channel":
        await call.message.edit_text(prompts[field], parse_mode="HTML")
        await state.set_state(ProfileSetupSG.edit_channel)
    else:
        await call.message.edit_text(prompts[field], parse_mode="HTML")
        if field == "niche": await state.set_state(ProfileSetupSG.edit_niche)
        if field == "about": await state.set_state(ProfileSetupSG.edit_about)
    
    await call.answer()

@router.message(ProfileSetupSG.edit_niche)
async def save_niche(message: types.Message, state: FSMContext, session: AsyncSession):
    user = await session.get(User, message.from_user.id)
    user.niche = message.text
    await session.commit()
    await message.answer("✅ Ниша обновлена!", reply_markup=get_main_menu())
    await state.clear()
    await menu_profile(message, session)

@router.message(ProfileSetupSG.edit_about)
async def save_about(message: types.Message, state: FSMContext, session: AsyncSession):
    user = await session.get(User, message.from_user.id)
    user.expert_desc = message.text
    await session.commit()
    await message.answer("✅ Описание обновлено!", reply_markup=get_main_menu())
    await state.clear()
    await menu_profile(message, session)

@router.callback_query(ProfileSetupSG.edit_goal, SetupCallback.filter(F.action == "goal"))
async def save_goal(call: types.CallbackQuery, callback_data: SetupCallback, state: FSMContext, session: AsyncSession):
    user = await session.get(User, call.from_user.id)
    goals_map = {"sales": "Продажи", "engagement": "Вовлечение", "expert": "Экспертность", "brand": "Личный бренд"}
    user.content_goal = goals_map.get(callback_data.value, "Продажи")
    await session.commit()
    await call.message.answer("✅ Цель обновлена!", reply_markup=get_main_menu())
    await state.clear()
    await menu_profile(call.message, session)

@router.message(ProfileSetupSG.edit_channel)
async def save_channel(message: types.Message, state: FSMContext, session: AsyncSession, bot: Bot):
    channel_id = None
    if message.forward_from_chat and message.forward_from_chat.type == 'channel':
        channel_id = message.forward_from_chat.id
    elif message.text.startswith('@'):
        try:
            chat = await bot.get_chat(message.text)
            channel_id = chat.id
        except: pass
    
    if not channel_id:
        await message.answer("❌ Не удалось найти канал.")
        return

    try:
        member = await bot.get_chat_member(channel_id, bot.id)
        if member.status not in ('administrator', 'creator'):
            await message.answer("⚠️ Я не админ в этом канале.")
            return
    except:
        await message.answer("❌ Ошибка доступа.")
        return

    user = await session.get(User, message.from_user.id)
    user.channel_id = channel_id
    await session.commit()
    await message.answer("✅ Канал обновлен!", reply_markup=get_main_menu())
    await state.clear()
    await menu_profile(message, session)


# --- 4. МЕНЮ: МОЙ ПЛАН И ИСТОРИЯ ---

@router.message(F.text == "📅 Мой контент-план")
async def menu_my_plan(message: types.Message, session: AsyncSession):
    user_id = message.from_user.id
    last_plan_stmt = select(ContentPlan.id).where(ContentPlan.user_id == user_id).order_by(ContentPlan.created_at.desc()).limit(1)
    last_plan_id = await session.scalar(last_plan_stmt)
    
    if not last_plan_id:
        await message.answer("У вас пока нет плана. Нажмите '➕ Создать новый план'.")
        return

    posts_stmt = select(Post).where(Post.plan_id == last_plan_id).order_by(Post.day_number)
    result = await session.execute(posts_stmt)
    posts = result.scalars().all()

    await message.answer(
        "📅 <b>Ваш текущий план:</b>", 
        reply_markup=get_plan_keyboard(posts), 
        parse_mode="HTML"
    )

@router.callback_query(F.data == "open_history_list")
async def show_history_list(call: types.CallbackQuery, session: AsyncSession):
    user_id = call.from_user.id
    stmt = select(ContentPlan).where(ContentPlan.user_id == user_id).order_by(ContentPlan.created_at.desc())
    result = await session.execute(stmt)
    plans = result.scalars().all()
    
    if not plans:
        await call.answer("История пуста", show_alert=True)
        return

    await call.message.edit_text(
        "📜 <b>Архив ваших планов:</b>",
        reply_markup=get_history_list_keyboard(plans),
        parse_mode="HTML"
    )

@router.callback_query(PlanHistoryCallback.filter(F.action == "open"))
async def open_old_plan(call: types.CallbackQuery, callback_data: PlanHistoryCallback, session: AsyncSession):
    plan_id = callback_data.plan_id
    stmt = select(Post).where(Post.plan_id == plan_id).order_by(Post.day_number)
    result = await session.execute(stmt)
    posts = result.scalars().all()
    
    await call.message.edit_text(
        f"📅 <b>План #{plan_id}:</b>",
        reply_markup=get_plan_keyboard(posts),
        parse_mode="HTML"
    )

@router.callback_query(F.data == "back_to_profile")
async def back_to_profile_cb(call: types.CallbackQuery, session: AsyncSession):
    await menu_profile(call.message, session)


# --- 5. ГЕНЕРАЦИЯ НОВОГО ПЛАНА ---

async def start_new_plan_flow(message_or_call, state: FSMContext, session: AsyncSession, user_id: int):
    user = await session.get(User, user_id)
    if not user or not user.niche:
        msg = "Сначала заполните профиль (/start)."
        if isinstance(message_or_call, types.CallbackQuery): await message_or_call.message.answer(msg)
        else: await message_or_call.answer(msg)
        return

    # Загружаем базовые данные в стейт
    await state.update_data(niche=user.niche, expert_desc=user.expert_desc, channel_id=user.channel_id)
    
    text = "<b>Шаг 1/2:</b> Выберите цель для ЭТОГО контент-плана\nИли напишите свою тему, нажав кнопку ниже:"
    kb = get_goals_keyboard(is_new_plan=True) 
    
    if isinstance(message_or_call, types.CallbackQuery):
        await message_or_call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await message_or_call.answer(text, reply_markup=kb, parse_mode="HTML")
    
    await state.set_state(ProfileSetupSG.choose_goal_new_plan)

# Хендлер для выбора цели (КНОПКИ)
@router.callback_query(ProfileSetupSG.choose_goal_new_plan, SetupCallback.filter(F.action == "goal_new"))
async def process_goal_new_plan(call: types.CallbackQuery, callback_data: SetupCallback, state: FSMContext):
    
    # ЕСЛИ НАЖАЛИ "СВОЯ ТЕМА"
    if callback_data.value == "own_input":
        await call.message.edit_text(
            "✍️ <b>Напишите тему/цель вашего плана:</b>\n"
            "<i>(Например: Прогрев к курсу по дизайну, Неделя разбора кейсов, или просто 'Хочу поднять охваты')</i>",
            parse_mode="HTML"
        )
        await state.set_state(ProfileSetupSG.input_own_goal_new_plan)
        return

    # ЕСЛИ ВЫБРАЛИ ГОТОВУЮ
    goals_map = {"sales": "Продажи", "engagement": "Вовлечение", "expert": "Экспертность", "brand": "Личный бренд"}
    selected_goal = goals_map.get(callback_data.value, "Продажи")
    
    await state.update_data(content_goal=selected_goal)
    
    # Переход к количеству
    await call.message.edit_text(
        f"Цель: <b>{selected_goal}</b>.\n"
        "<b>Шаг 2/2:</b> Сколько постов составить?",
        reply_markup=get_quantity_keyboard(),
        parse_mode="HTML"
    )
    await state.set_state(ProfileSetupSG.choose_quantity)

# Хендлер для ввода СВОЕЙ ЦЕЛИ (ТЕКСТ)
@router.message(ProfileSetupSG.input_own_goal_new_plan)
async def process_own_goal_input(message: types.Message, state: FSMContext):
    custom_goal = message.text
    await state.update_data(content_goal=custom_goal)
    
    await message.answer(
        f"Тема: <b>{custom_goal}</b>.\n"
        "<b>Шаг 2/2:</b> Сколько постов составить?",
        reply_markup=get_quantity_keyboard(),
        parse_mode="HTML"
    )
    await state.set_state(ProfileSetupSG.choose_quantity)


@router.message(F.text == "➕ Создать новый план")
async def menu_new_plan(message: types.Message, state: FSMContext, session: AsyncSession):
    await start_new_plan_flow(message, state, session, message.from_user.id)

@router.callback_query(F.data == "create_new_plan")
async def callback_new_plan(call: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    await start_new_plan_flow(call, state, session, call.from_user.id)
    await call.answer()

@router.callback_query(ProfileSetupSG.choose_quantity, SetupCallback.filter(F.action == "quantity"))
async def process_quantity_and_generate(call: types.CallbackQuery, callback_data: SetupCallback, state: FSMContext, session: AsyncSession):
    quantity = int(callback_data.value)
    data = await state.get_data()
    
    user_id = call.from_user.id
    
    # Создаем план
    new_plan = ContentPlan(user_id=user_id)
    session.add(new_plan)
    await session.commit()
    
    await call.message.edit_text(f"⏳ Генерирую план из {quantity} постов (Тема: {data.get('content_goal')})...")
    
    try:
        plan_text = await llm_client.generate_content_plan(
            niche=data.get('niche'),
            about=data.get('expert_desc'),
            goal=data.get('content_goal'), 
            quantity=quantity
        )
        parsed_posts = parse_plan_text(plan_text)
        
        if not parsed_posts:
            await call.message.edit_text("⚠️ Ошибка генерации. Попробуйте еще раз.")
            return

        db_posts = []
        for post_data in parsed_posts:
            post = Post(
                plan_id=new_plan.id,
                user_id=user_id,
                day_number=post_data['day'],
                topic=post_data['topic'],
                status='generated'
            )
            session.add(post)
            db_posts.append(post)
        
        await session.commit()
        
        # ТВОЯ ЛОГИКА: Сортировка сохранена
        db_posts.sort(key=lambda x: x.day_number)
        
        await call.message.delete()
        await call.message.answer(
            f"✅ <b>План готов!</b>\nТема: {data.get('content_goal')}",
            reply_markup=get_plan_keyboard(db_posts),
            parse_mode="HTML"
        )
        
        # ИСПРАВЛЕНО: Вместо пустой строки "" отправляем текст
        await call.message.answer(
            "Ваш план сохранен. Вы можете редактировать каждый пост отдельно.", 
            reply_markup=get_main_menu()
        )
        await state.clear()
        
    except Exception as e:
        # ИСПРАВЛЕНО: Безопасная отправка ошибки
        await call.message.answer(f"❌ Ошибка: {str(e)}")