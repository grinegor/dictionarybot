import json
import re
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI

from dictionarybot.config import AssociationStyle, Settings


@dataclass(slots=True)
class TokenUsage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    estimated_cost_usd: float | None = None
    model: str | None = None

    def add(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            prompt_tokens=_sum_optional(self.prompt_tokens, other.prompt_tokens),
            completion_tokens=_sum_optional(self.completion_tokens, other.completion_tokens),
            total_tokens=_sum_optional(self.total_tokens, other.total_tokens),
            estimated_cost_usd=_sum_optional(
                self.estimated_cost_usd,
                other.estimated_cost_usd,
            ),
            model=self.model if self.model == other.model else other.model,
        )


@dataclass(slots=True)
class TranslationResult:
    ru_text: str
    usage: TokenUsage


@dataclass(slots=True)
class AssociationResult:
    variants: list[str]
    usage: TokenUsage


@dataclass(slots=True)
class ImportCandidate:
    en_text: str
    ru_text: str | None
    needs_translation: bool


@dataclass(slots=True)
class ImportParseResult:
    candidates: list[ImportCandidate]
    usage: TokenUsage


class OpenAIService:
    def __init__(self, settings: Settings) -> None:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required for AI features.")
        self.settings = settings
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)

    async def translate_word(self, en_text: str) -> TranslationResult:
        payload = await self._json_response(
            request_type="translation",
            model=self.settings.openai_translation_model,
            reasoning_effort=self.settings.openai_translation_reasoning_effort,
            verbosity=self.settings.openai_translation_verbosity,
            schema={
                "type": "object",
                "properties": {"ru_text": {"type": "string"}},
                "required": ["ru_text"],
                "additionalProperties": False,
            },
            system=(
                "Ты помощник для англо-русского словаря. Верни 2-3 главных русских "
                "значения английского слова или фразы одной строкой через запятую. "
                "Пусть слова будут расположены по убыванию частоты встречаемого перевода."
                " Не добавляй примеры, транскрипцию, часть речи или пояснения."
            ),
            user=f"English: {en_text}",
        )
        return TranslationResult(ru_text=str(payload.data["ru_text"]).strip(), usage=payload.usage)

    async def generate_associations(
        self,
        en_text: str,
        ru_text: str,
        style: AssociationStyle,
    ) -> AssociationResult:
        style_hint = {
            "neutral": (
                "спокойный, понятный, без чрезмерного юмора; "
                "варианты должны быть практичными"
            ),
            "funny": (
                "забавный, живой, легко запоминающийся; "
                "добавь игру слов или смешной образ"
            ),
            "absurd": (
                "абсурдный, яркий, немного нелепый, но все еще полезный; "
                "варианты должны быть очень образными"
            ),
        }[style]
        payload = await self._json_response(
            request_type="association",
            model=self.settings.openai_association_model,
            reasoning_effort=self.settings.openai_association_reasoning_effort,
            verbosity=self.settings.openai_association_verbosity,
            schema={
                "type": "object",
                "properties": {
                    "variants": {
                        "type": "array",
                        "minItems": self.settings.openai_association_variants,
                        "maxItems": self.settings.openai_association_variants,
                        "items": {"type": "string"},
                    }
                },
                "required": ["variants"],
                "additionalProperties": False,
            },
            system=(
                "Ты придумываешь короткие русские мнемонические ассоциации для "
                "запоминания английского слова.\n\n"
                "Ассоциация должна помогать русскоязычному человеку вспомнить "
                "английское слово по русскому значению.\n\n"
                "Используй один или несколько приемов:\n"
                "- фонетическая зацепка: русское слово или фраза, похожая на "
                "английское слово по звучанию;\n"
                "- вшивание значения в образ или сцену;\n"
                "- яркий визуальный образ;\n"
                "- ритм, рифма или аллитерация;\n"
                "- разделение слова на куски.\n\n"
                "Ассоциация должна быть одной короткой фразой до 90 символов.\n"
                "Без объяснений, без нумерации, без кавычек.\n"
                "Строго запрещено использовать в ассоциации исходное слово или "
                "любую его часть на латинице, также запрещена полная транскрибация "
                "кириллицей.\n"
                "Созвучие можно передавать только кириллицей."
            ),
            user=(
                f"English: {en_text}\n"
                f"Russian meaning: {ru_text}\n"
                f"Style: {style_hint}\n"
                f"Generate {self.settings.openai_association_variants} variants. "
                "Do not include the English word itself in any variant."
            ),
        )
        variants = [
            variant
            for item in payload.data["variants"]
            if (variant := str(item).strip()) and not contains_source_word(variant, en_text)
        ]
        return AssociationResult(
            variants=variants[: self.settings.openai_association_variants],
            usage=payload.usage,
        )

    async def parse_import_text(self, text: str) -> ImportParseResult:
        try:
            payload = await self._json_response(
                request_type="import_parse",
                model=self.settings.openai_import_model,
                reasoning_effort=self.settings.openai_import_reasoning_effort,
                verbosity=self.settings.openai_import_verbosity,
                schema=self._import_schema(),
                system=self._import_system_prompt(),
                user=text,
            )
            candidates = self._import_candidates(payload)
            if (
                candidates
                or self.settings.openai_import_fallback_model == self.settings.openai_import_model
            ):
                return ImportParseResult(candidates=candidates, usage=payload.usage)
        except Exception:
            if self.settings.openai_import_fallback_model == self.settings.openai_import_model:
                raise
            payload = await self._json_response(
                request_type="import_parse",
                model=self.settings.openai_import_fallback_model,
                reasoning_effort=self.settings.openai_import_reasoning_effort,
                verbosity=self.settings.openai_import_verbosity,
                schema=self._import_schema(),
                system=self._import_system_prompt(),
                user=text,
            )
            return ImportParseResult(
                candidates=self._import_candidates(payload),
                usage=payload.usage,
            )

        fallback_payload = await self._json_response(
            request_type="import_parse",
            model=self.settings.openai_import_fallback_model,
            reasoning_effort=self.settings.openai_import_reasoning_effort,
            verbosity=self.settings.openai_import_verbosity,
            schema=self._import_schema(),
            system=self._import_system_prompt(),
            user=text,
        )
        return ImportParseResult(
            candidates=self._import_candidates(fallback_payload),
            usage=payload.usage.add(fallback_payload.usage),
        )

    @staticmethod
    def _import_candidates(payload: "_JsonPayload") -> list[ImportCandidate]:
        return [
            ImportCandidate(
                en_text=str(item["en_text"]).strip(),
                ru_text=str(item["ru_text"]).strip() if item.get("ru_text") else None,
                needs_translation=bool(item["needs_translation"]),
            )
            for item in payload.data["cards"]
            if str(item.get("en_text", "")).strip()
        ]

    @staticmethod
    def _import_schema() -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "cards": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "en_text": {"type": "string"},
                            "ru_text": {"type": ["string", "null"]},
                            "needs_translation": {"type": "boolean"},
                        },
                        "required": ["en_text", "ru_text", "needs_translation"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["cards"],
            "additionalProperties": False,
        }

    @staticmethod
    def _import_system_prompt() -> str:
        return (
            "Ты надежный парсер импорта для англо-русского словаря. Твоя задача — "
            "восстановить карточки даже из грязного, сломанного или частично XML/HTML "
            "текста. Ищи пары English -> Russian в любых форматах: строки с дефисом, "
            "таблицы с табами, reversed pairs Russian<TAB>English, XML-фрагменты вроде "
            '<tts name="Text">word</tts><text name="Translation">перевод</text>, '
            "обрезанный XML без корневого тега, склеенный текст без переносов вроде "
            "aversionотвращениеresponsibilityответственность. Если явно видишь пару, "
            "сохрани ее. Английская сторона должна быть в en_text, русская — в ru_text. "
            "Если видишь английское слово без русского значения, предложи 2-3 главных "
            "русских значения одной строкой через запятую и поставь needs_translation=true. "
            "Если русское значение есть явно, поставь needs_translation=false. Не добавляй "
            "карточки, которых нет в исходном импорте. Не добавляй примеры, транскрипцию, "
            "части речи или пояснения."
        )

    async def _json_response(
        self,
        request_type: str,
        model: str,
        schema: dict[str, Any],
        system: str,
        user: str,
        reasoning_effort: str,
        verbosity: str,
    ) -> "_JsonPayload":
        request_params: dict[str, Any] = {
            "model": model,
            "reasoning": {"effort": reasoning_effort},
            "input": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "text": {
                "verbosity": verbosity,
                "format": {
                    "type": "json_schema",
                    "name": f"dictionarybot_{request_type}",
                    "schema": schema,
                    "strict": True,
                }
            },
        }
        response = await self.client.responses.create(**request_params)
        raw_text = getattr(response, "output_text", None)
        if not raw_text:
            raw_text = self._collect_text(response)
        return _JsonPayload(data=json.loads(raw_text), usage=self._usage(response, model))

    def _usage(self, response: Any, model: str) -> TokenUsage:
        usage = getattr(response, "usage", None)
        prompt = getattr(usage, "input_tokens", None) if usage else None
        completion = getattr(usage, "output_tokens", None) if usage else None
        total = getattr(usage, "total_tokens", None) if usage else None
        cost = None
        if (
            prompt is not None
            and completion is not None
            and self.settings.openai_input_usd_per_1m_tokens is not None
            and self.settings.openai_output_usd_per_1m_tokens is not None
        ):
            cost = (
                prompt * self.settings.openai_input_usd_per_1m_tokens
                + completion * self.settings.openai_output_usd_per_1m_tokens
            ) / 1_000_000
        return TokenUsage(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
            estimated_cost_usd=cost,
            model=model,
        )

    @staticmethod
    def _collect_text(response: Any) -> str:
        chunks: list[str] = []
        for output in getattr(response, "output", []) or []:
            for content in getattr(output, "content", []) or []:
                text = getattr(content, "text", None)
                if text:
                    chunks.append(text)
        return "".join(chunks)


@dataclass(slots=True)
class _JsonPayload:
    data: dict[str, Any]
    usage: TokenUsage


def _sum_optional[T: int | float](left: T | None, right: T | None) -> T | None:
    if left is None:
        return right
    if right is None:
        return left
    return left + right


def contains_source_word(text: str, source: str) -> bool:
    source_tokens = [token.casefold() for token in re.findall(r"[A-Za-z]+", source)]
    if not source_tokens:
        return False
    text_lower = text.casefold()
    if " ".join(source_tokens) in text_lower:
        return True
    text_tokens = set(re.findall(r"[a-z]+", text_lower))
    return any(token in text_tokens for token in source_tokens)
