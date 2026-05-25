import re

_SPACE_RE = re.compile(r"\s+")


def clean_text(value: str) -> str:
    return _SPACE_RE.sub(" ", value.strip())


def normalize_english(value: str) -> str:
    return clean_text(value).casefold()
