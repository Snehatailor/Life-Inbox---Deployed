let isSavingNote = false;
let isAnalyzingInbox = false;
let calendarTasks = [];
let calendarCursor = new Date(new Date().getFullYear(), new Date().getMonth(), 1);
const pendingNoteActions = new Set();
const pendingTaskActions = new Set();
const itemFilterFields = {
  q: 'itemSearch',
  item_type: 'itemTypeFilter',
  category: 'categoryFilter',
  priority: 'priorityFilter',
  processing_status: 'processingStatusFilter'
};

function setStatus(elementId, message, isError = false) {
  const element = document.getElementById(elementId);
  element.textContent = message;
  element.classList.toggle('error', isError);
}

// Toasts: short confirmations in the corner, optionally with one action
// (usually Undo). Errors that need fixing stay inline next to their field.
function showToast(message, {actionLabel, onAction, duration} = {}) {
  const region = document.getElementById('toastRegion');
  const toast = document.createElement('div');
  toast.className = 'toast';
  const text = document.createElement('span');
  text.className = 'toast-text';
  text.textContent = message;
  toast.appendChild(text);

  let timer = null;
  const dismiss = () => {
    clearTimeout(timer);
    toast.classList.add('toast-leaving');
    setTimeout(() => toast.remove(), 200);
  };

  if (actionLabel && onAction) {
    const action = document.createElement('button');
    action.type = 'button';
    action.className = 'toast-action';
    action.textContent = actionLabel;
    action.addEventListener('click', () => {
      dismiss();
      onAction();
    });
    toast.appendChild(action);
  }

  const close = document.createElement('button');
  close.type = 'button';
  close.className = 'toast-close';
  close.setAttribute('aria-label', 'Dismiss message');
  close.textContent = '×';
  close.addEventListener('click', dismiss);
  toast.appendChild(close);

  region.appendChild(toast);
  // Keep at most three on screen.
  while (region.children.length > 3) region.firstElementChild.remove();
  timer = setTimeout(dismiss, duration || (actionLabel ? 6000 : 3500));
  return {dismiss};
}

const EMPTY_ICONS = {
  inbox: '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
  search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
  check: '<path d="m9 11 3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>'
};

// A friendly "nothing here" card. `action` is trusted, static HTML.
function emptyStateHtml({icon, title, text, action = ''}) {
  return `<div class="empty-state">
    <span class="empty-icon" aria-hidden="true"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${EMPTY_ICONS[icon]}</svg></span>
    <strong>${title}</strong>
    <p>${text}</p>
    ${action}
  </div>`;
}

function showSkeleton(rootId, count = 3) {
  const root = document.getElementById(rootId);
  root.innerHTML = Array.from({length: count}, () =>
    '<div class="skeleton-card" aria-hidden="true"><span class="skeleton-line wide"></span><span class="skeleton-line"></span></div>'
  ).join('') + '<span class="visually-hidden">Loading…</span>';
}

// Small counts next to Inbox and Tasks in the menu. Refreshed (debounced)
// whenever either list reloads, so saves, deletes and undos all update them.
let navCountTimer = null;

function updateNavCounts() {
  clearTimeout(navCountTimer);
  navCountTimer = setTimeout(async () => {
    try {
      const [items, openTasks] = await Promise.all([
        fetchJson('/api/items?limit=500', undefined, 'Unable to count items.'),
        fetchJson('/api/tasks?status=open', undefined, 'Unable to count tasks.')
      ]);
      setNavCount('inbox', items.length >= 500 ? '500+' : items.length, 'items');
      setNavCount('tasks', openTasks.length, 'open tasks');
    } catch {
      // Counts are a nicety; the lists themselves report load errors.
    }
  }, 300);
}

function setNavCount(view, count, noun) {
  const badge = document.querySelector(`[data-count="${view}"]`);
  if (!badge) return;
  badge.textContent = String(count);
  badge.hidden = !count;
  badge.setAttribute('aria-label', `${count} ${noun}`);
}

function setButtonBusy(buttonId, busy, busyLabel, idleLabel) {
  const button = document.getElementById(buttonId);
  button.disabled = busy;
  button.textContent = busy ? busyLabel : idleLabel;
  button.setAttribute('aria-busy', String(busy));
}

function priorityClass(priority) {
  // Only the three known levels get a color class; anything else stays a plain pill.
  const level = String(priority || '').toLowerCase();
  return ['high', 'medium', 'low'].includes(level) ? `pill priority-${level}` : 'pill';
}

function friendlyTimestamp(isoTimestamp) {
  // "Today, 10:50 PM", "Yesterday, 6:42 PM", "Sat 24 Oct, 6:42 PM",
  // or "24 Oct 2025, 6:42 PM" for another year. Unparseable values are
  // shown as stored so nothing silently disappears.
  const stamp = new Date(isoTimestamp);
  if (!isoTimestamp || Number.isNaN(stamp.getTime())) return isoTimestamp || '';
  const time = stamp.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const day = new Date(stamp);
  day.setHours(0, 0, 0, 0);
  const daysAgo = Math.round((today - day) / 86400000);
  if (daysAgo === 0) return `Today, ${time}`;
  if (daysAgo === 1) return `Yesterday, ${time}`;
  const sameYear = stamp.getFullYear() === today.getFullYear();
  const date = stamp.toLocaleDateString(undefined, sameYear
    ? { weekday: 'short', day: 'numeric', month: 'short' }
    : { day: 'numeric', month: 'short', year: 'numeric' });
  return `${date}, ${time}`;
}

function timestampElement(isoTimestamp) {
  const element = document.createElement('time');
  element.dateTime = isoTimestamp || '';
  element.textContent = friendlyTimestamp(isoTimestamp);
  const stamp = new Date(isoTimestamp);
  if (!Number.isNaN(stamp.getTime())) element.title = stamp.toLocaleString();
  return element;
}

function dateFromIso(isoDate) {
  // Parse date-only values in local time; Date("YYYY-MM-DD") is UTC and can
  // otherwise place a schedule on the previous day in the Americas.
  return new Date(`${isoDate}T12:00:00`);
}

function relativeDueLabel(isoDate) {
  if (!isoDate) return '';
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const target = dateFromIso(isoDate);
  target.setHours(0, 0, 0, 0);
  const days = Math.round((target - today) / 86400000);
  if (days === 0) return 'Today';
  if (days === 1) return 'Tomorrow';
  if (days > 1) return `In ${days} days`;
  if (days === -1) return 'Yesterday';
  return `${Math.abs(days)} days overdue`;
}

function daysLeftFromIso(isoDate) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const target = dateFromIso(isoDate);
  target.setHours(0, 0, 0, 0);
  return Math.round((target - today) / 86400000);
}

function paintDaysBadge(badge) {
  const dueOn = badge.dataset.dueOn;
  if (!dueOn) {
    badge.hidden = true;
    return;
  }
  const left = daysLeftFromIso(dueOn);
  let level = 'safe';
  let label = `${left} days left`;
  if (left < 0) { level = 'overdue'; label = `${-left} day${left === -1 ? '' : 's'} overdue`; }
  else if (left === 0) { level = 'due'; label = 'Due today'; }
  else if (left === 1) { level = 'soon'; label = '1 day left'; }
  else if (left <= 2) { level = 'soon'; }
  badge.hidden = false;
  badge.className = `days-badge days-${level}`;
  badge.textContent = label;
}

function refreshDynamicDates() {
  document.querySelectorAll('.days-badge').forEach(paintDaysBadge);
  document.querySelectorAll('[data-due-on]').forEach(element => {
    const dueOn = element.dataset.dueOn;
    element.textContent = dueOn ? `${relativeDueLabel(dueOn)} · ${dueOn}` : '';
  });
}

function itemFilterParams() {
  const params = new URLSearchParams();
  for (const [name, elementId] of Object.entries(itemFilterFields)) {
    const value = document.getElementById(elementId).value.trim();
    if (value) params.set(name, value);
  }
  return params;
}

function hasItemFilters() {
  return itemFilterParams().size > 0;
}

// The query string last used for the lists; popstate compares against it so
// switching screens (which also fires popstate) does not reload every list.
let lastListQuery = window.location.search;

function updateUrl(updates) {
  const url = new URL(window.location.href);
  for (const [name, value] of Object.entries(updates)) {
    if (value) {
      url.searchParams.set(name, value);
    } else {
      url.searchParams.delete(name);
    }
  }
  window.history.pushState({}, '', url);
  lastListQuery = url.search;
}

function syncControlsFromUrl() {
  const params = new URLSearchParams(window.location.search);
  for (const [name, elementId] of Object.entries(itemFilterFields)) {
    const element = document.getElementById(elementId);
    const value = params.get(name) || '';
    if (
      name === 'category'
      && value
      && !Array.from(element.options).some(option => option.value === value)
    ) {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = value;
      element.appendChild(option);
    }
    element.value = value;
  }
  // The sidebar search mirrors the Inbox search words.
  document.getElementById('globalSearch').value = params.get('q') || '';

  const taskStatus = params.get('task_status');
  document.getElementById('taskStatusFilter').value =
    ['open', 'completed', 'dismissed'].includes(taskStatus)
      ? taskStatus
      : 'open';
}

function populateCategoryFilter(data) {
  const select = document.getElementById('categoryFilter');
  const selected =
    new URLSearchParams(window.location.search).get('category')
    || select.value;
  const categories = Array.from(
    new Set((data.buckets || []).map(bucket => bucket.name))
  ).sort((first, second) => first.localeCompare(second));

  select.replaceChildren();
  const allOption = document.createElement('option');
  allOption.value = '';
  allOption.textContent = 'All';
  select.appendChild(allOption);

  if (selected && !categories.includes(selected)) {
    categories.push(selected);
    categories.sort((first, second) => first.localeCompare(second));
  }
  for (const category of categories) {
    const option = document.createElement('option');
    option.value = category;
    option.textContent = category;
    select.appendChild(option);
  }
  select.value = selected;
}

function applyItemFilters(event) {
  event.preventDefault();
  const values = {};
  const params = itemFilterParams();
  for (const name of Object.keys(itemFilterFields)) {
    values[name] = params.get(name) || '';
  }
  updateUrl(values);
  document.getElementById('globalSearch').value = values.q;
  loadNotes();
}

// The sidebar search box: open Inbox and search all items for the words,
// with the other filters cleared so nothing is hidden by accident.
function searchEverything(event) {
  event.preventDefault();
  const input = document.getElementById('globalSearch');
  const query = input.value.trim();
  for (const elementId of Object.values(itemFilterFields)) {
    document.getElementById(elementId).value = '';
  }
  document.getElementById('itemSearch').value = query;
  // One history entry for screen + words. Setting location.hash separately
  // would fire popstate and reset the filters before the search runs.
  const url = new URL(window.location.href);
  for (const name of Object.keys(itemFilterFields)) url.searchParams.delete(name);
  if (query) url.searchParams.set('q', query);
  url.hash = 'inbox';
  window.history.pushState({}, '', url);
  lastListQuery = url.search;
  showView('inbox');
  loadNotes();
  input.blur();
}

function clearItemFilters() {
  for (const elementId of Object.values(itemFilterFields)) {
    document.getElementById(elementId).value = '';
  }
  document.getElementById('globalSearch').value = '';
  updateUrl(
    Object.fromEntries(
      Object.keys(itemFilterFields).map(name => [name, ''])
    )
  );
  loadNotes();
}

function changeTaskStatusFilter() {
  const status = document.getElementById('taskStatusFilter').value;
  updateUrl({task_status: status});
  loadTasks();
}

async function fetchJson(url, options, friendlyError) {
  let response;
  try {
    response = await fetch(url, options);
  } catch {
    throw new Error(friendlyError);
  }

  if (!response.ok) {
    throw new Error(friendlyError);
  }

  if (response.status === 204) {
    return null;
  }

  try {
    return await response.json();
  } catch {
    throw new Error(friendlyError);
  }
}

// ------------------------------------------------------------------
// Capture: one box for notes, links, PDFs, images and voice notes.
// The text and any attached file decide which existing endpoint is used.
// ------------------------------------------------------------------
const CAPTURE_LABELS = {
  note: 'Note', url: 'Link', pdf: 'PDF', image: 'Image', voice: 'Voice note', textfile: 'Text file'
};
const CAPTURE_PROGRESS = {
  note: 'Saving your note…',
  url: 'Saving the link and fetching the page text…',
  pdf: 'Saving PDF and extracting text…',
  image: 'Saving image and reading any text in it…',
  voice: 'Uploading voice note…',
  textfile: 'Saving text file…'
};
const FILE_KIND_NAMES = { pdf: 'PDF', image: 'image', voice: 'audio file', textfile: 'text file' };

let attachedFile = null;

function looksLikeUrl(text) {
  // Only a bare link becomes a URL capture; a sentence containing a link
  // stays a note so none of the person's words are dropped.
  return /^https?:\/\/\S+$/i.test(text);
}

function fileKind(file) {
  const type = (file.type || '').toLowerCase();
  const name = (file.name || '').toLowerCase();
  if (type === 'application/pdf' || name.endsWith('.pdf')) return 'pdf';
  if (type.startsWith('image/') || /\.(png|jpe?g|webp|gif)$/.test(name)) return 'image';
  if (type.startsWith('audio/') || type === 'video/webm' || /\.(webm|wav|mp3|m4a|ogg)$/.test(name)) return 'voice';
  if (/\.(txt|md|log|csv|tsv|json|xml|ya?ml)$/.test(name)) return 'textfile';
  return null;
}

function updateCaptureHint() {
  const hint = document.getElementById('captureHint');
  const text = document.getElementById('noteText').value.trim();
  let message = '';
  if (attachedFile) {
    message = `Will save the ${FILE_KIND_NAMES[fileKind(attachedFile)]}`;
    if (text) message += ' and your text as a separate note';
  } else if (looksLikeUrl(text)) {
    message = 'Looks like a link: Life Inbox will save it and fetch the page text';
  }
  hint.textContent = message;
  hint.hidden = !message;
}

function renderAttachedFile() {
  const chip = document.getElementById('captureAttachment');
  if (!attachedFile) {
    chip.hidden = true;
    chip.replaceChildren();
    return;
  }
  const name = document.createElement('span');
  name.className = 'attachment-name';
  name.textContent = `${CAPTURE_LABELS[fileKind(attachedFile)]} · ${attachedFile.name}`;
  const remove = document.createElement('button');
  remove.type = 'button';
  remove.className = 'ghost attachment-remove';
  remove.setAttribute('aria-label', `Remove ${attachedFile.name}`);
  remove.textContent = '×';
  remove.addEventListener('click', clearAttachedFile);
  chip.replaceChildren(name, remove);
  chip.hidden = false;
}

function attachCaptureFile(file) {
  if (!file) return;
  if (!fileKind(file)) {
    setStatus(
      'noteStatus',
      `“${file.name}” can't be saved here. Life Inbox accepts PDFs, images, audio, and text, CSV or JSON files.`,
      true
    );
    document.getElementById('captureFile').value = '';
    return;
  }
  attachedFile = file;
  setStatus('noteStatus', '');
  renderAttachedFile();
  updateCaptureHint();
}

function clearAttachedFile() {
  attachedFile = null;
  document.getElementById('captureFile').value = '';
  renderAttachedFile();
  updateCaptureHint();
}

async function postCapture(kind, payload) {
  if (kind === 'note' || kind === 'url') {
    return fetchJson(
      kind === 'note' ? '/api/items' : '/api/items/url',
      {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(kind === 'note' ? {raw_text: payload} : {url: payload})
      },
      `Unable to save ${kind}.`
    );
  }
  const formData = new FormData();
  formData.append('file', payload, payload.name || 'voice-note.webm');
  return fetchJson(`/api/items/${kind}`, {method: 'POST', body: formData}, `Unable to upload ${kind}.`);
}

function captureResult(kind, item) {
  if (item && item.processing_status && item.processing_status !== 'ready') {
    return {
      text: `${CAPTURE_LABELS[kind]} saved, but processing failed: ${(item.error_message || 'unknown error').replace(/\.+$/, '')}.`,
      isError: true
    };
  }
  if (kind === 'voice') {
    return {
      text: item && item.extracted_text
        ? 'Voice note saved and transcribed.'
        : 'Voice note saved. Add or edit the transcript if needed.',
      isError: false
    };
  }
  const done = {
    note: 'Note saved.',
    url: 'Link saved and page text fetched.',
    pdf: 'PDF saved and processed.',
    image: 'Image saved and processed.'
  };
  return {text: done[kind], isError: false};
}

async function refreshAfterCapture() {
  await loadNotes('Saved, but the list could not refresh. Reload to try again.');
  await loadLatestAnalysis();
  await loadDashboard();
  await loadCalendar();
}

// The Save button and Ctrl/Cmd+Enter. Saves the attached file (if any),
// then the text as a link or a note. Nothing typed or attached is cleared
// unless it was saved.
async function addNote() {
  if (isSavingNote) return;

  const textarea = document.getElementById('noteText');
  const text = textarea.value.trim();
  const file = attachedFile;
  if (!text && !file) {
    setStatus('noteStatus', 'Write a note, paste a link, or attach a file before saving.', true);
    textarea.focus();
    return;
  }

  isSavingNote = true;
  setButtonBusy('addNoteButton', true, 'Saving…', 'Save');
  const messages = [];
  let hadError = false;
  let savedSomething = false;

  try {
    if (file) {
      const kind = fileKind(file);
      setStatus('noteStatus', CAPTURE_PROGRESS[kind]);
      try {
        const result = captureResult(kind, await postCapture(kind, file));
        messages.push(result.text);
        hadError = hadError || result.isError;
        savedSomething = true;
        if (attachedFile === file) clearAttachedFile();
      } catch {
        messages.push(`We could not upload that ${FILE_KIND_NAMES[kind]}. It is still attached—please try again.`);
        hadError = true;
      }
    }

    if (text && (savedSomething || !file)) {
      const kind = !file && looksLikeUrl(text) ? 'url' : 'note';
      setStatus('noteStatus', CAPTURE_PROGRESS[kind]);
      try {
        const result = captureResult(kind, await postCapture(kind, text));
        messages.push(result.text);
        hadError = hadError || result.isError;
        savedSomething = true;
        if (textarea.value.trim() === text) textarea.value = '';
      } catch {
        messages.push(
          kind === 'url'
            ? 'We could not save that link. It is still in the box—please try again.'
            : 'We could not save your note. Your text is still here—please try again.'
        );
        hadError = true;
      }
    }

    if (hadError) {
      setStatus('noteStatus', messages.join(' '), true);
    } else {
      setStatus('noteStatus', '');
      showToast(messages.join(' '));
    }
    if (savedSomething) await refreshAfterCapture();
  } finally {
    isSavingNote = false;
    setButtonBusy('addNoteButton', false, 'Saving…', 'Save');
    updateCaptureHint();
  }
}

let voiceRecorder = null;
let voiceChunks = [];
let voiceStream = null;

function setRecordingUi(recording) {
  const button = document.getElementById('recordVoiceButton');
  const label = recording ? 'Stop recording and save' : 'Record a voice note';
  button.classList.toggle('recording', recording);
  button.setAttribute('aria-pressed', String(recording));
  button.setAttribute('aria-label', label);
  button.title = label;
}

async function saveRecording(file) {
  setStatus('voiceStatus', '');
  setStatus('noteStatus', 'Saving recorded voice note…');
  try {
    const result = captureResult('voice', await postCapture('voice', file));
    if (result.isError) {
      setStatus('noteStatus', result.text, true);
    } else {
      setStatus('noteStatus', '');
      showToast(result.text);
    }
    await refreshAfterCapture();
  } catch {
    setStatus('noteStatus', 'We could not save that recording. Please try recording again.', true);
  }
}

async function toggleVoiceRecording() {
  if (voiceRecorder && voiceRecorder.state === 'recording') {
    voiceRecorder.stop();
    setRecordingUi(false);
    setStatus('voiceStatus', 'Processing…');
    return;
  }

  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    setStatus('voiceStatus', 'Recording is not available in this browser. Attach an audio file instead.', true);
    return;
  }

  try {
    voiceStream = await navigator.mediaDevices.getUserMedia({audio: true});
    voiceChunks = [];
    voiceRecorder = new MediaRecorder(voiceStream);
    voiceRecorder.addEventListener('dataavailable', event => {
      if (event.data && event.data.size > 0) voiceChunks.push(event.data);
    });
    voiceRecorder.addEventListener('stop', async () => {
      if (voiceStream) {
        voiceStream.getTracks().forEach(track => track.stop());
        voiceStream = null;
      }
      const blob = new Blob(voiceChunks, {type: voiceRecorder.mimeType || 'audio/webm'});
      voiceRecorder = null;
      if (!blob.size) {
        setStatus('voiceStatus', 'Recording was empty.', true);
        return;
      }
      const file = new File([blob], `recording-${Date.now()}.webm`, {
        type: blob.type || 'audio/webm'
      });
      await saveRecording(file);
    });
    voiceRecorder.start();
    setRecordingUi(true);
    setStatus('voiceStatus', 'Recording… tap again to stop and save.');
  } catch {
    setStatus(
      'voiceStatus',
      'Could not access the microphone. You can attach an audio file instead.',
      true
    );
  }
}

function setUpCaptureBox() {
  const card = document.getElementById('captureCard');
  const textarea = document.getElementById('noteText');
  const isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
  document.getElementById('captureShortcut').textContent = isMac ? '⌘ + Enter' : 'Ctrl + Enter';

  textarea.addEventListener('input', updateCaptureHint);
  textarea.addEventListener('keydown', event => {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      addNote();
    }
  });
  // Pasting a screenshot or copied file attaches it; pasted text behaves normally.
  textarea.addEventListener('paste', event => {
    const files = event.clipboardData && event.clipboardData.files;
    if (files && files.length) {
      event.preventDefault();
      attachCaptureFile(files[0]);
    }
  });

  let dragDepth = 0;
  card.addEventListener('dragenter', event => {
    if (!event.dataTransfer || !Array.from(event.dataTransfer.types || []).includes('Files')) return;
    event.preventDefault();
    dragDepth += 1;
    card.classList.add('dragging');
  });
  card.addEventListener('dragover', event => {
    if (card.classList.contains('dragging')) event.preventDefault();
  });
  card.addEventListener('dragleave', () => {
    dragDepth = Math.max(0, dragDepth - 1);
    if (!dragDepth) card.classList.remove('dragging');
  });
  card.addEventListener('drop', event => {
    if (!event.dataTransfer || !event.dataTransfer.files.length) return;
    event.preventDefault();
    dragDepth = 0;
    card.classList.remove('dragging');
    attachCaptureFile(event.dataTransfer.files[0]);
  });
}

function esc(str) {
  return String(str ?? '').replace(/[&<>'"]/g, tag => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', "'":'&#39;', '"':'&quot;'
  }[tag]));
}

function actionButton(label, className, onClick) {
  const button = document.createElement('button');
  button.type = 'button';
  button.textContent = label;
  button.className = className;
  button.addEventListener('click', onClick);
  return button;
}

function captureTypeLabel(itemType) {
  if (itemType === 'pdf') return 'PDF';
  if (itemType === 'image') return 'Image';
  if (itemType === 'voice') return 'Voice';
  if (itemType === 'url') return 'URL';
  return 'Item';
}

function renderNote(note) {
  const root = document.createElement('div');
  root.className = 'note';
  root.dataset.noteId = String(note.id);

  const text = document.createElement('div');
  text.className = 'note-text';
  if (note.item_type === 'url') {
    const title = note.title || note.source_url || 'Saved URL';
    const body = note.extracted_text || note.raw_text || '';
    text.innerHTML = `<strong>${esc(title)}</strong><div class="muted">${esc(note.source_url || '')}</div>${body ? `<div>${esc(body.slice(0, 280))}${body.length > 280 ? '…' : ''}</div>` : ''}`;
  } else if (note.item_type === 'pdf') {
    const title = note.title || note.original_filename || 'PDF document';
    const body = note.extracted_text || note.raw_text || '';
    const preview = note.storage_path
      ? `<a href="/api/items/${note.id}/file" target="_blank" rel="noopener">Open PDF</a>`
      : '';
    text.innerHTML = `<strong>${esc(title)}</strong><div class="muted">${esc(note.original_filename || '')}${preview ? ` · ${preview}` : ''}</div>${body ? `<div>${esc(body.slice(0, 280))}${body.length > 280 ? '…' : ''}</div>` : ''}`;
  } else if (note.item_type === 'image') {
    const title = note.title || note.original_filename || 'Image';
    const ocr = note.extracted_text || '';
    const ai = note.ai_description || '';
    const thumb = note.storage_path
      ? `<img class="capture-thumb" src="/api/items/${note.id}/file?variant=thumb" alt="Thumbnail for ${esc(title)}" />`
      : '';
    const open = note.storage_path
      ? `<a href="/api/items/${note.id}/file" target="_blank" rel="noopener">Open image</a>`
      : '';
    text.innerHTML = [
      `<strong>${esc(title)}</strong>`,
      `<div class="muted">${esc(note.original_filename || '')}${open ? ` · ${open}` : ''}</div>`,
      thumb,
      `<div class="provenance"><span class="label">OCR (extracted)</span>: ${ocr ? esc(ocr.slice(0, 280)) + (ocr.length > 280 ? '…' : '') : '<em class="muted">none</em>'}</div>`,
      ai ? `<div class="provenance"><span class="label">AI description (inferred)</span>: ${esc(ai.slice(0, 320))}${ai.length > 320 ? '…' : ''}</div>` : ''
    ].join('');
  } else if (note.item_type === 'voice') {
    const title = note.title || note.original_filename || 'Voice note';
    const transcript = note.extracted_text || '';
    const player = note.storage_path
      ? `<audio controls preload="none" src="/api/items/${note.id}/file"></audio>`
      : '';
    text.innerHTML = [
      `<strong>${esc(title)}</strong>`,
      `<div class="muted">${esc(note.original_filename || '')}</div>`,
      player,
      `<div class="provenance"><span class="label">Transcript (extracted)</span>: ${transcript ? esc(transcript.slice(0, 320)) + (transcript.length > 320 ? '…' : '') : '<em class="muted">none yet — edit to add</em>'}</div>`
    ].join('');
  } else {
    text.textContent = note.raw_text;
  }

  const time = document.createElement('div');
  time.className = 'time';
  const status = note.processing_status ? ` · ${note.processing_status}` : '';
  const error = note.error_message ? ` · ${note.error_message}` : '';
  time.textContent = `#${note.id} · ${note.item_type}${status}${error} · `;
  time.append(timestampElement(note.created_at));

  const actions = document.createElement('div');
  actions.className = 'note-actions';

  if (note.item_type === 'text') {
    const editButton = actionButton('Edit', 'secondary', () => {
      showEditNote(note, root);
    });
    const deleteButton = actionButton('Delete', 'danger', () => {
      deleteExistingNote(note, root, editButton, deleteButton);
    });
    actions.append(editButton, deleteButton);
  } else if (
    ['url', 'pdf', 'image', 'voice'].includes(note.item_type) &&
    note.processing_status === 'failed'
  ) {
    actions.append(
      actionButton('Retry', '', async () => {
        try {
          const updated = await fetchJson(
            `/api/items/${note.id}/retry`,
            {method: 'POST'},
            'Unable to retry capture processing.'
          );
          root.replaceWith(renderNote(updated));
          const label = captureTypeLabel(note.item_type);
          setStatus(
            'noteStatus',
            updated.processing_status === 'ready'
              ? `${label} processed.`
              : `${label} still failed.`
          );
          await loadLatestAnalysis();
          await loadDashboard();
        } catch {
          setStatus('noteStatus', 'Retry failed.', true);
        }
      })
    );
    actions.append(
      actionButton('Delete', 'danger', () => {
        deleteExistingNote(note, root, null, null);
      })
    );
  } else if (
    (note.item_type === 'image' || note.item_type === 'voice') &&
    note.processing_status === 'ready'
  ) {
    actions.append(
      actionButton(
        note.item_type === 'voice' ? 'Edit transcript' : 'Edit OCR text',
        'secondary',
        () => {
          showEditExtractedText(note, root);
        }
      )
    );
    actions.append(
      actionButton('Delete', 'danger', () => {
        deleteExistingNote(note, root, null, null);
      })
    );
  } else if (note.item_type === 'pdf') {
    actions.append(
      actionButton('Delete', 'danger', () => {
        deleteExistingNote(note, root, null, null);
      })
    );
  } else {
    actions.append(
      actionButton('Delete', 'danger', () => {
        deleteExistingNote(note, root, null, null);
      })
    );
  }

  root.append(text, time, actions);
  return root;
}

function showEditExtractedText(note, root) {
  if (pendingNoteActions.has(note.id)) return;

  const textarea = document.createElement('textarea');
  textarea.className = 'note-edit-input';
  textarea.maxLength = 20000;
  textarea.value = note.extracted_text || '';

  const hint = document.createElement('div');
  hint.className = 'provenance';
  const isVoice = note.item_type === 'voice';
  hint.innerHTML = isVoice
    ? '<span class="label">Editing transcript</span> (extracted text from the original audio).'
    : '<span class="label">Editing extracted / OCR text</span> (facts). AI description stays separate.';

  const actions = document.createElement('div');
  actions.className = 'note-actions';

  const saveButton = actionButton(isVoice ? 'Save transcript' : 'Save OCR text', '', async () => {
    if (pendingNoteActions.has(note.id)) return;
    pendingNoteActions.add(note.id);
    saveButton.disabled = true;
    cancelButton.disabled = true;
    saveButton.textContent = 'Saving…';
    setStatus('noteStatus', 'Saving extracted text…');
    try {
      const updated = await fetchJson(
        `/api/items/${note.id}/extracted-text`,
        {
          method: 'PATCH',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({extracted_text: textarea.value})
        },
        'Unable to update extracted text.'
      );
      root.replaceWith(renderNote(updated));
      setStatus('noteStatus', isVoice ? 'Transcript updated.' : 'Extracted text updated.');
      await loadLatestAnalysis();
    } catch {
      setStatus('noteStatus', 'Could not update extracted text.', true);
      saveButton.disabled = false;
      cancelButton.disabled = false;
      saveButton.textContent = isVoice ? 'Save transcript' : 'Save OCR text';
    } finally {
      pendingNoteActions.delete(note.id);
    }
  });

  const cancelButton = actionButton('Cancel', 'secondary', () => {
    if (pendingNoteActions.has(note.id)) return;
    root.replaceWith(renderNote(note));
  });

  actions.append(saveButton, cancelButton);
  root.replaceChildren(hint, textarea, actions);
}

function showEditNote(note, root) {
  if (pendingNoteActions.has(note.id)) return;

  const textarea = document.createElement('textarea');
  textarea.className = 'note-edit-input';
  textarea.maxLength = 2000;
  textarea.value = note.raw_text;

  const actions = document.createElement('div');
  actions.className = 'note-actions';

  const saveButton = actionButton('Save', '', async () => {
    const text = textarea.value.trim();
    if (!text) {
      setStatus('noteStatus', 'Edited note text cannot be empty.', true);
      textarea.focus();
      return;
    }
    if (pendingNoteActions.has(note.id)) return;

    pendingNoteActions.add(note.id);
    saveButton.disabled = true;
    cancelButton.disabled = true;
    saveButton.textContent = 'Saving…';
    setStatus('noteStatus', 'Saving your changes…');

    try {
      const updatedNote = await fetchJson(
        `/api/items/${note.id}`,
        {
          method: 'PUT',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({raw_text: text})
        },
        'Unable to update note.'
      );
      LifeInboxPagination.afterLoadedNoteUpdated(itemPagination, updatedNote);
      root.replaceWith(renderNote(updatedNote));
      setStatus('noteStatus', 'Note updated.');
      await loadLatestAnalysis();
    } catch {
      setStatus(
        'noteStatus',
        'We could not update this note. Your changes are still here—please try again.',
        true
      );
      saveButton.disabled = false;
      cancelButton.disabled = false;
      saveButton.textContent = 'Save';
    } finally {
      pendingNoteActions.delete(note.id);
    }
  });

  const cancelButton = actionButton('Cancel', 'secondary', () => {
    if (pendingNoteActions.has(note.id)) return;
    root.replaceWith(renderNote(note));
    setStatus('noteStatus', 'Edit cancelled.');
  });

  actions.append(saveButton, cancelButton);
  root.replaceChildren(textarea, actions);
  textarea.focus();
}

// Delete with Undo: the card disappears at once, but the DELETE request is
// only sent after DELETE_UNDO_MS. Undo in that window and nothing is ever
// deleted. If the page is closed first, the request is still sent with
// keepalive so the person's choice is honoured.
const DELETE_UNDO_MS = 6000;
const pendingDeletes = new Map();

function deleteExistingNote(note, root) {
  if (pendingNoteActions.has(note.id) || pendingDeletes.has(note.id)) return;

  root.classList.add('note-leaving');
  setTimeout(() => {
    if (pendingDeletes.has(note.id)) root.hidden = true;
  }, 200);
  const timer = setTimeout(() => commitDelete(note.id), DELETE_UNDO_MS);
  pendingDeletes.set(note.id, {timer, root});
  showToast('Item deleted.', {
    actionLabel: 'Undo',
    duration: DELETE_UNDO_MS,
    onAction: () => undoDelete(note.id)
  });
}

function undoDelete(noteId) {
  const pending = pendingDeletes.get(noteId);
  if (!pending) return;
  clearTimeout(pending.timer);
  pendingDeletes.delete(noteId);
  if (pending.root.isConnected) {
    pending.root.hidden = false;
    pending.root.classList.remove('note-leaving');
  } else {
    // The list was reloaded in the meantime; render it again with the item.
    loadNotes();
  }
  showToast('Item restored.');
}

async function commitDelete(noteId, {keepalive = false} = {}) {
  const pending = pendingDeletes.get(noteId);
  if (!pending) return;
  clearTimeout(pending.timer);
  pendingDeletes.delete(noteId);

  if (keepalive) {
    fetch(`/api/items/${noteId}`, {method: 'DELETE', keepalive: true});
    return;
  }

  pendingNoteActions.add(noteId);
  try {
    await fetchJson(
      `/api/items/${noteId}`,
      {method: 'DELETE'},
      'Unable to delete note.'
    );
    LifeInboxPagination.afterLoadedNoteDeleted(itemPagination, noteId);
    pending.root.remove();
    await loadLatestAnalysis();
    await loadTasks();
    await loadDashboard();
    await loadCalendar();
  } catch {
    if (pending.root.isConnected) {
      pending.root.hidden = false;
      pending.root.classList.remove('note-leaving');
    } else {
      loadNotes();
    }
    showToast('We could not delete that item. It is back in your list—please try again.');
  } finally {
    pendingNoteActions.delete(noteId);
  }
}

window.addEventListener('pagehide', () => {
  for (const noteId of [...pendingDeletes.keys()]) {
    commitDelete(noteId, {keepalive: true});
  }
});

function renderTask(task) {
  const root = document.createElement('div');
  root.className = 'task';
  root.dataset.taskId = String(task.id);

  const text = document.createElement('strong');
  text.textContent = task.text;

  const priority = document.createElement('span');
  priority.className = priorityClass(task.priority);
  priority.textContent = task.priority;

  const content = document.createElement('div');
  content.append(text, priority);

  const meta = document.createElement('div');
  meta.className = 'task-meta';
  const timingLabel = task.timing_text
    ? ` · ${task.timing_text}${task.timing_confirmed ? ' (confirmed)' : ' (AI suggested)'}`
    : '';
  const sources = task.source_item_ids
    .map(itemId => `#${itemId}`)
    .join(', ');
  meta.textContent = `${task.status}${timingLabel} · Sources: ${sources}`;
  if (task.due_on) {
    const due = document.createElement('span');
    due.dataset.dueOn = task.due_on;
    due.textContent = ` · ${relativeDueLabel(task.due_on)} · ${task.due_on}`;
    meta.append(due);
  }

  const badge = document.createElement('span');
  badge.className = 'days-badge';
  badge.dataset.dueOn = task.due_on || '';
  paintDaysBadge(badge);
  if (task.due_on) priority.after(badge);
  const worth = document.createElement('span');
  worth.className = 'points-chip';
  worth.textContent = `+${task.points_value} pts`;
  priority.after(worth);

  const actions = document.createElement('div');
  actions.className = 'task-actions';

  if (task.status === 'open') {
    root.draggable = true;
    root.classList.add('task-draggable');
    root.addEventListener('dragstart', event => {
      event.dataTransfer.setData('text/x-task-id', String(task.id));
      event.dataTransfer.effectAllowed = 'move';
      root.classList.add('task-dragging');
    });
    root.addEventListener('dragend', () => root.classList.remove('task-dragging'));
    actions.append(
      actionButton('Complete', '', () => {
        transitionTask(task.id, 'complete', actions);
      }),
      actionButton('Dismiss', 'secondary', () => {
        transitionTask(task.id, 'dismiss', actions);
      }),
      actionButton('Snooze 1 day', 'secondary', async () => {
        const until = new Date();
        until.setUTCDate(until.getUTCDate() + 1);
        const iso = until.toISOString().slice(0, 10);
        try {
          await fetchJson(
            `/api/tasks/${task.id}/snooze`,
            {
              method: 'POST',
              headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({until: iso})
            },
            'Unable to snooze task.'
          );
          showToast(`Snoozed: back ${relativeDueLabel(iso).toLowerCase()}.`);
          await loadTasks();
          await loadAttention();
          await loadCalendar();
        } catch {
          setStatus('taskStatus', 'Could not snooze task.', true);
        }
      })
    );
    if (task.timing_text && !task.timing_confirmed) {
      actions.append(
        actionButton('Confirm date', 'secondary', async () => {
          try {
            await fetchJson(
              `/api/tasks/${task.id}/confirm-timing`,
              {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({timing_text: task.timing_text})
              },
              'Unable to confirm timing.'
            );
            showToast('Date confirmed.');
            await loadTasks();
            await loadDashboard();
            await loadAttention();
            await loadCalendar();
          } catch {
            setStatus('taskStatus', 'Could not confirm timing.', true);
          }
        })
      );
    }
    if (!task.due_on && task.suggested_due_on) {
      actions.append(
        actionButton(`Set deadline ${task.suggested_due_on}`, 'secondary', async () => {
          try {
            await fetchJson(
              `/api/tasks/${task.id}/confirm-timing`,
              {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({timing_text: task.suggested_due_on})
              },
              'Unable to set deadline.'
            );
            showToast(`Deadline set for ${task.suggested_due_on}.`);
            await loadTasks();
            await loadAttention();
            await loadCalendar();
          } catch {
            setStatus('taskStatus', 'Could not set deadline.', true);
          }
        })
      );
    }
    if (task.priority === 'High' && task.due_on) {
      actions.append(
        actionButton('Find time', 'secondary', () => toggleSlots(task, root))
      );
    }
    if (task.google_event_url) {
      actions.append(
        actionButton('Add to Google Calendar', 'secondary', () => {
          window.open(task.google_event_url, '_blank', 'noopener');
        })
      );
    }
    if (task.timing_confirmed && (task.due_on || task.timing_text)) {
      actions.append(
        actionButton('Preview calendar', 'secondary', () => {
          previewCalendarForTask(task);
        })
      );
    }
  } else if (task.binned_at) {
    const earned = document.createElement('span');
    earned.textContent = ` · Completed ${(task.completed_at || '').slice(0, 10)} · +${task.points_awarded || 0} pts kept`;
    meta.append(earned);
    actions.append(
      actionButton('Restore', '', async () => {
        try {
          await fetchJson(`/api/tasks/${task.id}/restore`, {method: 'POST'}, 'Unable to restore task.');
          showToast('Task restored to Completed.');
          await loadTasks();
        } catch {
          setStatus('taskStatus', 'Could not restore this task.', true);
        }
      })
    );
  } else {
    if (task.status === 'completed') {
      root.draggable = true;
      root.classList.add('task-draggable');
      root.addEventListener('dragstart', event => {
        event.dataTransfer.setData('text/x-task-id', String(task.id));
        event.dataTransfer.effectAllowed = 'move';
        root.classList.add('task-dragging');
      });
      root.addEventListener('dragend', () => root.classList.remove('task-dragging'));
      actions.append(
        actionButton('Bin it', 'secondary', () => binTask(task.id, root))
      );
    }
    actions.append(
      actionButton('Reopen', '', () => {
        transitionTask(task.id, 'reopen', actions);
      })
    );
  }

  root.append(content, meta, actions);
  return root;
}

async function transitionTask(taskId, action, actions) {
  if (pendingTaskActions.has(taskId)) return;

  pendingTaskActions.add(taskId);
  const buttons = actions.querySelectorAll('button');
  buttons.forEach(button => {
    button.disabled = true;
  });
  setStatus('taskStatus', '');

  try {
    await fetchJson(
      `/api/tasks/${taskId}/${action}`,
      {method: 'POST'},
      'Unable to update task.'
    );
    // Every transition moves the task out of the current filter, so let the
    // card strike through and fade before the list reloads.
    const card = actions.closest('.task');
    if (card) {
      card.classList.add(action === 'complete' ? 'task-completing' : 'task-leaving');
      await new Promise(resolve => setTimeout(resolve, 350));
    }
    const messages = {
      complete: 'Task completed.',
      dismiss: 'Task dismissed.',
      reopen: 'Task reopened.'
    };
    showToast(
      messages[action],
      action === 'reopen'
        ? {}
        : {actionLabel: 'Undo', onAction: () => undoTaskTransition(taskId, action)}
    );
    await loadTasks();
    await loadAttention();
    await loadCalendar();
  } catch {
    setStatus(
      'taskStatus',
      'We could not update this task. Please try again.',
      true
    );
    buttons.forEach(button => {
      button.disabled = false;
    });
  } finally {
    pendingTaskActions.delete(taskId);
  }
}

async function undoTaskTransition(taskId, action) {
  try {
    await fetchJson(
      `/api/tasks/${taskId}/reopen`,
      {method: 'POST'},
      'Unable to undo.'
    );
    showToast(action === 'complete' ? 'Task is open again.' : 'Task restored.');
    await loadTasks();
    await loadAttention();
    await loadCalendar();
  } catch {
    setStatus(
      'taskStatus',
      `We could not undo that. Show ${action === 'complete' ? 'Completed' : 'Dismissed'} tasks and click Reopen.`,
      true
    );
  }
}

let lastQuestPoints = null;

async function loadGame() {
  try {
    const game = await fetchJson('/api/game/today', undefined, 'Unable to load progress.');
    const circumference = 2 * Math.PI * 52;
    const ring = document.getElementById('questRing');
    ring.style.strokeDasharray = String(circumference);
    ring.style.strokeDashoffset = String(circumference * (1 - game.percent / 100));
    ring.classList.toggle('ring-complete', game.goal_met);
    document.getElementById('questPoints').textContent = String(game.points_today);
    document.getElementById('questGoal').textContent = String(game.goal);
    const left = Math.max(0, game.goal - game.points_today);
    document.getElementById('questLine').textContent = game.goal_met
      ? 'Daily goal reached. Everything from here is bonus.'
      : `${left} point${left === 1 ? '' : 's'} to go today.`;
    const lvl = game.level;
    document.getElementById('questLevel').textContent =
      `Lv ${lvl.number} ${lvl.title} · ${game.lifetime_points} pts`;
    const fill = document.getElementById('levelFill');
    const next = document.getElementById('levelNext');
    if (lvl.next_at === null) {
      fill.style.width = '100%';
      next.textContent = 'Top level reached.';
    } else {
      const pct = Math.round(((game.lifetime_points - lvl.floor) / (lvl.next_at - lvl.floor)) * 100);
      fill.style.width = `${Math.max(0, Math.min(100, pct))}%`;
      next.textContent = `${lvl.points_to_next} pts to the next level`;
    }
    const streakEl = document.getElementById('questStreak');
    streakEl.textContent = game.streak ? `🔥 ${game.streak}-day streak` : 'No streak yet';
    streakEl.classList.toggle('streak-live', game.streak > 0);
    document.getElementById('questDone').textContent =
      ` · ${game.tasks_done_today} done today`;
    const week = document.getElementById('questWeek');
    week.innerHTML = '';
    for (const day of game.history) {
      const cell = document.createElement('div');
      cell.className = `week-cell${day.goal_met ? ' week-met' : ''}`;
      cell.title = `${day.day}: ${day.points} pts`;
      cell.innerHTML = `<span class="week-bar"><i style="height:${Math.min(100, day.points)}%"></i></span><small>${day.weekday}</small>`;
      week.append(cell);
    }
    if (lastQuestPoints !== null && game.points_today > lastQuestPoints) {
      const pop = document.getElementById('questPop');
      pop.textContent = `+${game.points_today - lastQuestPoints}`;
      pop.classList.remove('quest-pop-go');
      void pop.offsetWidth;
      pop.classList.add('quest-pop-go');
      playChime(false);
      if (game.goal_met && lastQuestPoints < game.goal) {
        showToast('🎉 Daily goal reached: 100 points!');
        launchConfetti();
        playChime(true);
        document.getElementById('questCard').classList.add('quest-celebrate');
        setTimeout(() => document.getElementById('questCard').classList.remove('quest-celebrate'), 1800);
      }
    }
    lastQuestPoints = game.points_today;
  } catch {
    /* progress is decorative; ignore failures */
  }
}

// Voice to task: browser speech recognition first, recorded-audio upload as fallback.
async function addQuickTask(sentence) {
  const task = await fetchJson(
    '/api/tasks/quick',
    {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({sentence})
    },
    'Unable to add task.'
  );
  announceNewTask(task);
}

function announceNewTask(task) {
  const when = task.due_on ? ` · ${task.days_left_label}` : '';
  showToast(`Added “${task.text}” · ${task.priority} (+${task.points_value} pts)${when}`);
}

function setupQuickTask() {
  const form = document.getElementById('quickTaskForm');
  const input = document.getElementById('quickTaskInput');
  const mic = document.getElementById('quickMic');
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  let listening = null;

  async function submit(sentence) {
    const value = sentence.trim();
    if (!value) return;
    try {
      await addQuickTask(value);
      input.value = '';
      document.getElementById('taskStatusFilter').value = 'open';
      await loadTasks();
      await loadAttention();
      await loadCalendar();
    } catch {
      setStatus('taskStatus', 'Could not add that task. Try rephrasing it.', true);
    }
  }

  form.addEventListener('submit', event => {
    event.preventDefault();
    submit(input.value);
  });

  async function recordAndUpload() {
    if (listening) {
      listening.stop();
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({audio: true});
      const chunks = [];
      const recorder = new MediaRecorder(stream);
      listening = recorder;
      mic.classList.add('mic-live');
      recorder.ondataavailable = e => chunks.push(e.data);
      recorder.onstop = async () => {
        stream.getTracks().forEach(track => track.stop());
        mic.classList.remove('mic-live');
        listening = null;
        const form = new FormData();
        form.append('file', new Blob(chunks, {type: recorder.mimeType || 'audio/webm'}), 'voice-task.webm');
        try {
          const task = await fetchJson('/api/tasks/voice', {method: 'POST', body: form}, 'Unable to transcribe.');
          announceNewTask(task);
          await loadTasks();
        } catch {
          setStatus('taskStatus', 'Transcription is unavailable. Type the task instead.', true);
        }
      };
      recorder.start();
    } catch {
      setStatus('taskStatus', 'Microphone is not available. Type the task instead.', true);
    }
  }

  mic.addEventListener('click', () => {
    if (!Recognition) {
      recordAndUpload();
      return;
    }
    if (listening) {
      listening.stop();
      return;
    }
    const recognition = new Recognition();
    recognition.lang = navigator.language || 'en-US';
    recognition.interimResults = true;
    listening = recognition;
    mic.classList.add('mic-live');
    input.placeholder = 'Listening…';
    recognition.onresult = event => {
      input.value = Array.from(event.results).map(r => r[0].transcript).join(' ');
    };
    recognition.onerror = () => {
      setStatus('taskStatus', 'Could not hear that. Check the microphone permission or type it.', true);
    };
    recognition.onend = () => {
      mic.classList.remove('mic-live');
      input.placeholder = 'Say or type: “Call the dentist Friday, high priority”';
      listening = null;
      if (input.value.trim()) submit(input.value);
    };
    recognition.start();
  });
}
setupQuickTask();

async function binTask(taskId, card) {
  try {
    await fetchJson(`/api/tasks/${taskId}/bin`, {method: 'POST'}, 'Unable to bin task.');
    if (card) {
      card.classList.add('task-binned');
      await new Promise(resolve => setTimeout(resolve, 450));
    }
    showToast('Binned. Find it any time in Backlog.', {
      actionLabel: 'Undo',
      onAction: async () => {
        await fetchJson(`/api/tasks/${taskId}/restore`, {method: 'POST'}, 'Unable to undo.');
        await loadTasks();
      }
    });
    await loadTasks();
  } catch {
    setStatus('taskStatus', 'Could not bin this task.', true);
  }
}

function setupBinZone() {
  const zone = document.getElementById('binZone');
  zone.addEventListener('dragover', event => {
    event.preventDefault();
    zone.classList.add('bin-over');
  });
  zone.addEventListener('dragleave', () => zone.classList.remove('bin-over'));
  zone.addEventListener('drop', event => {
    event.preventDefault();
    zone.classList.remove('bin-over');
    const id = Number(event.dataTransfer.getData('text/x-task-id'));
    if (!id) return;
    const card = document.querySelector(`.task[data-task-id="${id}"]`);
    binTask(id, card);
  });
}
setupBinZone();

async function loadTasks() {
  loadGame();
  loadTeam();
  const filter = document.getElementById('taskStatusFilter').value;
  document.getElementById('binZone').hidden = filter !== 'completed';
  document.getElementById('taskDrops').hidden = filter !== 'open';
  paintDayStrip();
  try {
    const tasks = await fetchJson(
      `/api/tasks?status=${encodeURIComponent(filter)}`,
      undefined,
      'Unable to load tasks.'
    );
    const root = document.getElementById('tasksList');
    root.innerHTML = '';

    if (!tasks.length) {
      const emptyTasks = {
        open: {
          title: 'No open tasks',
          text: 'Analyze your inbox to turn notes like “renew passport this week” into tasks.',
          action: '<a class="button-link" href="#inbox">Go to Inbox</a>'
        },
        completed: {title: 'Nothing completed yet', text: 'Tasks you complete will be listed here.'},
        dismissed: {title: 'No dismissed tasks', text: 'Tasks you dismiss will be listed here.'},
        backlog: {title: 'Backlog is empty', text: 'Completed tasks you bin are kept here, with their points.'}
      };
      root.innerHTML = emptyStateHtml({icon: 'check', ...(emptyTasks[filter] || emptyTasks.open)});
      updateNavCounts();
      return true;
    }

    for (const task of tasks) {
      root.appendChild(renderTask(task));
    }
    updateNavCounts();
    return true;
  } catch {
    setStatus(
      'taskStatus',
      'We could not load tasks. Reload to try again.',
      true
    );
    return false;
  }
}

function renderAnalysis(data) {
  const root = document.getElementById('aiOutput');
  const generatedAt = data.generated_at
    ? friendlyTimestamp(data.generated_at)
    : null;
  const staleBanner = data.is_stale
    ? `<div class="banner warn" role="status">Analysis is stale — inbox items changed since this run. Re-analyze to refresh.</div>`
    : '';

  const bucketHtml = (data.buckets || []).map(bucket => `
    <div class="panel">
      <h3>${esc(bucket.name)}</h3>
      <ul>
        ${(bucket.notes || []).map(n =>
          `<li>${esc(n.title)} <span class="${priorityClass(n.priority)}">${esc(n.priority)}</span></li>`
        ).join('')}
      </ul>
    </div>
  `).join('');

  const todoHtml = (data.todos || []).map(t =>
    `<li><strong>${esc(t.task)}</strong> <span class="${priorityClass(t.priority)}">${esc(t.priority)}</span>${t.when ? ` · ${esc(t.when)}` : ''}</li>`
  ).join('');

  const pv = data.priority_view || {High: [], Medium: [], Low: []};
  const priorityHtml = ['High', 'Medium', 'Low'].map(level => `
    <div class="panel">
      <h3>${level} priority (${(pv[level] || []).length})</h3>
      <ul>
        ${(pv[level] || []).map(n => `<li>${esc(n.title)}</li>`).join('') || '<li class="muted">None</li>'}
      </ul>
    </div>
  `).join('');

  root.innerHTML = `
    ${staleBanner}
    ${generatedAt ? `<p class="muted"><strong>Generated:</strong> ${esc(generatedAt)}</p>` : ''}

    <h3>Buckets</h3>
    ${bucketHtml || '<p class="muted">No notes yet.</p>'}

    <h3>ToDos</h3>
    <ul>${todoHtml || '<li class="muted">No concrete ToDos detected.</li>'}</ul>

    <h3>Priority view</h3>
    ${priorityHtml}

    <p class="muted">Mode: ${esc(data.mode || 'unknown')}</p>
  `;
}

async function loadLatestAnalysis() {
  try {
    const data = await fetchJson(
      '/api/analyze/latest',
      undefined,
      'Unable to load saved analysis.'
    );
    if (!data) {
      document.getElementById('aiOutput').innerHTML =
        '<span class="muted">No saved analysis yet for this account.</span>';
      setStatus('analysisStatus', '');
      return;
    }

    populateCategoryFilter(data);
    renderAnalysis(data);
    const generatedAt = friendlyTimestamp(data.generated_at);
    setStatus(
      'analysisStatus',
      data.is_stale
        ? `Saved analysis from ${generatedAt} is stale — re-analyze after inbox changes.`
        : `Showing saved analysis generated ${generatedAt}.`,
      Boolean(data.is_stale)
    );
  } catch {
    setStatus(
      'analysisStatus',
      'We could not load the saved analysis. You can try analyzing again.',
      true
    );
  }
}

async function analyzeInbox() {
  if (isAnalyzingInbox) return;

  isAnalyzingInbox = true;
  setButtonBusy(
    'analyzeButton',
    true,
    'Analyzing…',
    'Analyze Entire Inbox with AI'
  );
  setStatus('analysisStatus', 'Analyzing your saved notes…');

  try {
    const data = await fetchJson(
      '/api/analyze',
      {method: 'POST'},
      'Unable to analyze inbox.'
    );
    populateCategoryFilter(data);
    renderAnalysis(data);
    await loadTasks();
    await loadTopics();
    await loadDashboard();
    await loadCalendar();
    setStatus('analysisStatus', 'Analysis complete.');
  } catch {
    setStatus(
      'analysisStatus',
      'We could not analyze your inbox. Your notes are still here—please try again.',
      true
    );
  } finally {
    isAnalyzingInbox = false;
    setButtonBusy(
      'analyzeButton',
      false,
      'Analyzing…',
      'Analyze Entire Inbox with AI'
    );
  }
}

const itemPagination = LifeInboxPagination.createState(
  LifeInboxPagination.PAGE_SIZE
);

function updateLoadMoreButton(failureMessage) {
  const existingMore = document.getElementById('loadMoreItems');
  if (existingMore) existingMore.remove();
  if (!itemPagination.hasMore) return;

  const root = document.getElementById('notesList');
  const more = document.createElement('button');
  more.id = 'loadMoreItems';
  more.type = 'button';
  more.className = 'secondary';
  more.textContent = itemPagination.listRequestInFlight
    ? 'Loading…'
    : 'Load more';
  more.disabled = itemPagination.listRequestInFlight;
  more.setAttribute(
    'aria-busy',
    String(itemPagination.listRequestInFlight)
  );
  more.addEventListener('click', () => {
    if (itemPagination.listRequestInFlight) return;
    loadNotes(failureMessage, {append: true});
  });
  root.appendChild(more);
}

async function loadNotes(
  failureMessage = 'We could not load your notes. Reload to try again.',
  {append = false} = {}
) {
  if (!LifeInboxPagination.beginListRequest(itemPagination)) {
    return false;
  }
  loadBoard();

  const params = itemFilterParams();
  if (!append) {
    LifeInboxPagination.resetForReload(itemPagination);
  }
  params.set('limit', String(itemPagination.pageSize));
  params.set('offset', String(itemPagination.loadedOffset));
  const filtered = [...params.keys()].some(
    key => key !== 'limit' && key !== 'offset' && params.get(key)
  );
  const query = params.toString();

  if (append) {
    updateLoadMoreButton(failureMessage);
  }

  try {
    const notes = await fetchJson(
      `/api/items?${query}`,
      undefined,
      'Unable to load notes.'
    );
    const root = document.getElementById('notesList');
    if (!append) {
      root.innerHTML = '';
    } else {
      const existingMore = document.getElementById('loadMoreItems');
      if (existingMore) existingMore.remove();
    }

    if (!append && !notes.length) {
      root.innerHTML = filtered
        ? emptyStateHtml({
          icon: 'search',
          title: 'No matches',
          text: 'Try different words, or clear the filters to see everything.',
          action: '<button type="button" class="secondary" onclick="clearItemFilters()">Clear filters</button>'
        })
        : emptyStateHtml({
          icon: 'inbox',
          title: 'Your inbox is empty',
          text: 'Save a thought, link or file on Today and it will show up here.',
          action: '<a class="button-link" href="#today">Capture something</a>'
        });
      setStatus(
        'searchStatus',
        filtered ? 'No results found.' : ''
      );
      updateNavCounts();
      return true;
    }

    const {textNotes, hasMore} = LifeInboxPagination.applyFetchedPage(
      itemPagination,
      notes,
      {append}
    );

    for (const note of textNotes) {
      if (pendingDeletes.has(note.id)) continue;
      root.appendChild(renderNote(note));
    }

    if (hasMore) {
      updateLoadMoreButton(failureMessage);
    }

    updateNavCounts();
    const loadedCount = itemPagination.loadedItems.length;
    setStatus(
      'searchStatus',
      filtered
        ? `${loadedCount}${hasMore ? '+' : ''} matching item${loadedCount === 1 ? '' : 's'}.`
        : hasMore
          ? `Showing ${loadedCount}+ items.`
          : ''
    );
    return true;
  } catch {
    if (append) {
      setStatus(
        'noteStatus',
        'We could not load more notes. Your current notes are still here—please try again.',
        true
      );
      updateLoadMoreButton(failureMessage);
    } else if (filtered) {
      setStatus(
        'searchStatus',
        'Search failed. Please try again.',
        true
      );
    } else {
      setStatus('noteStatus', failureMessage, true);
    }
    return false;
  } finally {
    LifeInboxPagination.endListRequest(itemPagination);
    if (itemPagination.hasMore) {
      updateLoadMoreButton(failureMessage);
    }
  }
}

async function loadTopics() {
  try {
    const topics = await fetchJson(
      '/api/topics',
      undefined,
      'Unable to load topics.'
    );
    const root = document.getElementById('topics');
    root.innerHTML = '';
    if (!topics.length) {
      root.innerHTML = '<div class="panel muted">No topics yet.</div>';
      return;
    }
    for (const topic of topics) {
      const row = document.createElement('div');
      row.className = 'topic';
      row.innerHTML = `<strong>${esc(topic.name)}</strong><div class="muted">${topic.item_count} item${topic.item_count === 1 ? '' : 's'}${topic.description ? ` · ${esc(topic.description)}` : ''}</div>`;
      root.appendChild(row);
    }
  } catch {
    setStatus('topicStatus', 'We could not load topics.', true);
  }
}

async function createTopic(event) {
  event.preventDefault();
  const input = document.getElementById('topicName');
  const name = input.value.trim();
  if (!name) return;
  try {
    await fetchJson(
      '/api/topics',
      {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name})
      },
      'Unable to create topic.'
    );
    input.value = '';
    setStatus('topicStatus', 'Topic added.');
    await loadTopics();
    await loadDashboard();
  } catch {
    setStatus('topicStatus', 'Could not create that topic. It may already exist.', true);
  }
}

async function loadDashboard() {
  try {
    const data = await fetchJson(
      '/api/dashboard',
      undefined,
      'Unable to load dashboard.'
    );
    const root = document.getElementById('dashboard');
    const section = (title, body) => `
      <div class="panel">
        <h3>${esc(title)}</h3>
        ${body}
      </div>
    `;
    const listOrEmpty = (items, render) =>
      items && items.length
        ? `<ul>${items.map(render).join('')}</ul>`
        : '<p class="muted">Nothing here yet.</p>';

    root.innerHTML = `
      <div class="dashboard-grid">
        ${section('Topics / Spaces', listOrEmpty(data.topics, t =>
          `<li><strong>${esc(t.name)}</strong> · ${t.item_count}</li>`
        ))}
        ${section('High Priority', listOrEmpty(data.high_priority, item =>
          `<li>${esc(item.effective_title || item.raw_text || ('#' + item.id))}${item.rationale ? `<div class="why">Why: ${esc(item.rationale)}</div>` : ''}</li>`
        ))}
        ${section('Open Tasks', listOrEmpty(data.open_tasks, task =>
          `<li><strong>${esc(task.text)}</strong> <span class="${priorityClass(task.priority)}">${esc(task.priority)}</span>${task.timing_text ? ` · ${esc(task.timing_text)}${task.timing_confirmed ? ' (confirmed)' : ' (AI suggested)'}` : ''}</li>`
        ))}
        ${section('Recently Captured', listOrEmpty(data.recently_captured, item =>
          `<li>#${item.id} · ${esc((item.raw_text || '').slice(0, 80))}</li>`
        ))}
        ${section('Needs Review', listOrEmpty(data.needs_review, item =>
          `<li>#${item.id} · ${esc(item.reason || 'Review needed')}</li>`
        ))}
        ${section('Related Items', listOrEmpty(data.related_items, rel =>
          `<li>#${rel.item_id_a} ↔ #${rel.item_id_b} <span class="pill">${esc(rel.relation_type)}</span></li>`
        ))}
      </div>
    `;
    setStatus('dashboardStatus', 'Dashboard updated.');
  } catch {
    setStatus('dashboardStatus', 'We could not load the organized dashboard.', true);
  }
}

function fillAskExample(text) {
  const input = document.getElementById('askQuestion');
  input.value = text;
  input.focus();
}

function renderAskResponse(data) {
  const root = document.getElementById('askOutput');
  root.innerHTML = '';
  const confidence = document.createElement('div');
  confidence.className = 'confidence';
  const modeLabel = data.mode ? ` · ${String(data.mode).replaceAll('_', ' ')}` : '';
  confidence.textContent = `Confidence: ${data.confidence} · ${data.answer_kind.replace('_', ' ')}${modeLabel}`;
  const answer = document.createElement('div');
  answer.textContent = data.answer;
  root.append(confidence, answer);
  if (data.citations && data.citations.length) {
    const heading = document.createElement('h3');
    heading.textContent = 'Sources';
    root.appendChild(heading);
    for (const cite of data.citations) {
      const block = document.createElement('div');
      block.className = 'citation';
      const link = cite.preview_url
        ? `<a href="${esc(cite.preview_url)}" target="_blank" rel="noopener">Open source</a>`
        : '';
      block.innerHTML = `<strong>${esc(cite.title)}</strong> (#${cite.item_id} · ${esc(cite.source_kind)}) ${link}<div>${esc(cite.excerpt)}</div>`;
      root.appendChild(block);
    }
  }
}

async function askInbox(event) {
  event.preventDefault();
  const input = document.getElementById('askQuestion');
  const question = input.value.trim();
  if (!question) return;
  setButtonBusy('askButton', true, 'Thinking…', 'Ask');
  setStatus('askStatus', 'Searching your inbox…');
  try {
    const data = await fetchJson(
      '/api/ask',
      {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({question})
      },
      'Unable to answer from your inbox.'
    );
    renderAskResponse(data);
    setStatus('askStatus', data.confidence === 'insufficient' ? 'Not enough evidence in your inbox.' : 'Answer ready.');
  } catch {
    setStatus('askStatus', 'Ask My Inbox failed.', true);
  } finally {
    setButtonBusy('askButton', false, 'Thinking…', 'Ask');
  }
}

async function loadAttention() {
  const briefingRoot = document.getElementById('briefing');
  const attentionRoot = document.getElementById('attention');
  try {
    const [briefing, board] = await Promise.all([
      fetchJson('/api/briefing', {}, 'Unable to load briefing.'),
      fetchJson('/api/attention', {}, 'Unable to load attention board.')
    ]);
    briefingRoot.innerHTML = [
      `<strong>Daily briefing</strong> · ${esc(briefing.reference_date)}`,
      `<div>${esc(briefing.summary)}</div>`,
      briefing.priority_suggestions.length
        ? `<div class="provenance"><span class="label">Suggested focus</span>: ${
            briefing.priority_suggestions
              .map(item => `#${item.task_id} ${esc(item.text)} (${esc(item.reason)})`)
              .join('; ')
          }</div>`
        : '<div class="muted">No timed open tasks yet.</div>'
    ].join('');

    const sections = [
      ['overdue', 'Overdue'],
      ['today', 'Today'],
      ['upcoming', 'Upcoming'],
      ['unscheduled', 'Unscheduled'],
      ['snoozed', 'Snoozed']
    ];
    attentionRoot.replaceChildren();
    for (const [key, label] of sections) {
      const panel = document.createElement('div');
      panel.className = 'panel';
      const items = board[key] || [];
      panel.innerHTML = `<strong>${esc(label)}</strong> <span class="muted">(${items.length})</span>`;
      if (!items.length) {
        const empty = document.createElement('div');
        empty.className = 'muted';
        empty.textContent = 'None';
        panel.appendChild(empty);
      } else {
        for (const item of items.slice(0, 8)) {
          const row = document.createElement('div');
          row.className = 'task-meta';
          const phrase = item.original_timing_phrase
            ? ` · “${item.original_timing_phrase}”`
            : '';
          const due = item.normalized_due_on ? ` → ${item.normalized_due_on}` : '';
          const conf = item.due_confidence ? ` · ${item.due_confidence}` : '';
          const needs = item.needs_confirmation ? ' · needs confirmation' : '';
          row.textContent = `#${item.id} ${item.text}${phrase}${due}${conf}${needs}`;
          panel.appendChild(row);
        }
      }
      attentionRoot.appendChild(panel);
    }
    setStatus('briefingStatus', 'Attention board updated.');
  } catch {
    setStatus('briefingStatus', 'Could not load attention board.', true);
  }
}

async function previewCalendarForTask(task) {
  setStatus('calendarStatus', 'Building calendar preview…');
  try {
    const preview = await fetchJson(
      '/api/calendar/preview',
      {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({task_id: task.id})
      },
      'Unable to preview calendar event.'
    );
    const root = document.getElementById('calendarPreview');
    root.innerHTML = [
      `<strong>Calendar preview</strong> (${esc(preview.provider)} / ${esc(preview.status)})`,
      `<div>${esc(preview.title)} · ${esc(preview.start_date)} (${esc(preview.timezone)})</div>`,
      `<div class="provenance">${(preview.notes || []).map(note => esc(note)).join(' · ')}</div>`
    ].join('');
    const confirmBtn = actionButton('Confirm (mock only)', '', async () => {
      try {
        const confirmed = await fetchJson(
          '/api/calendar/confirm',
          {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({draft_id: preview.draft_id})
          },
          'Unable to confirm calendar action.'
        );
        setStatus(
          'calendarStatus',
          confirmed.status === 'confirmed_mock'
            ? 'Mock calendar confirmation recorded. No external event created.'
            : `Calendar action status: ${confirmed.status}`
        );
        root.innerHTML += `<div class="provenance"><span class="label">Receipt</span>: ${esc(confirmed.status)} / ${esc(confirmed.provider)}</div>`;
      } catch (error) {
        setStatus('calendarStatus', error.message || 'Calendar confirm blocked or failed.', true);
      }
    });
    root.appendChild(confirmBtn);
    setStatus('calendarStatus', 'Preview ready — confirm explicitly to record a mock receipt.');
  } catch (error) {
    setStatus('calendarStatus', error.message || 'Calendar preview failed.', true);
  }
}

function renderCalendar() {
  const title = document.getElementById('calendarTitle');
  const grid = document.getElementById('calendarGrid');
  if (!title || !grid) return;
  title.textContent = new Intl.DateTimeFormat(undefined, {
    month: 'long', year: 'numeric'
  }).format(calendarCursor);
  grid.replaceChildren();
  const year = calendarCursor.getFullYear();
  const month = calendarCursor.getMonth();
  const first = new Date(year, month, 1);
  const start = new Date(year, month, 1 - first.getDay());
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  for (let index = 0; index < 42; index += 1) {
    const day = new Date(start);
    day.setDate(start.getDate() + index);
    const cell = document.createElement('div');
    cell.className = 'calendar-day';
    if (day.getMonth() !== month) cell.classList.add('muted-day');
    if (day.getTime() === today.getTime()) cell.classList.add('today');
    const dateLabel = document.createElement('span');
    dateLabel.className = 'calendar-date';
    dateLabel.textContent = String(day.getDate());
    cell.appendChild(dateLabel);
    const isoDate = [day.getFullYear(), String(day.getMonth() + 1).padStart(2, '0'), String(day.getDate()).padStart(2, '0')].join('-');
    for (const entry of calendarTasks.filter(task => task.due_on === isoDate)) {
      const event = document.createElement('div');
      event.className = `calendar-entry${entry.source === 'inbox' ? ' inbox-entry' : ''}`;
      event.title = `${entry.text} — ${entry.timing_text || entry.due_on}`;
      event.textContent = entry.text;
      cell.appendChild(event);
    }
    grid.appendChild(cell);
  }
}

async function loadGcalStatus() {
  const dot = document.getElementById('gcalDot');
  const line = document.getElementById('gcalLine');
  try {
    const status = await fetchJson('/api/calendar/status', undefined, 'Unable to load calendar status.');
    const live = status.oauth_connected && status.writes_enabled;
    dot.className = `gcal-dot ${live ? 'gcal-on' : 'gcal-link'}`;
    dot.title = live ? 'Connected to Google Calendar' : 'Link mode: events open in Google Calendar for you to save';
    line.textContent = live
      ? 'Connected. Confirmed events are written to your Google Calendar.'
      : 'Link mode: use “Add to Google Calendar” on any task, or download all deadlines as one .ics file to import. Nothing is written without your confirmation.';
  } catch {
    line.textContent = 'Could not check the calendar connection.';
  }
}

async function loadCalendar() {
  loadGcalStatus();
  try {
    calendarTasks = await fetchJson(
      '/api/calendar/tasks',
      undefined,
      'Unable to load inbox calendar.'
    );
    renderCalendar();
    setStatus(
      'calendarScheduleStatus',
      calendarTasks.length
        ? `${calendarTasks.length} scheduled inbox item${calendarTasks.length === 1 ? '' : 's'}.`
        : 'No dated inbox items yet.'
    );
  } catch {
    setStatus('calendarScheduleStatus', 'Could not load inbox calendar.', true);
  }
}

function moveCalendar(amount) {
  calendarCursor = new Date(calendarCursor.getFullYear(), calendarCursor.getMonth() + amount, 1);
  renderCalendar();
}

function goToCalendarToday() {
  const now = new Date();
  calendarCursor = new Date(now.getFullYear(), now.getMonth(), 1);
  renderCalendar();
}

async function loadAuthUser() {
  try {
    const user = await fetchJson('/api/auth/me', {}, 'Unable to load session.');
    document.getElementById('authUser').textContent =
      `Signed in as ${user.display_name} <${user.email}> (${user.auth_provider})`;
  } catch {
    document.getElementById('authUser').textContent = 'Not signed in';
  }
}

async function devLogin(event) {
  event.preventDefault();
  const email = document.getElementById('devLoginEmail').value.trim();
  if (!email) return;
  try {
    const user = await fetchJson(
      '/api/auth/dev-login',
      {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({email})
      },
      'Unable to sign in.'
    );
    setStatus('authStatus', `Signed in as ${user.email}`);
    await loadAuthUser();
    await loadLatestAnalysis();
    await loadNotes();
    await loadTasks();
    await loadAttention();
    await loadDashboard();
    await loadCalendar();
  } catch {
    setStatus('authStatus', 'Sign-in failed (dev login may be disabled).', true);
  }
}

async function logoutSession() {
  try {
    await fetchJson('/api/auth/logout', {method: 'POST'}, 'Unable to sign out.');
    setStatus('authStatus', 'Signed out.');
    await loadAuthUser();
    await loadLatestAnalysis();
    await loadNotes();
    await loadTasks();
    await loadAttention();
    await loadDashboard();
    await loadCalendar();
  } catch {
    setStatus('authStatus', 'Sign-out failed.', true);
  }
}

const weeklyTypeLabels = {
  text: 'notes', url: 'links', pdf: 'PDFs', image: 'images', voice: 'voice notes'
};

function renderWeeklyReview(review) {
  const root = document.getElementById('weeklyReview');
  const byType = Object.entries(review.captured.by_type)
    .map(([kind, count]) => `${count} ${esc(weeklyTypeLabels[kind] || kind)}`)
    .join(', ');
  const listOrEmpty = (entries, emptyText) => entries.length
    ? `<ul>${entries.join('')}</ul>`
    : `<p class="muted">${emptyText}</p>`;
  const summaryLabel = review.summary_kind === 'model_generated'
    ? 'Written by AI from the numbers below'
    : 'Written from the numbers below';

  root.innerHTML = [
    `<p class="week-summary">${esc(review.summary)}</p>`,
    `<p class="muted week-summary-kind">${summaryLabel}</p>`,
    '<div class="week-grid">',
    `<div class="week-card"><h3>📥 Captured</h3><p class="week-number">${review.captured.total}</p>`,
    `<p class="muted">${byType || 'Nothing new this week.'}</p></div>`,
    `<div class="week-card"><h3>✅ Completed</h3><p class="week-number">${review.completed_tasks.length}</p>`,
    listOrEmpty(
      review.completed_tasks.slice(0, 5).map(task => `<li>${esc(task.text)}</li>`),
      `No tasks finished yet. ${review.open_task_count} still open.`
    ),
    '</div>',
    `<div class="week-card"><h3>🔥 On your mind</h3>`,
    listOrEmpty(
      review.top_topics.map(topic => `<li>${esc(topic.name)} (${topic.count})</li>`),
      'Analyze your inbox to see topics.'
    ),
    '</div>',
    `<div class="week-card"><h3>🕸️ Not organized yet</h3><p class="week-number">${review.untouched_count}</p>`,
    listOrEmpty(
      review.untouched_items.slice(0, 5).map(item => `<li>#${item.id} ${esc(item.text || item.item_type)}</li>`),
      'Everything from this week is organized.'
    ),
    '</div>',
    '</div>'
  ].join('');
  root.hidden = false;
}

async function loadWeeklyReview() {
  setButtonBusy('weeklyReviewButton', true, 'Reviewing…', 'Review my week');
  setStatus('weeklyReviewStatus', 'Looking back at your week…');
  try {
    const review = await fetchJson('/api/review/week', {}, 'Could not load your weekly review. Try again.');
    renderWeeklyReview(review);
    setStatus('weeklyReviewStatus', '');
  } catch (error) {
    setStatus('weeklyReviewStatus', error.message, true);
  } finally {
    setButtonBusy('weeklyReviewButton', false, 'Reviewing…', 'Review my week');
  }
}

// Screens: one <section class="view" data-view="..."> is shown at a time,
// chosen by the URL hash (#today, #inbox, ...). Query-string filters are
// untouched, so search state and screens work together.
const VIEW_NAMES = ['today', 'inbox', 'tasks', 'calendar', 'ask', 'sections'];
const VIEW_TITLES = {
  today: 'Today', inbox: 'Inbox', tasks: 'Tasks',
  calendar: 'Calendar', ask: 'Ask', sections: 'Sections'
};
// Anchors from the old single-page layout keep working.
const VIEW_ALIASES = { capture: 'today', week: 'today', organized: 'inbox', notes: 'inbox' };

function viewFromHash() {
  const hash = window.location.hash.replace(/^#/, '');
  if (VIEW_NAMES.includes(hash)) return hash;
  return VIEW_ALIASES[hash] || 'today';
}

// Set by shortcuts that open a screen and want a specific field focused.
let focusAfterRoute = null;

function goToViewAndFocus(view, elementId) {
  if (viewFromHash() === view) {
    document.getElementById(elementId).focus();
    return;
  }
  focusAfterRoute = elementId;
  window.location.hash = view;
}

function showView(name, { moveFocus = false } = {}) {
  document.querySelectorAll('.view').forEach(view => {
    view.hidden = view.dataset.view !== name;
  });
  document.querySelectorAll('[data-view-link]').forEach(link => {
    if (link.dataset.viewLink === name) {
      link.setAttribute('aria-current', 'page');
    } else {
      link.removeAttribute('aria-current');
    }
  });
  document.title = name === 'today' ? 'Life Inbox' : `${VIEW_TITLES[name]} · Life Inbox`;
  window.scrollTo(0, 0);
  if (!moveFocus) return;
  // Chrome fires popstate (moveFocus false) before hashchange on a hash
  // change, so a focus request is only used here, on the hashchange pass.
  const requestedFocus = focusAfterRoute && document.getElementById(focusAfterRoute);
  focusAfterRoute = null;
  if (requestedFocus) {
    requestedFocus.focus();
  } else {
    // Tell screen-reader and keyboard users the screen changed.
    const heading = document.querySelector(`#view-${name} h1`);
    if (heading) {
      heading.setAttribute('tabindex', '-1');
      heading.focus({ preventScroll: true });
    }
  }
}

function routeFromHash(options) {
  const name = viewFromHash();
  const hash = window.location.hash.replace(/^#/, '');
  if (hash && hash !== name) {
    // Rewrite an old alias (#notes) to its screen (#inbox) without a new history entry.
    const url = new URL(window.location.href);
    url.hash = name;
    window.history.replaceState(window.history.state, '', url);
  }
  showView(name, options);
}

function renderGreeting() {
  const now = new Date();
  const hour = now.getHours();
  const greeting = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening';
  document.getElementById('todayGreeting').textContent = greeting;
  document.getElementById('todayDate').textContent = now.toLocaleDateString(undefined, {
    weekday: 'long', day: 'numeric', month: 'long'
  });
}

// Keyboard shortcuts. They never fire while typing in a field or with
// Ctrl/Cmd/Alt held, so normal typing and browser shortcuts are untouched.
const GO_TO_KEYS = { h: 'today', i: 'inbox', t: 'tasks', c: 'calendar', a: 'ask', s: 'sections' };
let waitingForGoKey = false;
let goKeyTimer = null;

function openShortcuts() {
  const dialog = document.getElementById('shortcutsDialog');
  if (!dialog.open) dialog.showModal();
}

function isTypingTarget(element) {
  if (!element) return false;
  const tag = element.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || element.isContentEditable;
}

function focusSearch() {
  const global = document.getElementById('globalSearch');
  if (global.offsetParent !== null) {
    global.focus();
    global.select();
    return;
  }
  // Phones hide the sidebar search; use the Inbox one instead.
  goToViewAndFocus('inbox', 'itemSearch');
}

document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && isTypingTarget(event.target) && event.target.type === 'search') {
    event.target.blur();
    return;
  }
  if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return;
  if (isTypingTarget(event.target) || document.getElementById('shortcutsDialog').open) return;

  const key = event.key.toLowerCase();
  if (waitingForGoKey) {
    waitingForGoKey = false;
    clearTimeout(goKeyTimer);
    if (GO_TO_KEYS[key]) {
      event.preventDefault();
      window.location.hash = GO_TO_KEYS[key];
    }
    return;
  }
  if (key === 'g') {
    waitingForGoKey = true;
    goKeyTimer = setTimeout(() => { waitingForGoKey = false; }, 1200);
  } else if (key === 'n') {
    event.preventDefault();
    goToViewAndFocus('today', 'noteText');
  } else if (event.key === '/') {
    event.preventDefault();
    focusSearch();
  } else if (event.key === '?') {
    event.preventDefault();
    openShortcuts();
  }
});

window.addEventListener('hashchange', () => {
  routeFromHash({ moveFocus: true });
  loadGame();
  loadTeam();
});
routeFromHash();
renderGreeting();
setUpCaptureBox();
showSkeleton('notesList');
showSkeleton('tasksList', 2);

syncControlsFromUrl();
loadAuthUser();
loadNotes();
loadLatestAnalysis();
loadTasks();
loadTopics();
loadDashboard();
loadAttention();
loadCalendar();
window.setInterval(refreshDynamicDates, 60 * 1000);
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) {
    refreshDynamicDates();
    loadGame();
  }
});

window.addEventListener('popstate', () => {
  routeFromHash();
  if (window.location.search === lastListQuery) return;
  lastListQuery = window.location.search;
  syncControlsFromUrl();
  loadNotes();
  loadTasks();
});


// ---- Drop anywhere + sort board (by domain / by format) ----
const FORMAT_ICONS = {
  pdf: '📄', image: '🖼️', audio: '🎙️', link: '🔗', note: '📝',
  spreadsheet: '📊', data: '🧩', textfile: '📃', other: '📦'
};
let sortOptions = {domains: [], formats: {}};
let sortMode = 'domain';
let sortFormatFilter = '';
let sortItems = [];
let boardLoading = false;

async function loadSortOptions() {
  try {
    sortOptions = await fetchJson('/api/sorting/options', undefined, 'Unable to load sort options.');
  } catch {
    sortOptions = {domains: ['Unsorted'], formats: {}};
  }
}

async function loadBoard() {
  if (boardLoading) return;
  boardLoading = true;
  try {
    if (!sortOptions.domains.length) await loadSortOptions();
    sortItems = await fetchJson('/api/items?limit=500', undefined, 'Unable to load the board.');
    renderBoard();
  } catch {
    document.getElementById('sortBoard').textContent = 'Could not load the board.';
  } finally {
    boardLoading = false;
  }
}

function renderBoard() {
  const board = document.getElementById('sortBoard');
  const chips = document.getElementById('sortChips');
  const formats = sortOptions.formats || {};
  const present = new Set(sortItems.map(item => item.file_format));

  chips.replaceChildren();
  const all = document.createElement('button');
  all.type = 'button';
  all.className = `chip${sortFormatFilter ? '' : ' chip-on'}`;
  all.textContent = `All formats · ${sortItems.length}`;
  all.addEventListener('click', () => { sortFormatFilter = ''; renderBoard(); });
  chips.append(all);
  for (const key of Object.keys(formats)) {
    if (!present.has(key)) continue;
    const count = sortItems.filter(item => item.file_format === key).length;
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = `chip${sortFormatFilter === key ? ' chip-on' : ''}`;
    chip.textContent = `${FORMAT_ICONS[key] || ''} ${formats[key]} · ${count}`;
    chip.addEventListener('click', () => { sortFormatFilter = sortFormatFilter === key ? '' : key; renderBoard(); });
    chips.append(chip);
  }

  document.querySelectorAll('[data-sort-mode]').forEach(button => {
    button.classList.toggle('chip-on', button.dataset.sortMode === sortMode);
  });

  const visible = sortItems.filter(item => !sortFormatFilter || item.file_format === sortFormatFilter);
  const columns = sortMode === 'domain'
    ? sortOptions.domains
    : Object.keys(formats);
  const keyOf = item => (sortMode === 'domain' ? item.domain : item.file_format);

  board.replaceChildren();
  if (!sortItems.length) {
    board.innerHTML = '<p class="muted">Nothing to sort yet. Drop files, links or text anywhere on the page.</p>';
    return;
  }
  for (const column of columns) {
    const cards = visible.filter(item => keyOf(item) === column);
    if (sortMode === 'format' && !cards.length) continue;
    const col = document.createElement('section');
    col.className = `board-col${column === 'Unsorted' ? ' board-col-unsorted' : ''}`;
    col.dataset.column = column;
    const heading = document.createElement('h3');
    heading.textContent = `${sortMode === 'format' ? (FORMAT_ICONS[column] || '') + ' ' + (formats[column] || column) : column} · ${cards.length}`;
    col.append(heading);
    for (const item of cards) col.append(renderBoardCard(item));
    if (!cards.length) {
      const empty = document.createElement('p');
      empty.className = 'board-empty';
      empty.textContent = sortMode === 'domain' ? 'Drop an item here' : 'Empty';
      col.append(empty);
    }
    if (sortMode === 'domain') {
      col.addEventListener('dragover', event => {
        if (!event.dataTransfer.types.includes('text/x-item-id')) return;
        event.preventDefault();
        col.classList.add('board-col-over');
      });
      col.addEventListener('dragleave', () => col.classList.remove('board-col-over'));
      col.addEventListener('drop', event => {
        col.classList.remove('board-col-over');
        const id = Number(event.dataTransfer.getData('text/x-item-id'));
        if (!id) return;
        event.preventDefault();
        event.stopPropagation();
        moveItemToDomain(id, column);
      });
    }
    board.append(col);
  }
}

function renderBoardCard(item) {
  const card = document.createElement('div');
  card.className = 'board-card';
  card.draggable = true;
  card.dataset.itemId = String(item.id);
  const title = item.title || item.original_filename || (item.raw_text || '').slice(0, 60) || `Item #${item.id}`;
  const guess = item.domain_source === 'auto' && item.domain === 'Unsorted'
    ? '<span class="pill">needs sorting</span>'
    : item.domain_source === 'user' ? '<span class="pill">moved by you</span>' : '';
  card.innerHTML = `<span class="board-ico">${FORMAT_ICONS[item.file_format] || '📦'}</span>`
    + `<span class="board-title">${esc(title.length > 70 ? title.slice(0, 67) + '…' : title)}</span>`
    + `<span class="board-sub">${esc(sortOptions.formats[item.file_format] || item.file_format)}${sortMode === 'format' ? ' · ' + esc(item.domain) : ''} ${guess}</span>`;
  card.addEventListener('dragstart', event => {
    event.dataTransfer.setData('text/x-item-id', String(item.id));
    event.dataTransfer.effectAllowed = 'move';
    card.classList.add('board-dragging');
  });
  card.addEventListener('dragend', () => card.classList.remove('board-dragging'));
  return card;
}

async function moveItemToDomain(itemId, domain) {
  const previous = sortItems.find(item => item.id === itemId);
  try {
    await fetchJson(
      `/api/items/${itemId}/domain`,
      {
        method: 'PATCH',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({domain})
      },
      'Unable to move item.'
    );
    showToast(`Moved to ${domain}.`, previous ? {
      actionLabel: 'Undo',
      onAction: async () => {
        await fetchJson(`/api/items/${itemId}/domain`, {
          method: 'PATCH',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({domain: previous.domain_source === 'user' ? previous.domain : null})
        }, 'Unable to undo.');
        await loadBoard();
      }
    } : {});
    await loadBoard();
  } catch {
    setStatus('searchStatus', 'Could not move that item.', true);
  }
}

function setSortMode(mode) {
  sortMode = mode;
  renderBoard();
}

// Drop anywhere: files, links and text, several at once.
function setupDropAnywhere() {
  const overlay = document.getElementById('dropOverlay');
  let depth = 0;
  const isExternal = event => {
    const types = Array.from(event.dataTransfer?.types || []);
    if (types.includes('text/x-item-id') || types.includes('text/x-task-id')) return false;
    return types.includes('Files') || types.includes('text/uri-list') || types.includes('text/plain');
  };
  document.addEventListener('dragenter', event => {
    if (!isExternal(event)) return;
    depth += 1;
    overlay.hidden = false;
  });
  document.addEventListener('dragover', event => {
    if (isExternal(event)) event.preventDefault();
  });
  document.addEventListener('dragleave', () => {
    depth = Math.max(0, depth - 1);
    if (!depth) overlay.hidden = true;
  });
  document.addEventListener('drop', event => {
    depth = 0;
    overlay.hidden = true;
    if (!isExternal(event)) return;
    event.preventDefault();
    handleDroppedData(event.dataTransfer);
  });
}

async function handleDroppedData(dataTransfer) {
  const jobs = [];
  for (const file of Array.from(dataTransfer.files || [])) {
    const kind = fileKind(file);
    jobs.push(kind
      ? {label: file.name, run: () => postCapture(kind, file)}
      : {label: file.name, run: () => Promise.reject(new Error('unsupported'))});
  }
  if (!jobs.length) {
    const uri = (dataTransfer.getData('text/uri-list') || '').split('\n').map(l => l.trim()).filter(l => l && !l.startsWith('#'));
    const plain = (dataTransfer.getData('text/plain') || '').trim();
    for (const url of uri) jobs.push({label: url, run: () => postCapture('url', url)});
    if (!uri.length && plain) {
      jobs.push(looksLikeUrl(plain)
        ? {label: plain, run: () => postCapture('url', plain)}
        : {label: 'text', run: () => postCapture('note', plain)});
    }
  }
  if (!jobs.length) return;

  showToast(`Sorting ${jobs.length} dropped item${jobs.length === 1 ? '' : 's'}…`);
  const saved = [];
  const failed = [];
  for (const job of jobs) {
    try {
      saved.push(await job.run());
    } catch {
      failed.push(job.label);
    }
  }
  const summary = saved
    .map(item => `${sortOptions.formats[item.file_format] || item.file_format} → ${item.domain}`)
    .join(', ');
  showToast(
    `${saved.length ? `Saved ${saved.length}: ${summary}.` : ''}${failed.length ? ` Could not save: ${failed.join(', ')}.` : ''}`.trim()
  );
  await loadNotes();
  await loadBoard();
  updateNavCounts();
}

setupDropAnywhere();
loadSortOptions();


// ---- Drag a task onto a priority lane or a day ----
function localIso(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

function paintDayStrip() {
  const strip = document.getElementById('dayStrip');
  strip.replaceChildren();
  const names = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  for (let offset = 0; offset < 7; offset += 1) {
    const date = new Date();
    date.setDate(date.getDate() + offset);
    const cell = document.createElement('div');
    cell.className = 'day-cell';
    cell.dataset.iso = localIso(date);
    cell.innerHTML = `<small>${offset === 0 ? 'Today' : names[date.getDay()]}</small><strong>${date.getDate()}</strong>`;
    strip.append(cell);
  }
}

async function patchTask(taskId, body, message) {
  try {
    await fetchJson(
      `/api/tasks/${taskId}`,
      {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)},
      'Unable to update task.'
    );
    showToast(message);
    await loadTasks();
    await loadAttention();
    await loadCalendar();
  } catch {
    setStatus('taskStatus', 'Could not update that task.', true);
  }
}

function setupTaskDrops() {
  const wire = (zone, onDrop) => {
    zone.addEventListener('dragover', event => {
      if (!event.dataTransfer.types.includes('text/x-task-id')) return;
      event.preventDefault();
      zone.classList.add('drop-hot');
    });
    zone.addEventListener('dragleave', () => zone.classList.remove('drop-hot'));
    zone.addEventListener('drop', event => {
      zone.classList.remove('drop-hot');
      const id = Number(event.dataTransfer.getData('text/x-task-id'));
      if (!id) return;
      event.preventDefault();
      onDrop(id);
    });
  };
  document.querySelectorAll('#priorityLanes .lane').forEach(lane => {
    wire(lane, id => patchTask(id, {priority: lane.dataset.priority}, `Priority set to ${lane.dataset.priority}.`));
  });
  document.getElementById('dayStrip').addEventListener('dragover', event => {
    if (event.dataTransfer.types.includes('text/x-task-id')) event.preventDefault();
  });
  document.getElementById('dayStrip').addEventListener('drop', event => {
    const cell = event.target.closest('.day-cell');
    const id = Number(event.dataTransfer.getData('text/x-task-id'));
    if (!cell || !id) return;
    event.preventDefault();
    cell.classList.remove('drop-hot');
    patchTask(id, {due_on: cell.dataset.iso}, `Deadline set for ${cell.dataset.iso}.`);
  });
  document.getElementById('dayStrip').addEventListener('dragover', event => {
    const cell = event.target.closest('.day-cell');
    document.querySelectorAll('.day-cell.drop-hot').forEach(c => c.classList.remove('drop-hot'));
    if (cell) cell.classList.add('drop-hot');
  });
}
setupTaskDrops();


// ---- Phase 6 polish: sound and confetti ----
let soundOn = true;
try { soundOn = localStorage.getItem('questSound') !== 'off'; } catch { /* storage unavailable */ }
let audioContext = null;

function paintSoundToggle() {
  const button = document.getElementById('soundToggle');
  button.textContent = soundOn ? '🔊 Sound on' : '🔇 Sound off';
  button.setAttribute('aria-pressed', String(soundOn));
}

function playChime(big) {
  if (!soundOn) return;
  try {
    audioContext = audioContext || new (window.AudioContext || window.webkitAudioContext)();
    const notes = big ? [523.25, 659.25, 783.99, 1046.5] : [659.25, 880];
    notes.forEach((freq, i) => {
      const osc = audioContext.createOscillator();
      const gain = audioContext.createGain();
      const start = audioContext.currentTime + i * 0.11;
      osc.type = 'sine';
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.0001, start);
      gain.gain.exponentialRampToValueAtTime(0.18, start + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.28);
      osc.connect(gain).connect(audioContext.destination);
      osc.start(start);
      osc.stop(start + 0.3);
    });
  } catch { /* audio is optional */ }
}

function launchConfetti() {
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const canvas = document.getElementById('confettiCanvas');
  const ctx = canvas.getContext('2d');
  canvas.width = window.innerWidth;
  canvas.height = window.innerHeight;
  canvas.style.display = 'block';
  const colors = ['#2fb36d', '#3b8ea5', '#f2b134', '#e5584d', '#8e6bd8'];
  const pieces = Array.from({length: 120}, () => ({
    x: canvas.width / 2 + (Math.random() - 0.5) * 120,
    y: canvas.height * 0.35,
    vx: (Math.random() - 0.5) * 12,
    vy: -Math.random() * 12 - 4,
    size: 5 + Math.random() * 6,
    color: colors[Math.floor(Math.random() * colors.length)],
    spin: Math.random() * Math.PI,
    vs: (Math.random() - 0.5) * 0.4
  }));
  const startedAt = performance.now();
  function frame(now) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    for (const piece of pieces) {
      piece.vy += 0.38;
      piece.x += piece.vx;
      piece.y += piece.vy;
      piece.spin += piece.vs;
      ctx.save();
      ctx.translate(piece.x, piece.y);
      ctx.rotate(piece.spin);
      ctx.fillStyle = piece.color;
      ctx.fillRect(-piece.size / 2, -piece.size / 4, piece.size, piece.size / 2);
      ctx.restore();
    }
    if (now - startedAt < 2600) {
      requestAnimationFrame(frame);
    } else {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      canvas.style.display = 'none';
    }
  }
  requestAnimationFrame(frame);
}

document.getElementById('soundToggle').addEventListener('click', () => {
  soundOn = !soundOn;
  try { localStorage.setItem('questSound', soundOn ? 'on' : 'off'); } catch { /* ignore */ }
  paintSoundToggle();
  if (soundOn) playChime(false);
});
paintSoundToggle();


// ---- Phase 8: suggested time slots for High tasks ----
async function toggleSlots(task, card, minutes = 45) {
  let panel = card.querySelector('.slots-panel');
  if (panel && !panel.dataset.reload) {
    panel.remove();
    return;
  }
  if (!panel) {
    panel = document.createElement('div');
    panel.className = 'slots-panel';
    card.append(panel);
  }
  delete panel.dataset.reload;
  panel.textContent = 'Looking for free time…';
  try {
    const result = await fetchJson(
      `/api/tasks/${task.id}/slots?minutes=${minutes}`,
      undefined,
      'Unable to find time.'
    );
    panel.replaceChildren();
    const head = document.createElement('div');
    head.className = 'slots-head';
    const label = document.createElement('label');
    label.textContent = 'Time needed ';
    const select = document.createElement('select');
    for (const value of [15, 30, 45, 60, 90, 120, 180]) {
      const option = document.createElement('option');
      option.value = String(value);
      option.textContent = value >= 60 ? `${value / 60} h` : `${value} min`;
      option.selected = value === result.minutes;
      select.append(option);
    }
    select.addEventListener('change', () => {
      panel.dataset.reload = '1';
      toggleSlots(task, card, Number(select.value));
    });
    label.append(select);
    head.append(label);
    panel.append(head);
    if (!result.slots.length) {
      const none = document.createElement('p');
      none.className = 'muted';
      none.textContent = `No free ${minutes}-minute slot before the deadline. Try a shorter block or move the deadline.`;
      panel.append(none);
    }
    for (const slot of result.slots) {
      const button = actionButton(slot.label, 'secondary slot-btn', () => {
        window.open(slot.google_url, '_blank', 'noopener');
      });
      panel.append(button);
    }
    const note = document.createElement('p');
    note.className = 'muted slots-note';
    note.textContent = result.calendar_loaded
      ? 'Avoids the meetings in your imported calendar. Opens Google Calendar for you to confirm.'
      : 'No calendar imported, so these only respect 9–18 weekdays. Import your calendar on the Google Calendar screen.';
    panel.append(note);
  } catch {
    panel.textContent = 'Could not look up free time.';
  }
}

async function loadBusySummary() {
  try {
    const summary = await fetchJson('/api/calendar/busy', undefined, 'Unable to load calendar import.');
    const line = document.getElementById('busyLine');
    document.getElementById('busyClear').hidden = !summary.count;
    line.textContent = summary.count
      ? `${summary.count} busy blocks loaded (${summary.first.slice(0, 10)} to ${summary.last.slice(0, 10)}). “Find time” avoids them.`
      : 'Import your calendar so “Find time” avoids your meetings.';
  } catch { /* optional */ }
}

document.getElementById('busyFile').addEventListener('change', async event => {
  const file = event.target.files[0];
  event.target.value = '';
  if (!file) return;
  const form = new FormData();
  form.append('file', file);
  try {
    const result = await fetchJson('/api/calendar/busy/import', {method: 'POST', body: form}, 'Unable to import calendar.');
    showToast(`Imported ${result.imported} busy blocks.`);
    await loadBusySummary();
  } catch {
    showToast('That file could not be imported. Use an .ics export from your calendar.');
  }
});
document.getElementById('busyClear').addEventListener('click', async () => {
  await fetch('/api/calendar/busy', {method: 'DELETE'});
  showToast('Imported calendar cleared.');
  await loadBusySummary();
});
loadBusySummary();


// ---- Phase 9: team leaderboard (opt-in, points only) ----
async function teamRequest(url, method, body, failure) {
  const options = {method};
  if (body !== undefined) {
    options.headers = {'Content-Type': 'application/json'};
    options.body = JSON.stringify(body);
  }
  const response = await fetch(url, options);
  if (!response.ok) {
    let detail = failure;
    try { detail = (await response.json()).detail || failure; } catch { /* keep default */ }
    throw new Error(typeof detail === 'string' ? detail : failure);
  }
  return response.status === 204 ? null : response.json();
}

async function loadTeam() {
  const body = document.getElementById('teamBody');
  if (!body) return;
  try {
    const {team} = await fetchJson('/api/teams/me', undefined, 'Unable to load team.');
    renderTeam(team);
  } catch {
    body.textContent = 'Could not load your team.';
  }
}

function teamFormHtml() {
  return `
    <p class="sub">Compete on weekly points with friends or colleagues. Only your name, points, streak and tasks done are shared — never task text.</p>
    <div class="team-forms">
      <form id="teamCreateForm" class="team-form">
        <label>Create a team <input name="name" maxlength="40" minlength="2" required placeholder="Team name"></label>
        <label class="check"><input type="checkbox" name="share" checked> Show my points on the board</label>
        <button type="submit">Create</button>
      </form>
      <form id="teamJoinForm" class="team-form">
        <label>Join with a code <input name="code" maxlength="20" minlength="4" required placeholder="Invite code" autocomplete="off"></label>
        <label class="check"><input type="checkbox" name="share" checked> Show my points on the board</label>
        <button type="submit" class="secondary">Join</button>
      </form>
    </div>
    <p id="teamError" class="status" role="status" aria-live="polite"></p>`;
}

function renderTeam(team) {
  const body = document.getElementById('teamBody');
  if (!team) {
    body.innerHTML = teamFormHtml();
    const wire = (id, url, field) => {
      document.getElementById(id).addEventListener('submit', async event => {
        event.preventDefault();
        const form = new FormData(event.target);
        const payload = {share: form.get('share') === 'on'};
        payload[field] = form.get(field);
        try {
          const result = await teamRequest(url, 'POST', payload, 'Could not do that.');
          renderTeam(result.team);
          showToast(field === 'name' ? 'Team created. Share the invite code.' : 'You joined the team.');
        } catch (error) {
          setStatus('teamError', error.message, true);
        }
      });
    };
    wire('teamCreateForm', '/api/teams', 'name');
    wire('teamJoinForm', '/api/teams/join', 'code');
    return;
  }
  const medals = ['🥇', '🥈', '🥉'];
  const rows = team.rows.map(row => `
    <tr class="${row.is_me ? 'team-me' : ''}">
      <td>${medals[row.rank - 1] || row.rank}</td>
      <td>${esc(row.display_name)}${row.is_me ? ' <span class="pill">you</span>' : ''}<small>${esc(row.level)}</small></td>
      <td><strong>${row.points_week}</strong></td>
      <td>${row.tasks_week}</td>
      <td>${row.streak ? '🔥 ' + row.streak : '–'}</td>
    </tr>`).join('');
  body.innerHTML = `
    <div class="team-head">
      <div><strong>${esc(team.name)}</strong> <span class="muted">· ${team.member_count} member${team.member_count === 1 ? '' : 's'}</span></div>
      <div class="team-code">Invite code <code id="teamCode">${esc(team.invite_code)}</code>
        <button type="button" class="ghost" id="teamCopy">Copy</button></div>
    </div>
    <table class="team-table">
      <thead><tr><th>#</th><th>Name</th><th>Week pts</th><th>Done</th><th>Streak</th></tr></thead>
      <tbody>${rows || '<tr><td colspan="5" class="muted">Nobody is sharing points yet.</td></tr>'}</tbody>
    </table>
    ${team.private_count ? `<p class="muted team-private">${team.private_count} member${team.private_count === 1 ? ' keeps' : 's keep'} points private.</p>` : ''}
    <div class="team-foot">
      <label class="check"><input type="checkbox" id="teamShare" ${team.i_share ? 'checked' : ''}> Show my points on the board</label>
      <button type="button" class="ghost" id="teamLeave">Leave team</button>
    </div>
    <p id="teamError" class="status" role="status" aria-live="polite"></p>`;
  document.getElementById('teamCopy').addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(team.invite_code);
      showToast('Invite code copied.');
    } catch {
      showToast(`Invite code: ${team.invite_code}`);
    }
  });
  document.getElementById('teamShare').addEventListener('change', async event => {
    try {
      const result = await teamRequest('/api/teams/me', 'PATCH', {share: event.target.checked}, 'Could not update sharing.');
      renderTeam(result.team);
      showToast(event.target.checked ? 'Your points are now visible to the team.' : 'Your points are now private.');
    } catch (error) {
      setStatus('teamError', error.message, true);
    }
  });
  document.getElementById('teamLeave').addEventListener('click', async () => {
    if (!window.confirm('Leave this team? Your points stay yours.')) return;
    try {
      await teamRequest('/api/teams/leave', 'POST', undefined, 'Could not leave the team.');
      renderTeam(null);
      showToast('You left the team.');
    } catch (error) {
      setStatus('teamError', error.message, true);
    }
  });
}
loadTeam();
