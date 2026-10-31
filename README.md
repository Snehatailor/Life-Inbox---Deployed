# Life Inbox

Life Inbox is a small web app for capturing things you want to remember and organizing them later. You can save text, links, PDFs, images, and voice notes. You can sort them into topics and tasks, search them, and ask questions that cite your own items.

This repository is a working starting point, not a finished product. Your team may change the product, the interface, or the structure when you have a reason.

**Just want to run it?** See [`docs/RUNNING.md`](docs/RUNNING.md): short steps for Windows, macOS and Linux.

**If you use Cursor or another coding agent, first tell it to read `AGENTS.md`.** The copy-paste prompts are in the next section. The run steps are immediately after that.

You do not need to understand the entire codebase before your first change. Ask the coding agent to explain only the part involved in what you are trying to build.

## If you use a coding agent

Paste this first:

```text
Read AGENTS.md first.

Then inspect this repository and explain Life Inbox to me in simple language.

Tell me:
1. what the product currently does,
2. how the frontend, backend and database fit together,
3. where AI is currently used,
4. how to run the app,
5. how to run the tests.

Do not change any code yet.
```

When you have an idea, paste this before any edits:

```text
I want to improve Life Inbox in the following way:

<describe the idea in plain English>

First inspect the existing implementation.

Before changing code:
1. explain what already exists,
2. propose the smallest sensible implementation,
3. tell me which parts of the system will change,
4. explain important product or engineering trade-offs,
5. explain how we will verify it works.

Do not modify files yet. Wait for my approval.
```

After you approve the plan:

```text
Proceed with the approved plan.

Work in small, verifiable steps.
Preserve existing working behavior.
Add or update tests for important behavior.
Run relevant tests.

When finished, tell me:
1. what changed,
2. what you tested,
3. what still does not work,
4. what I should manually verify.
```

A coding agent can help you with no OpenAI key. See “Two kinds of AI” below.

## Team setup

Teams are 5–6 students. One team uses one fork.

1. One teammate creates the fork.
2. That person adds every teammate as a collaborator.
3. Also add Tarun (GitHub: `tmiiitd`) as a collaborator.
4. Everyone else accepts the invite and clones that same fork.

Do not each make your own fork.

**Team Registration Form:** <https://docs.google.com/forms/d/e/1FAIpQLSdUe0jSuUQSnbed5FXjFH_cuydNIl9CxYICpYa9Rqd-bgXUGg/viewform>

If you are not in a registered team, the instructor will assign you to one.

The 10-day sprint is described in `BUILD_SPRINT.md`.

## New here? Start with these steps

The path is: fork → clone → run → understand → improve → test → demo. You always start from the latest `main`.

### 1. Fork as a team

One teammate opens <https://github.com/AI-WORKSHOP-SEP26/life-inbox> and clicks **Fork**. That person’s GitHub account holds the team repository.

On the fork, open **Settings → Collaborators → Add people**. Invite every teammate, and invite Tarun (`tmiiitd`). Everyone accepts the invite.

### 2. Clone the team’s fork

macOS and Linux:

```bash
git clone https://github.com/TEAM_FORK_OWNER/life-inbox.git
cd life-inbox
```

Windows PowerShell:

```powershell
git clone https://github.com/TEAM_FORK_OWNER/life-inbox.git
cd life-inbox
```

Replace `TEAM_FORK_OWNER` with the GitHub username that created the fork. After clone you are on the latest `main`. That is the starting point.

### 3. Open a terminal in the repo

The prompt should be inside the `life-inbox` folder before every later command. Check:

macOS and Linux:

```bash
ls README.md
```

Windows PowerShell:

```powershell
dir README.md
```

You should see `README.md`. If the command cannot find it, `cd` into the folder you cloned.

### 4. Verify Python 3.12

This class uses Python 3.12. Stop if you do not see a version that starts with `3.12`. Install 3.12, then open a new terminal. Details are in `docs/TROUBLESHOOTING.md`.

macOS and Linux:

```bash
python3.12 --version
```

Windows PowerShell:

```powershell
py -3.12 --version
```

Expected: `Python 3.12.x`. A “command not found” message, or any other version, means stop.

### 5. Create and activate a virtual environment

A virtual environment (`.venv`) is a Python just for this project.

macOS and Linux:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python --version
```

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python --version
```

Expected: `Python 3.12.x` again. Your prompt often shows `(.venv)`. If `python --version` is not 3.12, the environment was created with the wrong interpreter. Stop and use `docs/TROUBLESHOOTING.md`.

### 6. Install dependencies

With `.venv` still active:

```bash
python -m pip install -r requirements.txt
```

Expected: the command ends without an error. The last lines usually say a package was successfully installed.

### 7. Local settings for the first run

You do not need a database URL, an upload folder, or an API key to start.

From this folder, with those variables left unset:

- the database file is `data/life_inbox.db`
- uploads go in `data/uploads/`

Both paths are ignored by Git. Run Alembic and Uvicorn from this folder so they use those files.

**Dev Login stays off for the first run.** It is a passwordless sign-in box, not a real account system. With it off, the header shows `Local Owner <local@life-inbox.local>` and every note you save stays in that one local inbox. In the same terminal you will use to start the server:

macOS and Linux:

```bash
export LIFE_INBOX_ALLOW_DEV_LOGIN=false
```

Windows PowerShell:

```powershell
$env:LIFE_INBOX_ALLOW_DEV_LOGIN="false"
```

The page can still show the Dev login box. Clicking **Sign in** should then say that sign-in failed because dev login may be disabled. You can save notes without that box.

The app does not read a `.env` file. Editing `.env.example` does nothing until you export the variable in the terminal. If the variable is unset, the code turns Dev Login **on**. That is why the first-run commands set it to `false`.

**Turn Dev Login on only if your team wants separate inboxes on one computer.** Stop the server, then in that same terminal:

macOS and Linux:

```bash
export LIFE_INBOX_ALLOW_DEV_LOGIN=true
```

Windows PowerShell:

```powershell
$env:LIFE_INBOX_ALLOW_DEV_LOGIN="true"
```

Start the server again. Type an email and click **Sign in**. A second person uses a different browser profile (or an incognito window), signs in with a different email, and sees none of the first person’s notes, tasks, search results, or dashboard. There is no password. Do not treat this as production login.

**Secrets.** Never commit an API key. Never put one in source code. Never paste one into a coding-agent conversation. Put secrets in environment variables only, in the terminal that starts the app.

On your own laptop, with the app open only at `127.0.0.1`, you may leave `LIFE_INBOX_SESSION_SECRET` unset. The app uses a built-in local value. If another person can open the app, or you deploy it, set a long private `LIFE_INBOX_SESSION_SECRET` in the environment and do not commit it.

### 8. Create the database tables

Alembic is the tool that creates the tables. The app does not create them when it starts.

```bash
python -m alembic upgrade head
python -m alembic current
```

Expected: `upgrade head` finishes without an error. The output of `current` includes `(head)`.

### 9. Start Uvicorn

Uvicorn is the program that serves the app.

```bash
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Expected: a line like `Uvicorn running on http://127.0.0.1:8000`. Leave this terminal open. Stop the server later with Control+C.

The `export` or `$env:` from step 7 must be in this same terminal. A new terminal does not keep it.

### 10. Open the app

In a browser, open <http://127.0.0.1:8000>.

Expected: a page titled Life Inbox, with a large text box and an **Add Note** button.

### 11. Create a test note and refresh

Type a sentence in the large text box. Click **Add Note**. The sentence appears under **Raw saved notes**. Refresh the browser. The sentence is still there.

### 12. Run the tests

Open a second terminal. `cd` into the repo, activate `.venv` the same way as step 5, then:

```bash
python -m pytest
```

Expected: a summary line that says `passed` and does not say `failed`. The tests use temporary databases and do not call OpenAI. You can leave the server running in the first terminal.

## Setup worked if...

- Life Inbox loads in the browser
- I can create a text item
- Refresh does not lose it
- `python -m alembic current` shows `(head)`
- `python -m pytest` passes

If one of these fails, use `docs/TROUBLESHOOTING.md`.

## Two kinds of AI

These are independent.

**A coding assistant** (Cursor, Claude Code, Gemini, Copilot, ChatGPT, or another tool) edits this project with you. It does not need `OPENAI_API_KEY`. Tell it to read `AGENTS.md` first.

**AI inside Life Inbox** is optional. If you export `OPENAI_API_KEY`, some features call OpenAI. Never commit that key, never put it in source code, and never paste it into a coding-agent conversation. Set it only as an environment variable.

Without a key, these still work:

- save, edit, and delete text notes
- save a public `http` or `https` link (the app fetches the page; localhost links are rejected)
- upload a text-based PDF and read extracted text
- upload an image and see a thumbnail; image descriptions stay on a local summary
- upload or record a voice note, play it, and type a transcript yourself
- **Analyze Entire Inbox with AI** uses a built-in organizer: rules in the code, not a model
- topics, saved tasks, search, and filters
- **Ask My Inbox** quotes matching passages from your inbox and cites them
- the Attention board, in-app reminders, and a calendar preview you confirm on this computer

A key adds three calls:

- live organization (`OPENAI_MODEL`, default `gpt-5-mini`)
- Ask answers written by a model from those same passages, still with citations (`OPENAI_MODEL`)
- automatic voice transcript through Whisper (`OPENAI_TRANSCRIPTION_MODEL`, default `whisper-1`)

If a live call fails, organization and Ask fall back to the no-key behavior.

Image text recognition is separate from the API key. It needs the Tesseract program and the `pytesseract` package, which are not in `requirements.txt`. Without them, the image still uploads and the description stays local. Image “vision” does not call a model, even when a key is set.

Optional, in the same terminal as Uvicorn:

macOS and Linux:

```bash
export OPENAI_API_KEY="your-api-key"
export OPENAI_MODEL="gpt-5-mini"
export OPENAI_TRANSCRIPTION_MODEL="whisper-1"
```

Windows PowerShell:

```powershell
$env:OPENAI_API_KEY="your-api-key"
$env:OPENAI_MODEL="gpt-5-mini"
$env:OPENAI_TRANSCRIPTION_MODEL="whisper-1"
```

## What you are starting from

You can capture text, URLs, PDFs, images, and voice. **Analyze Entire Inbox with AI** groups items and creates tasks that stay in the database. You can add topics yourself. Search and filters narrow the saved list. Ask My Inbox answers from your items and shows sources. Attention groups open tasks by time. Reminders stay in the app. Calendar preview asks you to confirm; the default confirmation is a mock receipt on this computer, not a Google Calendar write.

Some of this is rough. The screen is crowded. Analysis looks at the whole inbox. Dates, categories, and duplicates can be wrong. That is the point of the sprint: pick a direction and make a coherent product. Read `BUILD_SPRINT.md`.

Deeper behavior, routes, and tables are in `docs/architecture.md`. A longer browser checklist is in `docs/manual-testing.md`. Hosting is in `docs/deployment.md` and is not part of the first run.

While the server is stopped, `python -m scripts.seed_demo_notes` can insert sample notes. With no API key it uses a built-in list.

## Repository layout

```text
life-inbox/
├── app/
│   ├── main.py            # HTTP routes
│   ├── database.py        # saved items, tasks, topics
│   ├── schemas.py         # request and response shapes
│   ├── organizer.py       # live or built-in organization
│   ├── auth.py            # session cookie and dev login
│   ├── config.py          # environment defaults
│   ├── attention/         # dates, attention, briefing
│   ├── capture/           # URL, PDF, image, voice
│   ├── integrations/      # calendar preview and mock confirm
│   ├── retrieval/         # search and Ask
│   ├── templates/index.html
│   └── static/            # browser JavaScript and CSS
├── migrations/versions/   # database revisions applied by Alembic
├── tests/
├── docs/
├── AGENTS.md              # rules for coding agents
├── BUILD_SPRINT.md        # 10-day team sprint
├── README.md
├── requirements.txt
├── alembic.ini
└── .env.example
```
