from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ReasoningEffort = Literal["minimal", "low", "medium", "high"]
Verbosity = Literal["low", "medium", "high"]
AssociationStyle = Literal["neutral", "funny", "absurd"]


def _parse_int_csv(value: int | str | list[int] | tuple[int, ...] | None) -> list[int]:
    if value is None or value == "":
        return []
    if isinstance(value, int):
        return [value]
    if isinstance(value, (list, tuple)):
        return [int(item) for item in value]
    return [int(item.strip()) for item in value.split(",") if item.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str = Field(alias="BOT_TOKEN")
    database_url: str = Field("sqlite+aiosqlite:///./dictionarybot.db", alias="DATABASE_URL")

    admin_tg_ids: list[int] = Field(default_factory=list, alias="ADMIN_TG_IDS")

    openai_api_key: str | None = Field(None, alias="OPENAI_API_KEY")
    openai_model: str = Field("gpt-5.4-mini", alias="OPENAI_MODEL")
    openai_reasoning_effort: ReasoningEffort = Field("medium", alias="OPENAI_REASONING_EFFORT")
    openai_verbosity: Verbosity = Field("low", alias="OPENAI_VERBOSITY")

    openai_translation_model: str = Field("gpt-5.4-mini", alias="OPENAI_TRANSLATION_MODEL")
    openai_translation_reasoning_effort: ReasoningEffort = Field(
        "medium", alias="OPENAI_TRANSLATION_REASONING_EFFORT"
    )
    openai_translation_verbosity: Verbosity = Field("low", alias="OPENAI_TRANSLATION_VERBOSITY")

    openai_import_model: str = Field("gpt-5.4-mini", alias="OPENAI_IMPORT_MODEL")
    openai_import_fallback_model: str = Field("gpt-5.4", alias="OPENAI_IMPORT_FALLBACK_MODEL")
    openai_import_reasoning_effort: ReasoningEffort = Field(
        "medium", alias="OPENAI_IMPORT_REASONING_EFFORT"
    )
    openai_import_verbosity: Verbosity = Field("low", alias="OPENAI_IMPORT_VERBOSITY")
    openai_import_chunk_lines: int = Field(40, alias="OPENAI_IMPORT_CHUNK_LINES")
    openai_import_chunk_chars: int = Field(6000, alias="OPENAI_IMPORT_CHUNK_CHARS")
    import_preview_limit: int = Field(30, alias="IMPORT_PREVIEW_LIMIT")
    import_max_file_bytes: int = Field(1_048_576, alias="IMPORT_MAX_FILE_BYTES")

    openai_association_model: str = Field("gpt-5.5", alias="OPENAI_ASSOCIATION_MODEL")
    openai_association_reasoning_effort: ReasoningEffort = Field(
        "low", alias="OPENAI_ASSOCIATION_REASONING_EFFORT"
    )
    openai_association_verbosity: Verbosity = Field("low", alias="OPENAI_ASSOCIATION_VERBOSITY")
    openai_association_variants: int = Field(3, alias="OPENAI_ASSOCIATION_VARIANTS")
    openai_input_usd_per_1m_tokens: float | None = Field(
        None, alias="OPENAI_INPUT_USD_PER_1M_TOKENS"
    )
    openai_output_usd_per_1m_tokens: float | None = Field(
        None, alias="OPENAI_OUTPUT_USD_PER_1M_TOKENS"
    )

    @field_validator("admin_tg_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, value: int | str | list[int] | tuple[int, ...] | None) -> list[int]:
        return _parse_int_csv(value)

    @field_validator(
        "openai_input_usd_per_1m_tokens",
        "openai_output_usd_per_1m_tokens",
        mode="before",
    )
    @classmethod
    def empty_float_to_none(cls, value: str | float | None) -> float | None:
        if value == "":
            return None
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
