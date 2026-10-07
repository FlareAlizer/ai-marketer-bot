import pytest

from services.html_tools import (
    clip,
    markdown_to_html,
    prepare_llm_html,
    sanitize_html,
    strip_tags,
    visible_length,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("<b>Жирный</b> и <i>курсив</i>", "<b>Жирный</b> и <i>курсив</i>"),
        # Незакрытые теги закрываются
        ("<b>Хук <i>мысль", "<b>Хук <i>мысль</i></b>"),
        # Закрывающий тег без пары отбрасывается
        ("Текст</b> дальше", "Текст дальше"),
        # Неправильная вложенность выравнивается
        ("<b>а <i>б</b> в</i>", "<b>а <i>б</i></b> в"),
        # Неподдерживаемые теги убираются, содержимое остаётся
        ("<h1>Заголовок</h1><p>Абзац</p>", "Заголовок\nАбзац"),
        ("строка<br>ещё<br/>одна", "строка\nещё\nодна"),
        ("<ul><li>раз</li><li>два</li></ul>", "• раз\n• два"),
        # Спецсимволы в тексте экранируются
        ("Цена < 1000 & скидка > 5%", "Цена &lt; 1000 &amp; скидка &gt; 5%"),
        ('<span class="tg-spoiler">секрет</span>', "<tg-spoiler>секрет</tg-spoiler>"),
        ("<span>обычный</span>", "обычный"),
        ('<a href="https://example.com/?a=1&b=2">ссылка</a>', '<a href="https://example.com/?a=1&amp;b=2">ссылка</a>'),
        # Ссылки с небезопасной схемой превращаются в обычный текст
        ('<a href="javascript:alert(1)">клик</a>', "клик"),
        ("<script>alert(1)</script>", "alert(1)"),
    ],
)
def test_sanitize_html(raw: str, expected: str) -> None:
    assert sanitize_html(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "<b>Хук <i>мысль",
        "Цена < 1000 & скидка",
        "<h1>Заголовок</h1><p>Абзац</p>\n\n\n\nКонец",
        '<a href="https://example.com/?a=1&b=2">ссылка</a> &amp; <tg-spoiler>тсс</tg-spoiler>',
        '<blockquote expandable>цитата</blockquote><pre><code class="language-python">x = 1 < 2</code></pre>',
    ],
)
def test_sanitize_html_is_idempotent(raw: str) -> None:
    once = sanitize_html(raw)
    assert sanitize_html(once) == once


def test_strip_tags_and_visible_length() -> None:
    assert strip_tags("<b>a</b> &lt; b &amp; c") == "a < b & c"
    assert visible_length("<b>привет</b>") == 6
    # Теги и сущности в лимит не входят, а эмодзи вне BMP занимает две единицы UTF-16
    assert visible_length("<b>&amp;</b>") == 1
    assert visible_length("🚀") == 2


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("**важно** и *мысль*", "<b>важно</b> и <i>мысль</i>"),
        ("* пункт один\n* пункт два", "• пункт один\n• пункт два"),
        ("```html\n<b>текст</b>\n```", "<b>текст</b>"),
        ("2 * 3 = 6", "2  3 = 6"),
        ("без разметки", "без разметки"),
    ],
)
def test_markdown_to_html(raw: str, expected: str) -> None:
    assert markdown_to_html(raw) == expected


def test_prepare_llm_html_never_leaves_asterisks_or_open_tags() -> None:
    result = prepare_llm_html("**Хук**\n\n<i>Вывод без закрытия\n* пункт")
    assert "*" not in result
    assert result == "<b>Хук</b>\n\n<i>Вывод без закрытия\n• пункт</i>"


def test_clip() -> None:
    assert clip("короткий", 20) == "короткий"
    assert clip("а" * 30, 10) == "а" * 9 + "…"
    assert len(clip("слово " * 100, 255)) <= 255
