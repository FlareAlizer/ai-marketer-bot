from openai import AsyncOpenAI
from config.config import config

import logging
import re

# --- MASTER PROMPTS (PRODUCT LEVEL) ---

SYSTEM_PROMPT = """
Ты — профессиональный автор Telegram-каналов с миллионной аудиторией и эксперт по контент-маркетингу.
Твоя задача — писать тексты, которые читают взахлеб, сохраняют и пересылают. Твои тексты — это искусство маркетинга.

ФИЛОСОФИЯ TELEGRAM-ТЕКСТА:
1. **Уважение к времени:** Никакой воды. Сразу к сути.
2. **Личность:** Пиши от первого лица, но профессионально. Избегай канцеляризмов.
3. **Визуальная чистота:** Короткие абзацы (2-4 строки). Пустая строка между абзацами.
4. **Табу:**
   - НИКАКИХ ПРИВЕТСТВИЙ ("Дорогие подписчики", "Всем привет"). Начинай сразу с хука.
   - НИКАКОГО MARKDOWN. Запрещено использовать символы: * (звездочки), _ (нижнее подчеркивание для курсива), ` (бэктики). 
   - Если ты используешь звездочки для списков или выделения — это считается критической ошибкой.

5. **ВАЖНО:** Всегда закрывай каждый открытый тег. Если открыл <i>, обязан написать </i>.


ТВОЙ ИНСТРУМЕНТАРИЙ (ТОЛЬКО HTML):
- <b>Жирный</b> — для акцентов и важных смыслов.
- <i>Курсив</i> — для внутренних диалогов, мыслей или цитат.
- <u>Подчеркивание</u> — для выделения ключевых терминов или терминологии.
- <tg-spoiler>Скрытый текст</tg-spoiler> — используй для интриги, ответов на вопросы или "пасхалок" внутри текста.
- Используй комбинации, например: <b><u>Важная мысль</u></b>.
- Списки: используй только эмодзи-маркеры. Никаких буллитов-звездочек.
"""

PLAN_GENERATION_PROMPT = """
ЗАДАЧА:
Разработай контент-стратегию из {quantity} постов для эксперта.

ВВОДНЫЕ:
- Ниша: {niche}
- Автор: {about}
- ГЛАВНАЯ ЦЕЛЬ / ТЕМА ЭТОГО ПЛАНА: {goal}

СТРАТЕГИЯ:
Построй логическую цепочку постов, которая приведет к цели "{goal}".
Чередуй форматы: Личная история, Экспертный разбор, Кейс/Пример, Провокация/Миф, Продажа/Призыв.

ФОРМАТ ВЫВОДА (Строго список):
Пост 1: [Цепляющий Заголовок] - [О чем писать (суть)]
Пост 2: [Цепляющий Заголовок] - [О чем писать (суть)]
...

ВАЖНО: Заголовки должны быть кликбейтными, но честными (как на YouTube обложках).
"""

POST_GENERATION_PROMPT = """
ЗАДАЧА:
ЗАДАЧА:
Напиши пост для Telegram-канала (Пост №{post_number} из плана).

КОНТЕКСТ:
- Ниша: {niche}
- Автор: {about}
- Тема поста: {topic}
{thesis_part}

СТРУКТУРА ИДЕАЛЬНОГО ТЕЛЕГРАМ-ПОСТА:
1. **HOOK (Заголовок):** Короткая, бьющая в боль или любопытство фраза. Выдели тегом <b>.
2. **BODY (Мясо):** Раскрытие темы. Минимум воды, максимум пользы/эмоций. Используй списки с эмодзи.
3. **PUNCHLINE (Вывод):** Одна сильная мысль в конце. Выдели ее через <i> или <u>.
4. **CTA (Призыв):** Четкое действие (Подпишись / Забери гайд). Выдели жирным <b>.

ВИЗУАЛЬНОЕ ОФОРМЛЕНИЕ (ЭКСПЕРИМЕНТИРУЙ):
- Сделай пост визуально "дорогим". Используй <tg-spoiler>, чтобы спрятать паскалки, интригующие моменты в тексте.
- Используй комбинации форматирования для акцентов, на которых должен споткнуться взгляд.
- Смело сочетай теги, чтобы текст не выглядел монотонным полотном.

ТРЕБОВАНИЯ:
- Длина: 1000-1800 знаков.
- Стиль: "Умный друг". Не поучай, а делись опытом.
- КРИТИЧЕСКИЙ ЗАПРЕТ: НИ ОДНОЙ ЗВЕЗДОЧКИ (*). Только чистый HTML
    Проверь, что все теги  закрыты.

КРИТИЧЕСКОЕ ПРАВИЛО:
Ты работаешь внутри системы, которая ПОНИМАЕТ ТОЛЬКО HTML. 
Любая звездочка (*) или нижнее подчеркивание (_) приведет к ОШИБКЕ СЕРВЕРА.
Вместо **текст** пиши <b>текст</b>.
Вместо *текст* пиши <i>текст</i>.
"""

EDIT_INSTRUCTION_PROMPT = """
ЗАДАЧА:
Ты — редактор Telegram-канала. Отредактируй пост по требованию.

ИСХОДНЫЙ ТЕКСТ:
{current_text}

ТРЕБОВАНИЕ:
{instruction}

ВАЖНО: Сохрани HTML-разметку. Верни только готовый текст.
"""


SHORTEN_PROMPT = """
ЗАДАЧА:
Сократи текст поста так, чтобы он стал короче 1000 символов (включая HTML-теги), но сохранил смысл, структуру и призыв к действию. Это нужно для подписи к фотографии.

ИСХОДНЫЙ ТЕКСТ:
{text}

ТРЕБОВАНИЯ:
- Итоговая длина: 800-950 знаков.
- Сохрани HTML-разметку (<b>, <i>, <u>).
- Верни только готовый сокращенный текст.
- НИКАКИХ ЗВЕЗДОЧЕК (*).
"""



class LLMService:
    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=config.OPENAI_API_KEY.get_secret_value(),
            base_url=config.OPENAI_BASE_URL
        )
        self.model = config.OPENAI_MODEL

    def _fix_markdown_to_html(self, text: str) -> str:
        """Принудительная замена ** на <b> и удаление одиночных *"""
        text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
        text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)
        return text.replace('*', '')

    async def _chat_completion(self, user_content: str, system_content: str = SYSTEM_PROMPT) -> str:
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": user_content}
                ],
                temperature=0.75,
            )
            return self._fix_markdown_to_html(response.choices[0].message.content)
        except Exception as e:
            logging.error(f"LLM Error: {e}")
            return "⚠️ Сбой нейросети."

    # ВОССТАНОВЛЕННЫЙ МЕТОД ГЕНЕРАЦИИ ПЛАНА
    async def generate_content_plan(self, niche: str, about: str, goal: str, quantity: int) -> str:
        prompt = PLAN_GENERATION_PROMPT.format(
            quantity=quantity, niche=niche, about=about, goal=goal
        )
        return await self._chat_completion(prompt)

    # ВОССТАНОВЛЕННЫЙ МЕТОД ГЕНЕРАЦИИ ПОСТА
    async def generate_post_text(self, niche: str, about: str, topic: str, post_number: int, thesis: str = None) -> str:
        thesis_part = f"- Тезисы: {thesis}" if thesis else ""
        prompt = POST_GENERATION_PROMPT.format(
            niche=niche, about=about, topic=topic, post_number=post_number, thesis_part=thesis_part
        )
        return await self._chat_completion(prompt)

    async def refine_post_text(self, current_text: str, instruction: str) -> str:
        prompt = f"Отредактируй пост. Текущий текст:\n{current_text}\n\nИнструкция: {instruction}. Сохрани HTML."
        return await self._chat_completion(prompt)

    # МЕТОД ДЛЯ СЖАТИЯ ПОД ФОТО
    async def shorten_post_for_caption(self, text: str) -> str:
        prompt = SHORTEN_PROMPT.format(text=text)
        return await self._chat_completion(prompt)

llm_client = LLMService()