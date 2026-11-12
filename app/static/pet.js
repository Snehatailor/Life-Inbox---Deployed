// The Life Inbox pet: roams, sleeps, reacts to your coins, takes notes when
// tapped, and reminds you of tasks that have a saved time slot.
//
// It runs in two places with the same code:
//  - /pet            the page the desktop companion app shows full screen
//  - the main app    an optional overlay ("Show my pet roaming on this page")

(function () {
  'use strict';

  const POLL_MS = 20000;
  const PET_SIZE = 56;
  const WALK_SPEED = 46; // px per second
  const ALERT_STORE = 'lifeInboxPetAlerts';
  const QUIPS_EVERY_MS = 75000;

  // ---------- Pure helpers (tested with Node) ----------

  function alertKey(reminder) {
    return `${reminder.task_id}|${reminder.slot_start}|${reminder.phase}`;
  }

  function alertText(reminder, petName) {
    const task = reminder.text.length > 60 ? `${reminder.text.slice(0, 57)}…` : reminder.text;
    if (reminder.phase === 'soon') return `${petName}: “${task}” starts ${reminder.label}.`;
    if (reminder.phase === 'now') return `${petName}: time for “${task}” — now!`;
    if (reminder.phase === 'missed') return `${petName}: you missed “${task}” (${reminder.label}). Reschedule it?`;
    return '';
  }

  // Reminders worth speaking up about that we have not already announced.
  function newAlerts(reminders, seen) {
    return reminders.filter(r => {
      if (r.phase === 'later' || seen[alertKey(r)]) return false;
      // "Remind me in 5 min" was just set: a heads-up now would only repeat it.
      if (r.phase === 'soon' && r.lead_minutes !== null && r.lead_minutes !== undefined && r.lead_minutes <= 15) return false;
      return true;
    });
  }

  // True when the text names a time, so "Make task" would set a reminder.
  function mentionsReminderTime(text) {
    return /\b(?:in|after)\s+(?:\d+(?:\.\d+)?|an?|half\s+an?)\s*(?:minutes?|mins?|m|hours?|hrs?|h)\b|\b(?:at|@)\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b|\bremind\b/i.test(text || '');
  }

  function pickQuip(state, hour, random) {
    const lines = [];
    if (state.overdue_count) lines.push(`${state.overdue_count} overdue — shall we tackle one?`);
    if (state.due_today.length) lines.push(`${state.due_today.length} due today. You've got this!`);
    if (state.goal_met) lines.push('You hit your daily goal! 🎉');
    else lines.push(`${Math.max(0, state.goal - state.points_today)} coins to today's goal.`);
    if (state.streak) lines.push(`🔥 ${state.streak}-day streak. Keep it going!`);
    if (hour >= 23 || hour < 6) lines.push('Shouldn\'t you be asleep? 😴');
    return lines[Math.floor(random() * lines.length)];
  }

  function isSleepyHour(hour) {
    return hour >= 23 || hour < 6;
  }

  // Procrastination Radar: the pet nudges about an at-risk task once per day.
  function nudgeKey(atRisk, day) {
    return `nudge|${atRisk.task_id}|${day}`;
  }

  function nudgeText(atRisk, petName) {
    const task = atRisk.text.length > 60 ? `${atRisk.text.slice(0, 57)}…` : atRisk.text;
    const why = atRisk.reasons && atRisk.reasons.length ? ` (${atRisk.reasons.slice(0, 2).join(', ').toLowerCase()})` : '';
    return `${petName}: “${task}” is slipping${why}. Want to just start for 10 minutes?`;
  }

  function tenMinuteSlot(now) {
    return {start: now.toISOString(), end: new Date(now.getTime() + 10 * 60 * 1000).toISOString()};
  }

  const api = {alertKey, alertText, newAlerts, pickQuip, isSleepyHour, mentionsReminderTime, nudgeKey, nudgeText, tenMinuteSlot};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof window === 'undefined') return;

  // ---------- Browser part ----------

  let root = null;
  let els = {};
  let state = null;
  let pos = {x: 120, y: 0};
  let facing = 1;
  let mode = 'idle';
  let modeUntil = 0;
  let lastFrame = 0;
  let fallSpeed = 0;
  let rafId = 0;
  let pollTimer = 0;
  let quipTimer = 0;
  let dragging = false;
  let panelOpen = false;
  let signedOut = false;
  let bubbleTimer = 0;
  let lastCoins = null;
  let audioCtx = null;
  const bridge = window.petBridge || null;

  function seenAlerts() {
    try { return JSON.parse(localStorage.getItem(ALERT_STORE) || '{}'); } catch { return {}; }
  }

  function rememberAlert(reminder) {
    rememberKey(alertKey(reminder));
  }

  function rememberKey(key) {
    const seen = seenAlerts();
    const cutoff = Date.now() - 24 * 3600 * 1000;
    for (const old of Object.keys(seen)) if (seen[old] < cutoff) delete seen[old];
    seen[key] = Date.now();
    try { localStorage.setItem(ALERT_STORE, JSON.stringify(seen)); } catch { /* storage unavailable */ }
  }

  function localDay() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  }

  // Only when nothing else is being said: reminders always come first.
  function maybeNudge() {
    if (!state || !state.at_risk || activeAlert || alertQueue.length || panelOpen || !els.bubble.hidden) return;
    const key = nudgeKey(state.at_risk, localDay());
    if (seenAlerts()[key]) return;
    rememberKey(key);
    const atRisk = state.at_risk;
    say(nudgeText(atRisk, state.pet.name), 60 * 1000, [
      {label: '▶ Start 10 min', primary: true, run: async () => {
        await post(`/api/tasks/${atRisk.task_id}/slot`, tenMinuteSlot(new Date()));
        cheer('Go go go! I\'ll check in after 10 minutes. ⏱️');
        poll();
      }},
      {label: 'Not now', run: async () => {
        say('OK, I won\'t ask about it again today.', 3000);
      }}
    ]);
    hop();
  }

  async function call(path, options) {
    const response = await fetch(path, options);
    if (!response.ok) {
      const error = new Error(`HTTP ${response.status}`);
      error.status = response.status;
      throw error;
    }
    return response.status === 204 ? null : response.json();
  }

  function post(path, body) {
    return call(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function bounds() {
    return {w: root.clientWidth, h: root.clientHeight};
  }

  function groundY() {
    const {h} = bounds();
    const bottomGap = window.innerWidth < 768 && !bridge ? 74 : 10;
    return Math.max(0, h - PET_SIZE - 18 - bottomGap);
  }

  // ---------- Building the DOM ----------

  function build() {
    const wrap = el('div', 'pet-wrap');
    const bubble = el('div', 'pet-bubble');
    bubble.hidden = true;
    const body = el('button', 'pet-body');
    body.type = 'button';
    body.setAttribute('aria-label', 'Your pet. Tap to open notes and reminders.');
    const mood = el('span', 'pet-mood');
    const label = el('span', 'pet-label');
    wrap.append(bubble, body, mood, label);
    const panel = buildPanel();
    root.append(wrap, panel);
    els = {wrap, bubble, body, mood, label, panel};
    wireDrag(body);
    wirePassThrough();
  }

  function buildPanel() {
    const panel = el('section', 'pet-panel');
    panel.hidden = true;
    panel.innerHTML = `
      <header class="pp-head">
        <strong class="pp-title"></strong>
        <span class="pp-coins"></span>
        <button type="button" class="pp-close" aria-label="Close">×</button>
      </header>
      <nav class="pp-tabs" role="tablist">
        <button type="button" role="tab" data-tab="note" class="on">Note</button>
        <button type="button" role="tab" data-tab="today">Today</button>
      </nav>
      <div class="pp-tab" data-pane="note">
        <textarea class="pp-text" rows="4" placeholder="Jot something down, or say a task…" aria-label="Note"></textarea>
        <div class="pp-row">
          <button type="button" class="pp-save">Save note</button>
          <button type="button" class="pp-task secondary">Make task</button>
          <button type="button" class="pp-mic secondary" title="Dictate" hidden>🎤</button>
        </div>
        <p class="pp-status" role="status"></p>
      </div>
      <form class="pp-tab pp-signin" data-pane="signin" hidden>
        <p class="pp-signin-lede">Sign in with your Life Inbox account so I can save notes and remind you.</p>
        <input class="pp-email" type="email" autocomplete="email" placeholder="you@example.com" aria-label="Email" required>
        <input class="pp-password" type="password" autocomplete="current-password" placeholder="Password" aria-label="Password" required>
        <div class="pp-row">
          <button type="submit" class="pp-signin-go">Sign in</button>
          <button type="button" class="pp-signup secondary">Create account</button>
        </div>
        <p class="pp-signin-status" role="status"></p>
      </form>
      <div class="pp-tab" data-pane="today" hidden>
        <div class="pp-list"></div>
        <button type="button" class="pp-open secondary">Open Life Inbox</button>
      </div>`;
    panel.querySelector('.pp-close').addEventListener('click', () => setPanel(false));
    panel.querySelectorAll('.pp-tabs button').forEach(button => {
      button.addEventListener('click', () => showTab(button.dataset.tab));
    });
    panel.querySelector('.pp-save').addEventListener('click', () => saveText('note'));
    panel.querySelector('.pp-task').addEventListener('click', () => saveText('task'));
    panel.querySelector('.pp-open').addEventListener('click', openApp);
    panel.querySelector('.pp-signin').addEventListener('submit', event => {
      event.preventDefault();
      signIn();
    });
    panel.querySelector('.pp-signup').addEventListener('click', openApp);
    panel.querySelector('.pp-text').addEventListener('input', event => {
      const reminder = mentionsReminderTime(event.target.value);
      panel.querySelector('.pp-task').classList.toggle('secondary', !reminder);
      status(reminder ? '⏰ That has a time. Press “Make task” and I will remind you.' : '');
    });
    panel.querySelector('.pp-text').addEventListener('keydown', event => {
      if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) saveText('note');
    });
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (Recognition) {
      const mic = panel.querySelector('.pp-mic');
      mic.hidden = false;
      mic.addEventListener('click', () => {
        const recognition = new Recognition();
        recognition.lang = navigator.language || 'en-US';
        recognition.interimResults = true;
        recognition.onresult = event => {
          panel.querySelector('.pp-text').value = Array.from(event.results).map(r => r[0].transcript).join(' ');
        };
        recognition.onerror = () => status('Could not hear you. Check the microphone permission.');
        recognition.start();
        status('Listening…');
      });
    }
    return panel;
  }

  async function signIn() {
    const email = els.panel.querySelector('.pp-email').value.trim();
    const password = els.panel.querySelector('.pp-password').value;
    const line = els.panel.querySelector('.pp-signin-status');
    if (!email || !password) { line.textContent = 'Enter your email and password.'; return; }
    line.textContent = 'Signing in…';
    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({email, password})
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        line.textContent = typeof data.detail === 'string' ? data.detail : 'Sign-in failed.';
        return;
      }
      els.panel.querySelector('.pp-password').value = '';
      line.textContent = '';
      signedOut = false;
      els.panel.querySelector('.pp-tabs').hidden = false;
      showTab('note');
      say('Signed in! Tap me any time. 🐾', 4000);
      poll();
    } catch {
      line.textContent = 'Could not reach Life Inbox. Check your internet connection.';
    }
  }

  function showTab(name) {
    els.panel.querySelectorAll('.pp-tabs button').forEach(b => b.classList.toggle('on', b.dataset.tab === name));
    els.panel.querySelectorAll('.pp-tab').forEach(t => { t.hidden = t.dataset.pane !== name; });
    if (name === 'note') els.panel.querySelector('.pp-text').focus();
  }

  function status(text) {
    els.panel.querySelector('.pp-status').textContent = text;
  }

  async function saveText(kind) {
    const textarea = els.panel.querySelector('.pp-text');
    const value = textarea.value.trim();
    if (!value) { status('Write something first.'); return; }
    try {
      if (kind === 'note') {
        await post('/api/items', {raw_text: value});
        status('Saved to your inbox ✓');
        say(`${state ? state.pet.name : 'Pet'}: noted! 📝`, 4000);
      } else {
        const task = await post('/api/tasks/quick', {sentence: value, tz: Intl.DateTimeFormat().resolvedOptions().timeZone});
        if (task.slot_start) {
          const at = new Date(task.slot_start).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
          status(`⏰ Reminder set for ${at}: “${task.text}”`);
          say(`I'll remind you at ${at}! ⏰`, 5000);
        } else {
          status(`Task added: “${task.text}” (${task.priority}, +${task.points_value} coins)`);
          say('Task added! ✅', 4000);
        }
      }
      textarea.value = '';
      hop();
      poll();
    } catch {
      status('Could not save. Is Life Inbox running?');
    }
  }

  function openApp() {
    if (bridge && bridge.openApp) bridge.openApp();
    else window.open('/', '_blank', 'noopener');
  }

  // ---------- Panel and bubble ----------

  function setPanel(open) {
    panelOpen = open;
    els.panel.hidden = !open;
    if (open) {
      els.panel.querySelector('.pp-tabs').hidden = signedOut;
      if (signedOut) {
        showTab('signin');
        placePanel();
        els.panel.querySelector('.pp-email').focus();
      } else {
        renderToday();
        placePanel();
        showTab('note');
      }
    }
    els.wrap.classList.toggle('pet-panel-open', open);
    if (!open) setTimeout(showNextAlert, 300);
    if (bridge && bridge.setFocusable) bridge.setFocusable(open);
  }

  function placePanel() {
    const {w, h} = bounds();
    const width = 300;
    const left = Math.min(Math.max(8, pos.x + PET_SIZE / 2 - width / 2), w - width - 8);
    const panelHeight = els.panel.offsetHeight || 260;
    const top = pos.y - panelHeight - 14 > 8 ? pos.y - panelHeight - 14 : Math.min(h - panelHeight - 8, pos.y + PET_SIZE + 12);
    els.panel.style.left = `${left}px`;
    els.panel.style.top = `${Math.max(8, top)}px`;
  }

  function renderToday() {
    const list = els.panel.querySelector('.pp-list');
    list.replaceChildren();
    if (!state) { list.append(el('p', 'pp-empty', 'Loading…')); return; }
    const make = (text, meta, taskId, isReminder = false) => {
      const row = el('div', 'pp-item');
      const info = el('div', 'pp-info');
      info.append(el('div', 'pp-task-text', text), el('small', 'pp-meta', meta));
      row.append(info);
      if (taskId) {
        const done = el('button', 'pp-done', '✓');
        done.title = 'Mark done';
        done.setAttribute('aria-label', `Mark done: ${text}`);
        done.addEventListener('click', async () => {
          try { await call(`/api/tasks/${taskId}/complete`, {method: 'POST'}); cheer('Well done! 🎉'); poll(); } catch { status('Could not complete that.'); }
        });
        row.append(done);
        if (isReminder) {
          const later = el('button', 'pp-later secondary', '⏰');
          later.title = 'Remind me again in 5 minutes';
          later.setAttribute('aria-label', `Snooze 5 minutes: ${text}`);
          later.addEventListener('click', async () => {
            try { await post(`/api/tasks/${taskId}/remind-later`, {minutes: 5}); say('OK, in 5 minutes. ⏰', 3000); poll(); } catch { status('Could not snooze that.'); }
          });
          row.insertBefore(later, done);
        }
      }
      list.append(row);
    };
    for (const r of state.reminders) {
      make(r.text, `${r.phase === 'missed' ? 'Missed' : r.phase === 'now' ? 'Now' : 'Slot'} · ${r.label}`, r.task_id, true);
    }
    for (const t of state.due_today) make(t.text, `Due today · ${t.priority}`, t.task_id);
    if (!list.children.length) {
      list.append(el('p', 'pp-empty', state.overdue_count ? `${state.overdue_count} overdue task(s). Open Life Inbox to catch up.` : 'Nothing scheduled right now. 🌤️'));
    }
  }

  // A speech bubble. `actions` adds buttons ({label, primary, run}) and keeps it up longer.
  function say(text, ms = 7000, actions = null, onClose = null) {
    if (!text) return;
    els.bubble.replaceChildren(el('div', 'pb-text', text));
    if (actions) {
      const row = el('div', 'pb-actions');
      for (const action of actions) {
        const button = el('button', action.primary ? 'pb-primary' : '', action.label);
        button.type = 'button';
        button.addEventListener('click', async () => {
          row.querySelectorAll('button').forEach(b => { b.disabled = true; });
          try { await action.run(); } catch { say('Hmm, that did not work. Is Life Inbox running?', 4000); }
        });
        row.append(button);
      }
      els.bubble.append(row);
    }
    els.bubble.hidden = false;
    clearTimeout(bubbleTimer);
    bubbleTimer = setTimeout(() => {
      els.bubble.hidden = true;
      if (onClose) onClose();
    }, ms);
  }

  // Reminders wait in a queue so two at once don't hide each other.
  let alertQueue = [];
  let activeAlert = null;

  function reminderActions(reminder) {
    return [
      {label: '✓ Done', primary: true, run: async () => {
        await call(`/api/tasks/${reminder.task_id}/complete`, {method: 'POST'});
        activeAlert = null;
        cheer('Well done! 🎉');
        poll();
        setTimeout(showNextAlert, 1500);
      }},
      {label: '⏰ 5 min', run: async () => {
        const task = await post(`/api/tasks/${reminder.task_id}/remind-later`, {minutes: 5});
        const at = new Date(task.slot_start).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
        activeAlert = null;
        say(`OK, I'll ask again at ${at}. ⏰`, 4000);
        poll();
        setTimeout(showNextAlert, 4200);
      }}
    ];
  }

  function showNextAlert() {
    if (activeAlert || !alertQueue.length || !els.bubble || panelOpen) return;
    activeAlert = alertQueue.shift();
    const question = alertText(activeAlert, state ? state.pet.name : 'Pet');
    const more = alertQueue.length ? ` (+${alertQueue.length} more)` : '';
    const ask = activeAlert.phase === 'soon' ? 'Ready? Or snooze 5 min?' : 'Is it done, or snooze 5 min?';
    say(`${question}${more}\n${ask}`, 3 * 60 * 1000, reminderActions(activeAlert), () => {
      activeAlert = null;
      showNextAlert();
    });
    chime(activeAlert.phase === 'now');
    hop();
  }

  function chime(big) {
    try {
      audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
      (big ? [659.25, 880, 1174.66] : [740, 988]).forEach((freq, i) => {
        const osc = audioCtx.createOscillator();
        const gain = audioCtx.createGain();
        const start = audioCtx.currentTime + i * 0.13;
        osc.type = 'triangle';
        osc.frequency.value = freq;
        gain.gain.setValueAtTime(0.0001, start);
        gain.gain.exponentialRampToValueAtTime(0.16, start + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.3);
        osc.connect(gain).connect(audioCtx.destination);
        osc.start(start);
        osc.stop(start + 0.32);
      });
    } catch { /* audio is optional */ }
  }

  // ---------- Movement ----------

  // Keep the speech bubble fully on screen when the pet is near an edge.
  function placeBubble() {
    if (els.bubble.hidden) return;
    const {w} = bounds();
    const width = els.bubble.offsetWidth;
    const centre = pos.x + PET_SIZE / 2;
    const left = Math.min(Math.max(8, centre - width / 2), w - width - 8);
    const shift = Math.round(left - (centre - width / 2));
    els.bubble.style.setProperty('--shift', `${shift}px`);
  }

  function render() {
    placeBubble();
    const flip = facing === 1 ? 1 : -1;
    els.wrap.style.transform = `translate3d(${Math.round(pos.x)}px, ${Math.round(pos.y)}px, 0)`;
    els.body.style.setProperty('--flip', String(flip));
    els.wrap.dataset.mode = dragging ? 'drag' : mode;
  }

  function chooseMode(now) {
    if (panelOpen || dragging) { mode = 'idle'; modeUntil = now + 800; return; }
    const hour = new Date().getHours();
    const roll = Math.random();
    if (isSleepyHour(hour) && roll < 0.7) mode = 'sleep';
    else if (roll < 0.55) mode = 'walk';
    else if (roll < 0.8) mode = 'idle';
    else if (roll < 0.9) mode = 'sleep';
    else { mode = 'idle'; hop(); }
    if (mode === 'walk') facing = Math.random() < 0.5 ? -1 : 1;
    modeUntil = now + (mode === 'walk' ? 3000 + Math.random() * 5000 : mode === 'sleep' ? 6000 + Math.random() * 9000 : 2000 + Math.random() * 4000);
    els.mood.textContent = mode === 'sleep' ? '💤' : moodIcon();
  }

  function moodIcon() {
    if (!state) return '';
    if (state.goal_met) return '✨';
    if (state.overdue_count) return '❗';
    return '';
  }

  function frame(time) {
    rafId = requestAnimationFrame(frame);
    const dt = Math.min(0.1, (time - (lastFrame || time)) / 1000);
    lastFrame = time;
    if (!els.wrap) return;
    if (!dragging) {
      if (time > modeUntil) chooseMode(time);
      const {w} = bounds();
      if (mode === 'walk') {
        pos.x += facing * WALK_SPEED * dt;
        if (pos.x < 6) { pos.x = 6; facing = 1; }
        if (pos.x > w - PET_SIZE - 6) { pos.x = w - PET_SIZE - 6; facing = -1; }
      }
      // gravity back to the ground after being picked up or resized
      const ground = groundY();
      if (pos.y < ground - 0.5) {
        fallSpeed += 2200 * dt;
        pos.y = Math.min(ground, pos.y + fallSpeed * dt);
      } else {
        pos.y = ground;
        fallSpeed = 0;
      }
    }
    render();
    if (panelOpen) placePanel();
  }

  function hop() {
    els.body.classList.remove('pet-hop');
    void els.body.offsetWidth;
    els.body.classList.add('pet-hop');
  }

  function cheer(text) {
    hop();
    chime(true);
    say(text, 5000);
  }

  function wireDrag(handle) {
    let startX = 0;
    let startY = 0;
    let offsetX = 0;
    let offsetY = 0;
    let moved = false;
    handle.addEventListener('pointerdown', event => {
      handle.setPointerCapture(event.pointerId);
      startX = event.clientX;
      startY = event.clientY;
      offsetX = event.clientX - pos.x;
      offsetY = event.clientY - pos.y;
      moved = false;
      dragging = true;
    });
    handle.addEventListener('pointermove', event => {
      if (!dragging) return;
      if (!moved && Math.hypot(event.clientX - startX, event.clientY - startY) < 5) return;
      moved = true;
      const {w, h} = bounds();
      pos.x = Math.min(Math.max(0, event.clientX - offsetX), w - PET_SIZE);
      pos.y = Math.min(Math.max(0, event.clientY - offsetY), h - PET_SIZE);
    });
    handle.addEventListener('pointerup', event => {
      handle.releasePointerCapture(event.pointerId);
      dragging = false;
      if (!moved) setPanel(!panelOpen);
      else say('Wheee! 🎈', 1800);
    });
  }

  // Desktop companion: the window is click-through except over the pet.
  function wirePassThrough() {
    if (!bridge || !bridge.setInteractive) return;
    document.addEventListener('mousemove', event => {
      const over = event.target.closest && event.target.closest('.pet-wrap, .pet-panel');
      bridge.setInteractive(Boolean(over) || dragging);
    });
    document.addEventListener('mouseleave', () => bridge.setInteractive(false));
  }

  // ---------- State, reminders and cheering ----------

  function applyState(next) {
    const first = !state;
    const previousCoins = lastCoins;
    state = next;
    els.body.textContent = state.pet.emoji;
    els.label.textContent = state.pet.name;
    els.panel.querySelector('.pp-title').textContent = `${state.pet.emoji} ${state.pet.name}`;
    els.panel.querySelector('.pp-coins').textContent = `🪙 ${state.balance}`;
    els.mood.textContent = mode === 'sleep' ? '💤' : moodIcon();
    if (panelOpen) renderToday();

    if (!first && previousCoins !== null && state.points_today > previousCoins) {
      cheer(`+${state.points_today - previousCoins} coins! 🪙`);
    }
    lastCoins = state.points_today;

    const seen = seenAlerts();
    const fresh = newAlerts(state.reminders, seen);
    for (const reminder of fresh) {
      rememberAlert(reminder);
      alertQueue.push(reminder);
      const text = alertText(reminder, state.pet.name);
      if (bridge && bridge.notify) bridge.notify(`${state.pet.emoji} ${state.pet.name}`, text.replace(`${state.pet.name}: `, ''));
      else if (window.Notification && Notification.permission === 'granted') new Notification(`${state.pet.emoji} ${state.pet.name}`, {body: text});
    }
    // a reminder that was finished or moved elsewhere no longer needs asking about
    const live = new Set(state.reminders.map(alertKey));
    alertQueue = alertQueue.filter(r => live.has(alertKey(r)));
    if (activeAlert && !live.has(alertKey(activeAlert))) {
      activeAlert = null;
      els.bubble.hidden = true;
    }
    showNextAlert();
    // Wait past the first poll so the greeting does not cover the nudge.
    if (!first) maybeNudge();
  }

  async function poll() {
    try {
      applyState(await call('/api/pet/state'));
      signedOut = false;
    } catch (error) {
      if (error.status === 401) {
        const firstTime = !signedOut;
        signedOut = true;
        if (!state && els.body) {
          // Nothing loaded yet: show the starter pet so there is something to tap.
          els.body.textContent = '🐱';
          els.label.textContent = 'Tap to sign in';
          els.panel.querySelector('.pp-title').textContent = '🐱 Life Inbox Pet';
        }
        if (firstTime && els.bubble && !panelOpen) say('Tap me to sign in to Life Inbox. 🐾', 9000);
      }
    }
  }

  function startQuips() {
    clearInterval(quipTimer);
    quipTimer = setInterval(() => {
      if (!state || panelOpen || dragging || !els.bubble.hidden) return;
      say(pickQuip(state, new Date().getHours(), Math.random), 6000);
    }, QUIPS_EVERY_MS);
  }

  // ---------- Public API ----------

  function mount(container, options = {}) {
    unmount();
    root = container;
    build();
    pos = {x: Math.max(20, bounds().w * 0.35), y: 0};
    pos.y = groundY();
    lastFrame = 0;
    rafId = requestAnimationFrame(frame);
    poll();
    pollTimer = setInterval(poll, POLL_MS);
    startQuips();
    if (options.greet !== false) setTimeout(() => say('Hi! Tap me for notes and reminders. 🐾', 5000), 800);
    if (window.Notification && Notification.permission === 'default' && !bridge) {
      try { Notification.requestPermission(); } catch { /* ignore */ }
    }
  }

  function unmount() {
    cancelAnimationFrame(rafId);
    clearInterval(pollTimer);
    clearInterval(quipTimer);
    if (root) root.replaceChildren();
    root = null;
    els = {};
    state = null;
    lastCoins = null;
    alertQueue = [];
    activeAlert = null;
  }

  window.LifeInboxPet = {
    mount,
    unmount,
    refresh: () => { if (root) poll(); },
    isMounted: () => Boolean(root),
    _helpers: api
  };
})();
