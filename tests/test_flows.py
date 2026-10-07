"""Сценарии целиком: апдейты проходят через настоящий диспетчер, Telegram и модель подставные."""

from datetime import datetime

from aiogram.methods import AnswerCallbackQuery, SendMessage, SendPhoto
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.models import ContentPlan, Post, PostStatus, User
from keyboards.editor import EditorCallback, PublishCallback
from keyboards.menu import BTN_NEW_PLAN, BTN_PROFILE
from keyboards.plan import PostSelectCallback
from keyboards.profile import PlanHistoryCallback, SetupCallback
from states.editor import PostEditorSG
from states.profile import ProfileSetupSG
from tests.conftest import CHANNEL_ID, OTHER_USER_ID, USER_ID, Chat, FakeTelegram

Factory = async_sessionmaker[AsyncSession]


def forwarded_from_channel(channel_id: int = CHANNEL_ID) -> dict:
    return {
        "forward_origin": {
            "type": "channel",
            "date": int(datetime.now().timestamp()),
            "chat": {"id": channel_id, "type": "channel", "title": "Канал"},
            "message_id": 5,
        }
    }


async def seed(factory: Factory, user_id: int = USER_ID, posts: int = 3, **post_kwargs) -> list[int]:
    """Пользователь с заполненным профилем и планом из нескольких постов."""
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                full_name="Аня",
                niche="Дизайн",
                expert_desc="Дизайнер интерьеров",
                content_goal="Продажи",
                channel_id=CHANNEL_ID,
            )
        )
        plan = ContentPlan(user_id=user_id)
        plan.posts = [
            Post(user_id=user_id, day_number=number, topic=f"Тема {number}", **post_kwargs)
            for number in range(1, posts + 1)
        ]
        session.add(plan)
        await session.commit()
        return [post.id for post in plan.posts]


async def get_post(factory: Factory, post_id: int) -> Post:
    async with factory() as session:
        return await session.get(Post, post_id)


def alerts(telegram: FakeTelegram) -> list[str]:
    return [request.text for request in telegram.sent(AnswerCallbackQuery) if request.text]


# --- Анкета и создание плана ---


async def test_onboarding_saves_profile_and_creates_plan(chat: Chat, session_factory: Factory, telegram, llm) -> None:
    await chat.say("/start")
    # Имя пользователя с «<» не ломает HTML-сообщение
    assert "Привет, Аня &lt;b&gt;!" in telegram.texts()[-1]

    await chat.say("Дизайн <интерьеров>")
    assert "🔥 Дизайн &lt;интерьеров&gt; — отличная ниша!" in telegram.texts()[-1]
    await chat.say("Дизайнер, 10 лет опыта")
    await chat.click(SetupCallback(action="goal", value="expert"))
    await chat.say("Пересланный пост", **forwarded_from_channel())
    assert await chat.state() == ProfileSetupSG.choose_quantity.state

    # Профиль сохранён ещё до генерации плана
    async with session_factory() as session:
        user = await session.get(User, USER_ID)
        assert (user.niche, user.expert_desc, user.content_goal, user.channel_id) == (
            "Дизайн <интерьеров>",
            "Дизайнер, 10 лет опыта",
            "Экспертность",
            CHANNEL_ID,
        )

    await chat.click(SetupCallback(action="quantity", value="5"))
    assert llm.calls == [
        (
            "plan",
            {"niche": "Дизайн <интерьеров>", "about": "Дизайнер, 10 лет опыта", "goal": "Экспертность", "quantity": 5},
        )
    ]
    async with session_factory() as session:
        posts = (await session.scalars(select(Post).order_by(Post.day_number))).all()
        assert [(post.day_number, post.topic, post.user_id) for post in posts] == [
            (number, f"Тема {number} - суть", USER_ID) for number in range(1, 6)
        ]
    assert await chat.state() is None
    assert "✅ <b>План готов!</b>" in telegram.texts()[-2]

    # Повторный /start узнаёт пользователя, анкета заново не запускается
    await chat.say("/start")
    assert "Рад тебя видеть снова" in telegram.texts()[-1]
    assert await chat.state() is None


async def test_non_text_answer_in_onboarding_is_rejected(chat: Chat, telegram) -> None:
    await chat.say("/start")
    await chat.say(None, sticker={"file_id": "s", "file_unique_id": "u", "type": "regular", "width": 1, "height": 1,
                                  "is_animated": False, "is_video": False})  # fmt: skip
    assert "Нужно текстовое сообщение" in telegram.texts()[-1]
    assert await chat.state() == ProfileSetupSG.input_niche.state

    await chat.say("н" * 101)
    assert "Слишком длинно" in telegram.texts()[-1]
    assert await chat.state() == ProfileSetupSG.input_niche.state


async def test_foreign_channel_cannot_be_bound(chat: Chat, session_factory: Factory, telegram: FakeTelegram) -> None:
    # Бот — админ канала, но пользователь к каналу отношения не имеет
    telegram.admins.discard((CHANNEL_ID, USER_ID))
    await chat.say("/start")
    await chat.say("Ниша")
    await chat.say("О себе")
    await chat.click(SetupCallback(action="goal", value="sales"))
    await chat.say("Пересланный пост", **forwarded_from_channel())

    assert "Вы не администратор этого канала" in telegram.texts()[-1]
    assert await chat.state() == ProfileSetupSG.input_channel.state
    async with session_factory() as session:
        assert (await session.get(User, USER_ID)).channel_id is None


async def test_failed_generation_leaves_no_empty_plan(chat: Chat, session_factory: Factory, telegram, llm) -> None:
    await seed(session_factory, posts=0)
    async with session_factory() as session:
        plans_before = len((await session.scalars(select(ContentPlan))).all())

    await chat.say(BTN_NEW_PLAN)
    await chat.click(SetupCallback(action="goal_new", value="sales"))
    llm.fail = True
    await chat.click(SetupCallback(action="quantity", value="7"))

    assert telegram.texts()[-1] == "⚠️ Ошибка генерации. Попробуйте еще раз."
    # Кнопки количества снова на экране, шаг не сброшен — можно повторить
    assert telegram.requests[-1].reply_markup is not None
    assert await chat.state() == ProfileSetupSG.choose_quantity.state
    async with session_factory() as session:
        assert len((await session.scalars(select(ContentPlan))).all()) == plans_before

    llm.fail = False
    await chat.click(SetupCallback(action="quantity", value="7"))
    async with session_factory() as session:
        assert len((await session.scalars(select(Post))).all()) == 7


async def test_quantity_from_forged_callback_is_rejected(chat: Chat, session_factory: Factory, telegram, llm) -> None:
    await seed(session_factory, posts=0)
    await chat.say(BTN_NEW_PLAN)
    await chat.click(SetupCallback(action="goal_new", value="sales"))
    await chat.click(SetupCallback(action="quantity", value="5000"))
    assert llm.calls == []
    assert alerts(telegram) == ["Выберите количество кнопкой."]


async def test_custom_goal_is_escaped_and_used(chat: Chat, session_factory: Factory, telegram, llm) -> None:
    await seed(session_factory, posts=0)
    await chat.say(BTN_NEW_PLAN)
    await chat.click(SetupCallback(action="goal_new", value="own_input"))
    await chat.say("Прогрев <к курсу>")
    assert "Тема: <b>Прогрев &lt;к курсу&gt;</b>." in telegram.texts()[-1]
    await chat.click(SetupCallback(action="quantity", value="5"))
    assert llm.calls[0][1]["goal"] == "Прогрев <к курсу>"


# --- Редактор ---


async def test_opening_post_generates_text_once(chat: Chat, session_factory: Factory, telegram, llm) -> None:
    (post_id,) = await seed(session_factory, posts=1)

    await chat.click(PostSelectCallback(post_id=post_id, action="edit"))
    assert (await get_post(session_factory, post_id)).text == llm.post_text
    assert "🛠 <b>Редактор поста #1</b>" in telegram.texts()[-1]

    await chat.click(PostSelectCallback(post_id=post_id, action="edit"))
    assert [name for name, _ in llm.calls] == ["post"]


async def test_llm_failure_is_not_saved_as_post_text(chat: Chat, session_factory: Factory, telegram, llm) -> None:
    (post_id,) = await seed(session_factory, posts=1)
    llm.fail = True
    await chat.click(PostSelectCallback(post_id=post_id, action="edit"))

    assert (await get_post(session_factory, post_id)).text is None
    assert telegram.texts()[-1] == "❌ Ошибка нейросети. Попробуйте ещё раз чуть позже."


async def test_foreign_post_is_not_accessible(other_chat: Chat, session_factory: Factory, telegram, llm) -> None:
    (post_id,) = await seed(session_factory, posts=1, text="Чужой текст")
    plan_id = (await get_post(session_factory, post_id)).plan_id

    await other_chat.click(PostSelectCallback(post_id=post_id, action="edit"))
    await other_chat.click(EditorCallback(action="text_regen", post_id=post_id))
    await other_chat.click(PublishCallback(action="now", post_id=post_id))
    await other_chat.click(PlanHistoryCallback(plan_id=plan_id, action="open"))

    assert alerts(telegram) == ["Пост не найден. Откройте план заново."] * 3 + ["План не найден"]
    assert llm.calls == []
    assert telegram.sent(SendMessage) == []
    post = await get_post(session_factory, post_id)
    assert (post.text, post.status) == ("Чужой текст", PostStatus.GENERATED)
    assert OTHER_USER_ID != post.user_id


async def test_ai_edit_failure_keeps_original_text(chat: Chat, session_factory: Factory, telegram, llm) -> None:
    (post_id,) = await seed(session_factory, posts=1, text="<b>Исходный</b> текст")
    await chat.click(EditorCallback(action="text_ai", post_id=post_id))
    assert await chat.state() == PostEditorSG.waiting_for_ai_instruction.state

    llm.fail = True
    await chat.say("сделай короче")
    assert (await get_post(session_factory, post_id)).text == "<b>Исходный</b> текст"
    assert await chat.state() is None

    llm.fail = False
    await chat.click(EditorCallback(action="text_ai", post_id=post_id))
    await chat.say("сделай короче")
    assert (await get_post(session_factory, post_id)).text == llm.refined_text
    assert llm.calls[-1] == ("refine", {"current_text": "<b>Исходный</b> текст", "instruction": "сделай короче"})


async def test_manual_text_keeps_formatting_and_escapes(chat: Chat, session_factory: Factory) -> None:
    (post_id,) = await seed(session_factory, posts=1, text="Старый")
    await chat.click(EditorCallback(action="text_manual", post_id=post_id))
    await chat.say("Цена < 1000 & скидка", entities=[{"type": "bold", "offset": 0, "length": 4}])

    assert (await get_post(session_factory, post_id)).text == "<b>Цена</b> &lt; 1000 &amp; скидка"


async def test_long_topic_fits_column_and_goes_to_model_as_thesis(chat: Chat, session_factory: Factory, llm) -> None:
    (post_id,) = await seed(session_factory, posts=1, text="Старый")
    new_topic = "Как я начал бизнес. " + "Рассказать про первый провал. " * 15
    await chat.click(EditorCallback(action="topic_manual", post_id=post_id))
    await chat.say(new_topic)

    post = await get_post(session_factory, post_id)
    assert len(post.topic) <= 255
    assert post.topic.startswith("Как я начал бизнес.")
    assert post.text == llm.post_text
    assert llm.calls[-1][1]["thesis"] == new_topic.strip()


async def test_menu_button_cancels_pending_input(chat: Chat, session_factory: Factory, telegram) -> None:
    (post_id,) = await seed(session_factory, posts=1, text="Текст поста")
    await chat.click(EditorCallback(action="text_manual", post_id=post_id))
    await chat.say(BTN_PROFILE)

    assert await chat.state() is None
    assert "👤 <b>Ваш профиль:</b>" in telegram.texts()[-1]
    # Следующее сообщение уже не станет текстом поста
    await chat.say("просто сообщение")
    assert (await get_post(session_factory, post_id)).text == "Текст поста"
    assert "Не понял сообщение" in telegram.texts()[-1]


async def test_buttons_of_another_post_edit_their_own_post(chat: Chat, session_factory: Factory, llm) -> None:
    first, second = await seed(session_factory, posts=2, text="Текст")
    # Открыт второй пост, но нажата кнопка под сообщением первого
    await chat.click(PostSelectCallback(post_id=second, action="edit"))
    await chat.click(EditorCallback(action="text_regen", post_id=first))

    assert (await get_post(session_factory, first)).text == llm.post_text
    assert (await get_post(session_factory, second)).text == "Текст"


async def test_card_opens_from_photo_preview(chat: Chat, session_factory: Factory, telegram) -> None:
    (post_id,) = await seed(session_factory, posts=1, text="Текст", media_file_id="photo-id", media_type="photo")
    await chat.click(EditorCallback(action="preview", post_id=post_id))
    assert telegram.sent(SendPhoto)[-1].caption == "Текст"

    # У сообщения с фото нет текста: карточка приходит новым сообщением, а не правкой
    await chat.click(EditorCallback(action="back_to_main", post_id=post_id), message_text=None)
    assert "🛠 <b>Редактор поста #1</b>" in telegram.sent(SendMessage)[-1].text


# --- Медиа ---

PHOTO = {"photo": [{"file_id": "small", "file_unique_id": "a", "width": 90, "height": 90},
                   {"file_id": "big", "file_unique_id": "b", "width": 800, "height": 800}]}  # fmt: skip


async def test_media_is_attached_to_short_post(chat: Chat, session_factory: Factory, telegram) -> None:
    (post_id,) = await seed(session_factory, posts=1, text="Короткий текст")
    await chat.click(EditorCallback(action="add_media", post_id=post_id))
    await chat.say("это не фото")
    assert "Пришлите одно фото или видео" in telegram.texts()[-1]

    await chat.say(None, **PHOTO)
    post = await get_post(session_factory, post_id)
    assert (post.media_file_id, post.media_type) == ("big", "photo")
    assert await chat.state() is None


async def test_long_text_is_compressed_for_caption(chat: Chat, session_factory: Factory, telegram, llm) -> None:
    long_text = "а" * 1500
    (post_id,) = await seed(session_factory, posts=1, text=long_text)
    await chat.click(EditorCallback(action="add_media", post_id=post_id))
    await chat.say(None, **PHOTO)
    assert "В вашем посте сейчас 1500 символов" in telegram.texts()[-1]
    assert (await get_post(session_factory, post_id)).media_file_id is None

    # Модель вернула текст, который всё ещё не влезает: ничего не меняем
    llm.short_text = "б" * 1100
    await chat.click(EditorCallback(action="compress_yes", post_id=post_id))
    post = await get_post(session_factory, post_id)
    assert (post.text, post.media_file_id) == (long_text, None)

    llm.short_text = "Короткий текст"
    await chat.click(EditorCallback(action="add_media", post_id=post_id))
    await chat.say(None, **PHOTO)
    await chat.click(EditorCallback(action="compress_yes", post_id=post_id))
    post = await get_post(session_factory, post_id)
    assert (post.text, post.media_file_id, post.media_type) == ("Короткий текст", "big", "photo")


# --- Публикация и расписание ---


async def test_publish_now_sends_once(chat: Chat, session_factory: Factory, telegram) -> None:
    (post_id,) = await seed(session_factory, posts=1, text="<b>Пост</b>")
    await chat.click(PublishCallback(action="now", post_id=post_id))

    to_channel = [request for request in telegram.sent(SendMessage) if request.chat_id == CHANNEL_ID]
    assert [request.text for request in to_channel] == ["<b>Пост</b>"]
    assert (await get_post(session_factory, post_id)).status == PostStatus.PUBLISHED
    assert telegram.texts()[-1] == "🚀 Опубликовано!"

    # Второе нажатие в канал ничего не отправляет
    await chat.click(PublishCallback(action="now", post_id=post_id))
    assert len([request for request in telegram.sent(SendMessage) if request.chat_id == CHANNEL_ID]) == 1
    assert alerts(telegram)[-1] == "Этот пост уже опубликован."

    # «К списку постов» работает и после публикации
    await chat.click(EditorCallback(action="back", post_id=post_id))
    assert telegram.texts()[-1] == "📅 <b>Ваш контент-план:</b>"


async def test_single_schedule(chat: Chat, session_factory: Factory, telegram) -> None:
    (post_id,) = await seed(session_factory, posts=1, text="Пост")
    await chat.click(PublishCallback(action="schedule_single", post_id=post_id))

    await chat.say("завтра в обед")
    assert "Неверный формат даты" in telegram.texts()[-1]
    await chat.say("01.01.2020 10:00")
    assert "Дата не может быть в прошлом" in telegram.texts()[-1]
    assert (await get_post(session_factory, post_id)).status == PostStatus.GENERATED

    await chat.say("25.12.2099 14:00")
    post = await get_post(session_factory, post_id)
    assert (post.status, post.scheduled_time) == (PostStatus.SCHEDULED, datetime(2099, 12, 25, 14, 0))
    assert "✅ Пост #1 запланирован на 25.12.2099 14:00" in telegram.texts()[-1]
    assert await chat.state() is None


async def test_batch_schedule_skips_published_and_textless(chat: Chat, session_factory: Factory, telegram) -> None:
    ids = await seed(session_factory, posts=4, text="Пост")
    async with session_factory() as session:
        (await session.get(Post, ids[0])).status = PostStatus.PUBLISHED
        (await session.get(Post, ids[2])).text = None
        await session.commit()

    await chat.click(PublishCallback(action="schedule_batch", post_id=ids[1]))
    await chat.say("Пн 25:00")
    assert "Не понял формат" in telegram.texts()[-1]
    await chat.say("Каждый день 18:30")

    posts = [await get_post(session_factory, post_id) for post_id in ids]
    assert [post.status for post in posts] == [
        PostStatus.PUBLISHED,  # уже вышел, повторно не ставится
        PostStatus.SCHEDULED,
        PostStatus.GENERATED,  # без текста
        PostStatus.SCHEDULED,
    ]
    first, second = posts[1].scheduled_time, posts[3].scheduled_time
    assert (first.hour, first.minute) == (18, 30)
    assert (second - first).days == 1
    assert first.date() > datetime.now().date() or first > datetime.now()
    report = telegram.texts()[-1]
    assert "✅ Запланировано 2 постов по графику!" in report
    assert "Не попали в график: #3" in report


async def test_stale_button_gets_an_answer(chat: Chat, telegram) -> None:
    await chat.click("editor:menu_topic")  # формат кнопок старой версии, без ID поста
    await chat.click(SetupCallback(action="quantity", value="5"))  # шаг уже не активен
    assert alerts(telegram) == ["Кнопка устарела. Откройте раздел заново через меню."] * 2
