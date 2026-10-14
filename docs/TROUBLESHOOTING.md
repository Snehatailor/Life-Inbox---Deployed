# Troubleshooting

Start here when the README quick start does not match what you see. Run commands from the `life-inbox` folder with `.venv` activated, unless a step says otherwise.

## Python 3.12 not found / wrong Python

**What you may see:** `command not found`, `Python was not found`, or a version such as 3.11 or 3.13.

**What it means:** This class uses Python 3.12. A different `python` or `python3` on the machine will build the project wrong.

**Run this:**

macOS and Linux:

```bash
python3.12 --version
```

Windows PowerShell:

```powershell
py -3.12 --version
```

**Expected result:** `Python 3.12.x`.

**Still stuck?** Install 3.12 from [python.org](https://www.python.org/downloads/) or the method your instructor gave you. Close the terminal, open a new one, and run the version command again. On macOS, `python3` is often not 3.12. Create `.venv` with `python3.12`, not `python3`, unless `python3 --version` itself prints 3.12.

## Virtual environment not activated

**What you may see:** `python --version` is not 3.12, or `python -m alembic` says `No module named alembic`. The prompt has no `(.venv)`.

**What it means:** The shell is using some other Python, not the one you created for this project.

**Run this:**

macOS and Linux:

```bash
source .venv/bin/activate
python --version
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python --version
```

If Windows says running scripts is disabled, this lasts only for the current window:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

If you created `.venv` before Python 3.12 was available, remove it and create it again.

macOS and Linux:

```bash
rm -rf .venv
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Windows PowerShell:

```powershell
Remove-Item -Recurse -Force .venv
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

**Expected result:** `Python 3.12.x`, and the prompt often shows `(.venv)`.

**Still stuck?** You are probably in the wrong folder. `cd` into the cloned `life-inbox` folder and try the activate command again.

## Dependency installation failure

**What you may see:** `pip` prints an error, or a later command cannot import `fastapi` or `alembic`.

**What it means:** The packages in `requirements.txt` are not installed into this `.venv`, or the install was interrupted.

**Run this** with `.venv` active, from the repo folder:

```bash
python -m pip install -r requirements.txt
```

**Expected result:** the command ends without an error. The last lines usually say a package was successfully installed.

**Still stuck?** If the error mentions a network timeout, run the same command again. If it says you are not allowed to write to a system Python path, `.venv` is not active. Do not use `sudo`.

## Port 8000 already in use

**What you may see:** Uvicorn says the address is already in use, or the browser shows an old page you do not recognize.

**What it means:** Something is already listening on port 8000, often a server you started earlier.

**Run this:**

macOS and Linux:

```bash
lsof -i :8000
```

Windows PowerShell:

```powershell
netstat -ano | findstr :8000
```

If that process is a Uvicorn you started, go to that terminal and press Control+C. If you do not recognize the process, ask a teammate before stopping it. Then:

```bash
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

**Expected result:** `Uvicorn running on http://127.0.0.1:8000`.

**Still stuck?** A second terminal may still be running the server. Check each terminal window before you start another one.

## Alembic / database problems

**What you may see:** `No module named alembic`, `No config file 'alembic.ini'`, `database is locked`, or the app says a table does not exist.

**What it means:** The tables were not created, Alembic ran in the wrong folder, or it is talking to a different database file than the app.

**Run this** from the `life-inbox` folder, with `.venv` active:

```bash
python -m alembic upgrade head
python -m alembic current
```

**Expected result:** `upgrade head` finishes without an error. The output of `current` includes `(head)`.

**Still stuck?**

| What you see | What it means | What to do |
| --- | --- | --- |
| `No module named alembic` | `.venv` is not active, or requirements are not installed | Activate `.venv` and install requirements again. |
| `No config file 'alembic.ini'` | You are not in the repo folder | `cd` into `life-inbox` and retry. |
| `database is locked` | The server has the file open | Stop Uvicorn with Control+C, then run Alembic again. |
| Tables missing, or “no such table” | Alembic and the app are not using the same file | See the variable check below. |

The app and Alembic share `data/life_inbox.db` only when `DATABASE_URL` is unset and you run both from the repo folder.

macOS and Linux:

```bash
echo "$DATABASE_URL"
```

Windows PowerShell:

```powershell
echo $env:DATABASE_URL
```

Empty output means you are on the default file. If it prints a path you did not choose, unset it and run Alembic again.

macOS and Linux:

```bash
unset DATABASE_URL
python -m alembic upgrade head
```

Windows PowerShell:

```powershell
Remove-Item Env:DATABASE_URL
python -m alembic upgrade head
```

Do not point `DATABASE_URL` at a database that contains someone else’s real notes.

## Server starts but the browser does not load

**What you may see:** the terminal looks busy, but the browser cannot open the page, or a refresh loses a note you just saved.

**What it means:** the address is wrong, the server did not finish starting, or the browser and the database are not the same file.

**Run this:** look at the server terminal. It must still be running. In the browser open <http://127.0.0.1:8000> with `http`, not `https`, and not another port.

**Expected result:** you see `Uvicorn running on http://127.0.0.1:8000` and later `Application startup complete`. The page title is Life Inbox.

**Still stuck?** If the terminal shows a traceback, copy it from the first `Error` or `Traceback` line. If it mentions SQLite or Alembic, use the database section above. If a refresh loses a note, stop the server, unset a surprise `DATABASE_URL`, run `python -m alembic upgrade head` again, and start Uvicorn in that same terminal.

## OpenAI key issues

**What you may see:** organization uses simple rules, Ask quotes passages instead of writing a new answer, or a voice note has no automatic transcript. Or a command fails because a key was pasted into a file.

**What it means:** No key is a valid way to run the app. A key is needed only for live organization, model-written Ask answers, and Whisper. The app does not read `.env` or `.env.example`.

**Run this** in the same terminal where you will start Uvicorn, then start the server again:

macOS and Linux:

```bash
export OPENAI_API_KEY="your-api-key"
```

Windows PowerShell:

```powershell
$env:OPENAI_API_KEY="your-api-key"
```

**Expected result:** after restart, **Analyze Entire Inbox with AI** can call the model. Without the variable, the built-in organizer, search, and extractive Ask still work.

**Still stuck?** Do not commit a key, do not put it in source code, and do not paste it into a coding-agent conversation. Image text recognition is separate: without the Tesseract program and `pytesseract` (not in `requirements.txt`), OCR text stays empty and the image description stays a local summary.

## Tests fail

**What you may see:** `python -m pytest` reports `failed`, or the failure names a file your team changed.

**What it means:** A behavior the tests already cover does not match the code now. Read the last failure, not only the final count.

**Run this** from the repo folder, with `.venv` active:

macOS and Linux:

```bash
unset OPENAI_API_KEY
python -m pytest -q --tb=short
```

Windows PowerShell:

```powershell
Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue
python -m pytest -q --tb=short
```

**Expected result:** a summary line that says `passed` and does not say `failed`.

**Still stuck?** The tests create temporary databases. They do not need your `data/life_inbox.db`. Compare the failing file with `git diff`. If the failure started after an agent edit, use the next section.

## Coding agent changed too much / broke working behavior

**What you may see:** the app no longer does something that worked, and `git status` lists more files than you expected.

**What it means:** The agent edited beyond the approved plan. Look at the evidence before you keep or delete the edit.

**Run this:**

```bash
git status
git diff
python -m pytest -q --tb=short
```

If an uncommitted file should go back to the last commit, and you are sure you do not want those edits:

```bash
git restore path/to/file
```

**Expected result:** `git status` lists only the files you meant to change, and the relevant tests pass.

**Still stuck?** Ask a teammate before restoring a file you do not understand. Do not use destructive history commands to “clean up”. Tell the agent what the diff and the test output showed, and ask for a smaller change.

## Basic Git confusion

**What you may see:** you cannot find your teammates’ commits, or `git status` mentions a branch you did not choose.

**What it means:** You may have cloned the instructor repository, or your own extra fork, instead of the team fork. One team uses one fork. Everyone clones that fork.

**Run this** from the `life-inbox` folder:

```bash
git status
git remote -v
```

**Expected result:** `git status` shows you are on `main`. `git remote -v` shows the team fork, the GitHub account that created it, not a second personal fork and not only `AI-WORKSHOP-SEP26/life-inbox` unless that person is the fork owner.

**Still stuck?** Stop making commits in the wrong copy. Clone the team fork again using the URL from that repository’s green **Code** button. Accept the collaborator invite first if GitHub refused the clone.

## Still stuck after this page?

Make the failure happen again. Copy the exact error, without API keys or private notes. Ask one teammate, then send the Doubts / Blocker Form with what you tried and what you saw:

<https://docs.google.com/forms/d/e/1FAIpQLSctcIFbwPS9LUeC3wZethUUlseoJXyaX6bO-G7DdWZtoswkMA/viewform>
