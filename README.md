# DictionaryBot MVP

Telegram AI-словарь с карточками EN -> RU, ассоциациями через OpenAI и FSRS-повторением.

## Что уже заложено

- Один словарь на пользователя внутри общей базы.
- Allow list по Telegram ID.
- Карточки: английский текст, русский перевод, опциональная ассоциация.
- Два независимых FSRS-режима для одной карточки:
  - обычный: EN -> RU;
  - ассоциативный: RU + association -> EN.
- OpenAI-only MVP:
  - перевод слова;
  - парсинг импорта;
  - генерация 3 ассоциаций за раз.
- Личные настройки стиля ассоциаций:
  - нейтральный;
  - забавный;
  - абсурдный.
- Админ-команды:
  - `/allow 123456789`;
  - `/deny 123456789`;
  - `/stats`.

## Локальный запуск

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Заполни `.env`:

```env
BOT_TOKEN=...
ADMIN_TG_IDS=твой_telegram_id
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-5.4-mini
OPENAI_REASONING_EFFORT=medium
OPENAI_VERBOSITY=low
```

По умолчанию используется локальная SQLite-база:

```env
DATABASE_URL=sqlite+aiosqlite:///./dictionarybot.db
```

Для PostgreSQL позже:

```env
DATABASE_URL=postgresql+asyncpg://dictionarybot:password@localhost:5432/dictionarybot
```

Запуск:

```bash
dictionarybot
```

или:

```bash
python -m dictionarybot.main
```

## OpenAI-настройки

Все серверные настройки живут в `.env`. Модель не хардкодится в логике.

```env
OPENAI_MODEL=gpt-5.4-mini
OPENAI_REASONING_EFFORT=medium
OPENAI_VERBOSITY=low
OPENAI_TRANSLATION_MODEL=gpt-5.4-mini
OPENAI_TRANSLATION_REASONING_EFFORT=medium
OPENAI_TRANSLATION_VERBOSITY=low
OPENAI_IMPORT_MODEL=gpt-5.4-mini
OPENAI_IMPORT_FALLBACK_MODEL=gpt-5.4
OPENAI_IMPORT_REASONING_EFFORT=medium
OPENAI_IMPORT_VERBOSITY=low
OPENAI_IMPORT_CHUNK_LINES=40
OPENAI_IMPORT_CHUNK_CHARS=6000
IMPORT_PREVIEW_LIMIT=30
IMPORT_MAX_FILE_BYTES=1048576
OPENAI_ASSOCIATION_MODEL=gpt-5.5
OPENAI_ASSOCIATION_REASONING_EFFORT=low
OPENAI_ASSOCIATION_VERBOSITY=low
OPENAI_ASSOCIATION_VARIANTS=3
```

Для оценки стоимости в `/stats` можно добавить тарифы:

```env
OPENAI_INPUT_USD_PER_1M_TOKENS=
OPENAI_OUTPUT_USD_PER_1M_TOKENS=
```

Если тарифы пустые, бот считает вызовы и токены, но не оценивает стоимость.

## Основной UX

- `/start` или нижнее меню.
- `➕ Добавить`: слово или пара `word - перевод`.
- Если слово уже есть, бот показывает старую карточку и предлагает редактировать.
- При добавлении можно:
  - не добавлять ассоциацию;
  - написать свою;
  - сгенерировать 3 варианта через OpenAI.
- `🔁 Повторение`: обычный режим EN -> RU.
- `🧠 Ассоциации`: режим RU + ассоциация -> EN.
- `📥 Импорт`: принимает текст до 100 слов за раз или файл `.xml`/`.pdf`/`.txt` до 1 МБ, показывает превью, пользователь подтверждает или исправляет вручную.
- `📚 Словарь`: последние карточки с быстрым редактированием.
- `⚙️ Настройки`: стиль ассоциаций.

## Тесты

```bash
pytest
```
