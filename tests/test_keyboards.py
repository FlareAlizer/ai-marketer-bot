from datetime import datetime

from aiogram.types import InlineKeyboardMarkup

from db.models import ContentPlan, Post, PostStatus
from keyboards.editor import (
    EditorCallback,
    PublishCallback,
    get_after_publish_keyboard,
    get_compression_choice_keyboard,
    get_editor_main_keyboard,
    get_preview_keyboard,
)
from keyboards.menu import BTN_NEW_PLAN, BTN_PLAN, BTN_PROFILE, get_main_menu
from keyboards.plan import PostSelectCallback, get_plan_keyboard, short_headline
from keyboards.profile import (
    ALLOWED_QUANTITIES,
    PlanHistoryCallback,
    SetupCallback,
    get_goals_keyboard,
    get_history_list_keyboard,
    get_quantity_keyboard,
    goal_title,
)

CALLBACK_DATA_LIMIT = 64  # байт, ограничение Telegram


def buttons(markup: InlineKeyboardMarkup) -> list:
    return [button for row in markup.inline_keyboard for button in row]


def test_main_menu_layout() -> None:
    rows = get_main_menu().keyboard
    assert [[button.text for button in row] for row in rows] == [[BTN_PLAN, BTN_PROFILE], [BTN_NEW_PLAN]]


def test_short_headline() -> None:
    assert short_headline("<b>Как я начал</b> - история провала") == "Как я начал"
    assert short_headline('"Миф" — разбор') == "Миф"
    assert short_headline("Очень длинный заголовок без разделителя") == "Очень длинный заголо.."


def test_plan_keyboard_shows_status_and_carries_post_id() -> None:
    posts = [
        Post(id=11, day_number=1, topic="Первый", status=PostStatus.PUBLISHED),
        Post(id=12, day_number=2, topic="Второй", status=PostStatus.SCHEDULED),
        Post(id=13, day_number=3, topic="Третий", status=PostStatus.GENERATED),
    ]
    items = buttons(get_plan_keyboard(posts))
    assert [item.text for item in items] == ["✅ #1: Первый", "🕒 #2: Второй", "📝 #3: Третий", "➕ Новый план"]
    assert PostSelectCallback.unpack(items[1].callback_data) == PostSelectCallback(post_id=12, action="edit")
    assert items[-1].callback_data == "create_new_plan"


def test_editor_keyboards_carry_post_id() -> None:
    post_id = 987654321
    editor_actions = {
        EditorCallback.unpack(button.callback_data).action for button in buttons(get_editor_main_keyboard(post_id))
    }
    assert editor_actions == {"menu_topic", "menu_text", "add_media", "preview", "back"}

    preview = buttons(get_preview_keyboard(post_id))
    assert [PublishCallback.unpack(button.callback_data).action for button in preview[:3]] == [
        "now",
        "schedule_single",
        "schedule_batch",
    ]
    all_buttons = (
        buttons(get_editor_main_keyboard(post_id))
        + preview
        + buttons(get_compression_choice_keyboard(post_id))
        + buttons(get_after_publish_keyboard(post_id))
    )
    for button in all_buttons:
        assert len(button.callback_data.encode()) <= CALLBACK_DATA_LIMIT
        if button.callback_data != "go_to_main_menu":
            assert str(post_id) in button.callback_data


def test_goals_keyboard_for_onboarding_and_new_plan() -> None:
    onboarding = [SetupCallback.unpack(button.callback_data) for button in buttons(get_goals_keyboard())]
    assert {item.action for item in onboarding} == {"goal"}
    assert [item.value for item in onboarding] == ["sales", "engagement", "expert", "brand"]

    new_plan = [SetupCallback.unpack(button.callback_data) for button in buttons(get_goals_keyboard(is_new_plan=True))]
    assert {item.action for item in new_plan} == {"goal_new"}
    assert new_plan[-1].value == "own_input"


def test_goal_title() -> None:
    assert goal_title("expert") == "Экспертность"
    assert goal_title("что-то чужое") == "Продажи"


def test_quantity_keyboard_matches_allowed_values() -> None:
    values = {int(SetupCallback.unpack(button.callback_data).value) for button in buttons(get_quantity_keyboard())}
    assert values == ALLOWED_QUANTITIES == {5, 7, 10, 14, 30}


def test_history_keyboard() -> None:
    plans = [ContentPlan(id=5, created_at=datetime(2026, 1, 31, 12, 0))]
    items = buttons(get_history_list_keyboard(plans))
    assert items[0].text == "📅 План от 31.01.2026"
    assert PlanHistoryCallback.unpack(items[0].callback_data).plan_id == 5
    assert items[-1].callback_data == "back_to_profile"
