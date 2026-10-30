# Task Quest: gamified tasks plan

Branch: `game/task-quest` (from `main` @ 6b3681d)

## Status

| Phase | State |
|---|---|
| 0 Foundations | Done |
| 1 Dates and days left | Done |
| 2 Points and daily ring | Done |
| 3 Bin and backlog | Done |
| 4 Voice to task | Done (browser speech or typed; server transcription needs an OpenAI key) |
| 5 Google Calendar | Done in link mode: prefilled event links and .ics. Two-way sync needs OAuth or the connector |
| 6 Polish | Done: confetti, chime with mute, level bar, streak flame, how-it-works panel |
| 7 Drag and drop | Done: drop anywhere, domain/format board, task lanes and day strip |
| 8 Time slots | Done: "Find time" on High tasks, using busy times from an imported .ics (no Google sign-in needed); events open in Google Calendar to confirm |
| 9 Team leaderboard | Done: invite-code teams, opt-in weekly board, points/streak only |
| 10 Spoken briefing | Done: button, `B` shortcut and "what's due today?" typed or spoken |

## What already exists (we build on it)

- Tasks with `priority` (High/Medium/Low), `due_on`, `status`, `snoozed_until`, `reminder_at`, and complete/reopen/dismiss/snooze endpoints (`app/main.py`).
- Voice notes: `POST /api/items/voice`, `app/capture/voice_extract.py`, and a recorder in `app/static/app.js` (`voiceRecorder`).
- Calendar: `app/integrations/calendar.py`, with `/api/calendar/status|tasks|preview|confirm` and a Calendar screen.
- Weekly review (`app/review.py`) and the attention board (`app/attention/dates.py`).

## Game rules (decide once, used by every phase)

| Rule | Value |
|---|---|
| Points per task | High 30, Medium 20, Low 10 |
| Daily goal | 100 points. The ring fills as points accumulate; hitting 100 triggers a celebration |
| Early bonus | +5 if done 1+ day before the deadline |
| Overdue | Still scores, at 50% |
| Streak | Consecutive days that reach 100 |
| Days left | Computed live from `due_on` vs today: "3 days left", "Due today", "2 days overdue". Colour shifts green -> amber -> red as the deadline nears |

## Phases

### Phase 0: Branch and foundations (0.5 day)
- Branch created. Add migration `0013` with `tasks.completed_at`, `tasks.points_awarded` and `tasks.binned_at` (all nullable), plus a `point_events` table (owner, task, points, day).
- Put the scoring rules in one module, `app/game/scoring.py`, with unit tests.
- Done when: migration applies on a fresh DB; scoring tests pass.

### Phase 1: Meaningful dates and live days-left (1 day)
- When a task is created without a date, suggest one from priority (High +2d, Medium +5d, Low +10d) and from the dates the AI finds in the note. Keep the existing "confirm timing" flow so the user approves it.
- Server returns `days_left` and `urgency` (`safe | soon | due | overdue`) on every task.
- UI shows the live badge. The page recomputes at midnight and on tab focus, so no refresh is needed.
- Done when: a task due tomorrow reads "1 day left" and flips to "Due today" at midnight without reload.

### Phase 2: Points and daily progress to 100 (1 day)
- Completing a task writes a `point_events` row. `GET /api/game/today` returns points, goal, streak and the last 7 days.
- Add a progress ring and point counter to the Today screen. The ring animates on completion and shows a "+20" pop-up.
- Done when: completing High + Medium + Low + Low = 70 points, and the ring shows 70/100.

### Phase 3: Garbage bin with a backlog (1 day)
- Dragging (or a button on) a done task to the bin sets `binned_at`. It leaves the active list but stays in a **Backlog** screen with date, points and restore.
- Points are never lost when binned. Restoring doesn't re-award points.
- Done when: binned tasks vanish from Tasks, appear in Backlog, and the daily total is unchanged.

### Phase 4: Voice to task (1 day)
- A mic button on Tasks. It records, transcribes via the existing voice pipeline, and turns the sentence into a task. "Call the dentist Friday, high priority" gives text, priority High and the next Friday as the date.
- Browser speech recognition is the fallback when no OpenAI key is set.
- Done when: speaking one sentence creates a correct task with a confirmation toast.

### Phase 5: Google Calendar in the nav bar (1.5 days)
- New **Google Calendar** nav item showing upcoming events next to task deadlines in one view.
- Per-task "Add to Google Calendar" through the existing preview/confirm flow, so nothing is written without approval.
- Connection options: (a) OAuth in the app via `app/integrations/calendar.py`, or (b) the Google Calendar MCP connector for our own agent-side use. See below.
- Done when: a task with a deadline creates a calendar event after the user confirms.

### Phase 6: Polish and playtest (1 day)
- Sounds and confetti at 100, a streak flame, a level title ("Apprentice" to "Legend") by lifetime points, and an empty-state tour.
- Update docs and manual tests, then run the full test suite and open a PR.

### Phase 7: Drag and drop, sorted by domain and data format (2 days)
- **Drop anywhere** on the app: files, links, selected text, and several items at once. Today's capture box only takes one file at a time.
- **Format detection** (by MIME type and extension, not just the name): PDF, image, audio, link, text, spreadsheet/CSV, doc. Each gets its own icon and pipeline (the existing PDF, OCR and voice extractors).
- **Domain detection** (Work, Health, Finance, Study, Home, Social...): reuse `app/organizer.py` topics, plus keyword rules and the AI categoriser when a key is set. Low-confidence guesses go to an "Unsorted" tray for one-click confirmation.
- **Two-way sorting view:** an Inbox board grouped by **domain** (columns) with a **format** filter/chip row, switchable to group by format. Drag a card between domain columns to recategorise it; the app remembers the correction.
- **Task dragging:** drag a task to a priority lane (High/Medium/Low, which changes its points), to a date on the calendar (which sets its deadline), or to the bin.
- Done when: dropping a PDF, a screenshot and a link together creates three items, each in the right format and domain; moving one to another domain sticks after reload.

### Phase 8: Auto-suggested time slots for High tasks (1.5 days)
- Reads free/busy from Google Calendar (depends on Phase 5) and proposes 2-3 slots before each High task's deadline, sized by an estimate (default 45 min, editable).
- One tap books the slot through the existing preview/confirm flow. Nothing is booked without approval.

### Phase 9: Team leaderboard (2 days)
- Builds on multi-user ownership (migration 0011). Adds teams, an invite code, and a weekly leaderboard of points, streaks and tasks done.
- Privacy: only points and counts are shared, never task text. Opt-in per user.

### Phase 10: Spoken "what's due today?" (0.5 day)
- A button (and the "?" shortcut) reads out today's overdue and due tasks, plus points to go, using browser speech synthesis. Pairs with Phase 4 so you can ask by voice.

### Phase 11: More features (pick any; each is independent)
| Feature | What it does | Time |
|---|---|---|
| Daily quests | "Finish one High task before noon" gives bonus points | 1 day |
| Streak freeze | Spend points to protect a streak on a busy day | 0.5 day |
| Levels and badges | Titles by lifetime points; badges such as "5-day streak", "Inbox zero" | 1 day |
| Focus timer | Pomodoro on a task, with bonus points for finishing the session | 1 day |
| Recurring tasks | Daily/weekly repeats that regenerate when done | 1.5 days |
| Subtasks | Checklist inside a task; partial points as you tick | 1 day |
| Smart nudges | Browser notification when a deadline is close and you are under 100 | 1 day |
| Weekly game recap | Extend the weekly review with points, best day and streak | 0.5 day |
| Undo "oops" bin restore | Restore from the bin with the points kept | 0.5 day |
| Export | Download points history and backlog as CSV | 0.5 day |

## Time estimate

One developer working with a coding agent, full days including tests:

| Block | Phases | Time |
|---|---|---|
| Core game (rules, dates, points, bin) | 0-3 | 3.5 days |
| Voice and Google Calendar | 4-5 | 2.5 days |
| Polish and playtest | 6 | 1 day |
| **Subtotal (original brief)** | 0-6 | **7 days** |
| Drag and drop with domain/format sorting | 7 | 2 days |
| Time slots, leaderboard, spoken briefing | 8-10 | 4 days |
| **Total with everything above** | 0-10 | **13 days** |
| Optional extras | 11 | 0.5-1.5 days each, about 8.5 days for all |

Suggested order: 0, 1, 2, 3, 7, 4, 5, 6 for a playable demo in about 9 days, then 8, 10 and 9. Phase 8 can't start until Phase 5 is done. Estimates assume Google credentials are ready by Phase 5; waiting on Google approval can add days.

## MCPs and connectors

| Need | Option | Status |
|---|---|---|
| Google Calendar | **Google Calendar** connector (create/list/search events, suggest times) | Found in the registry, **not connected** |
| Voice to text | Speko (transcribe audio) is available, but the app already has Whisper and browser speech, so it is **not needed** | Skip |
| Planning docs | Google Drive connector is already attached | Optional |

Important: MCP connectors let *Claude* act on your calendar during development or as an assistant. They are not a way for the web app itself to call Google. The app's own integration (Phase 5a) needs Google OAuth credentials from you.

## What we can do with this (ideas beyond the brief)

- **Daily quests:** "Finish one High task before noon" for bonus points.
- **Streak and level system** with weekly review stats ("you hit 100 on 5 of 7 days").
- **Smart nudges:** when a deadline is within 24h and the ring is below 100, suggest the cheapest task that reaches the goal.
- **Calendar time-blocking:** auto-suggest a free slot for each High task (the connector has `suggest_time`).
- **Team mode:** shared leaderboard using the existing multi-user ownership.
- **Voice check-in:** "what's due today?" read aloud.

## Open questions

1. Is 100 points per day the goal for everyone, or should it scale with workload?
2. Should overdue tasks lose points or just score less (plan assumes 50%)?
3. Do you have Google OAuth client credentials, or should we start with the connector only?
