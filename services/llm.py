"""Клиент LLM поверх OpenAI-совместимого API."""

import logging

from openai import APIStatusError, AsyncOpenAI, OpenAIError

from config.config import Settings
from services.html_tools import prepare_llm_html
from services.prompts import (
    SYSTEM_PROMPT,
    build_edit_prompt,
    build_plan_prompt,
    build_post_prompt,
    build_shorten_prompt,
)

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Модель не ответила или вернула пустой ответ. Текст ошибки пользователю не показывается."""


class LLMService:
    def __init__(self, client: AsyncOpenAI, model: str, temperature: float | None = None) -> None:
        self._client = client
        self._model = model
        self._temperature = temperature

    @classmethod
    def from_settings(cls, settings: Settings) -> "LLMService":
        # Таймаут и повторы (сеть, 429, 5xx — с нарастающей паузой) делает сам SDK
        client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY.get_secret_value(),
            base_url=settings.OPENAI_BASE_URL,
            timeout=settings.OPENAI_TIMEOUT,
            max_retries=settings.OPENAI_MAX_RETRIES,
        )
        return cls(client, settings.OPENAI_MODEL, settings.OPENAI_TEMPERATURE)

    async def close(self) -> None:
        await self._client.close()

    async def _complete(self, user_content: str, system_content: str = SYSTEM_PROMPT) -> str:
        params: dict = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content},
            ],
        }
        if self._temperature is not None:
            params["temperature"] = self._temperature

        try:
            response = await self._client.chat.completions.create(**params)
        except OpenAIError as exc:
            # Текст исключения в лог не пишем: в нём бывают фрагменты ключа и запроса
            status = exc.status_code if isinstance(exc, APIStatusError) else "-"
            logger.error("Запрос к LLM не выполнен: %s, статус %s", type(exc).__name__, status)
            raise LLMError("запрос к модели не выполнен") from exc

        content = response.choices[0].message.content if response.choices else None
        if not content or not content.strip():
            logger.error("LLM вернула пустой ответ")
            raise LLMError("пустой ответ модели")
        return content.strip()

    async def generate_content_plan(self, niche: str | None, about: str | None, goal: str | None, quantity: int) -> str:
        """Возвращает сырой текст плана; разбирает его services.parsers.parse_plan_text."""
        return await self._complete(build_plan_prompt(niche, about, goal, quantity))

    async def generate_post_text(
        self,
        niche: str | None,
        about: str | None,
        topic: str,
        post_number: int,
        thesis: str | None = None,
    ) -> str:
        raw = await self._complete(build_post_prompt(niche, about, topic, post_number, thesis))
        return prepare_llm_html(raw)

    async def refine_post_text(self, current_text: str, instruction: str) -> str:
        raw = await self._complete(build_edit_prompt(current_text, instruction))
        return prepare_llm_html(raw)

    async def shorten_post_for_caption(self, text: str) -> str:
        raw = await self._complete(build_shorten_prompt(text))
        return prepare_llm_html(raw)
