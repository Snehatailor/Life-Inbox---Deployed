# Life Inbox desktop pet

A small Electron app. Your pet (bought in the Life Inbox coin shop) walks along the
bottom of your screen, **on top of every other app**. Tap it to jot down a note or
make a task; it tells you when a task's time slot is about to start.

It is just a transparent, always-on-top window showing Life Inbox's `/pet` page. The
window ignores the mouse everywhere except over the pet and its panel, so you keep
working underneath.

## Run it

Life Inbox must be running (default `http://127.0.0.1:8000`).

```bash
cd desktop-pet
npm install      # first time only; downloads Electron
npm start
```

- A 🐾 menu-bar / tray icon lets you **show or hide** the pet, open Life Inbox, reload
  the pet, or quit.
- Another address? `LIFE_INBOX_URL=http://127.0.0.1:9000 npm start`
- If Life Inbox is not running yet, the app waits and retries every 5 seconds.

## What the pet does

- **Roams** along the bottom of the primary display, naps, hops, and falls back to the
  ground if you drag it somewhere. Drag it anywhere; tap it (without dragging) to open
  the panel.
- **Note tab:** write (or dictate, where the system supports it) and press *Save note*
  to put it in your Inbox, or *Make task* to create a task. “Call the dentist Friday,
  high priority” works.
- **Today tab:** tasks with a time slot and tasks due today. Tick ✓ to finish one; the
  pet cheers when your coins go up.
- **Quick reminders:** in the Note tab, type a task with a time and press *Make task*: “send the meeting link in 20 min”, “call mom at 5pm”, “pay the bill tomorrow at 9am”, or “… remind me in 5 mins” (that last time wins over any other in the sentence). The pet tells you when the time arrives. Times use your own time zone. *Save note* only saves text; it never sets a reminder.
- **Done or snooze:** when a reminder comes up, the pet's bubble asks *“Is it done, or snooze 5 min?”* with **✓ Done** (completes the task and cheers) and **⏰ 5 min** (moves the reminder 5 minutes later and asks again then). If several are due they queue, and the Today tab has the same ✓ and ⏰ buttons. While the note panel is open the pet waits to ask.
- **Reminders:** schedule a slot (Life Inbox → a High task → ⋯ → *Find a time* → click a
  time). The pet speaks up 10 minutes before, when the slot starts, and if you missed it,
  with a native notification and a chime. Each reminder is announced once.
- **Different pets:** buy more in the **Pet shop** (Today → Daily quest). Coins you
  spend never lower your daily progress, streak or level.

## Limits

- Roams the **primary display** only.
- It runs as its own browser session. In single-user local mode (the default) that just
  works. If you enabled Dev Login, the companion is not signed in: use local mode.
- Run from source with `npm start`; there is no packaged installer or code signing yet.
- Dictation uses the web speech API, which Electron may not provide on every system.
