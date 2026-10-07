"""Работа с HTML-разметкой Telegram: очистка ответов модели, подсчёт длины, обрезка."""

import html
import re
from html.parser import HTMLParser

# Лимиты Telegram считаются по видимому тексту (после разбора разметки)
MESSAGE_LIMIT = 4096
CAPTION_LIMIT = 1024

# Теги, которые понимает Telegram в parse_mode=HTML
_ALLOWED_TAGS = {
    "b", "strong", "i", "em", "u", "ins", "s", "strike", "del",
    "tg-spoiler", "tg-emoji", "code", "pre", "blockquote", "a",
}  # fmt: skip
# После этих блочных тегов нужен перенос строки, иначе абзацы склеятся
_BLOCK_TAGS = {"p", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr"}
_SAFE_LINK = re.compile(r"^(https?://|tg://|mailto:)", re.IGNORECASE)


class _TelegramHtmlSanitizer(HTMLParser):
    """Пересобирает текст: оставляет разрешённые теги, остальное экранирует или выбрасывает."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        # Стек открытых тегов: (тег в исходнике, тег в результате)
        self.stack: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        if tag == "br":
            self.out.append("\n")
        elif tag == "li":
            self.out.append("• ")
        elif tag == "span" and attr.get("class") == "tg-spoiler":
            self._open(tag, "tg-spoiler", "")
        elif tag == "a":
            href = attr.get("href") or ""
            if _SAFE_LINK.match(href):
                self._open(tag, tag, f' href="{html.escape(href, quote=True)}"')
        elif tag == "tg-emoji":
            emoji_id = attr.get("emoji-id") or ""
            if emoji_id.isdigit():
                self._open(tag, tag, f' emoji-id="{emoji_id}"')
        elif tag == "code":
            lang = attr.get("class") or ""
            suffix = f' class="{html.escape(lang, quote=True)}"' if lang.startswith("language-") else ""
            self._open(tag, tag, suffix)
        elif tag == "blockquote":
            self._open(tag, tag, " expandable" if "expandable" in attr else "")
        elif tag in _ALLOWED_TAGS:
            self._open(tag, tag, "")

    def handle_endtag(self, tag: str) -> None:
        if tag in _BLOCK_TAGS:
            self.out.append("\n")
            return
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                # Закрываем и сам тег, и всё, что осталось открытым внутри него
                self._close_down_to(index)
                return
        # Закрывающий тег без пары просто пропускаем

    def handle_data(self, data: str) -> None:
        self.out.append(html.escape(data, quote=False))

    def result(self) -> str:
        self.close()
        self._close_down_to(0)
        text = "".join(self.out)
        return re.sub(r"\n{3,}", "\n\n", text).strip()

    def _open(self, source_tag: str, out_tag: str, attrs: str) -> None:
        self.stack.append((source_tag, out_tag))
        self.out.append(f"<{out_tag}{attrs}>")

    def _close_down_to(self, index: int) -> None:
        while len(self.stack) > index:
            _, out_tag = self.stack.pop()
            self.out.append(f"</{out_tag}>")


def sanitize_html(text: str) -> str:
    """Приводит текст к разметке, которую Telegram гарантированно разберёт.

    Незнакомые теги убираются (содержимое остаётся), незакрытые — закрываются,
    одиночные «<» и «&» экранируются. Повторный вызов результат не меняет.
    """
    parser = _TelegramHtmlSanitizer()
    parser.feed(text)
    return parser.result()


def strip_tags(text: str) -> str:
    """Видимый текст без разметки."""
    return html.unescape(re.sub(r"<[^>]+>", "", text))


def visible_length(text: str) -> int:
    """Длина так, как её считает Telegram: видимый текст в кодовых единицах UTF-16."""
    return len(strip_tags(text).encode("utf-16-le")) // 2


def markdown_to_html(text: str) -> str:
    """Исправляет Markdown, который модель иногда выдаёт вопреки инструкции."""
    text = text.strip()
    # Обёртка ```html ... ```
    text = re.sub(r"^```[a-zA-Z]*\s*\n", "", text)
    text = re.sub(r"\n```\s*$", "", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"^[ \t]*\*[ \t]+", "• ", text, flags=re.MULTILINE)
    text = re.sub(r"(?<![\w*])\*(?=\S)(.+?)(?<=\S)\*(?!\w)", r"<i>\1</i>", text)
    return text.replace("*", "")


def prepare_llm_html(text: str) -> str:
    """Ответ модели -> текст поста, пригодный для отправки в Telegram."""
    return sanitize_html(markdown_to_html(text))


def clip(text: str, limit: int) -> str:
    """Обрезает строку до limit символов, добавляя многоточие."""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
