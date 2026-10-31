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
    return reminders.filter(r => r.phase !== 'later' && !seen[alertKey(r)]);
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

  const api = {alertKey, alertText, newAlerts, pickQuip, isSleepyHour};
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
  let bubbleTimer = 0;
  let lastCoins = null;
  let audioCtx = null;
  const bridge = window.petBridge || null;

  function seenAlerts() {
    try { return JSON.parse(localStorage.getItem(ALERT_STORE) || '{}'); } catch { return {}; }
  }

  function rememberAlert(reminder) {
    const seen = seenAlerts();
    const cutoff = Date.now() - 24 * 3600 * 1000;
    for (const key of Object.keys(seen)) if (seen[key] < cutoff) delete seen[key];
    seen[alertKey(reminder)] = Date.now();
    try { localStorage.setItem(ALERT_STORE, JSON.stringify(seen)); } catch { /* storage unavailable */ }
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
        const task = await post('/api/tasks/quick', {sentence: value});
        status(`Task added: “${task.text}” (${task.priority}, +${task.points_value} coins)`);
        say('Task added! ✅', 4000);
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
      renderToday();
      placePanel();
      showTab('note');
    }
    els.wrap.classList.toggle('pet-panel-open', open);
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
    const make = (text, meta, taskId) => {
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
      }
      list.append(row);
    };
    for (const r of state.reminders) {
      make(r.text, `${r.phase === 'missed' ? 'Missed' : r.phase === 'now' ? 'Now' : 'Slot'} · ${r.label}`, r.task_id);
    }
    for (const t of state.due_today) make(t.text, `Due today · ${t.priority}`, t.task_id);
    if (!list.children.length) {
      list.append(el('p', 'pp-empty', state.overdue_count ? `${state.overdue_count} overdue task(s). Open Life Inbox to catch up.` : 'Nothing scheduled right now. 🌤️'));
    }
  }

  function say(text, ms = 7000) {
    if (!text) return;
    els.bubble.textContent = text;
    els.bubble.hidden = false;
    clearTimeout(bubbleTimer);
    bubbleTimer = setTimeout(() => { els.bubble.hidden = true; }, ms);
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

  function render() {
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
    if (fresh.length) {
      const top = fresh[0];
      const text = alertText(top, state.pet.name);
      say(text, 25000);
      chime(top.phase === 'now');
      hop();
      if (bridge && bridge.notify) bridge.notify(`${state.pet.emoji} ${state.pet.name}`, text.replace(`${state.pet.name}: `, ''));
      else if (window.Notification && Notification.permission === 'granted') new Notification(`${state.pet.emoji} ${state.pet.name}`, {body: text});
      fresh.forEach(rememberAlert);
    }
  }

  async function poll() {
    try {
      applyState(await call('/api/pet/state'));
    } catch (error) {
      if (error.status === 401 && els.bubble) say('Sign in to Life Inbox so I can help.', 8000);
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
  }

  window.LifeInboxPet = {
    mount,
    unmount,
    refresh: () => { if (root) poll(); },
    isMounted: () => Boolean(root),
    _helpers: api
  };
})();
