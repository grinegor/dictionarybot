import asyncio
import fcntl
import hashlib
import logging
import os
import tempfile
from typing import TextIO

from dictionarybot.app import create_bot_app
from dictionarybot.config import get_settings


def acquire_single_instance_lock(bot_token: str) -> TextIO:
    token_hash = hashlib.sha256(bot_token.encode("utf-8")).hexdigest()[:12]
    lock_path = os.path.join(tempfile.gettempdir(), f"dictionarybot-{token_hash}.lock")
    lock_file = open(lock_path, "w", encoding="utf-8")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        lock_file.close()
        raise RuntimeError("Another DictionaryBot instance is already running.") from exc
    lock_file.write(f"{os.getpid()}\n")
    lock_file.flush()
    return lock_file


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = get_settings()
    try:
        lock_file = acquire_single_instance_lock(settings.bot_token)
    except RuntimeError as exc:
        logging.error("%s", exc)
        raise SystemExit(1) from exc
    try:
        asyncio.run(create_bot_app(settings).run())
    finally:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()


if __name__ == "__main__":
    main()
