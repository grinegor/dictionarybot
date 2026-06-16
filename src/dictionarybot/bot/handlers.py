import asyncio
import html
import re
from contextlib import suppress
from io import BytesIO

from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BotCommand, CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from dictionarybot.bot import keyboards as kb
from dictionarybot.bot.middleware import AccessMiddleware
from dictionarybot.bot.states import AddCardStates, DictionaryStates, ImportStates, ReviewStates
from dictionarybot.config import Settings
from dictionarybot.db.models import Card, User
from dictionarybot.db.repositories import (
    ASSOCIATION_MODE,
    NORMAL_MODE,
    CardRepository,
    StatsRepository,
    UsageRepository,
    UserRepository,
)
from dictionarybot.db.session import Database
from dictionarybot.services.fsrs import FsrsService
from dictionarybot.services.openai_service import ImportCandidate, OpenAIService, TokenUsage
from dictionarybot.utils.text import clean_text, normalize_english

router = Router()
fsrs = FsrsService()
_settings: Settings | None = None
DICTIONARY_PAGE_SIZE = 10
IMPORT_SKIP_DETAILS_LIMIT = 12
NORMAL_RANDOM_MODE = "normal_random"
ASSOCIATION_RANDOM_MODE = "association_random"
REVIEW_MODES = {NORMAL_MODE, ASSOCIATION_MODE, NORMAL_RANDOM_MODE, ASSOCIATION_RANDOM_MODE}
RANDOM_REVIEW_MODES = {NORMAL_RANDOM_MODE, ASSOCIATION_RANDOM_MODE}
ASSOCIATION_REVIEW_MODES = {ASSOCIATION_MODE, ASSOCIATION_RANDOM_MODE}
NAVIGATION_TRIGGERS = {
    kb.BTN_ADD,
    kb.BTN_REVIEW,
    kb.BTN_ASSOC_REVIEW,
    kb.BTN_REVIEW_RANDOM,
    kb.BTN_ASSOC_RANDOM,
    kb.BTN_IMPORT,
    kb.BTN_DICTIONARY,
    kb.BTN_SETTINGS,
    kb.BTN_MENU,
    "/add",
    "/review",
    "/assoc",
    "/review_random",
    "/assoc_random",
    "/import",
    "/dictionary",
    "/settings",
}
CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
LATIN_RE = re.compile(r"[A-Za-z]")
XMLISH_PAIR_RE = re.compile(
    r"(?:<(?:tts|text)\b[^>]*name=[\"']Text[\"'][^>]*>|name=[\"']Text[\"']>)"
    r"(?P<en>.*?)"
    r"</(?:tts|text)>"
    r"\s*<text\b[^>]*name=[\"']Translation[\"'][^>]*>"
    r"(?P<ru>.*?)"
    r"</text>",
    re.IGNORECASE | re.DOTALL,
)


def register_handlers(dispatcher: Dispatcher, settings: Settings, database: Database) -> None:
    global _settings
    _settings = settings
    dispatcher.message.middleware(AccessMiddleware(settings, database))
    dispatcher.callback_query.middleware(AccessMiddleware(settings, database))
    dispatcher.include_router(router)
    dispatcher.startup.register(_setup_commands)


async def _setup_commands(bot: Bot) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="🏠 Главное меню"),
            BotCommand(command="add", description="➕ Добавить"),
            BotCommand(command="review", description="🔁 Повторение"),
            BotCommand(command="assoc", description="🧠 Ассоциации"),
            BotCommand(
                command="review_random",
                description="🎲 Повторение рандом",
            ),
            BotCommand(
                command="assoc_random",
                description="🎲 Ассоциации рандом",
            ),
            BotCommand(command="import", description="📥 Импорт"),
            BotCommand(command="settings", description="⚙️ Настройки"),
            BotCommand(command="dictionary", description="📚 Словарь"),
            BotCommand(command="stats", description="📊 Админ-статистика"),
        ]
    )


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext, app_user: User) -> None:
    review_was_active = await is_review_state(state)
    await state.clear()
    await send_main_menu(message, reset_reply_keyboard=review_was_active)


@router.callback_query(F.data.startswith("menu:"))
async def menu_callbacks(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    app_user: User,
) -> None:
    action = callback.data.split(":", 1)[1]
    review_was_active = await is_review_state(state)
    await state.clear()
    if review_was_active:
        await clear_reply_keyboard(callback.message, disable_notification=True)
    if action == "home":
        await callback.message.edit_text(main_menu_text(), reply_markup=kb.start_inline_menu())
    elif action == "add":
        await begin_add(callback.message, state, edit=True)
    elif action == "review":
        await show_review_mode_menu(callback.message, "normal", edit=True)
    elif action == "review_fsrs":
        await ask_review_size(callback.message, NORMAL_MODE, edit=True)
    elif action == "assoc_review":
        await show_review_mode_menu(callback.message, "association", edit=True)
    elif action == "assoc_fsrs":
        await ask_review_size(callback.message, ASSOCIATION_MODE, edit=True)
    elif action == "review_random":
        await ask_review_size(callback.message, NORMAL_RANDOM_MODE, edit=True)
    elif action == "assoc_random":
        await ask_review_size(callback.message, ASSOCIATION_RANDOM_MODE, edit=True)
    elif action == "settings":
        await show_settings(callback.message, app_user, edit=True)
    elif action == "dictionary":
        await render_dictionary_page(callback.message, session, app_user, offset=0, edit=True)
    elif action == "import":
        await begin_import(callback.message, state, edit=True)
    await callback.answer()


@router.message(F.text.in_(NAVIGATION_TRIGGERS))
async def navigation_trigger(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    app_user: User,
) -> None:
    review_was_active = await is_review_state(state)
    await state.clear()
    text = message.text
    if review_was_active:
        await clear_reply_keyboard(message, disable_notification=True)
    if text in {kb.BTN_ADD, "/add"}:
        await begin_add(message, state)
    elif text in {kb.BTN_REVIEW, "/review"}:
        await show_review_mode_menu(message, "normal")
    elif text in {kb.BTN_ASSOC_REVIEW, "/assoc"}:
        await show_review_mode_menu(message, "association")
    elif text in {kb.BTN_REVIEW_RANDOM, "/review_random"}:
        await ask_review_size(message, NORMAL_RANDOM_MODE)
    elif text in {kb.BTN_ASSOC_RANDOM, "/assoc_random"}:
        await ask_review_size(message, ASSOCIATION_RANDOM_MODE)
    elif text in {kb.BTN_IMPORT, "/import"}:
        await begin_import(message, state)
    elif text in {kb.BTN_DICTIONARY, "/dictionary"}:
        await render_dictionary_page(message, session, app_user, offset=0)
    elif text in {kb.BTN_SETTINGS, "/settings"}:
        await show_settings(message, app_user)
    elif text == kb.BTN_MENU:
        await send_main_menu(message, disable_notification=True)


@router.message(Command("add"))
async def add_entry(message: Message, state: FSMContext) -> None:
    await begin_add(message, state)


async def begin_add(message: Message, state: FSMContext, edit: bool = False) -> None:
    await state.clear()
    await state.set_state(AddCardStates.waiting_card_input)
    text = (
        "➕ <b>Добавить</b>\n\n"
        "Отправь слово или пару.\n\n"
        "Примеры:\n"
        "<code>stubborn</code>\n"
        "<code>stubborn - упрямый</code>"
    )
    if edit:
        await message.edit_text(text, reply_markup=kb.menu_only())
    else:
        await message.answer(text, reply_markup=kb.menu_only())


@router.message(AddCardStates.waiting_card_input)
async def add_card_input(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    app_user: User,
) -> None:
    text = clean_text(message.text or "")
    if not text:
        await message.answer("Отправь слово текстом или выбери действие в меню.")
        return
    pair = parse_pair(text)
    cards = CardRepository(session, fsrs)

    if pair:
        en_text, ru_text = pair
        existing = await cards.get_by_en(app_user.id, en_text)
        if existing:
            await show_duplicate(message, existing)
            await state.clear()
            return
        await state.update_data(pending_en=en_text, pending_ru=ru_text)
        await state.set_state(None)
        await ask_association(message)
        return

    existing = await cards.get_by_en(app_user.id, text)
    if existing:
        await show_duplicate(message, existing)
        await state.clear()
        return

    await state.update_data(pending_en=text)
    settings = current_settings()
    try:
        service = OpenAIService(settings)
    except RuntimeError:
        await state.set_state(AddCardStates.waiting_ru_manual)
        prompt = await message.answer(
            "OpenAI API не настроен. Напиши перевод вручную.",
            reply_markup=kb.menu_only(),
        )
        await state.update_data(translation_flow_message_id=prompt.message_id)
        return

    thinking = await message.answer("Перевожу через OpenAI...")
    try:
        result = await service.translate_word(text)
    except Exception as exc:
        await log_usage(
            session,
            app_user.id,
            request_type="translation",
            usage=TokenUsage(model=settings.openai_translation_model),
            status="error",
            error_message=str(exc),
        )
        await state.set_state(AddCardStates.waiting_ru_manual)
        await state.update_data(translation_flow_message_id=thinking.message_id)
        await thinking.edit_text(
            "Не получилось перевести автоматически. Напиши перевод вручную.",
            reply_markup=kb.menu_only(),
        )
        return

    await log_usage(session, app_user.id, "translation", result.usage)
    await state.update_data(pending_ru=result.ru_text)
    await state.set_state(None)
    await thinking.edit_text(
        f"🇬🇧 <b>{e(text)}</b>\n🇷🇺 <b>{e(result.ru_text)}</b>\n\nСохранить такой перевод?",
        reply_markup=kb.translation_choice(),
    )


@router.callback_query(F.data == "add:translation_ok")
async def add_translation_ok(callback: CallbackQuery) -> None:
    await ask_association(callback.message, edit=True)
    await callback.answer()


@router.callback_query(F.data == "add:translation_manual")
async def add_translation_manual(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddCardStates.waiting_ru_manual)
    await state.update_data(translation_flow_message_id=callback.message.message_id)
    await callback.message.edit_text("✍️ Напиши перевод на русском.", reply_markup=kb.menu_only())
    await callback.answer()


@router.message(AddCardStates.waiting_ru_manual)
async def add_ru_manual(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.update_data(pending_ru=clean_text(message.text or ""))
    await state.set_state(None)
    flow_message_id = data.get("translation_flow_message_id")
    if flow_message_id is not None:
        await message.bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=flow_message_id,
            text="🧠 Добавить ассоциацию к карточке?",
            reply_markup=kb.association_choice(),
        )
    else:
        await ask_association(message)


async def ask_association(message: Message, edit: bool = False) -> None:
    text = "🧠 Добавить ассоциацию к карточке?"
    if edit:
        await message.edit_text(text, reply_markup=kb.association_choice())
    else:
        await message.answer(text, reply_markup=kb.association_choice())


@router.callback_query(F.data == "add:assoc_skip")
async def add_assoc_skip(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    app_user: User,
) -> None:
    await save_pending_card(
        callback.message,
        state,
        session,
        app_user,
        association_text=None,
        edit=True,
    )
    await callback.answer()


@router.callback_query(F.data == "add:assoc_manual")
async def add_assoc_manual(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddCardStates.waiting_association_manual)
    await state.update_data(association_flow_message_id=callback.message.message_id)
    await callback.message.edit_text(
        "✍️ Напиши ассоциацию одной строкой.",
        reply_markup=kb.menu_only(),
    )
    await callback.answer()


@router.message(AddCardStates.waiting_association_manual)
async def add_association_manual(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    app_user: User,
) -> None:
    data = await state.get_data()
    await save_pending_card(
        message,
        state,
        session,
        app_user,
        clean_text(message.text or ""),
        edit_message_id=data.get("association_flow_message_id"),
    )


@router.callback_query(F.data == "add:assoc_generate")
async def add_assoc_generate(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    app_user: User,
) -> None:
    data = await state.get_data()
    settings = current_settings()
    try:
        service = OpenAIService(settings)
    except RuntimeError:
        await callback.message.answer("OpenAI API не настроен. Напиши ассоциацию вручную.")
        await state.set_state(AddCardStates.waiting_association_manual)
        await callback.answer()
        return

    await callback.answer("Генерирую...")
    try:
        result = await service.generate_associations(
            en_text=data["pending_en"],
            ru_text=data["pending_ru"],
            style=app_user.association_style,  # type: ignore[arg-type]
        )
    except Exception as exc:
        await log_usage(
            session,
            app_user.id,
            request_type="association",
            usage=TokenUsage(model=settings.openai_association_model),
            status="error",
            error_message=str(exc),
        )
        await callback.message.answer(
            "Не получилось сгенерировать. Можно написать свою ассоциацию."
        )
        await state.set_state(AddCardStates.waiting_association_manual)
        return

    await log_usage(session, app_user.id, "association", result.usage)
    if not result.variants:
        await callback.message.edit_text(
            "Не получилось сгенерировать варианты без исходного слова. Попробуй еще раз.",
            reply_markup=kb.association_choice(),
        )
        return
    await state.update_data(association_variants=result.variants)
    text = "\n".join(f"{idx + 1}. {e(value)}" for idx, value in enumerate(result.variants))
    await callback.message.edit_text(
        f"✨ Варианты ассоциаций:\n\n{text}\n\nВыбери одну или сгенерируй еще.",
        reply_markup=kb.association_variants(result.variants),
    )


@router.callback_query(F.data.startswith("add:assoc_pick:"))
async def add_assoc_pick(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    app_user: User,
) -> None:
    idx = int(callback.data.rsplit(":", 1)[1])
    data = await state.get_data()
    variants = data.get("association_variants", [])
    if idx >= len(variants):
        await callback.answer("Вариант не найден", show_alert=True)
        return
    await save_pending_card(
        callback.message,
        state,
        session,
        app_user,
        variants[idx],
        edit=True,
    )
    await callback.answer()


async def save_pending_card(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    app_user: User,
    association_text: str | None,
    edit: bool = False,
    edit_message_id: int | None = None,
) -> None:
    data = await state.get_data()
    cards = CardRepository(session, fsrs)
    result = await cards.create_card(
        user=app_user,
        en_text=data["pending_en"],
        ru_text=data["pending_ru"],
        association_text=association_text,
    )
    await state.clear()
    if result.created:
        text = f"✅ Карточка сохранена.\n\n{format_card(result.card)}"
        if edit_message_id is not None:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=edit_message_id,
                text=text,
                reply_markup=kb.card_saved_actions(),
            )
        elif edit:
            await message.edit_text(text, reply_markup=kb.card_saved_actions())
        else:
            await message.answer(text, reply_markup=kb.card_saved_actions())
    else:
        await show_duplicate(message, result.card, edit=edit, edit_message_id=edit_message_id)


async def show_duplicate(
    message: Message,
    card: Card,
    edit: bool = False,
    edit_message_id: int | None = None,
) -> None:
    text = "Похоже, это слово уже есть в твоем словаре:\n\n" + format_card(card)
    if edit_message_id is not None:
        await message.bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=edit_message_id,
            text=text,
            reply_markup=kb.duplicate_card(card.id),
        )
    elif edit:
        await message.edit_text(text, reply_markup=kb.duplicate_card(card.id))
    else:
        await message.answer(text, reply_markup=kb.duplicate_card(card.id))


@router.callback_query(F.data.startswith("card:edit:"))
async def card_edit_menu(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    app_user: User,
) -> None:
    card_id = int(callback.data.rsplit(":", 1)[1])
    card = await CardRepository(session, fsrs).get_by_id(app_user.id, card_id)
    if not card:
        await callback.answer("Карточка не найдена", show_alert=True)
        return
    await state.clear()
    await state.update_data(edit_card_id=card.id)
    await callback.message.answer(
        "Что редактируем?\n\n" + format_card(card),
        reply_markup=kb.edit_card(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("dict:edit:"))
async def dictionary_card_edit_menu(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    app_user: User,
) -> None:
    _, _, card_id_text, offset_text, search_text = callback.data.split(":")
    card = await CardRepository(session, fsrs).get_by_id(app_user.id, int(card_id_text))
    if not card:
        await callback.answer("Карточка не найдена", show_alert=True)
        return
    data = await state.get_data()
    await state.update_data(
        edit_card_id=card.id,
        dictionary_return_offset=int(offset_text),
        dictionary_return_search=search_text == "1",
        dictionary_return_query=data.get("dictionary_search_query"),
    )
    await callback.message.edit_text(
        "Что редактируем?\n\n" + format_card(card),
        reply_markup=kb.edit_card(dictionary_return=True),
    )
    await callback.answer()


@router.callback_query(F.data == "edit:delete")
async def edit_delete(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    app_user: User,
) -> None:
    data = await state.get_data()
    card_id = data.get("edit_card_id")
    if card_id is None:
        await callback.answer("Карточка не выбрана", show_alert=True)
        return
    card = await CardRepository(session, fsrs).get_by_id(app_user.id, int(card_id))
    if not card:
        await callback.answer("Карточка не найдена", show_alert=True)
        await state.clear()
        return
    await callback.message.edit_text(
        "Удалить карточку?\n\n" + format_card(card),
        reply_markup=kb.delete_card_confirm(dictionary_return=has_dictionary_return(data)),
    )
    await callback.answer()


@router.callback_query(F.data == "edit:delete_confirm")
async def edit_delete_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    app_user: User,
) -> None:
    data = await state.get_data()
    card_id = data.get("edit_card_id")
    if card_id is None:
        await callback.answer("Карточка не выбрана", show_alert=True)
        return
    repo = CardRepository(session, fsrs)
    card = await repo.get_by_id(app_user.id, int(card_id))
    if not card:
        await callback.answer("Карточка уже удалена", show_alert=True)
        await state.clear()
        return
    title = card.en_text
    return_offset, return_query = dictionary_return_context(data)
    await repo.delete_card(card)
    await state.clear()
    if has_dictionary_return(data):
        if return_query:
            await state.update_data(dictionary_search_query=return_query)
        await render_dictionary_page(
            callback.message,
            session,
            app_user,
            offset=return_offset,
            edit=True,
            search_query=return_query,
        )
        await callback.answer(f"Удалено: {title}")
        return
    await callback.message.edit_text(f"🗑 Карточка удалена: <b>{e(title)}</b>")
    await callback.answer()


@router.callback_query(F.data == "edit:ru")
async def edit_ru(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddCardStates.waiting_edit_ru)
    await callback.message.answer("Напиши новый русский перевод.", reply_markup=kb.menu_only())
    await callback.answer()


@router.message(AddCardStates.waiting_edit_ru)
async def edit_ru_save(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    app_user: User,
) -> None:
    data = await state.get_data()
    card = await CardRepository(session, fsrs).get_by_id(app_user.id, int(data["edit_card_id"]))
    if not card:
        await message.answer("Карточка не найдена.")
        await state.clear()
        return
    await CardRepository(session, fsrs).update_card(card, ru_text=message.text or "")
    await state.clear()
    await message.answer("✅ Перевод обновлен.\n\n" + format_card(card))


@router.callback_query(F.data == "edit:assoc")
async def edit_assoc(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    app_user: User,
) -> None:
    card = await current_edit_card(callback, state, session, app_user)
    if card is None:
        return
    await state.update_data(edit_association_message_id=callback.message.message_id)
    await callback.message.edit_text(
        "🧠 <b>Ассоциация</b>\n\n" + format_card(card),
        reply_markup=kb.edit_association_choice(bool(card.association_text)),
    )
    await callback.answer()


@router.callback_query(F.data == "edit:back")
async def edit_back(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    app_user: User,
) -> None:
    card = await current_edit_card(callback, state, session, app_user)
    if card is None:
        return
    data = await state.get_data()
    await state.set_state(None)
    await callback.message.edit_text(
        "Что редактируем?\n\n" + format_card(card),
        reply_markup=kb.edit_card(dictionary_return=has_dictionary_return(data)),
    )
    await callback.answer()


@router.callback_query(F.data == "edit:assoc_manual")
async def edit_assoc_manual(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    app_user: User,
) -> None:
    card = await current_edit_card(callback, state, session, app_user)
    if card is None:
        return
    await state.set_state(AddCardStates.waiting_edit_association)
    await state.update_data(edit_association_message_id=callback.message.message_id)
    await callback.message.edit_text(
        "✍️ Напиши новую ассоциацию одной строкой.\n\n" + format_card(card),
        reply_markup=kb.menu_only(),
    )
    await callback.answer()


@router.message(AddCardStates.waiting_edit_association)
async def edit_assoc_save(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    app_user: User,
) -> None:
    data = await state.get_data()
    card = await CardRepository(session, fsrs).get_by_id(app_user.id, int(data["edit_card_id"]))
    if not card:
        await message.answer("Карточка не найдена.")
        await state.clear()
        return
    raw = clean_text(message.text or "")
    association = None if raw.casefold() in {"без", "-", "нет"} else raw
    await save_edited_association(
        message,
        state,
        session,
        card,
        association_text=association,
        edit_message_id=data.get("edit_association_message_id"),
    )


@router.callback_query(F.data == "edit:assoc_generate")
async def edit_assoc_generate(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    app_user: User,
) -> None:
    card = await current_edit_card(callback, state, session, app_user)
    if card is None:
        return
    settings = current_settings()
    try:
        service = OpenAIService(settings)
    except RuntimeError:
        await state.set_state(AddCardStates.waiting_edit_association)
        await state.update_data(edit_association_message_id=callback.message.message_id)
        await callback.message.edit_text(
            "OpenAI API не настроен. Напиши ассоциацию вручную.\n\n" + format_card(card),
            reply_markup=kb.menu_only(),
        )
        await callback.answer()
        return

    await callback.answer("Генерирую...")
    try:
        result = await service.generate_associations(
            en_text=card.en_text,
            ru_text=card.ru_text,
            style=app_user.association_style,  # type: ignore[arg-type]
        )
    except Exception as exc:
        await log_usage(
            session,
            app_user.id,
            request_type="association",
            usage=TokenUsage(model=settings.openai_association_model),
            status="error",
            error_message=str(exc),
        )
        await state.set_state(AddCardStates.waiting_edit_association)
        await state.update_data(edit_association_message_id=callback.message.message_id)
        await callback.message.edit_text(
            "Не получилось сгенерировать. Напиши ассоциацию вручную.\n\n" + format_card(card),
            reply_markup=kb.menu_only(),
        )
        return

    await log_usage(session, app_user.id, "association", result.usage)
    if not result.variants:
        await callback.message.edit_text(
            "Не получилось сгенерировать варианты без исходного слова. Попробуй еще раз.\n\n"
            + format_card(card),
            reply_markup=kb.edit_association_choice(bool(card.association_text)),
        )
        return
    await state.update_data(edit_association_variants=result.variants)
    text = "\n".join(f"{idx + 1}. {e(value)}" for idx, value in enumerate(result.variants))
    await callback.message.edit_text(
        f"✨ Варианты ассоциаций:\n\n{text}\n\nВыбери одну или сгенерируй еще.",
        reply_markup=kb.edit_association_variants(result.variants, bool(card.association_text)),
    )


@router.callback_query(F.data.startswith("edit:assoc_pick:"))
async def edit_assoc_pick(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    app_user: User,
) -> None:
    idx = int(callback.data.rsplit(":", 1)[1])
    data = await state.get_data()
    variants = data.get("edit_association_variants", [])
    if idx >= len(variants):
        await callback.answer("Вариант не найден", show_alert=True)
        return
    card = await current_edit_card(callback, state, session, app_user)
    if card is None:
        return
    await save_edited_association(
        callback.message,
        state,
        session,
        card,
        association_text=variants[idx],
        edit=True,
    )
    await callback.answer()


@router.callback_query(F.data == "edit:assoc_remove")
async def edit_assoc_remove(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    app_user: User,
) -> None:
    card = await current_edit_card(callback, state, session, app_user)
    if card is None:
        return
    await save_edited_association(
        callback.message,
        state,
        session,
        card,
        association_text=None,
        edit=True,
    )
    await callback.answer()


async def current_edit_card(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    app_user: User,
) -> Card | None:
    data = await state.get_data()
    card_id = data.get("edit_card_id")
    if card_id is None:
        await callback.answer("Карточка не выбрана", show_alert=True)
        return None
    card = await CardRepository(session, fsrs).get_by_id(app_user.id, int(card_id))
    if not card:
        await callback.answer("Карточка не найдена", show_alert=True)
        await state.clear()
        return None
    return card


async def save_edited_association(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    card: Card,
    association_text: str | None,
    edit: bool = False,
    edit_message_id: int | None = None,
) -> None:
    data = await state.get_data()
    await CardRepository(session, fsrs).update_card(
        card,
        association_text=association_text,
        association_enabled=bool(association_text),
    )
    await state.set_state(None)
    await state.update_data(edit_card_id=card.id)
    text = (
        "✅ Ассоциация обновлена.\n\n"
        if association_text
        else "✅ Ассоциация убрана.\n\n"
    ) + format_card(card)
    markup = kb.edit_card(dictionary_return=has_dictionary_return(data))
    if edit_message_id is not None:
        await message.bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=edit_message_id,
            text=text,
            reply_markup=markup,
        )
    elif edit:
        await message.edit_text(text, reply_markup=markup)
    else:
        await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "card:cancel")
async def cancel_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()


@router.message(F.text.in_({kb.BTN_REVIEW, "/review"}))
@router.message(Command("review"))
async def review_entry(message: Message, state: FSMContext) -> None:
    await state.clear()
    await show_review_mode_menu(message, "normal")


@router.message(F.text.in_({kb.BTN_ASSOC_REVIEW, "/assoc"}))
@router.message(Command("assoc"))
async def assoc_review_entry(message: Message, state: FSMContext) -> None:
    await state.clear()
    await show_review_mode_menu(message, "association")


@router.message(F.text.in_({kb.BTN_REVIEW_RANDOM, "/review_random"}))
@router.message(Command("review_random"))
async def review_random_entry(message: Message, state: FSMContext) -> None:
    await state.clear()
    await ask_review_size(message, NORMAL_RANDOM_MODE)


@router.message(F.text.in_({kb.BTN_ASSOC_RANDOM, "/assoc_random"}))
@router.message(Command("assoc_random"))
async def assoc_random_entry(message: Message, state: FSMContext) -> None:
    await state.clear()
    await ask_review_size(message, ASSOCIATION_RANDOM_MODE)


async def show_review_mode_menu(message: Message, kind: str, edit: bool = False) -> None:
    if kind == "association":
        text = (
            "🧠 <b>Ассоциации</b>\n\n"
            "FSRS — умный подбор по расписанию.\n"
            "Рандом — случайные карточки без влияния на FSRS."
        )
    else:
        text = (
            "🔁 <b>Повторение</b>\n\n"
            "FSRS — умный подбор по расписанию.\n"
            "Рандом — случайные карточки без влияния на FSRS."
        )
    if edit:
        await message.edit_text(text, reply_markup=kb.review_mode_menu(kind))
    else:
        await message.answer(text, reply_markup=kb.review_mode_menu(kind))


async def ask_review_size(message: Message, mode: str, edit: bool = False) -> None:
    text = review_size_text(mode)
    if edit:
        await message.edit_text(text, reply_markup=kb.review_size(mode))
    else:
        await message.answer(text, reply_markup=kb.review_size(mode))


def review_size_text(mode: str) -> str:
    title = review_mode_title(mode)
    text = f"{title}\n\nСколько карточек взять?"
    if is_random_review_mode(mode):
        text += (
            "\n\nОценки Again / Hard / Good / Easy только переключают карточки "
            "и не влияют на будущие подборы."
        )
    return text


def review_mode_title(mode: str) -> str:
    labels = {
        NORMAL_MODE: "🔁 <b>Повторение FSRS</b>",
        ASSOCIATION_MODE: "🧠 <b>Ассоциации FSRS</b>",
        NORMAL_RANDOM_MODE: "🎲 <b>Повторение рандом</b>",
        ASSOCIATION_RANDOM_MODE: "🎲 <b>Ассоциации рандом</b>",
    }
    return labels.get(mode, "🔁 <b>Повторение</b>")


def empty_review_text(mode: str) -> str:
    if is_random_review_mode(mode):
        if is_association_review_mode(mode):
            return "Пока нет карточек с ассоциациями для случайной тренировки."
        return "Пока нет карточек для случайной тренировки."
    return "На сейчас нет карточек к повторению."


async def review_cards(
    session: AsyncSession,
    user_id: int,
    mode: str,
    limit: int,
) -> list[Card]:
    repo = CardRepository(session, fsrs)
    base_mode = review_base_mode(mode)
    if is_random_review_mode(mode):
        return await repo.random_cards(user_id, base_mode, limit)
    due = await repo.due_cards(user_id, base_mode, limit)
    return [card for card, _state in due]


def review_base_mode(mode: str) -> str:
    if is_association_review_mode(mode):
        return ASSOCIATION_MODE
    return NORMAL_MODE


def is_association_review_mode(mode: str) -> bool:
    return mode in ASSOCIATION_REVIEW_MODES


def is_random_review_mode(mode: str) -> bool:
    return mode in RANDOM_REVIEW_MODES


@router.callback_query(F.data.startswith("review:start:"))
async def review_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    app_user: User,
) -> None:
    _, _, mode, limit_text = callback.data.split(":")
    if mode not in REVIEW_MODES:
        await callback.answer("Неизвестный режим", show_alert=True)
        return
    cards = await review_cards(session, app_user.id, mode, int(limit_text))
    if not cards:
        await callback.message.edit_text(
            empty_review_text(mode),
            reply_markup=kb.menu_only(),
        )
        await callback.answer()
        return
    await state.set_state(ReviewStates.reviewing)
    await state.update_data(
        review_mode=mode,
        review_queue=[card.id for card in cards],
        review_index=0,
    )
    await callback.message.edit_reply_markup(reply_markup=None)
    await send_review_front(callback.message, state, session, app_user)
    await callback.answer()


async def send_review_front(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    app_user: User,
) -> None:
    data = await state.get_data()
    queue = data["review_queue"]
    idx = data["review_index"]
    if idx >= len(queue):
        await state.clear()
        await send_main_menu(message, disable_notification=True, reset_reply_keyboard=True)
        return
    card = await CardRepository(session, fsrs).get_by_id(app_user.id, int(queue[idx]))
    if not card:
        await state.update_data(review_index=idx + 1)
        await send_review_front(message, state, session, app_user)
        return
    mode = data["review_mode"]
    front = format_review_front(card, mode)
    await state.update_data(current_card_id=card.id, review_stage="front")
    await message.answer(
        format_review_card_text(idx, len(queue), front),
        reply_markup=kb.review_show_answer_keyboard(),
        disable_notification=True,
    )


@router.callback_query(F.data == "review:show")
async def review_show_answer(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    app_user: User,
) -> None:
    await show_review_answer(callback.message, state, session, app_user)
    await callback.answer()


@router.message(ReviewStates.reviewing, F.text == kb.BTN_SHOW_ANSWER)
async def review_show_answer_by_button(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    app_user: User,
) -> None:
    await show_review_answer(message, state, session, app_user)


async def show_review_answer(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    app_user: User,
) -> bool:
    data = await state.get_data()
    if not data.get("current_card_id"):
        await state.clear()
        await send_main_menu(message, disable_notification=True)
        return False
    if data.get("review_stage") == "answer":
        return False
    card = await CardRepository(session, fsrs).get_by_id(app_user.id, int(data["current_card_id"]))
    if not card:
        await message.answer(
            "Карточка не найдена.",
            reply_markup=kb.review_show_answer_keyboard(),
            disable_notification=True,
        )
        return False
    mode = str(data["review_mode"])
    if not is_association_review_mode(mode):
        answer = f"🇷🇺 <b>{e(card.ru_text)}</b>"
    else:
        answer = f"🇬🇧 <b>{e(card.en_text)}</b>"
    queue = data["review_queue"]
    idx = int(data["review_index"])
    await state.update_data(review_stage="answer")
    await message.answer(
        format_review_card_text(idx, len(queue), answer),
        reply_markup=kb.review_rating_keyboard(),
        disable_notification=True,
    )
    return True


@router.callback_query(F.data.startswith("review:rate:"))
async def review_rate(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    app_user: User,
) -> None:
    rating = callback.data.rsplit(":", 1)[1]
    data = await state.get_data()
    is_random = is_random_review_mode(str(data.get("review_mode", "")))
    saved = await rate_review_card(callback.message, state, session, app_user, rating)
    await callback.answer("Оценка сохранена" if saved and not is_random else None)


@router.message(ReviewStates.reviewing, F.text.in_(set(kb.RATING_BUTTON_TO_KEY)))
async def review_rate_by_button(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    app_user: User,
) -> None:
    rating = kb.RATING_BUTTON_TO_KEY[message.text]
    await rate_review_card(message, state, session, app_user, rating)


async def rate_review_card(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    app_user: User,
    rating: str,
) -> bool:
    data = await state.get_data()
    if data.get("review_stage") != "answer":
        await message.answer(
            "Сначала открой перевод.",
            reply_markup=kb.review_show_answer_keyboard(),
            disable_notification=True,
        )
        return False
    if not data.get("current_card_id"):
        await state.clear()
        await send_main_menu(message, disable_notification=True)
        return False
    card = await CardRepository(session, fsrs).get_by_id(app_user.id, int(data["current_card_id"]))
    if not card:
        await message.answer(
            "Карточка не найдена.",
            reply_markup=kb.review_show_answer_keyboard(),
            disable_notification=True,
        )
        return False
    mode = str(data["review_mode"])
    if not is_random_review_mode(mode):
        repo = CardRepository(session, fsrs)
        await repo.review_card(
            app_user,
            card,
            review_base_mode(mode),
            rating,
            desired_retention=app_user.fsrs_retention,
        )
        await session.commit()
    await state.update_data(review_index=int(data["review_index"]) + 1)
    await send_review_front(message, state, session, app_user)
    return True


@router.message(ReviewStates.reviewing)
async def review_unexpected_message(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if data.get("review_stage") == "answer":
        await message.answer(
            "Выбери оценку кнопкой ниже.",
            reply_markup=kb.review_rating_keyboard(),
            disable_notification=True,
        )
    else:
        await message.answer(
            "Нажми «Показать перевод».",
            reply_markup=kb.review_show_answer_keyboard(),
            disable_notification=True,
        )


@router.message(F.text.in_({kb.BTN_SETTINGS, "/settings"}))
@router.message(Command("settings"))
async def settings_entry(message: Message, state: FSMContext, app_user: User) -> None:
    await state.clear()
    await show_settings(message, app_user)


async def show_settings(message: Message, app_user: User, edit: bool = False) -> None:
    text = settings_text(app_user.association_style, app_user.fsrs_retention)
    if edit:
        await message.edit_text(text, reply_markup=kb.settings_menu())
    else:
        await message.answer(text, reply_markup=kb.settings_menu())


def settings_text(association_style: str, fsrs_retention: float) -> str:
    return (
        "⚙️ <b>Настройки</b>\n\n"
        f"🧠 Ассоциации: <b>{association_style_label(association_style)}</b>\n"
        f"🔁 FSRS: <b>{retention_label(fsrs_retention)}</b>"
    )


@router.callback_query(F.data == "settings:back")
async def settings_back(callback: CallbackQuery, app_user: User) -> None:
    await callback.message.edit_text(
        settings_text(app_user.association_style, app_user.fsrs_retention),
        reply_markup=kb.settings_menu(),
    )
    await callback.answer()


@router.callback_query(F.data == "settings:assoc")
async def settings_assoc(callback: CallbackQuery, app_user: User) -> None:
    await callback.message.edit_text(
        association_settings_text(app_user.association_style),
        reply_markup=kb.settings_association_menu(app_user.association_style),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("settings:style:"))
async def settings_style(
    callback: CallbackQuery,
    session: AsyncSession,
    app_user: User,
) -> None:
    style = callback.data.rsplit(":", 1)[1]
    if style not in {"neutral", "funny", "absurd"}:
        await callback.answer("Неизвестный стиль", show_alert=True)
        return
    if app_user.association_style == style:
        await callback.answer("Уже выбран")
        return
    await UserRepository(session, current_settings().admin_tg_ids).set_association_style(
        app_user,
        style,  # type: ignore[arg-type]
    )
    await callback.message.edit_text(
        association_settings_text(style),
        reply_markup=kb.settings_association_menu(style),
    )
    await callback.answer("Стиль обновлен")


@router.callback_query(F.data == "settings:fsrs")
async def settings_fsrs(callback: CallbackQuery, app_user: User) -> None:
    await callback.message.edit_text(
        fsrs_settings_text(app_user.fsrs_retention),
        reply_markup=kb.settings_fsrs_menu(app_user.fsrs_retention),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("settings:retention:"))
async def settings_retention(
    callback: CallbackQuery,
    session: AsyncSession,
    app_user: User,
) -> None:
    retention = float(callback.data.rsplit(":", 1)[1])
    if retention not in {0.85, 0.90, 0.95}:
        await callback.answer("Неизвестный режим", show_alert=True)
        return
    if round(app_user.fsrs_retention, 2) == retention:
        await callback.answer("Уже выбран")
        return
    await UserRepository(session, current_settings().admin_tg_ids).set_fsrs_retention(
        app_user,
        retention,
    )
    await callback.message.edit_text(
        fsrs_settings_text(retention),
        reply_markup=kb.settings_fsrs_menu(retention),
    )
    await callback.answer("FSRS обновлен")


def association_style_label(style: str) -> str:
    labels = {"neutral": "нейтральный", "funny": "забавный", "absurd": "абсурдный"}
    return labels.get(style, style)


def association_settings_text(style: str) -> str:
    return (
        "🧠 <b>Стиль ассоциаций</b>\n\n"
        "Выбери тон генерации.\n\n"
        f"Сейчас: <b>{association_style_label(style)}</b>"
    )


def fsrs_settings_text(retention: float) -> str:
    return (
        "🔁 <b>FSRS retention</b>\n\n"
        "Выбери частоту повторений.\n\n"
        "85% — легче, интервалы длиннее\n"
        "90% — баланс нагрузки\n"
        "95% — чаще, память крепче\n\n"
        f"Сейчас: <b>{retention_label(retention)}</b>"
    )


def retention_label(retention: float) -> str:
    labels = {
        0.85: "85% легкий",
        0.90: "90% баланс",
        0.95: "95% интенсивный",
    }
    return labels.get(round(retention, 2), f"{retention_percent(retention)}%")


def retention_percent(retention: float) -> int:
    return round(retention * 100)


@router.message(F.text.in_({kb.BTN_DICTIONARY, "/dictionary"}))
@router.message(Command("dictionary"))
async def dictionary_entry(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    app_user: User,
) -> None:
    await state.clear()
    await render_dictionary_page(message, session, app_user, offset=0)


@router.callback_query(F.data.startswith("dict:page:"))
async def dictionary_page_callback(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    app_user: User,
) -> None:
    await state.clear()
    offset = int(callback.data.rsplit(":", 1)[1])
    await render_dictionary_page(callback.message, session, app_user, offset=offset, edit=True)
    await callback.answer()


@router.callback_query(F.data.startswith("dict:search_page:"))
async def dictionary_search_page_callback(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    app_user: User,
) -> None:
    data = await state.get_data()
    query = data.get("dictionary_search_query")
    if not query:
        await callback.answer("Поисковый запрос потерялся. Запусти поиск заново.", show_alert=True)
        return
    offset = int(callback.data.rsplit(":", 1)[1])
    await render_dictionary_page(
        callback.message,
        session,
        app_user,
        offset=offset,
        edit=True,
        search_query=query,
    )
    await callback.answer()


@router.callback_query(F.data == "dict:return")
async def dictionary_return_callback(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    app_user: User,
) -> None:
    data = await state.get_data()
    offset, query = dictionary_return_context(data)
    await state.clear()
    if query:
        await state.update_data(dictionary_search_query=query)
    await render_dictionary_page(
        callback.message,
        session,
        app_user,
        offset=offset,
        edit=True,
        search_query=query,
    )
    await callback.answer()


@router.callback_query(F.data == "dict:search")
async def dictionary_search_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(DictionaryStates.waiting_search_query)
    await state.update_data(dictionary_search_message_id=callback.message.message_id)
    await callback.message.edit_text(
        "🔎 Напиши слово или часть перевода для поиска.",
        reply_markup=kb.dictionary_search_prompt(),
    )
    await callback.answer()


@router.callback_query(F.data == "dict:noop")
async def dictionary_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.message(DictionaryStates.waiting_search_query)
async def dictionary_search_query(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    app_user: User,
) -> None:
    query = clean_text(message.text or "")
    if not query:
        await message.answer("Напиши непустой поисковый запрос.")
        return
    await state.update_data(dictionary_search_query=query)
    await state.set_state(None)
    data = await state.get_data()
    await render_dictionary_page(
        message,
        session,
        app_user,
        offset=0,
        search_query=query,
        edit_message_id=data.get("dictionary_search_message_id"),
    )


async def render_dictionary_page(
    message: Message,
    session: AsyncSession,
    app_user: User,
    offset: int,
    edit: bool = False,
    search_query: str | None = None,
    edit_message_id: int | None = None,
) -> None:
    repo = CardRepository(session, fsrs)
    normalized_offset = max(offset, 0)
    if search_query:
        total = await repo.count_search_cards(app_user.id, search_query)
        cards = await repo.search_cards(
            app_user.id,
            search_query,
            limit=DICTIONARY_PAGE_SIZE,
            offset=normalized_offset,
        )
    else:
        total = await repo.count_cards(app_user.id)
        cards = await repo.list_cards(
            app_user.id,
            limit=DICTIONARY_PAGE_SIZE,
            offset=normalized_offset,
        )

    if total and normalized_offset >= total:
        normalized_offset = max(total - DICTIONARY_PAGE_SIZE, 0)
        await render_dictionary_page(
            message,
            session,
            app_user,
            offset=normalized_offset,
            edit=edit,
            search_query=search_query,
            edit_message_id=edit_message_id,
        )
        return

    page = normalized_offset // DICTIONARY_PAGE_SIZE + 1 if total else 0
    pages = (total + DICTIONARY_PAGE_SIZE - 1) // DICTIONARY_PAGE_SIZE if total else 0
    if search_query:
        title = f"📚 <b>Словарь</b>\n🔎 Поиск: <b>{e(search_query)}</b>"
        empty_text = "Ничего не нашел."
    else:
        title = "📚 <b>Словарь</b>"
        empty_text = "Словарь пока пустой."
    text = f"{title}\nКарточек: {total}\nСтраница: {page}/{pages}"
    if not total:
        text += f"\n\n{empty_text}"

    ratings = await repo.latest_review_ratings(
        app_user.id,
        [card.id for card in cards],
        mode=NORMAL_MODE,
    )
    markup = kb.dictionary_cards(
        [(card.id, card.en_text, ratings.get(card.id)) for card in cards],
        offset=normalized_offset,
        total=total,
        page_size=DICTIONARY_PAGE_SIZE,
        search=bool(search_query),
    )
    if edit:
        await message.edit_text(text, reply_markup=markup)
    elif edit_message_id is not None:
        await message.bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=edit_message_id,
            text=text,
            reply_markup=markup,
        )
    else:
        await message.answer(text, reply_markup=markup)


@router.message(F.text.in_({kb.BTN_IMPORT, "/import"}))
@router.message(Command("import"))
async def import_entry(message: Message, state: FSMContext) -> None:
    await begin_import(message, state)


async def begin_import(message: Message, state: FSMContext, edit: bool = False) -> None:
    await state.clear()
    await state.set_state(ImportStates.waiting_text)
    text = (
        "📥 <b>Импорт</b>\n\n"
        "Пришли текст (для стабильности не более 100 слов за раз) "
        "или файл .xml/.pdf/.txt до 1 МБ. "
        "Я вытащу пары EN/RU и предложу переводы там, где их нет."
    )
    if edit:
        await message.edit_text(text, reply_markup=kb.menu_only())
    else:
        await message.answer(text, reply_markup=kb.menu_only())


@router.message(ImportStates.waiting_text, F.document)
async def import_document(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    app_user: User,
    is_admin: bool,
) -> None:
    settings = current_settings()
    document = message.document
    if document is None:
        return

    filename = document.file_name or ""
    normalized_filename = filename.casefold()
    if not normalized_filename.endswith((".txt", ".xml", ".pdf")):
        await message.answer("Пока принимаю только файлы .xml, .pdf и .txt до 1 МБ.")
        return
    if document.file_size and document.file_size > settings.import_max_file_bytes:
        await message.answer(
            "Файл слишком большой для MVP-импорта. "
            f"Лимит: {settings.import_max_file_bytes / 1024 / 1024:.1f} МБ."
        )
        return

    buffer = BytesIO()
    try:
        await message.bot.download(document, destination=buffer)
        raw_file = buffer.getvalue()
        text = (
            extract_pdf_text(raw_file)
            if normalized_filename.endswith(".pdf")
            else decode_import_file(raw_file)
        )
    except Exception as exc:
        error_text = "Не получилось прочитать файл."
        if is_admin:
            error_text += f"\n\nТехнически: <code>{e(short_error(exc))}</code>"
        await message.answer(error_text)
        return

    await process_import_text(
        message,
        state,
        session,
        app_user,
        is_admin,
        text,
        source_label=f"файл {filename}",
    )


@router.message(ImportStates.waiting_text, F.text)
async def import_text(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    app_user: User,
    is_admin: bool,
) -> None:
    await process_import_text(
        message,
        state,
        session,
        app_user,
        is_admin,
        message.text or "",
        source_label="сообщение",
    )


async def process_import_text(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    app_user: User,
    is_admin: bool,
    text: str,
    source_label: str,
) -> None:
    settings = current_settings()

    local_candidates = parse_local_import(text)
    if local_candidates is not None:
        await show_import_preview(
            message,
            state,
            local_candidates,
            source_note=f"Разобрал {source_label} локально, без OpenAI.",
        )
        return

    try:
        service = OpenAIService(settings)
    except RuntimeError:
        await state.clear()
        await message.answer("OpenAI API не настроен, импорт через LLM пока недоступен.")
        return
    thinking = await message.answer("Разбираю импорт через OpenAI...")
    chunks = split_import_text(
        text,
        chunk_lines=settings.openai_import_chunk_lines,
        chunk_chars=settings.openai_import_chunk_chars,
    )
    candidates: list[ImportCandidate] = []
    try:
        for idx, chunk in enumerate(chunks, start=1):
            if len(chunks) > 1:
                await thinking.edit_text(
                    f"Разбираю импорт через OpenAI... пачка {idx}/{len(chunks)}"
                )
            parsed = await service.parse_import_text(chunk)
            candidates.extend(parsed.candidates)
            await log_usage(session, app_user.id, "import_parse", parsed.usage)
    except Exception as exc:
        await log_usage(
            session,
            app_user.id,
            request_type="import_parse",
            usage=TokenUsage(model=settings.openai_import_model),
            status="error",
            error_message=str(exc),
        )
        await state.clear()
        error_text = "Не получилось разобрать импорт. Попробуй более простой список."
        if is_admin:
            error_text += f"\n\nТехнически: <code>{e(short_error(exc))}</code>"
        await thinking.edit_text(error_text)
        return

    candidates = deduplicate_candidates(candidates)
    if not candidates:
        await state.clear()
        await thinking.edit_text("Не нашел карточек для импорта.")
        return

    await show_import_preview(
        thinking,
        state,
        candidates,
        source_note=f"Разобрал {source_label} через OpenAI пачками: {len(chunks)}.",
        edit=True,
    )


async def show_import_preview(
    message: Message,
    state: FSMContext,
    candidates: list[ImportCandidate],
    source_note: str,
    edit: bool = False,
) -> None:
    settings = current_settings()
    preview_lines = []
    payload = []
    preview_limit = settings.import_preview_limit
    for idx, item in enumerate(candidates[:preview_limit], start=1):
        ru = item.ru_text or "нужен перевод"
        marker = " 🤖" if item.needs_translation else ""
        preview_lines.append(f"{idx}. <b>{e(item.en_text)}</b> — <b>{e(ru)}</b>{marker}")
        payload.append({"en": item.en_text, "ru": item.ru_text or ""})
    for item in candidates[preview_limit:]:
        payload.append({"en": item.en_text, "ru": item.ru_text or ""})
    await state.update_data(import_cards=payload)
    hidden_count = max(len(candidates) - preview_limit, 0)
    hidden_text = f"\n\n...и еще {hidden_count} карточек." if hidden_count else ""
    text = (
        f"{source_note}\n"
        f"Нашел карточки: {len(candidates)}\n\n"
        + "\n".join(preview_lines)
        + hidden_text
        + "\n\n🤖 — перевод предложен моделью. Импортировать?"
    )
    if edit:
        await message.edit_text(text, reply_markup=kb.import_confirm())
    else:
        await message.answer(text, reply_markup=kb.import_confirm())


@router.callback_query(F.data == "import:confirm")
async def import_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    app_user: User,
) -> None:
    data = await state.get_data()
    repo = CardRepository(session, fsrs)
    created = 0
    skipped_items: list[tuple[str, str]] = []
    for item in data.get("import_cards", []):
        en_text = clean_text(item.get("en") or "")
        ru_text = clean_text(item.get("ru") or "")
        if not ru_text:
            skipped_items.append((en_text or "без английского слова", "нет перевода"))
            continue
        result = await repo.create_card(app_user, en_text, ru_text)
        if result.created:
            created += 1
        else:
            skipped_items.append((result.card.en_text, "уже есть в словаре"))
    await state.clear()
    text = format_import_result(created, skipped_items)
    await callback.message.edit_text(text, reply_markup=kb.import_done_actions())
    await callback.answer()


@router.callback_query(F.data == "import:manual")
async def import_manual(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ImportStates.waiting_manual_pairs)
    await callback.message.answer(
        "✍️ Пришли исправленный список парами, по одной карточке на строку:\n\n"
        "<code>stubborn - упрямый</code>\n"
        "<code>beyond - вне, за</code>"
    )
    await callback.answer()


@router.message(ImportStates.waiting_manual_pairs)
async def import_manual_pairs(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    app_user: User,
) -> None:
    lines = [clean_text(line) for line in (message.text or "").splitlines() if clean_text(line)]
    pairs = []
    skipped_items: list[tuple[str, str]] = []
    for line in lines:
        pair = parse_pair(line)
        if pair is None:
            skipped_items.append((line, "не удалось разобрать пару"))
            continue
        pairs.append(pair)
    if not pairs:
        await message.answer("Не увидел пар. Формат: <code>word - перевод</code>")
        return
    repo = CardRepository(session, fsrs)
    created = 0
    for en_text, ru_text in pairs:
        result = await repo.create_card(app_user, en_text, ru_text)
        if result.created:
            created += 1
        else:
            skipped_items.append((result.card.en_text, "уже есть в словаре"))
    await state.clear()
    await message.answer(
        format_import_result(created, skipped_items),
        reply_markup=kb.import_done_actions(),
    )


@router.callback_query(F.data == "import:cancel")
async def import_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer("Ок, импорт отменен.")
    await callback.answer()


@router.message(Command("allow"))
async def admin_allow(
    message: Message,
    session: AsyncSession,
    is_admin: bool,
) -> None:
    if not is_admin:
        return
    target = first_int(message.text or "")
    if target is None:
        await message.answer("Использование: <code>/allow 123456789</code>")
        return
    await UserRepository(session, current_settings().admin_tg_ids).allow_user(
        target,
        message.from_user.id if message.from_user else None,
    )
    await message.answer(f"✅ Пользователь <code>{target}</code> добавлен.")


@router.message(Command("deny"))
async def admin_deny(
    message: Message,
    session: AsyncSession,
    is_admin: bool,
) -> None:
    if not is_admin:
        return
    target = first_int(message.text or "")
    if target is None:
        await message.answer("Использование: <code>/deny 123456789</code>")
        return
    removed = await UserRepository(session, current_settings().admin_tg_ids).deny_user(target)
    await message.answer("✅ Удален из allow list." if removed else "Такого пользователя не было.")


@router.message(Command("stats"))
async def admin_stats(message: Message, session: AsyncSession, is_admin: bool) -> None:
    if not is_admin:
        return
    stats = await StatsRepository(session).overview()
    cost = stats["api_cost_usd"]
    cost_text = "не настроено" if cost is None else f"${cost:.4f}"
    await message.answer(
        "📊 Статистика\n\n"
        f"Пользователи: {stats['users']}\n"
        f"Allow list: {stats['allowed']}\n"
        f"Карточки: {stats['cards']}\n"
        f"С ассоциациями: {stats['association_cards']}\n"
        f"Повторения: {stats['reviews']}\n"
        f"OpenAI вызовы: {stats['api_calls']}\n"
        f"OpenAI токены: {stats['api_tokens']}\n"
        f"Оценка стоимости: {cost_text}"
    )


async def log_usage(
    session: AsyncSession,
    user_id: int | None,
    request_type: str,
    usage: TokenUsage,
    status: str = "ok",
    error_message: str | None = None,
) -> None:
    settings = current_settings()
    await UsageRepository(session).log(
        user_id=user_id,
        model=usage.model or settings.openai_model,
        request_type=request_type,
        status=status,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
        estimated_cost_usd=usage.estimated_cost_usd,
        error_message=error_message,
    )


def parse_pair(text: str) -> tuple[str, str] | None:
    if "\n" in text:
        parts = [clean_text(part) for part in text.splitlines() if clean_text(part)]
        if len(parts) == 2:
            return orient_pair(parts[0], parts[1])
    for delimiter in (" - ", " — ", " – ", " = ", " : ", "\t"):
        if delimiter in text:
            left, right = text.split(delimiter, 1)
            if left.strip() and right.strip():
                return orient_pair(left, right)
    return None


def parse_local_import(text: str) -> list[ImportCandidate] | None:
    xml_candidates = parse_xmlish_import(text)
    if xml_candidates:
        return xml_candidates

    lines = [clean_text(line) for line in text.splitlines() if clean_text(line)]
    if not lines:
        return []
    pairs = [parse_pair(line) for line in lines]
    if not pairs or any(pair is None for pair in pairs):
        return None
    return [
        ImportCandidate(en_text=en_text, ru_text=ru_text, needs_translation=False)
        for en_text, ru_text in pairs
        if en_text and ru_text
    ]


def parse_xmlish_import(text: str) -> list[ImportCandidate]:
    candidates: list[ImportCandidate] = []
    for match in XMLISH_PAIR_RE.finditer(text):
        en_text = clean_xml_value(match.group("en"))
        ru_text = clean_xml_value(match.group("ru"))
        if en_text and ru_text:
            candidates.append(
                ImportCandidate(en_text=en_text, ru_text=ru_text, needs_translation=False)
            )
    return candidates


def orient_pair(left: str, right: str) -> tuple[str, str]:
    first = clean_text(left)
    second = clean_text(right)
    if has_cyrillic(first) and has_latin(second):
        return second, first
    return first, second


def clean_xml_value(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return clean_text(html.unescape(without_tags))


def has_latin(value: str) -> bool:
    return LATIN_RE.search(value) is not None


def has_cyrillic(value: str) -> bool:
    return CYRILLIC_RE.search(value) is not None


def decode_import_file(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def extract_pdf_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("Для чтения PDF установи зависимость pypdf.") from exc

    reader = PdfReader(BytesIO(data))
    page_texts = [page.extract_text() or "" for page in reader.pages]
    text = "\n".join(page_texts).strip()
    if not text:
        raise RuntimeError(
            "В PDF не найден текстовый слой. Сканированные PDF пока не поддерживаются."
        )
    return text


def split_import_text(text: str, chunk_lines: int, chunk_chars: int = 6000) -> list[str]:
    lines = [line for line in text.splitlines() if clean_text(line)]
    if not lines:
        stripped = clean_text(text)
        return [stripped] if stripped else []
    if len(lines) == 1 and len(lines[0]) > chunk_chars:
        stripped = lines[0]
        return [
            stripped[idx : idx + chunk_chars]
            for idx in range(0, len(stripped), max(chunk_chars, 1))
        ]
    chunk_size = max(chunk_lines, 1)
    return [
        "\n".join(lines[idx : idx + chunk_size])
        for idx in range(0, len(lines), chunk_size)
    ]


def deduplicate_candidates(candidates: list[ImportCandidate]) -> list[ImportCandidate]:
    seen: set[str] = set()
    result: list[ImportCandidate] = []
    for candidate in candidates:
        key = normalize_english(candidate.en_text)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return result


def format_import_result(created: int, skipped_items: list[tuple[str, str]]) -> str:
    skipped_count = len(skipped_items)
    lines = [
        "✅ Импорт завершен.",
        f"Добавлено: {created}",
        f"Пропущено: {skipped_count}",
    ]
    if skipped_items:
        lines.append("")
        lines.append("Почему пропущено:")
        for idx, (word, reason) in enumerate(
            skipped_items[:IMPORT_SKIP_DETAILS_LIMIT],
            start=1,
        ):
            lines.append(f"{idx}. <b>{e(word)}</b> — {e(reason)}")
        hidden_count = skipped_count - IMPORT_SKIP_DETAILS_LIMIT
        if hidden_count > 0:
            lines.append(f"...и еще {hidden_count}.")
    return "\n".join(lines)


def format_card(card: Card) -> str:
    lines = [f"🇬🇧 <b>{e(card.en_text)}</b>", f"🇷🇺 <b>{e(card.ru_text)}</b>"]
    if card.association_enabled and card.association_text:
        lines.append(f"🧠 {e(card.association_text)}")
    return "\n".join(lines)


def format_review_front(card: Card, mode: str) -> str:
    if not is_association_review_mode(mode):
        return f"🇬🇧 <b>{e(card.en_text)}</b>"
    return f"🇷🇺 <b>{e(card.ru_text)}</b>\n🧠 {e(card.association_text or '')}"


def format_review_card_text(index: int, total: int, body: str) -> str:
    return f"{index + 1}/{total}\n\n{body}"


def has_dictionary_return(data: dict[str, object]) -> bool:
    return data.get("dictionary_return_offset") is not None


def dictionary_return_context(data: dict[str, object]) -> tuple[int, str | None]:
    offset = int(data.get("dictionary_return_offset") or 0)
    query = data.get("dictionary_return_query") if data.get("dictionary_return_search") else None
    return offset, str(query) if query else None


def first_int(text: str) -> int | None:
    match = re.search(r"\d+", text)
    return int(match.group(0)) if match else None


def e(value: object) -> str:
    return html.escape(str(value))


def short_error(exc: Exception) -> str:
    return str(exc).replace("\n", " ")[:700]


def current_settings() -> Settings:
    if _settings is None:
        raise RuntimeError("Bot settings are not initialized.")
    return _settings


async def is_review_state(state: FSMContext) -> bool:
    return await state.get_state() == ReviewStates.reviewing.state


async def send_main_menu(
    message: Message,
    disable_notification: bool = False,
    reset_reply_keyboard: bool = False,
) -> None:
    if reset_reply_keyboard:
        await clear_reply_keyboard(message, disable_notification=disable_notification)
    await message.answer(
        main_menu_text(),
        reply_markup=kb.start_inline_menu(),
        disable_notification=disable_notification,
    )


async def clear_reply_keyboard(message: Message, disable_notification: bool = False) -> None:
    keyboard_reset = await message.answer(
        "\u2063",
        reply_markup=kb.remove_reply_keyboard(),
        disable_notification=disable_notification,
    )
    await asyncio.sleep(0.35)
    with suppress(TelegramAPIError):
        await keyboard_reset.delete()


def main_menu_text() -> str:
    return (
        "<b>Личный AI-словарь 🇬🇧</b>\n\n"
        "Перевожу слова, храню в виде карточек, добавляю ассоциации, "
        "помогаю повторять по FSRS"
    )
