from dictionarybot.config import Settings


def test_settings_parse_admin_ids() -> None:
    settings = Settings(BOT_TOKEN="token", ADMIN_TG_IDS="1, 2,3")
    assert settings.admin_tg_ids == [1, 2, 3]


def test_settings_parse_single_admin_id() -> None:
    settings = Settings(BOT_TOKEN="token", ADMIN_TG_IDS=1)
    assert settings.admin_tg_ids == [1]


def test_empty_openai_prices_are_none() -> None:
    settings = Settings(
        BOT_TOKEN="token",
        OPENAI_INPUT_USD_PER_1M_TOKENS="",
        OPENAI_OUTPUT_USD_PER_1M_TOKENS="",
    )
    assert settings.openai_input_usd_per_1m_tokens is None
    assert settings.openai_output_usd_per_1m_tokens is None


def test_openai_route_defaults() -> None:
    settings = Settings(BOT_TOKEN="token")
    assert settings.openai_translation_model == "gpt-5.4-mini"
    assert settings.openai_translation_reasoning_effort == "medium"
    assert settings.openai_translation_verbosity == "low"
    assert settings.openai_import_model == "gpt-5.4-mini"
    assert settings.openai_import_fallback_model == "gpt-5.4"
    assert settings.openai_import_reasoning_effort == "medium"
    assert settings.openai_import_verbosity == "low"
    assert settings.openai_association_model == "gpt-5.5"
    assert settings.openai_association_reasoning_effort == "low"
    assert settings.openai_association_verbosity == "low"
