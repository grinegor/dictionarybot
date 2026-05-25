from dataclasses import dataclass

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from dictionarybot.bot.handlers import register_handlers
from dictionarybot.config import Settings
from dictionarybot.db.session import Database


@dataclass(slots=True)
class BotApp:
    settings: Settings
    database: Database
    bot: Bot
    dispatcher: Dispatcher

    async def run(self) -> None:
        await self.database.create_schema()
        register_handlers(self.dispatcher, self.settings, self.database)
        await self.dispatcher.start_polling(self.bot)


def create_bot_app(settings: Settings) -> BotApp:
    database = Database(settings.database_url)
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher(storage=MemoryStorage())
    return BotApp(settings=settings, database=database, bot=bot, dispatcher=dispatcher)
