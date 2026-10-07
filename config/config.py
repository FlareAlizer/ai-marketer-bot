"""Настройки бота. Читаются из переменных окружения и файла .env."""

from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    BOT_TOKEN: SecretStr

    # LLM: любой OpenAI-совместимый эндпоинт
    OPENAI_API_KEY: SecretStr
    OPENAI_BASE_URL: str
    OPENAI_MODEL: str = "gpt-5-mini"
    # Пустое значение — параметр не передаётся (часть моделей принимает только значение по умолчанию)
    OPENAI_TEMPERATURE: float | None = 0.75
    OPENAI_TIMEOUT: float = 60.0
    OPENAI_MAX_RETRIES: int = 2

    # PostgreSQL
    DB_USER: str
    DB_PASS: SecretStr
    DB_NAME: str
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432

    # Redis (хранилище состояний FSM)
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: SecretStr | None = None

    # Часовой пояс, в котором пользователи вводят время публикаций
    TIMEZONE: str = "Europe/Moscow"
    # Как часто планировщик проверяет отложенные посты, секунды
    SCHEDULER_POLL_INTERVAL: int = 30
    # На сколько секунд можно опоздать с публикацией (бот был выключен), прежде чем пост считается пропущенным
    SCHEDULER_MISFIRE_GRACE: int = 3600

    LOG_LEVEL: str = "INFO"

    @field_validator("OPENAI_TEMPERATURE", "REDIS_PASSWORD", mode="before")
    @classmethod
    def _empty_to_none(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("TIMEZONE")
    @classmethod
    def _check_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"неизвестный часовой пояс: {value}") from exc
        return value

    @property
    def database_url(self) -> URL:
        """URL для асинхронного движка. Собирается через URL.create, чтобы спецсимволы в пароле не ломали строку."""
        return URL.create(
            "postgresql+asyncpg",
            username=self.DB_USER,
            password=self.DB_PASS.get_secret_value(),
            host=self.DB_HOST,
            port=self.DB_PORT,
            database=self.DB_NAME,
        )

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.TIMEZONE)


@lru_cache
def get_settings() -> Settings:
    """Настройки создаются при первом обращении: импорт модулей не требует заполненного окружения."""
    return Settings()
