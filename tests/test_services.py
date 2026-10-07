"""LLM-клиент, отправка поста, проверка прав на канал и настройки. Сеть не используется."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError
from aiogram.methods import SendMessage
from aiogram.types import ChatMemberAdministrator, ChatMemberLeft, ChatMemberOwner, User
from openai import APIStatusError, OpenAIError

from config.config import Settings
from db.models import Post
from services.channels import ChannelCheck, check_channel_rights
from services.llm import LLMError, LLMService
from services.publisher import PublishError, check_post_ready, send_post

# --- LLM ---


def make_llm(content: str | None = "ответ", error: Exception | None = None, temperature: float | None = 0.75):
    create = AsyncMock()
    if error is not None:
        create.side_effect = error
    else:
        message = SimpleNamespace(content=content)
        create.return_value = SimpleNamespace(choices=[SimpleNamespace(message=message)])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return LLMService(client, "test-model", temperature), create  # type: ignore[arg-type]


async def test_llm_sends_system_and_user_messages() -> None:
    llm, create = make_llm("Пост 1: Тема")
    result = await llm.generate_content_plan("Ниша", "Автор", "Продажи", 5)

    assert result == "Пост 1: Тема"
    kwargs = create.call_args.kwargs
    assert kwargs["model"] == "test-model"
    assert kwargs["temperature"] == 0.75
    assert [message["role"] for message in kwargs["messages"]] == ["system", "user"]
    assert "<<<Ниша>>>" in kwargs["messages"][1]["content"]


async def test_llm_omits_temperature_when_not_set() -> None:
    llm, create = make_llm(temperature=None)
    await llm.generate_content_plan("Ниша", "Автор", "Продажи", 5)
    assert "temperature" not in create.call_args.kwargs


async def test_llm_post_text_is_cleaned_for_telegram() -> None:
    llm, _ = make_llm("**Хук**\n<p>Абзац с a < b</p><i>вывод")
    assert await llm.generate_post_text("Ниша", "Автор", "Тема", 1) == "<b>Хук</b>\nАбзац с a &lt; b\n<i>вывод</i>"


@pytest.mark.parametrize("content", [None, "", "   \n"])
async def test_llm_empty_answer_is_an_error(content: str | None) -> None:
    llm, _ = make_llm(content)
    with pytest.raises(LLMError):
        await llm.refine_post_text("текст", "короче")


async def test_llm_api_errors_become_llm_error() -> None:
    response = SimpleNamespace(status_code=500, headers={}, request=None)
    errors = [
        OpenAIError("connection refused"),
        APIStatusError("upstream", response=response, body=None),  # type: ignore[arg-type]
    ]
    for error in errors:
        llm, _ = make_llm(error=error)
        with pytest.raises(LLMError):
            await llm.shorten_post_for_caption("текст")


# --- Отправка поста ---


def make_post(**kwargs) -> Post:
    return Post(id=1, user_id=1, plan_id=1, day_number=1, topic="Тема", **kwargs)


def test_check_post_ready() -> None:
    assert check_post_ready(make_post(text=None)) is not None
    assert check_post_ready(make_post(text="  ")) is not None
    assert check_post_ready(make_post(text="Обычный пост")) is None
    # Длинный текст годится для сообщения, но не для подписи к медиа
    long_text = "<b>" + "а" * 1500 + "</b>"
    assert check_post_ready(make_post(text=long_text)) is None
    assert "1500" in check_post_ready(make_post(text=long_text, media_file_id="file", media_type="photo"))
    assert check_post_ready(make_post(text="а" * 5000)) is not None


async def test_send_post_picks_method_by_media() -> None:
    bot = AsyncMock()
    await send_post(bot, -100, make_post(text="<b>Текст</b>"))
    bot.send_message.assert_awaited_once_with(chat_id=-100, text="<b>Текст</b>", parse_mode="HTML")

    await send_post(bot, -100, make_post(text="Подпись", media_file_id="photo-id", media_type="photo"))
    bot.send_photo.assert_awaited_once_with(chat_id=-100, photo="photo-id", caption="Подпись", parse_mode="HTML")

    await send_post(bot, -100, make_post(text="Подпись", media_file_id="video-id", media_type="video"))
    bot.send_video.assert_awaited_once_with(chat_id=-100, video="video-id", caption="Подпись", parse_mode="HTML")


async def test_send_post_repairs_broken_markup() -> None:
    bot = AsyncMock()
    await send_post(bot, -100, make_post(text="<b>Незакрытый тег и a < b"))
    assert bot.send_message.await_args.kwargs["text"] == "<b>Незакрытый тег и a &lt; b</b>"


async def test_send_post_does_not_send_unready_post() -> None:
    bot = AsyncMock()
    with pytest.raises(PublishError):
        await send_post(bot, -100, make_post(text=None))
    bot.send_message.assert_not_awaited()


async def test_send_post_maps_telegram_errors() -> None:
    method = SendMessage(chat_id=-100, text="x")
    cases = [
        (TelegramNetworkError(method=method, message="timeout"), True),
        (TelegramForbiddenError(method=method, message="bot was kicked"), False),
        (TelegramBadRequest(method=method, message="chat not found"), False),
    ]
    for error, retryable in cases:
        bot = AsyncMock()
        bot.send_message.side_effect = error
        with pytest.raises(PublishError) as caught:
            await send_post(bot, -100, make_post(text="Текст"))
        assert caught.value.retryable is retryable


# --- Права на канал ---


def _admin(can_post: bool) -> ChatMemberAdministrator:
    flags = {
        name: False
        for name, field in ChatMemberAdministrator.model_fields.items()
        if field.is_required() and name not in {"user", "status"}
    }
    return ChatMemberAdministrator(user=_user(), **{**flags, "can_post_messages": can_post})


def _user() -> User:
    return User(id=1, is_bot=False, first_name="x")


@pytest.mark.parametrize(
    ("bot_member", "user_member", "expected"),
    [
        (ChatMemberOwner(user=_user(), is_anonymous=False), ChatMemberOwner(user=_user(), is_anonymous=False), "OK"),
        (_admin(True), ChatMemberOwner(user=_user(), is_anonymous=False), "OK"),
        (ChatMemberLeft(user=_user()), ChatMemberOwner(user=_user(), is_anonymous=False), "BOT_NOT_ADMIN"),
        (_admin(False), ChatMemberOwner(user=_user(), is_anonymous=False), "BOT_CANNOT_POST"),
        # Бот в канале есть, но тот, кто привязывает, каналом не управляет
        (_admin(True), ChatMemberLeft(user=_user()), "USER_NOT_ADMIN"),
    ],
)
async def test_check_channel_rights(bot_member, user_member, expected: str) -> None:
    bot = AsyncMock()
    bot.id = 42
    bot.get_chat_member.side_effect = [bot_member, user_member]
    assert await check_channel_rights(bot, -100, 7) is ChannelCheck[expected]


async def test_check_channel_rights_without_access() -> None:
    bot = AsyncMock()
    bot.id = 42
    bot.get_chat_member.side_effect = TelegramBadRequest(method=SendMessage(chat_id=1, text="x"), message="not found")
    assert await check_channel_rights(bot, -100, 7) is ChannelCheck.NO_ACCESS


# --- Настройки ---

_REQUIRED = {
    "BOT_TOKEN": "42:TEST",
    "OPENAI_API_KEY": "dummy",
    "OPENAI_BASE_URL": "http://llm.test/v1",
    "DB_USER": "user",
    "DB_PASS": "p@ss/w:rd#1",
    "DB_NAME": "db",
}


def test_settings_build_database_url_with_special_chars() -> None:
    settings = Settings(_env_file=None, **_REQUIRED)
    url = settings.database_url
    assert url.drivername == "postgresql+asyncpg"
    assert url.password == "p@ss/w:rd#1"
    assert url.host == "localhost"
    # Пароль не утекает в repr и в строку URL по умолчанию
    assert "p@ss" not in repr(settings)
    assert "p@ss" not in str(url)


def test_settings_empty_optional_values() -> None:
    settings = Settings(_env_file=None, **_REQUIRED, OPENAI_TEMPERATURE="", REDIS_PASSWORD="")
    assert settings.OPENAI_TEMPERATURE is None
    assert settings.REDIS_PASSWORD is None


def test_settings_reject_unknown_timezone() -> None:
    with pytest.raises(ValueError):
        Settings(_env_file=None, **_REQUIRED, TIMEZONE="Mars/Olympus")
