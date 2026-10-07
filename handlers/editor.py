import re
from datetime import datetime, timedelta
import logging

from aiogram import Router, F, types, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Post, User, ContentPlan
from states.editor import PostEditorSG
from keyboards.editor import (
    get_editor_main_keyboard, get_topic_edit_keyboard, get_text_edit_keyboard,
    get_preview_keyboard, get_back_keyboard, get_after_publish_keyboard, get_compression_choice_keyboard,
    EditorCallback, PublishCallback
)
from keyboards.plan import PostSelectCallback, get_plan_keyboard
from services.llm import llm_client
from services.scheduler import scheduler_service

router = Router()

@router.callback_query(PostSelectCallback.filter(F.action == "edit"))
async def open_post_editor(call: types.CallbackQuery, callback_data: PostSelectCallback, state: FSMContext, session: AsyncSession):
    # Мгновенный отклик, чтобы кнопка не "залипала"
    await call.answer("Открываю редактор...") 
    
    await state.update_data(current_post_id=callback_data.post_id)
    await state.set_state(PostEditorSG.viewing)
    await refresh_post_view(call, state, session)

async def refresh_post_view(event: types.Message | types.CallbackQuery, state: FSMContext, session: AsyncSession, is_preview: bool = False):
    if isinstance(event, types.CallbackQuery):
        message = event.message
    else:
        message = event

    data = await state.get_data()
    post_id = data.get("current_post_id")
    
    if not post_id:
        await message.answer("❌ Ошибка: пост не найден в памяти. Вернитесь в /plan")
        return

    post = await session.get(Post, post_id)

    # 1. Если текста еще нет — ГЕНЕРИРУЕМ
    if not post.text:
        user = await session.get(User, post.user_id)
        
        # Информируем пользователя
        status_text = "⏳ <b>Подождите, я создаю текст поста...</b>\nЭто займет около 10-15 секунд."
        if isinstance(event, types.CallbackQuery):
            await event.message.edit_text(status_text, parse_mode="HTML")
        else:
            await message.answer(status_text, parse_mode="HTML")

        try:
            generated_text = await llm_client.generate_post_text(
                niche=user.niche, 
                about=user.expert_desc, 
                topic=post.topic, 
                post_number=post.day_number
            )
            post.text = generated_text
            await session.commit()
        except Exception as e:
            await message.answer(f"❌ Ошибка нейросети: {e}")
            return

    # 2. РЕЖИМ ПРЕДПРОСМОТРА
    if is_preview:
        if isinstance(event, types.CallbackQuery): 
            try: await event.message.delete()
            except: pass
        
        try:
            if post.media_file_id:
                # (Логика сокращения текста под медиа, если нужно)
                if post.media_type == "photo":
                    await message.answer_photo(photo=post.media_file_id, caption=post.text, parse_mode="HTML", reply_markup=get_preview_keyboard())
                else:
                    await message.answer_video(video=post.media_file_id, caption=post.text, parse_mode="HTML", reply_markup=get_preview_keyboard())
            else:
                await message.answer(post.text, parse_mode="HTML", reply_markup=get_preview_keyboard())
        except Exception as e:
            await message.answer(f"⚠️ Ошибка разметки. Текст без оформления:\n\n{post.text}", reply_markup=get_preview_keyboard())
        return

    # 3. РЕЖИМ РЕДАКТОРА (Главное меню поста)
    import re
    clean_text = re.sub(r'<[^>]*>', '', post.text)
    short_text = clean_text[:250] + "..." if len(clean_text) > 250 else clean_text
    
    topic_display = post.topic[:60] + "..." if len(post.topic) > 60 else post.topic
    
    txt = (
        f"🛠 <b>Редактор поста #{post.day_number}</b>\n\n"
        f"<b>Тема:</b> {topic_display}\n"
        f"<b>Медиа:</b> {'✅ Прикреплено' if post.media_file_id else '❌ Отсутствует'}\n"
        f"➖➖➖➖➖➖➖➖\n\n"
        f"{short_text}\n\n"
        f"<i>Нажмите «Предпросмотр», чтобы увидеть пост целиком.</i>"
    )
    
    kb = get_editor_main_keyboard()
    
    if isinstance(event, types.CallbackQuery):
        await event.message.edit_text(txt, reply_markup=kb, parse_mode="HTML")
    else:
        await message.answer(txt, reply_markup=kb, parse_mode="HTML")


@router.callback_query(EditorCallback.filter(F.action == "back"))
async def back_to_plan_list(call: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    post_id = data.get("current_post_id")
    
    if not post_id:
        await call.answer("Контекст утерян. Используйте меню.")
        return

    post = await session.get(Post, post_id)
    # Получаем все посты этого же плана
    stmt = select(Post).where(Post.plan_id == post.plan_id).order_by(Post.day_number)
    posts = (await session.execute(stmt)).scalars().all()
    
    from keyboards.plan import get_plan_keyboard
    await call.message.edit_text(
        "📅 <b>Ваш контент-план:</b>",
        reply_markup=get_plan_keyboard(posts),
        parse_mode="HTML"
    )
    await call.answer()

# --- ВХОД В РЕДАКТОР ---
@router.callback_query(PostSelectCallback.filter(F.action == "edit"))
async def open_post_editor(call: types.CallbackQuery, callback_data: PostSelectCallback, state: FSMContext, session: AsyncSession):
    # Мгновенный отклик, чтобы кнопка не "залипала"
    await call.answer("Открываю редактор...") 
    
    await state.update_data(current_post_id=callback_data.post_id)
    await state.set_state(PostEditorSG.viewing)
    await refresh_post_view(call, state, session)

# --- НАВИГАЦИЯ ПО МЕНЮ ---
@router.callback_query(EditorCallback.filter(F.action == "menu_topic"))
async def menu_topic(call: types.CallbackQuery):
    await call.message.edit_text("⚙️ <b>Правка ТЕМЫ</b>\nВыберите действие:", reply_markup=get_topic_edit_keyboard(), parse_mode="HTML")

@router.callback_query(EditorCallback.filter(F.action == "menu_text"))
async def menu_text(call: types.CallbackQuery):
    await call.message.edit_text("⚙️ <b>Правка ТЕКСТА</b>\nВыберите действие:", reply_markup=get_text_edit_keyboard(), parse_mode="HTML")

@router.callback_query(EditorCallback.filter(F.action == "back_to_main"))
async def back_to_main(call: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    await state.set_state(PostEditorSG.viewing)
    await refresh_post_view(call, state, session)

@router.callback_query(EditorCallback.filter(F.action == "preview"))
async def show_preview(call: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    await refresh_post_view(call, state, session, is_preview=True)

# --- ПРАВКА ТЕМЫ ---
@router.callback_query(EditorCallback.filter(F.action == "topic_manual"))
async def topic_manual_start(call: types.CallbackQuery, state: FSMContext):
    await call.message.edit_text(
        "⌨️ <b>Ввод новой темы</b>\n\n"
        "Напишите новую тему. Можно добавить тезисы.\n"
        "<i>Пример: Как я начал бизнес. Рассказать про первый провал.</i>",
        reply_markup=get_back_keyboard(), parse_mode="HTML"
    )
    await state.set_state(PostEditorSG.waiting_for_new_topic_manual)

@router.message(PostEditorSG.waiting_for_new_topic_manual)
async def topic_manual_process(message: types.Message, state: FSMContext, session: AsyncSession):
    new_topic = message.text
    data = await state.get_data()
    post = await session.get(Post, data["current_post_id"])
    
    post.topic = new_topic
    await message.answer("🔄 Тема изменена. Генерирую новый текст...")
    
    user = await session.get(User, post.user_id)
    new_text = await llm_client.generate_post_text(
        niche=user.niche, about=user.expert_desc, topic=post.topic, post_number=post.day_number,
        thesis=new_topic
    )
    post.text = new_text
    await session.commit()
    
    await state.set_state(PostEditorSG.viewing)
    await refresh_post_view(message, state, session)

@router.callback_query(EditorCallback.filter(F.action == "topic_ai"))
async def topic_ai_process(call: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    await call.answer("Функция авто-темы в разработке, используйте ручной ввод", show_alert=True)

# --- ПРАВКА ТЕКСТА ---
@router.callback_query(EditorCallback.filter(F.action == "text_manual"))
async def text_manual_start(call: types.CallbackQuery, state: FSMContext):
    await call.message.edit_text("✏️ Пришлите новый текст поста полностью:", reply_markup=get_back_keyboard())
    await state.set_state(PostEditorSG.waiting_for_text_manual)

@router.message(PostEditorSG.waiting_for_text_manual)
async def text_manual_process(message: types.Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    post = await session.get(Post, data["current_post_id"])
    post.text = message.text or message.caption
    await session.commit()
    await message.answer("✅ Текст сохранен.")
    await state.set_state(PostEditorSG.viewing)
    await refresh_post_view(message, state, session)

@router.callback_query(EditorCallback.filter(F.action == "text_ai"))
async def text_ai_start(call: types.CallbackQuery, state: FSMContext):
    await call.message.edit_text("🤖 <b>AI-правка</b>\nЧто изменить? (короче, веселее, добавить призыв...)", reply_markup=get_back_keyboard(), parse_mode="HTML")
    await state.set_state(PostEditorSG.waiting_for_ai_instruction)

@router.message(PostEditorSG.waiting_for_ai_instruction)
async def text_ai_process(message: types.Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    post = await session.get(Post, data["current_post_id"])
    
    msg = await message.answer("🤖 Думаю...")
    new_text = await llm_client.refine_post_text(post.text, message.text)
    post.text = new_text
    await session.commit()
    await msg.delete()
    
    await message.answer("✅ Текст обновлен.")
    await state.set_state(PostEditorSG.viewing)
    await refresh_post_view(message, state, session)

@router.callback_query(EditorCallback.filter(F.action == "text_regen"))
async def text_regen(call: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    await call.message.edit_text("⏳ Переписываю текст...", parse_mode="HTML")
    data = await state.get_data()
    post = await session.get(Post, data["current_post_id"])
    user = await session.get(User, post.user_id)
    
    new_text = await llm_client.generate_post_text(
        niche=user.niche, about=user.expert_desc, topic=post.topic, post_number=post.day_number
    )
    post.text = new_text
    await session.commit()
    await refresh_post_view(call, state, session)

# --- МЕДИА ---
@router.callback_query(EditorCallback.filter(F.action == "add_media"))
async def add_media_start(call: types.CallbackQuery, state: FSMContext):
    # ИСПРАВЛЕНО: Четкая инструкция
    await call.message.edit_text(
        "📷 <b>Добавление медиа</b>\n\n"
        "Пришлите <b>ОДНО</b> фото или видео.\n"
        "<i>(Отправка альбомов из нескольких фото пока не поддерживается, бот сохранит только последний файл)</i>", 
        reply_markup=get_back_keyboard(),
        parse_mode="HTML"
    )
    await state.set_state(PostEditorSG.waiting_for_media)

@router.message(PostEditorSG.waiting_for_media, F.content_type.in_({types.ContentType.PHOTO, types.ContentType.VIDEO}))
async def add_media_process(message: types.Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    post = await session.get(Post, data["current_post_id"])
    
    # Сохраняем данные о медиа временно в стейт (не в БД!)
    media_file_id = message.photo[-1].file_id if message.photo else message.video.file_id
    media_type = "photo" if message.photo else "video"
    
    await state.update_data(temp_media_id=media_file_id, temp_media_type=media_type)

    # ПРОВЕРКА ДЛИНЫ
    if post.text and len(post.text) > 1000:
        await message.answer(
            "⚠️ <b>Текст слишком длинный для медиа-поста!</b>\n\n"
            f"В вашем посте сейчас {len(post.text)} символов. "
            "Лимит Telegram для подписи к фото — 1024 символа.\n\n"
            "Что мы сделаем?",
            reply_markup=get_compression_choice_keyboard(),
            parse_mode="HTML"
        )
        await state.set_state(PostEditorSG.waiting_for_media_compression_decision)
    else:
        # Если текст короткий — просто сохраняем медиа как раньше
        post.media_file_id = media_file_id
        post.media_type = media_type
        await session.commit()
        await message.answer("✅ Медиа успешно добавлено.")
        await state.set_state(PostEditorSG.viewing)
        await refresh_post_view(message, state, session)

#Обработка выбора пользователя
@router.callback_query(PostEditorSG.waiting_for_media_compression_decision, EditorCallback.filter())
async def process_compression_choice(call: types.CallbackQuery, callback_data: EditorCallback, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    post = await session.get(Post, data["current_post_id"])
    
    if callback_data.action == "compress_yes":
        await call.message.edit_text("⏳ Нейросеть сжимает текст, чтобы он поместился под фото...")
        
        # Сжимаем текст
        compressed_text = await llm_client.shorten_post_for_caption(post.text)
        
        # Сохраняем и текст, и медиа
        post.text = compressed_text
        post.media_file_id = data.get("temp_media_id")
        post.media_type = data.get("temp_media_type")
        await session.commit()
        
        await call.message.answer("✅ Текст оптимизирован, фото прикреплено.")
        
    elif callback_data.action == "compress_no":
        # Оставляем старый текст, медиа НЕ сохраняем
        await call.message.edit_text("🚫 Фото отклонено. Текст оставлен в оригинальном виде.")
        # Очищаем медиа, если оно было раньше
        post.media_file_id = None
        post.media_type = None
        await session.commit()

    # Возвращаемся в редактор
    await state.set_state(PostEditorSG.viewing)
    await refresh_post_view(call, state, session)
    await call.answer()

# --- ГИБКОЕ ПЛАНИРОВАНИЕ (BATCH) ---
@router.callback_query(PublishCallback.filter(F.action == "schedule_batch"))
async def start_batch_schedule(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer(
        "🗓 <b>Гибкая настройка графика</b>\n"
        "Напишите дни и время для публикации (начиная с завтра).\n"
        "Примеры:\n<code>Пн Ср Пт 10:00</code>\n<code>Каждый день 18:30</code>",
        parse_mode="HTML", reply_markup=get_back_keyboard()
    )
    await state.set_state(PostEditorSG.waiting_for_batch_schedule)

@router.message(PostEditorSG.waiting_for_batch_schedule)
async def process_batch_schedule(message: types.Message, state: FSMContext, session: AsyncSession):
    text = message.text.lower()
    days_map = {"пн":0, "вт":1, "ср":2, "чт":3, "пт":4, "сб":5, "вс":6}
    selected_days = []
    
    if "каждый" in text or "ежедневно" in text:
        selected_days = [0,1,2,3,4,5,6]
    else:
        for word in text.split():
            clean = word.strip(".,")
            if clean in days_map: selected_days.append(days_map[clean])
    
    selected_days = sorted(list(set(selected_days)))
    time_match = re.search(r'(\d{1,2})[:.](\d{2})', text)
    
    if not time_match or not selected_days:
        await message.answer("⚠️ Не понял формат. Попробуйте: <code>Пн Вт 15:00</code>", parse_mode="HTML")
        return
        
    h, m = int(time_match.group(1)), int(time_match.group(2))
    
    # Расстановка
    data = await state.get_data()
    post = await session.get(Post, data["current_post_id"])
    posts_stmt = select(Post).where(Post.plan_id == post.plan_id).order_by(Post.day_number)
    posts = (await session.execute(posts_stmt)).scalars().all()
    
    curr_date = datetime.now().replace(hour=h, minute=m, second=0, microsecond=0) + timedelta(days=1)
    count = 0
    idx = 0
    
    while idx < len(posts):
        if curr_date.weekday() in selected_days:
            p = posts[idx]
            p.status = "scheduled"
            p.scheduled_time = curr_date
            scheduler_service.add_scheduled_post(p.id, curr_date)
            idx += 1
            count += 1
        curr_date += timedelta(days=1)
        if count > 100: break # Safety
    
    await session.commit()
    await message.answer(f"✅ Запланировано {count} постов по графику!", reply_markup=get_after_publish_keyboard())
    await state.clear()

# --- ПУБЛИКАЦИЯ СЕЙЧАС ---
@router.callback_query(PublishCallback.filter(F.action == "now"))
async def process_publish_now(call: types.CallbackQuery, state: FSMContext, session: AsyncSession, bot: Bot):
    data = await state.get_data()
    post = await session.get(Post, data["current_post_id"])
    user = await session.get(User, post.user_id)
    
    if not user.channel_id:
        await call.message.answer("❌ Канал не привязан. Настройте профиль.")
        return

    try:
        # Здесь текст уже будет сжат нейросетью в add_media_process, если медиа есть
        if post.media_file_id:
            if post.media_type == "photo":
                await bot.send_photo(chat_id=user.channel_id, photo=post.media_file_id, caption=post.text, parse_mode="HTML")
            elif post.media_type == "video":
                await bot.send_video(chat_id=user.channel_id, video=post.media_file_id, caption=post.text, parse_mode="HTML")
        else:
            await bot.send_message(chat_id=user.channel_id, text=post.text, parse_mode="HTML")
        
        post.status = "published"
        from datetime import datetime
        post.scheduled_time = datetime.now()
        await session.commit()
        
        await call.message.answer("🚀 Опубликовано!", reply_markup=get_after_publish_keyboard())
        await state.clear()
        
    except Exception as e:
        await call.message.answer(f"❌ Ошибка публикации: {e}")

# --- КНОПКА НАЗАД (В СПИСОК) ---
@router.callback_query(EditorCallback.filter(F.action == "back"))
async def back_to_list(call: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    post_id = data.get("current_post_id")
    
    if post_id:
        post = await session.get(Post, post_id)
        plan_id = post.plan_id
        stmt = select(Post).where(Post.plan_id == plan_id).order_by(Post.day_number)
        result = await session.execute(stmt)
        posts = result.scalars().all()
        await call.message.edit_text(f"📅 План #{plan_id}:", reply_markup=get_plan_keyboard(posts), parse_mode="HTML")
    else:
        await call.message.answer("Вернитесь в меню (/start).")
    
    await state.clear()

# Обработка нажатия "Запланировать этот пост"
@router.callback_query(PublishCallback.filter(F.action == "schedule_single"))
async def start_single_schedule(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer(
        "Введите дату и время публикации в формате:\n"
        "<code>ДД.ММ.ГГГГ ЧЧ:ММ</code>\n\n"
        "Пример: <code>25.12.2025 14:00</code>",
        parse_mode="HTML", reply_markup=get_back_keyboard()
    )
    await state.set_state(PostEditorSG.waiting_for_single_date)

# Хендлер приема даты
@router.message(PostEditorSG.waiting_for_single_date)
async def process_single_schedule(message: types.Message, state: FSMContext, session: AsyncSession):
    try:
        # Парсим дату
        run_date = datetime.strptime(message.text, "%d.%m.%Y %H:%M")
        if run_date < datetime.now():
            await message.answer("⚠️ Дата не может быть в прошлом!")
            return
            
        data = await state.get_data()
        post_id = data.get("current_post_id")
        post = await session.get(Post, post_id)
        
        # Сохраняем в БД и планировщик
        post.status = "scheduled"
        post.scheduled_time = run_date
        await session.commit()
        
        scheduler_service.add_scheduled_post(post.id, run_date)
        
        await message.answer(
            f"✅ Пост #{post.day_number} запланирован на {message.text}",
            reply_markup=get_after_publish_keyboard()
        )
        await state.set_state(PostEditorSG.viewing)
        
    except ValueError:
        await message.answer("❌ Неверный формат даты. Используй: ДД.ММ.ГГГГ ЧЧ:ММ")

@router.callback_query(F.data == "go_to_main_menu")
async def go_to_main_menu_handler(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    from handlers.profile import get_main_menu # Импорт внутри, чтобы не было циклической ошибки
    await call.message.answer("Вы вернулись в главное меню. Что делаем дальше?", reply_markup=get_main_menu())
    await call.answer()
