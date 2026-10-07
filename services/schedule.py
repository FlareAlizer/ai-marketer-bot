"""Расчёт расписания публикаций. Чистые функции без обращения к Telegram и базе.

Все даты — «наивные» datetime в часовом поясе из настроек (TIMEZONE).
"""

import re
from collections.abc import Iterable
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

DATETIME_FORMAT = "%d.%m.%Y %H:%M"

_WEEKDAYS = {
    "пн": 0, "понедельник": 0,
    "вт": 1, "вторник": 1,
    "ср": 2, "среда": 2, "среду": 2,
    "чт": 3, "четверг": 3,
    "пт": 4, "пятница": 4, "пятницу": 4,
    "сб": 5, "суббота": 5, "субботу": 5,
    "вс": 6, "воскресенье": 6,
}  # fmt: skip
_EVERY_DAY = ("каждый", "ежедневно")
_TIME_RE = re.compile(r"(?<!\d)(\d{1,2})[:.](\d{2})(?!\d)")


def local_now(tz: ZoneInfo) -> datetime:
    """Текущее время в часовом поясе бота без tzinfo (так оно хранится в базе)."""
    return datetime.now(tz).replace(tzinfo=None, microsecond=0)


def parse_batch_schedule(text: str) -> tuple[list[int], time] | None:
    """Разбирает строку вида «Пн Ср Пт 10:00» или «Каждый день 18:30».

    Возвращает (дни недели 0..6, время) или None, если формат не распознан.
    """
    lowered = text.lower()
    time_match = _TIME_RE.search(lowered)
    if not time_match:
        return None
    hour, minute = int(time_match.group(1)), int(time_match.group(2))
    if hour > 23 or minute > 59:
        return None

    if any(word in lowered for word in _EVERY_DAY):
        weekdays = list(range(7))
    else:
        words = re.findall(r"[а-яё]+", lowered)
        weekdays = sorted({_WEEKDAYS[word] for word in words if word in _WEEKDAYS})
    if not weekdays:
        return None
    return weekdays, time(hour, minute)


def parse_single_datetime(text: str) -> datetime | None:
    """Разбирает «ДД.ММ.ГГГГ ЧЧ:ММ». None — если строка не подходит под формат."""
    try:
        return datetime.strptime(text.strip(), DATETIME_FORMAT)
    except ValueError:
        return None


def build_schedule(now: datetime, weekdays: Iterable[int], at: time, count: int) -> list[datetime]:
    """Возвращает count дат публикации начиная с завтрашнего дня по выбранным дням недели."""
    allowed = {day for day in weekdays if 0 <= day <= 6}
    if not allowed or count <= 0:
        return []
    slots: list[datetime] = []
    current = datetime.combine(now.date(), at) + timedelta(days=1)
    while len(slots) < count:
        if current.weekday() in allowed:
            slots.append(current)
        current += timedelta(days=1)
    return slots


def is_missed(scheduled: datetime, now: datetime, grace_seconds: int) -> bool:
    """True, если с назначенного времени прошло больше допустимого опоздания."""
    return (now - scheduled).total_seconds() > grace_seconds
