from dataclasses import dataclass
from datetime import datetime

from fsrs import Card as FsrsCard
from fsrs import Rating, Scheduler

RATING_LABELS: dict[str, str] = {
    "again": "Again",
    "hard": "Hard",
    "good": "Good",
    "easy": "Easy",
}


@dataclass(slots=True)
class NewFsrsState:
    card_json: str
    due_at: datetime


@dataclass(slots=True)
class FsrsReviewResult:
    card_json: str
    review_log_json: str
    reviewed_at: datetime
    next_due_at: datetime


class FsrsService:
    def __init__(self) -> None:
        self.scheduler = Scheduler()

    def create_state(self) -> NewFsrsState:
        card = FsrsCard()
        return NewFsrsState(card_json=card.to_json(), due_at=card.due)

    def review(self, card_json: str, rating_key: str) -> FsrsReviewResult:
        rating_name = RATING_LABELS[rating_key]
        card = FsrsCard.from_json(card_json)
        reviewed_card, review_log = self.scheduler.review_card(card, getattr(Rating, rating_name))
        return FsrsReviewResult(
            card_json=reviewed_card.to_json(),
            review_log_json=review_log.to_json(),
            reviewed_at=review_log.review_datetime,
            next_due_at=reviewed_card.due,
        )
