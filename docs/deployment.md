# Deployment guide (private beta foundation)

This milestone adds a **minimum responsible** multi-user beta foundation.
It intentionally stops before paid infra, real Google OAuth consent, or
public production deploy unless an owner explicitly authorizes those steps.

## Environments

| Env | DB | Auth | Notes |
| --- | --- | --- | --- |
| `local` (default) | SQLite | Dev login is passwordless and on unless set to false; anonymous maps to local owner | Temp DBs for agents/tests. The student quick start turns Dev Login off until a team wants separate inboxes. |
| `beta` | PostgreSQL required | Dev login must be off; anonymous API calls get 401 | Signed session cookies |
| `production` | PostgreSQL required | Same as beta | Not enabled in this teaching build |

## Ownership and isolation

Every request is bound to exactly one owner by the HTTP middleware in
`app/main.py`:

- A valid signed session for an existing user binds that user.
- `LIFE_INBOX_ENV=local` with no valid session binds the Local Owner
  (`local@life-inbox.local`). Signing out in local mode returns you to it.
- Any other environment with no valid session returns 401 for every `/api/*`
  route except `/api/health` and `/api/auth/*`. Nothing falls back to Local
  Owner.

`require_owner_id()` in `app/database.py` raises when no owner is bound.
`inbox_items`, `tasks`, `topics` and `analysis_runs` carry `owner_user_id`.
Derived rows are owned through their parents: `item_insights` via `item_id`,
`item_relations` only when both items share an owner, `task_source_items` and
`calendar_action_receipts` via their task. Foreign ids behave as not found
(404). `tests/test_isolation.py` covers both directions for every feature.

## Required environment variables

```bash
LIFE_INBOX_ENV=local|beta|production
DATABASE_URL=sqlite:////tmp/life_inbox.db   # or postgresql+psycopg://...
LIFE_INBOX_UPLOAD_DIR=/data/uploads
LIFE_INBOX_SESSION_SECRET=<32+ random chars>   # required in beta/production
LIFE_INBOX_AUTH_MODE=dev|google_stub
LIFE_INBOX_ALLOW_DEV_LOGIN=1|0
LIFE_INBOX_TIMEZONE=UTC
LIFE_INBOX_MAX_UPLOAD_MB=5
LIFE_INBOX_CALENDAR_PROVIDER=mock|google
```

Optional: `OPENAI_API_KEY` for live organization only (never in automated tests).

## Local run

```bash
export DATABASE_URL="sqlite:////tmp/life_inbox_beta.db"
export LIFE_INBOX_UPLOAD_DIR="/tmp/life_inbox_uploads"
export LIFE_INBOX_SESSION_SECRET="local-dev-secret-at-least-32-chars!!"
unset OPENAI_API_KEY
python3 -m pip install -r requirements.txt
python3 -m alembic upgrade head
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Dev login:

```bash
curl -c cookies.txt -X POST http://127.0.0.1:8000/api/auth/dev-login \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","display_name":"You"}'
```

## Container / Postgres sketch

`docker-compose.yml` boots Postgres + the app image. It is for private
evaluation only. Before any shared beta:

1. Replace `LIFE_INBOX_SESSION_SECRET`
2. Keep `LIFE_INBOX_ALLOW_DEV_LOGIN=0`
3. Do **not** enable real Google OAuth until owner approval
4. Mount durable upload storage and database volumes
5. Take a backup before migrations

Install Postgres driver when using compose: `pip install 'psycopg[binary]'`
(or add to a private requirements overlay). The base `requirements.txt`
stays SQLite-friendly for local teaching.

## Migrations / backups / rollback

- Alembic is the only schema owner: `alembic upgrade head`
- Backup SQLite file or Postgres dump **before** upgrading
- Rollback of data-bearing revisions is disabled by design; restore from backup
- Uploads live under `LIFE_INBOX_UPLOAD_DIR` (local filesystem backend)

## Security / readiness checklist

- [ ] Session secret is unique and long
- [ ] Dev login disabled outside local
- [ ] Google OAuth still stubbed (`/api/auth/google/start` → 501)
- [ ] Calendar writes still disabled
- [ ] User A cannot read, change, or infer anything from User B's data (`tests/test_isolation.py`)
- [ ] Anonymous `/api/items` returns 401 in beta
- [ ] Health endpoint reports env + warnings
- [ ] No secrets committed; uploads/DBs gitignored
- [ ] Owner approval before public DNS / paid hosting / live OAuth

## What this milestone does **not** do

- Real Google sign-in / OAuth consent
- Object storage (S3) wiring
- Public internet deployment
- Purchases or paid managed services
