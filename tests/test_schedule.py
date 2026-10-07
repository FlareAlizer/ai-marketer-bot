from datetime import datetime, time

import pytest

from services.schedule import build_schedule, is_missed, parse_batch_schedule, parse_single_datetime


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Пн Ср Пт 10:00", ([0, 2, 4], time(10, 0))),
        ("Каждый день 18:30", (list(range(7)), time(18, 30))),
        ("ежедневно в 9.05", (list(range(7)), time(9, 5))),
        ("пт, пн. 7:00", ([0, 4], time(7, 0))),
        ("Суббота и воскресенье 12:00", ([5, 6], time(12, 0))),
        ("вт вт вт 23:59", ([1], time(23, 59))),
    ],
)
def test_parse_batch_schedule(text: str, expected: tuple[list[int], time]) -> None:
    assert parse_batch_schedule(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Пн Ср Пт",  # нет времени
        "10:00",  # нет дней
        "Пн 25:00",  # нет такого часа
        "Пн 10:75",  # нет такой минуты
        "срочно всем 10:00",  # похожие слова — не дни недели
    ],
)
def test_parse_batch_schedule_rejects_bad_input(text: str) -> None:
    assert parse_batch_schedule(text) is None


def test_parse_single_datetime() -> None:
    assert parse_single_datetime(" 25.12.2026 14:00 ") == datetime(2026, 12, 25, 14, 0)
    for bad in ("", "завтра", "2026-12-25 14:00", "32.01.2026 10:00", "25.12.2026 24:00"):
        assert parse_single_datetime(bad) is None


def test_build_schedule_starts_tomorrow_and_follows_weekdays() -> None:
    now = datetime(2026, 10, 7, 23, 50)  # среда
    slots = build_schedule(now, [0, 2, 4], time(10, 0), 4)
    assert slots == [
        datetime(2026, 10, 9, 10, 0),  # пятница
        datetime(2026, 10, 12, 10, 0),  # понедельник
        datetime(2026, 10, 14, 10, 0),  # среда
        datetime(2026, 10, 16, 10, 0),  # пятница
    ]


def test_build_schedule_every_day_never_uses_today() -> None:
    now = datetime(2026, 10, 7, 8, 0)
    slots = build_schedule(now, range(7), time(18, 30), 3)
    assert slots == [datetime(2026, 10, 8 + shift, 18, 30) for shift in range(3)]


def test_build_schedule_handles_empty_input() -> None:
    now = datetime(2026, 10, 7, 8, 0)
    assert build_schedule(now, [], time(10, 0), 5) == []
    assert build_schedule(now, [9], time(10, 0), 5) == []
    assert build_schedule(now, [1], time(10, 0), 0) == []


def test_is_missed() -> None:
    scheduled = datetime(2026, 10, 7, 10, 0)
    assert not is_missed(scheduled, datetime(2026, 10, 7, 10, 0, 30), 3600)
    assert not is_missed(scheduled, datetime(2026, 10, 7, 11, 0), 3600)
    assert is_missed(scheduled, datetime(2026, 10, 7, 11, 0, 1), 3600)
