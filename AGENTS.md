# AGENTS.md — Life Inbox

Guidance for humans and coding agents working in this repository.

## Startup

```bash
python3 -m pip install -r requirements.txt
export DATABASE_URL="sqlite:////absolute/path/to/temp_life_inbox.db"
export LIFE_INBOX_UPLOAD_DIR="/tmp/life_inbox_uploads"
python3 -m alembic upgrade head
python3 -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000

Optional AI:

```bash
export OPENAI_API_KEY="..."
export OPENAI_MODEL="gpt-5-mini"
```

## Tests

```bash
unset OPENAI_API_KEY
python3 -m pytest -v --tb=short
```

Tests use isolated temporary SQLite databases via `DATABASE_URL` and set
`LIFE_INBOX_AUTO_CREATE_TABLES=1`. They must not call live paid APIs; mock
OpenAI and other external services.

## Migrations

Alembic is the only schema-management mechanism for real databases.

```bash
python3 -m alembic upgrade head
python3 -m alembic current
```

Do not rely on SQLAlchemy `create_all` outside automated tests.
`LIFE_INBOX_AUTO_CREATE_TABLES` is test-only.

## Architecture boundaries

- FastAPI app in `app/main.py`
- Persistence / domain writes in `app/database.py`
- Pydantic contracts in `app/schemas.py`
- Organization / AI in `app/organizer.py`
- Rich capture in `app/capture/` (`POST /api/items/url`, `/pdf`, `/image`, `/voice`)
- Retrieval / Ask in `app/retrieval/` (`GET /api/search`, `POST /api/ask`)
- Attention / reminders in `app/attention/` (`GET /api/attention`, `/api/briefing`)
- Calendar adapter in `app/integrations/calendar.py` (preview + mock confirm only)
- Auth / ownership in `app/auth.py` + `users.owner_user_id` scoping
- Config validation in `app/config.py`; deploy notes in `docs/deployment.md`
- Browser UI: `app/templates/index.html`, `app/static/*`
- Canonical API: `/api/items`, `/api/analyze`, `/api/tasks`
- Deprecated adapter: `/api/notes`

Prefer extending this stack. Do not introduce React, Vue, Kubernetes,
microservices, or a vector database without a demonstrated product need.

## Data safety

- Never use a real personal Life Inbox database for development or testing.
- Never commit secrets, API keys, OAuth tokens, generated DBs, or private uploads.
- Schema changes go through Alembic migrations.
- Distinguishing original source text, extracted text, AI-inferred content, and
  user-confirmed information is required as those features appear.
- External actions require explicit user confirmation.

## Git

- Milestone branches: `milestone/1-polished-core`, `milestone/2-...`, etc.
- Annotated tags: `milestone-1`, `milestone-2`, ...
- No force-push; no destructive history rewrites.
- Fix regressions on the newest cumulative milestone branch and add a test.

## Definition of done (per milestone)

1. Full pytest suite green
2. Migrations from empty DB succeed
3. App starts against a temp DB
4. Primary API + browser flows exercised
5. Docs updated (`docs/*`, this file)
6. No secrets in the diff
7. Milestone report written with exact run commands
