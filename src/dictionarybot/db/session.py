from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from dictionarybot.db.models import Base


class Database:
    def __init__(self, database_url: str) -> None:
        self.engine = create_async_engine(database_url, echo=False)
        self.session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def create_schema(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(_ensure_schema_updates)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.session_factory() as session:
            yield session


def _ensure_schema_updates(connection) -> None:
    inspector = inspect(connection)
    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "fsrs_retention" not in user_columns:
        connection.execute(
            text("ALTER TABLE users ADD COLUMN fsrs_retention FLOAT NOT NULL DEFAULT 0.9")
        )
