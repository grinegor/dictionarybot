from dictionarybot.bot.handlers import (
    decode_import_file,
    parse_local_import,
    parse_pair,
    split_import_text,
)


def test_parse_pair_dash() -> None:
    assert parse_pair("stubborn - упрямый") == ("stubborn", "упрямый")


def test_parse_pair_two_lines() -> None:
    assert parse_pair("beyond\nвне, за") == ("beyond", "вне, за")


def test_parse_pair_reversed_tab() -> None:
    assert parse_pair("отвращение, неприязнь\taversion") == ("aversion", "отвращение, неприязнь")


def test_parse_pair_none_for_single_word() -> None:
    assert parse_pair("stubborn") is None


def test_parse_local_import_many_pairs_without_openai() -> None:
    text = "\n".join(f"word{i} - перевод {i}" for i in range(300))
    candidates = parse_local_import(text)

    assert candidates is not None
    assert len(candidates) == 300
    assert candidates[0].en_text == "word0"
    assert candidates[0].ru_text == "перевод 0"
    assert candidates[0].needs_translation is False


def test_parse_local_import_returns_none_for_mixed_lines() -> None:
    assert parse_local_import("stubborn - упрямый\nbeyond") is None


def test_parse_local_import_xmlish_fragment() -> None:
    text = (
        'name="Text">aversion</tts><text name="Translation">отвращение, неприязнь</text>'
        '</card><card><tts name="Text">responsibility</tts>'
        '<text name="Translation">обязанность, ответственность</text>'
    )
    candidates = parse_local_import(text)

    assert candidates is not None
    assert [(item.en_text, item.ru_text) for item in candidates] == [
        ("aversion", "отвращение, неприязнь"),
        ("responsibility", "обязанность, ответственность"),
    ]


def test_split_import_text_by_lines() -> None:
    text = "\n".join(f"word{i}" for i in range(95))
    chunks = split_import_text(text, chunk_lines=40)

    assert len(chunks) == 3
    assert chunks[0].count("\n") == 39
    assert chunks[-1].splitlines()[-1] == "word94"


def test_split_import_text_single_long_line_by_chars() -> None:
    chunks = split_import_text("a" * 25, chunk_lines=40, chunk_chars=10)

    assert chunks == ["a" * 10, "a" * 10, "a" * 5]


def test_decode_import_file_cp1251() -> None:
    assert decode_import_file("aversion - отвращение".encode("cp1251")) == "aversion - отвращение"
