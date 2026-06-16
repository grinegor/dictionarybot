from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

BTN_ADD = "➕ Добавить"
BTN_REVIEW = "🔁 Повторение"
BTN_ASSOC_REVIEW = "🧠 Ассоциации"
BTN_REVIEW_RANDOM = "🎲 Повторение рандом"
BTN_ASSOC_RANDOM = "🎲 Ассоциации рандом"
BTN_IMPORT = "📥 Импорт"
BTN_DICTIONARY = "📚 Словарь"
BTN_SETTINGS = "⚙️ Настройки"
BTN_MENU = "🏠 Меню"
BTN_SHOW_ANSWER = "👁 Показать перевод"
BTN_AGAIN = "🔴 Again"
BTN_HARD = "🟠 Hard"
BTN_GOOD = "🟡 Good"
BTN_EASY = "🟢 Easy"

RATING_BUTTON_TO_KEY = {
    BTN_AGAIN: "again",
    BTN_HARD: "hard",
    BTN_GOOD: "good",
    BTN_EASY: "easy",
    "Again": "again",
    "Hard": "hard",
    "Good": "good",
    "Easy": "easy",
}


def menu_button() -> InlineKeyboardButton:
    return InlineKeyboardButton(text=BTN_MENU, callback_data="menu:home")


def menu_only() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[menu_button()]])


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_ADD), KeyboardButton(text=BTN_IMPORT)],
            [KeyboardButton(text=BTN_REVIEW), KeyboardButton(text=BTN_ASSOC_REVIEW)],
            [KeyboardButton(text=BTN_DICTIONARY), KeyboardButton(text=BTN_SETTINGS)],
        ],
        resize_keyboard=True,
        is_persistent=False,
        one_time_keyboard=False,
    )


def remove_reply_keyboard() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove(remove_keyboard=True)


def start_inline_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="➕ Добавить", callback_data="menu:add"),
                InlineKeyboardButton(text="📥 Импорт", callback_data="menu:import"),
            ],
            [
                InlineKeyboardButton(text=BTN_REVIEW, callback_data="menu:review"),
                InlineKeyboardButton(text=BTN_ASSOC_REVIEW, callback_data="menu:assoc_review"),
            ],
            [
                InlineKeyboardButton(text="📚 Словарь", callback_data="menu:dictionary"),
                InlineKeyboardButton(text="⚙️ Настройки", callback_data="menu:settings"),
            ],
        ]
    )


def review_mode_menu(kind: str) -> InlineKeyboardMarkup:
    if kind == "association":
        fsrs_text = "🧠 FSRS"
        random_text = "🎲 Рандом"
        fsrs_callback = "menu:assoc_fsrs"
        random_callback = "menu:assoc_random"
    else:
        fsrs_text = "🔁 FSRS"
        random_text = "🎲 Рандом"
        fsrs_callback = "menu:review_fsrs"
        random_callback = "menu:review_random"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=fsrs_text, callback_data=fsrs_callback),
                InlineKeyboardButton(text=random_text, callback_data=random_callback),
            ],
            [menu_button()],
        ]
    )


def translation_choice() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Подтвердить", callback_data="add:translation_ok"),
                InlineKeyboardButton(
                    text="✍️ Написать вручную",
                    callback_data="add:translation_manual",
                ),
            ],
            [menu_button()],
        ]
    )


def card_saved_actions() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="➕ Новая карточка", callback_data="menu:add"),
                menu_button(),
            ]
        ]
    )


def duplicate_card(card_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"card:edit:{card_id}"),
                InlineKeyboardButton(text="↩️ Отмена", callback_data="card:cancel"),
            ],
            [menu_button()],
        ]
    )


def association_choice() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✨ Сгенерировать 3", callback_data="add:assoc_generate"),
                InlineKeyboardButton(text="✍️ Своя", callback_data="add:assoc_manual"),
            ],
            [InlineKeyboardButton(text="Без ассоциации", callback_data="add:assoc_skip")],
            [menu_button()],
        ]
    )


def association_variants(variants: list[str]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"✅ {idx + 1}. {variant[:34]}",
                callback_data=f"add:assoc_pick:{idx}",
            )
        ]
        for idx, variant in enumerate(variants)
    ]
    rows.append(
        [
            InlineKeyboardButton(text="🔁 Еще 3", callback_data="add:assoc_generate"),
            InlineKeyboardButton(text="✍️ Своя", callback_data="add:assoc_manual"),
        ]
    )
    rows.append([InlineKeyboardButton(text="Без ассоциации", callback_data="add:assoc_skip")])
    rows.append([menu_button()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def edit_association_choice(has_association: bool) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="✨ Сгенерировать 3", callback_data="edit:assoc_generate"),
            InlineKeyboardButton(text="✍️ Своя", callback_data="edit:assoc_manual"),
        ]
    ]
    if has_association:
        rows.append([InlineKeyboardButton(text="🗑 Убрать", callback_data="edit:assoc_remove")])
    rows.append([InlineKeyboardButton(text="↩️ Карточка", callback_data="edit:back")])
    rows.append([menu_button()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def edit_association_variants(variants: list[str], has_association: bool) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"✅ {idx + 1}. {variant[:34]}",
                callback_data=f"edit:assoc_pick:{idx}",
            )
        ]
        for idx, variant in enumerate(variants)
    ]
    rows.append(
        [
            InlineKeyboardButton(text="🔁 Еще 3", callback_data="edit:assoc_generate"),
            InlineKeyboardButton(text="✍️ Своя", callback_data="edit:assoc_manual"),
        ]
    )
    if has_association:
        rows.append([InlineKeyboardButton(text="🗑 Убрать", callback_data="edit:assoc_remove")])
    rows.append([InlineKeyboardButton(text="↩️ Карточка", callback_data="edit:back")])
    rows.append([menu_button()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def edit_card(dictionary_return: bool = False) -> InlineKeyboardMarkup:
    back_button = (
        InlineKeyboardButton(text="↩️ Словарь", callback_data="dict:return")
        if dictionary_return
        else InlineKeyboardButton(text="↩️ Отмена", callback_data="card:cancel")
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🇷🇺 Перевод", callback_data="edit:ru"),
                InlineKeyboardButton(text="🧠 Ассоциация", callback_data="edit:assoc"),
            ],
            [InlineKeyboardButton(text="🗑 Удалить", callback_data="edit:delete")],
            [back_button],
            [menu_button()],
        ]
    )


def delete_card_confirm(dictionary_return: bool = False) -> InlineKeyboardMarkup:
    back_button = (
        InlineKeyboardButton(text="↩️ Словарь", callback_data="dict:return")
        if dictionary_return
        else InlineKeyboardButton(text="↩️ Отмена", callback_data="card:cancel")
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🗑 Да, удалить", callback_data="edit:delete_confirm"),
                back_button,
            ],
            [menu_button()],
        ]
    )


def review_size(mode: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="25", callback_data=f"review:start:{mode}:25"),
                InlineKeyboardButton(text="50", callback_data=f"review:start:{mode}:50"),
                InlineKeyboardButton(text="100", callback_data=f"review:start:{mode}:100"),
            ],
            [menu_button()],
        ]
    )


def review_show_answer_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_SHOW_ANSWER)],
            [KeyboardButton(text=BTN_MENU)],
        ],
        resize_keyboard=True,
        is_persistent=True,
        one_time_keyboard=False,
        input_field_placeholder="Открой перевод",
    )


def review_rating_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_AGAIN), KeyboardButton(text=BTN_HARD)],
            [KeyboardButton(text=BTN_GOOD), KeyboardButton(text=BTN_EASY)],
            [KeyboardButton(text=BTN_MENU)],
        ],
        resize_keyboard=True,
        is_persistent=True,
        one_time_keyboard=False,
        input_field_placeholder="Оцени карточку",
    )


def show_answer() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=BTN_SHOW_ANSWER, callback_data="review:show")],
            [menu_button()],
        ]
    )


def fsrs_rating() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Again", callback_data="review:rate:again"),
                InlineKeyboardButton(text="Hard", callback_data="review:rate:hard"),
            ],
            [
                InlineKeyboardButton(text="Good", callback_data="review:rate:good"),
                InlineKeyboardButton(text="Easy", callback_data="review:rate:easy"),
            ],
            [menu_button()],
        ]
    )


def settings_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🧠 Стиль ассоциаций", callback_data="settings:assoc")],
            [InlineKeyboardButton(text="🔁 Режим FSRS", callback_data="settings:fsrs")],
            [menu_button()],
        ]
    )


def settings_association_menu(current_style: str) -> InlineKeyboardMarkup:
    labels = {
        "neutral": "Нейтральный",
        "funny": "Забавный",
        "absurd": "Абсурдный",
    }
    rows = []
    for style, label in labels.items():
        marker = "✅ " if current_style == style else ""
        rows.append(
            [InlineKeyboardButton(text=f"{marker}{label}", callback_data=f"settings:style:{style}")]
        )
    rows.append([InlineKeyboardButton(text="↩️ Настройки", callback_data="settings:back")])
    rows.append([menu_button()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_fsrs_menu(current_retention: float) -> InlineKeyboardMarkup:
    labels = {
        0.85: "85% Легкий",
        0.90: "90% Баланс",
        0.95: "95% Интенсивный",
    }
    rows = []
    for retention, label in labels.items():
        marker = "✅ " if round(current_retention, 2) == retention else ""
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{marker}{label}",
                    callback_data=f"settings:retention:{retention}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="↩️ Настройки", callback_data="settings:back")])
    rows.append([menu_button()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def dictionary_cards(
    cards: list[tuple[int, str, int | None]],
    offset: int,
    total: int,
    page_size: int = 10,
    search: bool = False,
) -> InlineKeyboardMarkup:
    fsrs_markers = {
        1: "🔴",
        2: "🟠",
        3: "🟡",
        4: "🟢",
    }
    rows = [
        [
            InlineKeyboardButton(
                text=f"{offset + idx}. {title[:34]} {fsrs_markers.get(rating, '⚪️')}",
                callback_data=f"dict:edit:{card_id}:{offset}:{int(search)}",
            )
        ]
        for idx, (card_id, title, rating) in enumerate(cards, start=1)
    ]
    previous_offset = max(offset - page_size, 0)
    next_offset = offset + page_size
    page_prefix = "dict:search_page" if search else "dict:page"
    nav_row = [
        InlineKeyboardButton(
            text="⬅️",
            callback_data=f"{page_prefix}:{previous_offset}" if offset > 0 else "dict:noop",
        ),
        InlineKeyboardButton(text="🔎 Поиск", callback_data="dict:search"),
        InlineKeyboardButton(
            text="➡️",
            callback_data=f"{page_prefix}:{next_offset}" if next_offset < total else "dict:noop",
        ),
    ]
    rows.append(nav_row)
    rows.append([menu_button()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def dictionary_search_prompt() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="↩️ Словарь", callback_data="dict:page:0")],
            [menu_button()],
        ]
    )


def import_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Импортировать", callback_data="import:confirm"),
                InlineKeyboardButton(text="✍️ Исправить", callback_data="import:manual"),
            ],
            [InlineKeyboardButton(text="↩️ Отмена", callback_data="import:cancel")],
            [menu_button()],
        ]
    )


def import_done_actions() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📥 Импортировать еще", callback_data="menu:import")],
            [menu_button()],
        ]
    )
