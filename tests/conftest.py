"""Общие фикстуры: база в памяти, подставная модель и подставной Telegram."""

import itertools
from collections.abc import AsyncIterator, Iterator
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import (
    EditMessageText,
    GetChatMember,
    SendMessage,
    SendPhoto,
    SendVideo,
    TelegramMethod,
)
from aiogram.types import ChatMemberLeft, ChatMemberOwner, Message, Update, User
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from db.base import create_session_factory
from db.models import Base
from main import create_dispatcher
from services.llm import LLMError

USER_ID = 1001
OTHER_USER_ID = 2002
CHANNEL_ID = -1001000000001
BOT_ID = 42
TZ = ZoneInfo("Europe/Moscow")

_ids = itertools.count(1)


class FakeLLM:
    """Подменяет LLMService: возвращает заранее известные ответы и запоминает вызовы."""

    def __init__(self) -> None:
        self.fail = False
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.post_text = "<b>Хук</b>\n\nТекст поста"
        self.refined_text = "<b>Исправленный</b> текст"
        self.short_text = "Короткий текст"

    def _call(self, name: str, **kwargs: Any) -> None:
        self.calls.append((name, kwargs))
        if self.fail:
            raise LLMError("сбой")

    async def generate_content_plan(self, niche: str, about: str, goal: str, quantity: int) -> str:
        self._call("plan", niche=niche, about=about, goal=goal, quantity=quantity)
        return "\n".join(f"Пост {number}: Тема {number} - суть" for number in range(1, quantity + 1))

    async def generate_post_text(self, **kwargs: Any) -> str:
        self._call("post", **kwargs)
        return self.post_text

    async def refine_post_text(self, current_text: str, instruction: str) -> str:
        self._call("refine", current_text=current_text, instruction=instruction)
        return self.refined_text

    async def shorten_post_for_caption(self, text: str) -> str:
        self._call("shorten", text=text)
        return self.short_text


class FakeTelegram(BaseSession):
    """Сессия aiogram без сети: записывает запросы и отдаёт правдоподобные ответы."""

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod] = []
        # Кто администратор канала: (chat_id, user_id)
        self.admins: set[tuple[int, int]] = {(CHANNEL_ID, BOT_ID), (CHANNEL_ID, USER_ID)}
        self.errors: dict[type, Exception] = {}

    async def close(self) -> None:
        return None

    async def stream_content(self, *args: Any, **kwargs: Any) -> AsyncIterator[bytes]:
        yield b""

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: int | None = None) -> Any:  # noqa: ASYNC109 — сигнатура задана aiogram
        self.requests.append(method)
        error = self.errors.get(type(method))
        if error is not None:
            raise error
        if isinstance(method, SendMessage | SendPhoto | SendVideo | EditMessageText):
            text = getattr(method, "text", None) or getattr(method, "caption", None) or ""
            chat_id = method.chat_id if method.chat_id is not None else USER_ID
            return make_message(bot, text=text, chat_id=chat_id, from_bot=True)
        if isinstance(method, GetChatMember):
            member = User(id=method.user_id, is_bot=method.user_id == BOT_ID, first_name="Участник")
            if (method.chat_id, method.user_id) in self.admins:
                return ChatMemberOwner(user=member, is_anonymous=False)
            return ChatMemberLeft(user=member)
        return True

    def sent(self, method_type: type = SendMessage) -> list[Any]:
        return [request for request in self.requests if isinstance(request, method_type)]

    def texts(self) -> list[str]:
        """Тексты всех отправленных и отредактированных сообщений по порядку."""
        return [
            getattr(request, "text", None) or getattr(request, "caption", None) or ""
            for request in self.requests
            if isinstance(request, SendMessage | SendPhoto | SendVideo | EditMessageText)
        ]


def make_message(bot: Bot, text: str | None, chat_id: int = USER_ID, from_bot: bool = False, **extra: Any) -> Message:
    sender = (
        {"id": BOT_ID, "is_bot": True, "first_name": "Бот"}
        if from_bot
        else {"id": chat_id, "is_bot": False, "first_name": "Аня <b>"}
    )
    payload = {
        "message_id": next(_ids),
        "date": int(datetime.now().timestamp()),
        "chat": {"id": chat_id, "type": "private"},
        "from": sender,
        **extra,
    }
    if text is not None:
        payload["text"] = text
    return Message.model_validate(payload, context={"bot": bot})


class Chat:
    """Диалог одного пользователя с ботом: отправляет апдейты в диспетчер."""

    def __init__(self, dp: Dispatcher, bot: Bot, user_id: int = USER_ID) -> None:
        self.dp = dp
        self.bot = bot
        self.user_id = user_id

    async def say(self, text: str | None = None, **extra: Any) -> None:
        message = make_message(self.bot, text, chat_id=self.user_id, **extra)
        update = Update.model_validate(
            {"update_id": next(_ids), "message": message.model_dump(exclude_none=True, by_alias=True, mode="json")},
            context={"bot": self.bot},
        )
        await self.dp.feed_update(self.bot, update)

    async def click(self, callback_data: Any, message_text: str | None = "сообщение с кнопками") -> None:
        data = callback_data if isinstance(callback_data, str) else callback_data.pack()
        message = make_message(self.bot, message_text, chat_id=self.user_id, from_bot=True)
        update = Update.model_validate(
            {
                "update_id": next(_ids),
                "callback_query": {
                    "id": str(next(_ids)),
                    "from": {"id": self.user_id, "is_bot": False, "first_name": "Аня <b>"},
                    "chat_instance": "test",
                    "data": data,
                    "message": message.model_dump(exclude_none=True, by_alias=True, mode="json"),
                },
            },
            context={"bot": self.bot},
        )
        await self.dp.feed_update(self.bot, update)

    async def state(self) -> str | None:
        return await self.dp.fsm.get_context(self.bot, self.user_id, self.user_id).get_state()


class _SessionFactoryProxy:
    """Диспетчер создаётся один раз на все тесты, а база у каждого теста своя."""

    target: async_sessionmaker[AsyncSession] | None = None

    def __call__(self) -> AsyncSession:
        assert self.target is not None
        return self.target()


_factory_proxy = _SessionFactoryProxy()


@pytest.fixture(scope="session")
def _dispatcher() -> Dispatcher:
    # Роутеры модулей можно подключить только один раз за процесс
    return create_dispatcher(MemoryStorage(), _factory_proxy, FakeLLM(), TZ)  # type: ignore[arg-type]


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield create_session_factory(engine)
    await engine.dispose()


@pytest.fixture
def llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def telegram() -> Iterator[FakeTelegram]:
    fake = FakeTelegram()
    yield fake
    # Обработчик ошибок бота глотает исключения хендлеров — тест не должен пройти мимо такого
    crashed = [text for text in fake.texts() if "Что-то пошло не так" in text]
    assert not crashed, "в хендлере было необработанное исключение"


@pytest.fixture
def bot(telegram: FakeTelegram) -> Bot:
    return Bot(f"{BOT_ID}:TEST", session=telegram, default=DefaultBotProperties(parse_mode="HTML"))


@pytest.fixture
def dp(_dispatcher: Dispatcher, session_factory: async_sessionmaker[AsyncSession], llm: FakeLLM) -> Dispatcher:
    _factory_proxy.target = session_factory
    _dispatcher["llm"] = llm
    _dispatcher.storage.storage.clear()  # type: ignore[attr-defined]
    return _dispatcher


@pytest.fixture
def chat(dp: Dispatcher, bot: Bot) -> Chat:
    return Chat(dp, bot)


@pytest.fixture
def other_chat(dp: Dispatcher, bot: Bot) -> Chat:
    return Chat(dp, bot, user_id=OTHER_USER_ID)
