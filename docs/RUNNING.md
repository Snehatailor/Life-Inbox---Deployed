# Running Life Inbox on your laptop

Works on **Windows, macOS and Linux**. Each laptop runs its own copy with its own data.
This is the short version; the README has the long, step-by-step one and
`docs/TROUBLESHOOTING.md` covers problems.

## Before you start

- **Access:** the repository is private. Ask the owner to add you under
  *Settings → Collaborators*, then accept the invite. Without it, `git clone` says the
  repository was not found.
- **Python 3.12** (python.org; on Windows tick **Add python.exe to PATH**). 3.13 and
  newer are not what the project is built and tested on.
- **Git**.
- Optional, for the desktop pet only: **Node.js LTS** (nodejs.org).

## Run the app

### Windows (PowerShell)

```powershell
git clone https://github.com/swarnavjena0212/life-inbox_sj.git
cd life-inbox_sj
py -3.12 -m venv .venv
```

Turn the environment on. If Windows says running scripts is disabled, run the first line
too (it only lasts for this window):

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

```powershell
python -m pip install -r requirements.txt
$env:LIFE_INBOX_ALLOW_DEV_LOGIN="false"
python -m alembic upgrade head
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### macOS / Linux

```bash
git clone https://github.com/swarnavjena0212/life-inbox_sj.git
cd life-inbox_sj
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
export LIFE_INBOX_ALLOW_DEV_LOGIN=false
python -m alembic upgrade head
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### Then

Open <http://127.0.0.1:8000> in Chrome or Edge. Leave the terminal open; stop with
**Ctrl+C**.

The environment variable (`LIFE_INBOX_ALLOW_DEV_LOGIN`) only lasts for the terminal
window it was set in. Set it again in any new window before starting the server. When the
project is updated later, run `python -m alembic upgrade head` again before starting.

## Optional: the roaming desktop pet

Keep the app running, then open a **second** terminal:

```bash
cd desktop-pet
npm install
npm start
```

The pet appears at the bottom of your screen. Tap it for notes and reminders. Quit it from
the tray / menu-bar icon. See `desktop-pet/README.md`.

Another address? In PowerShell: `$env:LIFE_INBOX_URL="http://127.0.0.1:9000"` then
`npm start`. On macOS/Linux: `LIFE_INBOX_URL=http://127.0.0.1:9000 npm start`.

It has been built and tested on macOS. Transparent, always-on-top, click-through windows
are supported on Windows too, but it is untested there; native notification pop-ups on
Windows may need extra settings, so rely on the pet's speech bubble.

## Good to know

- **Your data is a file on your laptop** (`data/life_inbox.db`), not shared with anyone.
- **The team leaderboard needs one shared server.** If everyone runs their own copy, each
  person is a team of one. For a shared board, one machine (or a hosted copy) must run the
  server and everyone opens its address.
- **An OpenAI key is optional.** Without it everything works except the AI analysis and
  audio transcription (see the README for the `OPENAI_API_KEY` setting).
- **Voice dictation** needs Chrome or Edge and microphone permission.
- **Run the tests** (with the environment on): `python -m pytest -q`. The pet's logic tests
  also need Node and skip themselves if it is missing.

## If something goes wrong

| Problem | Try |
| --- | --- |
| `git clone` says not found | You are not a collaborator yet, or you are signed in to the wrong GitHub account |
| `py` / `python3.12` not found | Install Python 3.12 and open a **new** terminal |
| `Activate.ps1` is blocked | Run the `Set-ExecutionPolicy -Scope Process …` line above |
| `No module named …` | The environment is not on, or `pip install -r requirements.txt` was skipped |
| Page loads but shows errors | Run `python -m alembic upgrade head`, then restart the server |
| Port 8000 is busy | Use `--port 8001` and open that address instead |
| The pet says "Is Life Inbox running?" | Start the server first; the pet needs it |
