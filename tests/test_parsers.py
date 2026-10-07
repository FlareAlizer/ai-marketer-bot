import json

from db.models import TOPIC_MAX_LEN
from services.parsers import PlanItem, parse_plan_text


def test_plain_list_in_requested_format() -> None:
    text = (
        "Вот ваш план:\n"
        "Пост 1: [Как я потерял клиента] - [История провала и вывод]\n"
        "Пост 2: [5 мифов о дизайне] - [Разбор заблуждений]\n"
    )
    assert parse_plan_text(text) == [
        PlanItem(1, "Как я потерял клиента - История провала и вывод"),
        PlanItem(2, "5 мифов о дизайне - Разбор заблуждений"),
    ]


def test_markdown_numbering_variants() -> None:
    text = "**Пост 1:** Первая тема\n2) Вторая тема\n3. Третья тема\nДень 4 — Четвёртая тема\n- №5: Пятая тема"
    assert [item.topic for item in parse_plan_text(text)] == [
        "Первая тема",
        "Вторая тема",
        "Третья тема",
        "Четвёртая тема",
        "Пятая тема",
    ]


def test_lines_without_post_number_are_ignored() -> None:
    text = "В 2024: продажи выросли\nДлина 1000-1800 знаков\nИтого 10 постов: ниже\nПост 1: Тема"
    assert parse_plan_text(text) == [PlanItem(1, "Тема")]


def test_duplicates_gaps_and_order_are_normalized() -> None:
    text = "Пост 3: Третий\nПост 1: Первый\nПост 3: Повтор\nПост 7: Седьмой"
    assert parse_plan_text(text) == [PlanItem(1, "Первый"), PlanItem(2, "Третий"), PlanItem(3, "Седьмой")]


def test_limit_cuts_extra_posts() -> None:
    text = "\n".join(f"Пост {number}: Тема {number}" for number in range(1, 11))
    assert len(parse_plan_text(text, limit=5)) == 5


def test_html_is_stripped_and_long_topic_fits_column() -> None:
    text = f"Пост 1: <b>Заголовок</b> - {'очень длинное описание ' * 30}"
    (item,) = parse_plan_text(text)
    assert item.topic.startswith("Заголовок - очень длинное")
    assert len(item.topic) <= TOPIC_MAX_LEN


def test_json_with_numbered_keys() -> None:
    text = '```json\n[{"Пост 1": "<b>Первый</b>"}, {"Пост 2": "Второй"}]\n```'
    assert parse_plan_text(text) == [PlanItem(1, "Первый"), PlanItem(2, "Второй")]


def test_json_objects_and_strings() -> None:
    objects = json.dumps({"posts": [{"day": 2, "topic": "Второй"}, {"day": 1, "title": "Первый"}]})
    assert parse_plan_text(objects) == [PlanItem(1, "Первый"), PlanItem(2, "Второй")]
    strings = json.dumps(["Первый", "Второй"], ensure_ascii=False)
    assert parse_plan_text(strings) == [PlanItem(1, "Первый"), PlanItem(2, "Второй")]


def test_json_with_unexpected_values_does_not_crash() -> None:
    assert parse_plan_text('[{"Пост 1": 42}, {"Пост 2": null}, 7]') == []


def test_garbage_gives_empty_plan() -> None:
    assert parse_plan_text("") == []
    assert parse_plan_text("Извините, не могу помочь с этим запросом.") == []
