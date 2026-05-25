import asyncio
import logging

from dictionarybot.app import create_bot_app
from dictionarybot.config import get_settings


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = get_settings()
    asyncio.run(create_bot_app(settings).run())


if __name__ == "__main__":
    main()
