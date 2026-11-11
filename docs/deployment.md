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

## Email + password accounts

`POST /api/auth/register` and `POST /api/auth/login` take
`{"email", "password"}` (register also takes an optional `display_name`).
Passwords are at least 8 characters and are stored only as salted scrypt
hashes in `users.password_hash`. Ten failed sign-ins for one email within 15
minutes return 429 until the window passes (in-memory, per process).
`GET /api/auth/config` tells the page which sign-in options to show.

Set `LIFE_INBOX_AUTH_MODE=password` with `LIFE_INBOX_ENV=beta` for a public
deployment: anonymous visitors see only the sign-in form, and every account
gets its own private inbox.

## Sign in with Google

Off until both `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` are set; then a
**Continue with Google** button appears on the sign-in screen.

1. In Google Cloud Console → APIs & Services → Credentials, create an
   **OAuth client ID** of type **Web application**.
2. Add the authorized redirect URI
   `https://<your-service>.onrender.com/api/auth/google/callback`.
3. On the OAuth consent screen, add the `openid`, `email` and `profile`
   scopes. While the app is in "Testing", only listed test users can sign in;
   publish it to let anyone with a Google account sign in.
4. Set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` and (recommended)
   `GOOGLE_REDIRECT_URI` to that same callback URL in the service's
   environment. Never commit them.

Only Google accounts with a verified email are accepted. Signing in with
Google uses the existing account with that email, if there is one.

## Render (web service + Postgres)

| Setting | Value |
| --- | --- |
| Runtime | Python, `PYTHON_VERSION=3.12.10` |
| Build command | `pip install -r requirements.txt` |
| Start command | `python -m alembic upgrade head && python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips "*"` |
| Health check path | `/api/health` |

Environment: `LIFE_INBOX_ENV=beta`, `LIFE_INBOX_AUTH_MODE=password`,
`LIFE_INBOX_ALLOW_DEV_LOGIN=0`, a random 32+ character
`LIFE_INBOX_SESSION_SECRET`, `DATABASE_URL` set to the Render Postgres
internal URL (a `postgres://` URL is converted to `postgresql+psycopg://`
automatically), and `LIFE_INBOX_UPLOAD_DIR=/tmp/life_inbox_uploads`.

Without a persistent disk, uploaded PDF, image and audio files are lost
when the service restarts or redeploys. Their extracted text stays in
Postgres. Attach a Render disk and point `LIFE_INBOX_UPLOAD_DIR` at it to
keep the files.

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
