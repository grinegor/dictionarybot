from dictionarybot.services.openai_service import contains_source_word
from dictionarybot.utils.text import clean_text, normalize_english


def test_clean_text_collapses_whitespace() -> None:
    assert clean_text("  beyond   the   wall  ") == "beyond the wall"


def test_normalize_english_is_case_insensitive() -> None:
    assert normalize_english("  Stubborn ") == "stubborn"


def test_contains_source_word_blocks_generated_association_source() -> None:
    assert contains_source_word("stubborn звучит как стабильный бурный", "stubborn") is True
    assert contains_source_word("look up: лук вверх", "look up") is True
    assert contains_source_word("стабильно бурный человек", "stubborn") is False
