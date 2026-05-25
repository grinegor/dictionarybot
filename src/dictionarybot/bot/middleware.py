from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from dictionarybot.config import Settings
from dictionarybot.db.repositories import UserRepository
from dictionarybot.db.session import Database


class AccessMiddleware(BaseMiddleware):
    def __init__(self, settings: Settings, database: Database) -> None:
        self.settings = settings
        self.database = database

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = getattr(event, "from_user", None)
        if tg_user is None and isinstance(event, CallbackQuery):
            tg_user = event.from_user
        if tg_user is None:
            return await handler(event, data)

        async with self.database.session() as session:
            users = UserRepository(session, self.settings.admin_tg_ids)
            app_user = await users.get_or_create(
                telegram_id=tg_user.id,
                username=tg_user.username,
                first_name=tg_user.first_name,
            )
            allowed = await users.is_allowed(tg_user.id)
            data["session"] = session
            data["app_user"] = app_user
            data["is_admin"] = tg_user.id in self.settings.admin_tg_ids

            if not allowed:
                await session.commit()
                await self._deny(event, tg_user.id)
                return None

            try:
                result = await handler(event, data)
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise

    @staticmethod
    async def _deny(event: TelegramObject, telegram_id: int) -> None:
        text = (
            "🔒 Доступ пока закрыт.\n\n"
            f"Твой Telegram ID: <code>{telegram_id}</code>\n"
            "Попроси админа добавить тебя в allow list."
        )
        if isinstance(event, Message):
            await event.answer(text)
        elif isinstance(event, CallbackQuery):
            await event.answer("Доступ закрыт", show_alert=True)
