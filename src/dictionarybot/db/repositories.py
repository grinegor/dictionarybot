from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from dictionarybot.config import AssociationStyle
from dictionarybot.db.models import (
    AllowedUser,
    ApiUsageLog,
    Card,
    FsrsState,
    ReviewLog,
    User,
    utcnow,
)
from dictionarybot.services.fsrs import FsrsService
from dictionarybot.utils.text import clean_text, normalize_english

NORMAL_MODE = "normal"
ASSOCIATION_MODE = "association"


@dataclass(slots=True)
class CardCreateResult:
    card: Card
    created: bool


_UNSET = object()


class UserRepository:
    def __init__(self, session: AsyncSession, admin_tg_ids: list[int]) -> None:
        self.session = session
        self.admin_tg_ids = set(admin_tg_ids)

    async def get_or_create(
        self,
        telegram_id: int,
        username: str | None,
        first_name: str | None,
    ) -> User:
        user = await self.get_by_telegram_id(telegram_id)
        if user is None:
            user = User(telegram_id=telegram_id, username=username, first_name=first_name)
            self.session.add(user)
            await self.session.flush()
        else:
            user.username = username
            user.first_name = first_name
            user.last_seen_at = utcnow()
        return user

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        result = await self.session.execute(select(User).where(User.telegram_id == telegram_id))
        return result.scalar_one_or_none()

    async def is_allowed(self, telegram_id: int) -> bool:
        if telegram_id in self.admin_tg_ids:
            return True
        result = await self.session.execute(
            select(AllowedUser.id).where(AllowedUser.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none() is not None

    async def allow_user(
        self,
        telegram_id: int,
        added_by_telegram_id: int | None,
        note: str | None = None,
    ) -> AllowedUser:
        allowed = await self.session.scalar(
            select(AllowedUser).where(AllowedUser.telegram_id == telegram_id)
        )
        if allowed is None:
            allowed = AllowedUser(
                telegram_id=telegram_id,
                added_by_telegram_id=added_by_telegram_id,
                note=note,
            )
            self.session.add(allowed)
        else:
            allowed.note = note
        await self.session.flush()
        return allowed

    async def deny_user(self, telegram_id: int) -> bool:
        result = await self.session.execute(
            delete(AllowedUser).where(AllowedUser.telegram_id == telegram_id)
        )
        return result.rowcount > 0

    async def set_association_style(self, user: User, style: AssociationStyle) -> None:
        user.association_style = style
        await self.session.flush()


class CardRepository:
    def __init__(self, session: AsyncSession, fsrs: FsrsService) -> None:
        self.session = session
        self.fsrs = fsrs

    async def create_card(
        self,
        user: User,
        en_text: str,
        ru_text: str,
        association_text: str | None = None,
    ) -> CardCreateResult:
        en = clean_text(en_text)
        ru = clean_text(ru_text)
        association = clean_text(association_text) if association_text else None
        existing = await self.get_by_en(user.id, en)
        if existing is not None:
            return CardCreateResult(card=existing, created=False)

        card = Card(
            user_id=user.id,
            en_text=en,
            normalized_en_text=normalize_english(en),
            ru_text=ru,
            association_text=association,
            association_enabled=bool(association),
        )
        self.session.add(card)
        await self.session.flush()

        await self.ensure_fsrs_state(card, NORMAL_MODE)
        if card.association_enabled:
            await self.ensure_fsrs_state(card, ASSOCIATION_MODE)
        await self.session.flush()
        return CardCreateResult(card=card, created=True)

    async def get_by_id(self, user_id: int, card_id: int) -> Card | None:
        return await self.session.scalar(
            select(Card)
            .options(selectinload(Card.fsrs_states))
            .where(Card.id == card_id, Card.user_id == user_id)
        )

    async def get_by_en(self, user_id: int, en_text: str) -> Card | None:
        return await self.session.scalar(
            select(Card)
            .options(selectinload(Card.fsrs_states))
            .where(
                Card.user_id == user_id,
                Card.normalized_en_text == normalize_english(en_text),
            )
        )

    async def update_card(
        self,
        card: Card,
        en_text: str | None = None,
        ru_text: str | None = None,
        association_text: str | None | object = _UNSET,
        association_enabled: bool | None = None,
    ) -> None:
        if en_text is not None:
            card.en_text = clean_text(en_text)
            card.normalized_en_text = normalize_english(en_text)
        if ru_text is not None:
            card.ru_text = clean_text(ru_text)
        if association_text is not _UNSET:
            card.association_text = clean_text(association_text) if association_text else None
        if association_enabled is not None:
            card.association_enabled = association_enabled
        if card.association_text:
            card.association_enabled = True
            await self.ensure_fsrs_state(card, ASSOCIATION_MODE)
        else:
            card.association_enabled = False
        await self.session.flush()

    async def delete_card(self, card: Card) -> None:
        await self.session.execute(delete(ReviewLog).where(ReviewLog.card_id == card.id))
        await self.session.delete(card)
        await self.session.flush()

    async def ensure_fsrs_state(self, card: Card, mode: str) -> FsrsState:
        existing = await self.session.scalar(
            select(FsrsState).where(FsrsState.card_id == card.id, FsrsState.mode == mode)
        )
        if existing is not None:
            return existing
        new_state = self.fsrs.create_state()
        state = FsrsState(
            card_id=card.id,
            mode=mode,
            fsrs_card_json=new_state.card_json,
            due_at=new_state.due_at,
        )
        self.session.add(state)
        await self.session.flush()
        return state

    async def ensure_missing_fsrs_states(self, user_id: int, mode: str) -> int:
        missing_state = ~select(FsrsState.id).where(
            FsrsState.card_id == Card.id,
            FsrsState.mode == mode,
        ).exists()
        query = select(Card).where(Card.user_id == user_id, missing_state)
        if mode == ASSOCIATION_MODE:
            query = query.where(
                Card.association_enabled.is_(True),
                Card.association_text.is_not(None),
            )
        missing_cards = list((await self.session.scalars(query)).all())
        for card in missing_cards:
            await self.ensure_fsrs_state(card, mode)
        return len(missing_cards)

    async def due_cards(self, user_id: int, mode: str, limit: int) -> list[tuple[Card, FsrsState]]:
        await self.ensure_missing_fsrs_states(user_id, mode)
        now = datetime.now(UTC)
        query: Select[tuple[Card, FsrsState]] = (
            select(Card, FsrsState)
            .join(FsrsState, FsrsState.card_id == Card.id)
            .where(Card.user_id == user_id, FsrsState.mode == mode, FsrsState.due_at <= now)
            .order_by(FsrsState.due_at.asc(), Card.id.asc())
            .limit(limit)
        )
        if mode == ASSOCIATION_MODE:
            query = query.where(
                Card.association_enabled.is_(True),
                Card.association_text.is_not(None),
            )
        result = await self.session.execute(query)
        return list(result.all())

    async def list_cards(self, user_id: int, limit: int = 10, offset: int = 0) -> list[Card]:
        result = await self.session.execute(
            select(Card)
            .where(Card.user_id == user_id)
            .order_by(Card.updated_at.desc(), Card.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def search_cards(
        self,
        user_id: int,
        query: str,
        limit: int = 10,
        offset: int = 0,
    ) -> list[Card]:
        pattern = f"%{clean_text(query)}%"
        result = await self.session.execute(
            select(Card)
            .where(
                Card.user_id == user_id,
                Card.en_text.ilike(pattern) | Card.ru_text.ilike(pattern),
            )
            .order_by(Card.updated_at.desc(), Card.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_cards(self, user_id: int) -> int:
        count = await self.session.scalar(
            select(func.count(Card.id)).where(Card.user_id == user_id)
        )
        return count or 0

    async def count_search_cards(self, user_id: int, query: str) -> int:
        pattern = f"%{clean_text(query)}%"
        count = await self.session.scalar(
            select(func.count(Card.id)).where(
                Card.user_id == user_id,
                Card.en_text.ilike(pattern) | Card.ru_text.ilike(pattern),
            )
        )
        return count or 0

    async def review_card(self, user: User, card: Card, mode: str, rating_key: str) -> ReviewLog:
        state = await self.ensure_fsrs_state(card, mode)
        previous_due = state.due_at
        review = self.fsrs.review(state.fsrs_card_json, rating_key)
        state.fsrs_card_json = review.card_json
        state.due_at = review.next_due_at
        state.last_reviewed_at = review.reviewed_at
        log = ReviewLog(
            user_id=user.id,
            card_id=card.id,
            mode=mode,
            rating={"again": 1, "hard": 2, "good": 3, "easy": 4}[rating_key],
            reviewed_at=review.reviewed_at,
            previous_due_at=previous_due,
            next_due_at=review.next_due_at,
            fsrs_review_log_json=review.review_log_json,
        )
        self.session.add(log)
        await self.session.flush()
        return log


class UsageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def log(
        self,
        user_id: int | None,
        model: str,
        request_type: str,
        status: str = "ok",
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
        estimated_cost_usd: float | None = None,
        error_message: str | None = None,
    ) -> None:
        self.session.add(
            ApiUsageLog(
                user_id=user_id,
                provider="openai",
                model=model,
                request_type=request_type,
                status=status,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                estimated_cost_usd=estimated_cost_usd,
                error_message=error_message,
            )
        )
        await self.session.flush()


class StatsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def overview(self) -> dict[str, int | float | None]:
        users_count = await self.session.scalar(select(func.count(User.id)))
        allowed_count = await self.session.scalar(select(func.count(AllowedUser.id)))
        cards_count = await self.session.scalar(select(func.count(Card.id)))
        association_count = await self.session.scalar(
            select(func.count(Card.id)).where(Card.association_enabled.is_(True))
        )
        review_count = await self.session.scalar(select(func.count(ReviewLog.id)))
        api_calls = await self.session.scalar(select(func.count(ApiUsageLog.id)))
        api_tokens = await self.session.scalar(select(func.sum(ApiUsageLog.total_tokens)))
        api_cost = await self.session.scalar(select(func.sum(ApiUsageLog.estimated_cost_usd)))
        return {
            "users": users_count or 0,
            "allowed": allowed_count or 0,
            "cards": cards_count or 0,
            "association_cards": association_count or 0,
            "reviews": review_count or 0,
            "api_calls": api_calls or 0,
            "api_tokens": api_tokens or 0,
            "api_cost_usd": api_cost,
        }
