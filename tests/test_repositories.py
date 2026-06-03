import sqlite3

from sqlalchemy import delete, select

from dictionarybot.db.models import FsrsState, ReviewLog
from dictionarybot.db.repositories import (
    ASSOCIATION_MODE,
    NORMAL_MODE,
    CardRepository,
    UserRepository,
)
from dictionarybot.db.session import Database
from dictionarybot.services.fsrs import FsrsService


def _without_timezone(value):
    return value.replace(tzinfo=None) if value else None


async def test_card_duplicate_and_fsrs_modes() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()

    async with database.session() as session:
        user = await UserRepository(session, admin_tg_ids=[1]).get_or_create(
            telegram_id=1,
            username="admin",
            first_name="Admin",
        )
        cards = CardRepository(session, FsrsService())

        assert user.fsrs_retention == 0.9

        created = await cards.create_card(
            user,
            "stubborn",
            "упрямый",
            "стабильно бурный человек",
        )
        duplicate = await cards.create_card(user, " Stubborn ", "упорный")

        assert created.created is True
        assert duplicate.created is False
        assert duplicate.card.id == created.card.id

        normal_due = await cards.due_cards(user.id, NORMAL_MODE, 25)
        association_due = await cards.due_cards(user.id, ASSOCIATION_MODE, 25)

        assert len(normal_due) == 1
        assert len(association_due) == 1

        await cards.review_card(user, created.card, NORMAL_MODE, "good")
        await cards.delete_card(created.card)
        await session.commit()

        assert await cards.count_cards(user.id) == 0


async def test_user_fsrs_retention_can_be_updated() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()

    async with database.session() as session:
        users = UserRepository(session, admin_tg_ids=[1])
        user = await users.get_or_create(
            telegram_id=1,
            username="admin",
            first_name="Admin",
        )

        await users.set_fsrs_retention(user, 0.95)
        await session.commit()

        reloaded = await users.get_by_telegram_id(1)

        assert reloaded is not None
        assert reloaded.fsrs_retention == 0.95


async def test_user_settings_are_stored_per_user() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()

    async with database.session() as session:
        users = UserRepository(session, admin_tg_ids=[1])
        first = await users.get_or_create(
            telegram_id=1,
            username="first",
            first_name="First",
        )
        second = await users.get_or_create(
            telegram_id=2,
            username="second",
            first_name="Second",
        )

        await users.set_association_style(first, "absurd")
        await users.set_fsrs_retention(first, 0.95)
        await users.set_association_style(second, "neutral")
        await users.set_fsrs_retention(second, 0.85)
        await session.commit()

        reloaded_first = await users.get_by_telegram_id(1)
        reloaded_second = await users.get_by_telegram_id(2)

        assert reloaded_first is not None
        assert reloaded_second is not None
        assert reloaded_first.association_style == "absurd"
        assert reloaded_first.fsrs_retention == 0.95
        assert reloaded_second.association_style == "neutral"
        assert reloaded_second.fsrs_retention == 0.85


async def test_create_schema_adds_fsrs_retention_to_existing_users_table(tmp_path) -> None:
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                telegram_id BIGINT UNIQUE,
                username VARCHAR(255),
                first_name VARCHAR(255),
                association_style VARCHAR(32),
                created_at DATETIME,
                last_seen_at DATETIME
            )
            """
        )
        connection.execute(
            """
            INSERT INTO users (
                telegram_id,
                username,
                first_name,
                association_style,
                created_at,
                last_seen_at
            )
            VALUES (1, 'admin', 'Admin', 'funny', '2026-01-01 00:00:00', '2026-01-01 00:00:00')
            """
        )

    database = Database(f"sqlite+aiosqlite:///{db_path}")
    await database.create_schema()

    async with database.session() as session:
        user = await UserRepository(session, admin_tg_ids=[1]).get_by_telegram_id(1)

        assert user is not None
        assert user.fsrs_retention == 0.9


def test_fsrs_service_uses_scheduler_for_selected_retention() -> None:
    service = FsrsService()

    light = service.scheduler(0.85)
    balanced = service.scheduler(0.9)
    intensive = service.scheduler(0.95)

    assert light.desired_retention == 0.85
    assert balanced.desired_retention == 0.9
    assert intensive.desired_retention == 0.95
    assert service.scheduler(0.85) is light


async def test_fsrs_review_updates_state_and_log_per_mode() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()

    async with database.session() as session:
        user = await UserRepository(session, admin_tg_ids=[1]).get_or_create(
            telegram_id=1,
            username="admin",
            first_name="Admin",
        )
        cards = CardRepository(session, FsrsService())
        created = await cards.create_card(
            user,
            "broad",
            "широкий",
            "брод через широкую реку",
        )
        await session.commit()

        normal_before = await session.scalar(
            select(FsrsState).where(
                FsrsState.card_id == created.card.id,
                FsrsState.mode == NORMAL_MODE,
            )
        )
        association_before = await session.scalar(
            select(FsrsState).where(
                FsrsState.card_id == created.card.id,
                FsrsState.mode == ASSOCIATION_MODE,
            )
        )
        assert normal_before is not None
        assert association_before is not None
        normal_json_before = normal_before.fsrs_card_json
        association_json_before = association_before.fsrs_card_json

        normal_log = await cards.review_card(user, created.card, NORMAL_MODE, "again")
        await session.commit()
        await session.refresh(normal_before)
        await session.refresh(association_before)

        assert normal_log.rating == 1
        assert normal_log.previous_due_at is not None
        assert _without_timezone(normal_log.next_due_at) == _without_timezone(normal_before.due_at)
        assert _without_timezone(normal_before.last_reviewed_at) == _without_timezone(
            normal_log.reviewed_at
        )
        assert normal_before.fsrs_card_json != normal_json_before
        assert association_before.fsrs_card_json == association_json_before
        assert association_before.last_reviewed_at is None

        association_log = await cards.review_card(user, created.card, ASSOCIATION_MODE, "easy")
        await session.commit()
        await session.refresh(association_before)

        logs = (
            await session.scalars(
                select(ReviewLog).where(ReviewLog.card_id == created.card.id).order_by(ReviewLog.id)
            )
        ).all()

        assert association_log.rating == 4
        assert _without_timezone(association_log.next_due_at) == _without_timezone(
            association_before.due_at
        )
        assert _without_timezone(association_before.last_reviewed_at) == _without_timezone(
            association_log.reviewed_at
        )
        assert association_before.fsrs_card_json != association_json_before
        assert [log.rating for log in logs] == [1, 4]


async def test_latest_review_ratings_uses_selected_mode() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()

    async with database.session() as session:
        user = await UserRepository(session, admin_tg_ids=[1]).get_or_create(
            telegram_id=1,
            username="admin",
            first_name="Admin",
        )
        cards = CardRepository(session, FsrsService())
        first = await cards.create_card(user, "stubborn", "упрямый", "стаборно стоит")
        second = await cards.create_card(user, "beyond", "вне, за")

        await cards.review_card(user, first.card, NORMAL_MODE, "again")
        await cards.review_card(user, first.card, ASSOCIATION_MODE, "easy")
        await cards.review_card(user, first.card, NORMAL_MODE, "good")
        await session.commit()

        ratings = await cards.latest_review_ratings(
            user.id,
            [first.card.id, second.card.id],
            NORMAL_MODE,
        )

        assert ratings == {first.card.id: 3}


async def test_due_cards_self_heals_missing_fsrs_states() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()

    async with database.session() as session:
        user = await UserRepository(session, admin_tg_ids=[1]).get_or_create(
            telegram_id=1,
            username="admin",
            first_name="Admin",
        )
        cards = CardRepository(session, FsrsService())
        normal_only = await cards.create_card(user, "infer", "делать вывод")
        with_association = await cards.create_card(
            user,
            "broad",
            "широкий",
            "брод через широкую реку",
        )
        await session.execute(delete(FsrsState))
        await session.commit()

        normal_due = await cards.due_cards(user.id, NORMAL_MODE, 25)
        association_due = await cards.due_cards(user.id, ASSOCIATION_MODE, 25)

        normal_states = (
            await session.scalars(select(FsrsState).where(FsrsState.mode == NORMAL_MODE))
        ).all()
        association_states = (
            await session.scalars(select(FsrsState).where(FsrsState.mode == ASSOCIATION_MODE))
        ).all()

        assert {card.id for card, _state in normal_due} == {
            normal_only.card.id,
            with_association.card.id,
        }
        assert {state.card_id for state in normal_states} == {
            normal_only.card.id,
            with_association.card.id,
        }
        assert [card.id for card, _state in association_due] == [with_association.card.id]
        assert [state.card_id for state in association_states] == [with_association.card.id]


async def test_random_cards_filter_association_mode() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()

    async with database.session() as session:
        user = await UserRepository(session, admin_tg_ids=[1]).get_or_create(
            telegram_id=1,
            username="admin",
            first_name="Admin",
        )
        cards = CardRepository(session, FsrsService())
        normal_only = await cards.create_card(user, "infer", "делать вывод")
        with_association = await cards.create_card(
            user,
            "broad",
            "широкий",
            "брод через широкую реку",
        )
        await session.commit()

        normal_random = await cards.random_cards(user.id, NORMAL_MODE, 25)
        association_random = await cards.random_cards(user.id, ASSOCIATION_MODE, 25)

        assert {card.id for card in normal_random} == {
            normal_only.card.id,
            with_association.card.id,
        }
        assert [card.id for card in association_random] == [with_association.card.id]


async def test_search_cards_by_english_and_russian() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()

    async with database.session() as session:
        user = await UserRepository(session, admin_tg_ids=[1]).get_or_create(
            telegram_id=1,
            username="admin",
            first_name="Admin",
        )
        cards = CardRepository(session, FsrsService())
        await cards.create_card(user, "stubborn", "упрямый")
        await cards.create_card(user, "beyond", "вне, за")

        english_results = await cards.search_cards(user.id, "stub")
        russian_results = await cards.search_cards(user.id, "вне")

        assert await cards.count_search_cards(user.id, "stub") == 1
        assert english_results[0].en_text == "stubborn"
        assert russian_results[0].en_text == "beyond"
