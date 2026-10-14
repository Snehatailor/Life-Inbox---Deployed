# AGENTS.md — Life Inbox

Instructions for AI coding agents working with a sprint team on this repository.

Read this file before changing code. The student quick start is `README.md`. The team’s product direction is `BUILD_SPRINT.md`.

When the student is unfamiliar with the relevant code, explain the current path in plain language before proposing changes. Do not assume framework knowledge.

## 1. Before changing anything

- Read `README.md` and `BUILD_SPRINT.md`.
- Inspect the code that the request actually touches.
- Run the existing tests and read the failures before editing.
- Understand the current behavior you might change.

The team forked latest `main` and is building its own version. Do not invent a milestone branch, a tag workflow, or a second product backlog.

## 2. Engineering loop

Inspect → Plan → Implement → Test → Review.

Explain the existing behavior and the smallest plan. Wait for approval when the team asked you to wait. Then implement in small steps.

## 3. Change discipline

- Prefer a small change that finishes one behavior.
- Do not rewrite the app when a local change will do.
- Do not introduce React, Vue, a vector database, microservices, or Kubernetes without a demonstrated product need.
- Preserve working behavior unless the requested change deliberately changes it.
- The browser UI is server-rendered HTML plus `app/static/`. Extend that stack unless the team has a reason to leave it.

## 4. Architecture boundaries

| Area | Where it lives |
| --- | --- |
| HTTP API and pages | `app/main.py` |
| Saved records and writes | `app/database.py` |
| Request and response contracts | `app/schemas.py` |
| Inbox organization | `app/organizer.py` (OpenAI when `OPENAI_API_KEY` is set, otherwise a built-in organizer) |
| URL, PDF, image, voice | `app/capture/` |
| Search and Ask | `app/retrieval/` (local retrieval; Ask uses a model only when a key is set, then falls back) |
| Attention, dates, briefing | `app/attention/` |
| Calendar | `app/integrations/calendar.py` (preview; confirm is a local mock unless a team deliberately builds a real integration) |
| Sessions and ownership | `app/auth.py`, `owner_user_id` on owned records. See “Multi-user isolation” below. |
| Settings | `app/config.py` |
| Browser UI | `app/templates/index.html`, `app/static/` |

Canonical routes include `/api/items`, `/api/analyze`, `/api/tasks`, `/api/search`, and `/api/ask`. `/api/notes` is a deprecated adapter over the same items. Deeper notes are in `docs/architecture.md`.

Local defaults when variables are unset: SQLite at `sqlite:///./data/life_inbox.db` (Alembic’s `alembic.ini` uses `sqlite:///data/life_inbox.db` from the repo root), uploads in `data/uploads/`, `LIFE_INBOX_ENV=local`. Dev Login is **on** unless `LIFE_INBOX_ALLOW_DEV_LOGIN` is `false`, `0`, or `no`. The student quick start turns it off for the first run and documents how to turn it on. It is passwordless local sign-in, not production authentication. The process does not load a `.env` file.

On your own laptop, at `127.0.0.1` only, an unset `LIFE_INBOX_SESSION_SECRET` may use the built-in local default. If the app is reachable by another person, or it is deployed, set a private `LIFE_INBOX_SESSION_SECRET` and do not commit it.

Image OCR needs the Tesseract binary and `pytesseract`, which are not in `requirements.txt`. Image descriptions stay on the local fallback; the vision path does not call OpenAI. Whisper runs only when `OPENAI_API_KEY` is set (`OPENAI_TRANSCRIPTION_MODEL`, default `whisper-1`).

## 5. Data and AI safety

- Do not commit secrets, API keys, OAuth tokens, database files, or uploads.
- Do not use a real personal inbox database for development or testing.
- Keep the original capture (raw text, source URL, or stored file) before fragile extraction or model calls.
- Keep original text, extracted text, AI-derived fields, and user-confirmed fields distinct. User corrections outrank model output.
- Do not take a consequential external action (sending data to a calendar, account, or other service) without an explicit user confirmation step.
- Do not turn on real Google Calendar writes by default. The baseline confirm path stores a local mock receipt. If a team explicitly chooses a real calendar integration, require explicit user confirmation, keep secrets in environment variables, commit no credentials, mock the external calls in automated tests, and keep a local or fallback mode that does not write to Google.

## 6. Multi-user isolation

With Dev Login on, each email is a separate owner. With it off, in local mode, requests use the Local Owner. Outside local mode, a request with no owner fails closed (401). It must not fall back to Local Owner.

- Collection queries must be scoped to the current owner.
- Direct-ID reads and writes must verify ownership. A foreign id is not found, and the response must not include the other person’s data.
- Derived data is private user data too.
- Insights, analysis, relations, search evidence, Ask context, tasks, reminders, uploads, and dashboard aggregates must stay owner-scoped.
- An item relation may only connect two items owned by the same user.
- Derived tables without their own `owner_user_id` inherit ownership through their parent records. Do not query them globally.
- New user-facing persistence should get two-user isolation tests when applicable. `tests/test_isolation.py` must stay green.

## 7. Database

Alembic is the only schema mechanism. Add a revision under `migrations/versions/`. Apply it with `python -m alembic upgrade head`.

Do not hand-edit the SQLite file to change schema. Do not call SQLAlchemy `create_all` outside automated tests. `LIFE_INBOX_AUTO_CREATE_TABLES=1` is test-only.

## 8. Testing

- Run the current tests before you change behavior.
- Add or update tests for important behavior you change.
- Run the relevant tests after the change.
- Tests must not call live paid APIs. Mock OpenAI and other external services.
- Tests already use temporary SQLite databases. Do not point them at a personal database.

```bash
unset OPENAI_API_KEY
python -m pytest -q --tb=short
```

On Windows PowerShell, clear a key with `Remove-Item Env:OPENAI_API_KEY` if it is set.

## 9. Before saying done

Completion is a claim. Verification is evidence.

Before you say the work is done:

- relevant tests pass, and you report the command and the result
- you describe what a person should click or call to verify it
- migrations apply from an empty database when the schema changed
- the diff contains no secrets, databases, or uploads
- you summarize what changed, what you tested, what still fails, and what you did not change
