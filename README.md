# DictionaryBot MVP

Telegram AI dictionary with EN -> RU flashcards, OpenAI-powered associations, and FSRS reviews.

## What's Included

- One personal dictionary per user inside a shared database.
- Telegram ID allow list.
- Cards with English text, Russian translation, and an optional association.
- Two independent FSRS modes for the same card:
  - regular: EN -> RU;
  - associative: RU + association -> EN.
- Two random modes for free practice:
  - regular: EN -> RU;
  - associative: RU + association -> EN.
  - ratings in random modes do not affect future FSRS selections.
- OpenAI-only MVP:
  - word translation;
  - import parsing;
  - generation of 3 association variants at a time.
- Personal association style settings:
  - neutral;
  - funny;
  - absurd.
- Personal FSRS retention mode:
  - 85% light;
  - 90% balanced;
  - 95% intensive.
- Admin commands:
  - `/allow 123456789`;
  - `/deny 123456789`;
  - `/stats`.

## Local Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Fill in `.env`:

```env
BOT_TOKEN=...
ADMIN_TG_IDS=your_telegram_id
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-5.4-mini
OPENAI_REASONING_EFFORT=medium
OPENAI_VERBOSITY=low
```

By default, the bot uses a local SQLite database:

```env
DATABASE_URL=sqlite+aiosqlite:///./dictionarybot.db
```

For PostgreSQL later:

```env
DATABASE_URL=postgresql+asyncpg://dictionarybot:password@localhost:5432/dictionarybot
```

Run:

```bash
dictionarybot
```

or:

```bash
python -m dictionarybot.main
```

## OpenAI Settings

All server-side settings live in `.env`. The model is not hardcoded in the application logic.

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

To estimate costs in `/stats`, you can add pricing values:

```env
OPENAI_INPUT_USD_PER_1M_TOKENS=
OPENAI_OUTPUT_USD_PER_1M_TOKENS=
```

If pricing values are empty, the bot tracks calls and token usage but does not estimate cost.

## Main UX

- `/start` or the bottom menu.
- `➕ Add`: a word or a `word - translation` pair.
- If the word already exists, the bot shows the existing card and offers editing.
- When adding a card, the user can:
  - skip the association;
  - write a custom association;
  - generate 3 variants through OpenAI.
- `🔁 Review`: choose FSRS or random mode for EN -> RU.
- `🧠 Associations`: choose FSRS or random mode for RU + association -> EN.
- `📥 Import`: accepts text up to 100 words at a time or a `.xml`/`.pdf`/`.txt` file up to 1 MB, shows a preview, and lets the user confirm or fix items manually.
- `📚 Dictionary`: list all cards with search and editing.
- `⚙️ Settings`: association style and FSRS retention mode.

## Tests

```bash
pytest
```
