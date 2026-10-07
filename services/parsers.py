"""Разбор ответа модели с контент-планом."""

import json
import re
from dataclasses import dataclass

from db.models import TOPIC_MAX_LEN
from services.html_tools import clip, strip_tags

# «Пост 1: тема», «День 2 - тема», «3) тема», «4. тема», «№5 — тема»
_LINE_RE = re.compile(
    r"^(?:[-•–—]\s*)?(?:(?:пост|post|день|day)\s*)?[#№]?\s*(\d{1,3})\s*[-:.)–—]\s*(.+)$",
    re.IGNORECASE,
)
_NUMBER_KEYS = ("day", "number", "post", "id", "день", "пост", "номер")
_TOPIC_KEYS = ("topic", "title", "headline", "тема", "заголовок")


@dataclass(frozen=True)
class PlanItem:
    day: int
    topic: str


def _clean_topic(raw: object) -> str:
    if not isinstance(raw, str):
        return ""
    topic = strip_tags(raw).replace("*", "")
    topic = re.sub(r"[\[\]]", "", topic)
    topic = re.sub(r"\s+", " ", topic).strip(" \"'«»,")
    return clip(topic, TOPIC_MAX_LEN)


def _from_json(text: str) -> list[tuple[int, str]]:
    cleaned = re.sub(r"```[a-zA-Z]*", "", text).strip()
    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        return []
    if isinstance(data, dict):
        # {"posts": [...]} или {"Пост 1": "тема", ...}
        lists = [value for value in data.values() if isinstance(value, list)]
        data = lists[0] if lists else [data]
    if not isinstance(data, list):
        return []

    found: list[tuple[int, str]] = []
    for position, item in enumerate(data, start=1):
        if isinstance(item, str):
            found.append((position, item))
        elif isinstance(item, dict):
            found.extend(_from_json_object(item, position))
    return found


def _from_json_object(item: dict, position: int) -> list[tuple[int, str]]:
    lowered = {str(key).lower(): value for key, value in item.items()}
    topic = next((lowered[key] for key in _TOPIC_KEYS if isinstance(lowered.get(key), str)), None)
    if topic is not None:
        number = next((lowered[key] for key in _NUMBER_KEYS if isinstance(lowered.get(key), int)), position)
        return [(number, topic)]

    # Формат {"Пост 1": "тема"}: номер берём из ключа
    found = []
    for key, value in item.items():
        match = re.search(r"\d+", str(key))
        if match and isinstance(value, str):
            found.append((int(match.group()), value))
    return found


def _from_lines(text: str) -> list[tuple[int, str]]:
    found = []
    for line in text.splitlines():
        line = re.sub(r"^#+\s*", "", line.replace("*", "").strip())
        line = line.strip("[]{},\"' ")
        match = _LINE_RE.match(line)
        if match:
            found.append((int(match.group(1)), match.group(2)))
    return found


def parse_plan_text(text: str, limit: int | None = None) -> list[PlanItem]:
    """Достаёт из ответа модели список тем.

    Понимает JSON и построчный список. Повторы номеров отбрасываются, посты
    сортируются и нумеруются заново с единицы. limit — сколько постов просили.
    """
    raw_items = _from_json(text) or _from_lines(text)

    by_number: dict[int, str] = {}
    for number, raw_topic in raw_items:
        topic = _clean_topic(raw_topic)
        if topic and number not in by_number:
            by_number[number] = topic

    topics = [by_number[number] for number in sorted(by_number)]
    if limit is not None:
        topics = topics[:limit]
    return [PlanItem(day=index, topic=topic) for index, topic in enumerate(topics, start=1)]
