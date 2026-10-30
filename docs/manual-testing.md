# Manual testing / browser smoke checklist

Use a **temporary** database only.

```bash
export DATABASE_URL="sqlite:////tmp/life_inbox_manual.db"
unset OPENAI_API_KEY
python3 -m alembic upgrade head
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000

## Core smoke (Milestone 1+)

- [ ] Home page loads with capture box, analyze button, tasks, notes
- [ ] Save a note → it is sorted into a section (Sections screen) or waits under Inbox → Needs sorting
- [ ] Edit a note → text updates; analysis status becomes stale if prior analysis existed
- [ ] Delete a note → removed; linked orphan task disappears after analyze+delete
- [ ] Analyze Entire Inbox → buckets, todos, priority view, mode shown
- [ ] Reload page → latest analysis restored; tasks persist
- [ ] Complete / dismiss / reopen a task; filter by status
- [ ] Re-analyze after completing a task → task status unchanged
- [ ] Sidebar search finds notes and tasks (including done and deleted ones); Clear search hides the results
- [ ] With many notes, every section lists its items (up to 500 are loaded)
- [ ] After editing inbox post-analysis, stale banner / status appears
- [ ] Invalid empty note rejected with friendly status
- [ ] `/api/health` returns `{"status":"ok"}`

## Organization smoke (Milestone 2+)

- [ ] Sections lists Work, Finance, Health, Study, Home, Travel, Shopping, Social and Unsorted with open / item / done counts
- [ ] Drag a task or item onto another section; it stays there after reload
- [ ] Multi-action note creates multiple tasks from one source
- [ ] Confirm date on a task → labeled confirmed; survives re-analyze
- [ ] (Related-items panel was retired; `/api/relations` still works)
- [ ] `PATCH /api/items/{id}/insight` user title/topic/priority survives re-analysis

## Ask My Inbox smoke (Milestone 4+)

- [ ] Save notes mentioning a specific topic (book, renewal, restaurant)
- [ ] Ask a matching question → answer cites the correct item(s)
- [ ] Ask an unrelated factual question → insufficient evidence message, no citations
- [ ] Citation “Open source” opens URL or PDF preview where available
- [ ] `GET /api/search?q=...` returns ranked excerpts

## PDF capture smoke (Milestone 3B+)

- [ ] Choose a small text-based PDF → item appears with `item_type=pdf`
- [ ] Processing reaches `ready` with title + extracted preview (or `failed` with error)
- [ ] “Open PDF” link downloads/previews the stored file
- [ ] Retry on failed PDF succeeds when the file is readable
- [ ] Analyze inbox includes ready PDF items
- [ ] Non-PDF or empty/image-only PDF rejected or marked failed with clear message

## Image capture smoke (Milestone 3C+)

- [ ] Choose a PNG/JPEG → item appears with `item_type=image`
- [ ] Thumbnail preview and **Open image** link work
- [ ] OCR (extracted) and AI description (inferred) are labeled separately
- [ ] **Edit OCR text** saves corrected extracted text without changing AI description
- [ ] Retry on failed image succeeds when the file is readable
- [ ] Analyze inbox includes ready image items (after OCR text or description exists)
- [ ] Non-image upload rejected with a clear message

## Voice capture smoke (Milestone 3D+)

- [ ] Upload a short wav/webm → item appears with `item_type=voice`
- [ ] Audio player works from the item card
- [ ] Transcript empty or placeholder when transcription is unconfigured
- [ ] **Edit transcript** saves text and analyze includes the voice item
- [ ] Optional: Record → Stop uploads a browser recording (mic permission required)
- [ ] Retry on failed voice processing succeeds
- [ ] Non-audio upload rejected with a clear message

## URL capture smoke (Milestone 3A+)

- [ ] Paste a public https URL → item appears with `item_type=url`
- [ ] Processing reaches `ready` with title + extracted text (or `failed` with error)
- [ ] Retry on failed URL succeeds when upstream recovers
- [ ] Analyze inbox includes ready URL items
- [ ] Private/local URLs (127.0.0.1, localhost) rejected before fetch

## Multi-user / auth smoke

Turn Dev Login on first (`LIFE_INBOX_ALLOW_DEV_LOGIN=true` in the server terminal, then restart). It is passwordless. With it left off, the app uses one Local Owner.

- [ ] Dev login with email A; create a note; appears in list
- [ ] Dev login with email B; note from A is not visible; delete of A’s id returns 404
- [ ] Use two browser profiles (A and B). After both analyze, B's Organized
  dashboard (High Priority, Recently Captured, Needs Review, Related Items,
  topic counts), Tasks, Attention, Search and Ask show nothing of A's, and the
  reverse holds
- [ ] As B, A's ids return 404 for `/api/items/{id}`, `/file`, `/insight`,
  task actions, topic edits and `/api/relations/{id}/dismiss`
- [ ] Sign out clears session cookie
- [ ] `/api/auth/google/start` returns 501 stub (no real OAuth)
- [ ] `/api/health` returns status + environment metadata
- [ ] Spoofing `X-User-Id` does not change ownership

## Attention / calendar smoke

- [ ] After analysis, Attention section shows Today / Upcoming / Overdue / Unscheduled
- [ ] Daily briefing summary and suggested focus appear
- [ ] Confirm date on a timed task; original phrase preserved; due_on normalized
- [ ] Snooze (Tomorrow / In 3 days / Next week) hides the task from Today's priority sections and shows “N snoozed”
- [ ] Preview calendar shows provider notes and requires explicit confirm
- [ ] Confirm (mock) records a local receipt; `/api/calendar/status` shows writes_enabled=false
- [ ] With `LIFE_INBOX_CALENDAR_PROVIDER=google`, confirm returns blocked (no OAuth/writes)

## Error states

- [ ] Stop the server mid-request → friendly client error, text preserved in textarea
- [ ] Analyze with empty inbox → empty_inbox mode, no crash
- [ ] Failed “Load more” → friendly error; notes already on screen kept

## Do not

- Point `DATABASE_URL` at a real personal inbox database
- Commit API keys or generated `.db` files

## Task Quest smoke (game/task-quest)

Points: High 30, Medium 20, Low 10; +5 if done a day or more early; half if overdue. Daily goal 100.

- [ ] Open tasks show a "+N pts" chip and a days-left badge (green safe, amber soon, orange due today, red overdue)
- [ ] A task with no date offers "Set deadline <date>" (High +2d, Medium +5d, Low +10d)
- [ ] Complete a task → Today ring and points rise, "+N" pop-up shows; reopen takes the points back; complete again awards once
- [ ] Reaching 100 shows confetti, a toast and a chime; the ring turns green; the streak starts
- [ ] "Sound off" mutes the chime and survives a reload; reduced-motion skips confetti
- [ ] Completed filter: drag a task onto the bin (or "Bin it"); it appears under Backlog (bin) with points kept; Restore returns it
- [ ] Type or say "Call the dentist on Friday, high priority" → High task with the right date
- [ ] Google Calendar nav item shows a status dot; "Add to Google Calendar" opens a prefilled event; "Download deadlines (.ics)" imports into Google Calendar
- [ ] Drop several files, a link and text anywhere on the page → each saved; toast lists "format → domain"
- [ ] Inbox Sort board: By domain / By format, format chips filter; drag a card to another domain → "Moved to X" with Undo, survives reload
- [ ] Unsupported file (.docx) is refused with a clear message
- [ ] Open tasks: drag onto a priority lane (points change) or onto a day in the 7-day strip (deadline changes)

## Task Quest, phases 8-10

- [ ] Google Calendar screen: import a calendar .ics; the line shows the number of busy blocks; "Clear imported calendar" removes them
- [ ] On a High task with a deadline, "Find time" lists up to 3 slots (weekdays 09-18, before the deadline) that avoid imported meetings
- [ ] Changing "Time needed" refreshes the slots; clicking a slot opens a prefilled Google event (nothing is saved until you confirm there)
- [ ] Today: create a team (checkbox decides whether your points show), copy the invite code
- [ ] In a second browser profile with a different Dev Login email, join with the code; both appear ranked by weekly points
- [ ] Untick "Show my points on the board": you disappear from the rows and the others see "1 member keeps points private"
- [ ] Leave team; the last person to leave deletes the team and its code stops working
- [ ] "What's due today?" button, the `B` key, and typing or saying "what's due today?" in the task box read the briefing aloud (a toast shows the text if speech is unavailable); pressing again stops it

- [ ] Desktop: the "Navigation width" slider resizes the sidebar from 96 to 360 px; below 160 px it becomes an icon-only rail (counts and the calendar dot stay visible); double-click resets to 248; the width survives a reload; the slider is hidden on phones

## Sections, task row and search (workspace restructure)

- [ ] Today → Needs your attention shows High, Medium and Low sections (High open); each task has Complete, Snooze, Edit, Delete and More
- [ ] Edit changes the wording, priority, deadline and section; the task moves to the right priority section
- [ ] Delete moves an open task to Tasks → Backlog with an Undo toast; Restore brings it back open
- [ ] Complete removes the task from every list and shows it ticked (✓) on the Calendar on the day it was done
- [ ] Calendar bin: drag a ✓ task into it; it leaves the Calendar and appears in Backlog with its points kept
- [ ] Dropping an open task on the bin is refused with a clear message
- [ ] Sidebar search for a finished task finds it, labelled Done or Done · in Backlog, with Reopen / Restore
- [ ] Inbox only lists items that need sorting; picking a section moves the item out and the Inbox count drops

## Auto-raised priority

Rule: an open task with a deadline is raised to High within 2 days (or when overdue); a Low task within 5 days is raised to Medium. It never lowers. A priority you set yourself (Edit, priority lane, or saying "high/low priority" in quick-add) is pinned and never raised.

- [ ] A task due in 2 days with no stated priority appears under High with an "↑ due soon" tag, worth 30 points
- [ ] The tag tooltip says which priority it was raised from
- [ ] A task due in 5 days stays in its own section; "low priority" said in quick-add stays Low even when due today
- [ ] Edit a raised task's priority to Medium: the tag disappears and it stays Medium
- [ ] Completing a raised task awards points at the raised level
- [ ] Leave the page open across midnight (or change the date): lists reload and tasks move up without a manual refresh
