let isSavingNote = false;
let isAnalyzingInbox = false;
let calendarTasks = [];
let calendarCursor = new Date(new Date().getFullYear(), new Date().getMonth(), 1);
const pendingNoteActions = new Set();
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

// The sidebar search box: open Inbox and search all items for the words,
// with the other filters cleared so nothing is hidden by accident.
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
    const editButton = iconButton('edit', 'Edit', 'secondary', () => {
      showEditNote(note, root);
    });
    const deleteButton = iconButton('trash', 'Delete', 'danger', () => {
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
    pending.root.remove();
    await loadLatestAnalysis();
    await loadTasks();
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
    document.getElementById('questLevel').innerHTML =
      `Lv ${lvl.number} ${esc(lvl.title)} · ${coinHtml(game.lifetime_points)}`;
    const fill = document.getElementById('levelFill');
    const next = document.getElementById('levelNext');
    if (lvl.next_at === null) {
      fill.style.width = '100%';
      next.textContent = 'Top level reached.';
    } else {
      const pct = Math.round(((game.lifetime_points - lvl.floor) / (lvl.next_at - lvl.floor)) * 100);
      fill.style.width = `${Math.max(0, Math.min(100, pct))}%`;
      next.textContent = `${lvl.points_to_next} coins to the next level`;
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
      cell.title = `${day.day}: ${day.points} coins`;
      cell.innerHTML = `<span class="week-bar"><i style="height:${Math.min(100, day.points)}%"></i></span><small>${day.weekday}</small>`;
      week.append(cell);
    }
    if (lastQuestPoints !== null && game.points_today > lastQuestPoints) {
      const pop = document.getElementById('questPop');
      pop.innerHTML = coinHtml(game.points_today - lastQuestPoints, '+');
      pop.classList.remove('quest-pop-go');
      void pop.offsetWidth;
      pop.classList.add('quest-pop-go');
      playChime(false);
      if (game.goal_met && lastQuestPoints < game.goal) {
        showToast('🎉 Daily goal reached: 100 coins!');
        launchConfetti();
        playChime(true);
        document.getElementById('questCard').classList.add('quest-celebrate');
        setTimeout(() => document.getElementById('questCard').classList.remove('quest-celebrate'), 1800);
      }
    }
    lastQuestPoints = game.points_today;
    loadShopBalance();
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
      body: JSON.stringify({sentence, tz: Intl.DateTimeFormat().resolvedOptions().timeZone})
    },
    'Unable to add task.'
  );
  announceNewTask(task);
}

function announceNewTask(task) {
  if (task.slot_start) {
    const at = new Date(task.slot_start).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
    showToast(`⏰ Reminder set for ${at}: “${task.text}”. Your pet will tell you.`);
    return;
  }
  const when = task.due_on ? ` · ${task.days_left_label}` : '';
  showToast(`Added “${task.text}” · ${task.priority} (+${task.points_value} coins)${when}`);
}

const BRIEFING_COMMAND = /^(?:hey,?\s+)?(?:what(?:'s| is| do i have)?\b.*\b(?:due|today)\b|(?:read|give me|tell me)\b.*\b(?:briefing|agenda|tasks|due)\b|(?:daily )?briefing\??$|any(?:thing)? due\b.*)/i;

function setupQuickTask() {
  const form = document.getElementById('quickTaskForm');
  const input = document.getElementById('quickTaskInput');
  const mic = document.getElementById('quickMic');
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  let listening = null;

  async function submit(sentence) {
    const value = sentence.trim();
    if (!value) return;
    if (BRIEFING_COMMAND.test(value)) {
      input.value = '';
      speakBriefing();
      return;
    }
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
    renderAnalysis(data);
    await loadTasks();
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
  } else if (key === 'b') {
    event.preventDefault();
    speakBriefing();
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
// ---- One connected workspace: tasks, sections, inbox tray, search, calendar ----
// Sections are the domains. Every task and item lives in exactly one, and the
// same task row (Complete / Snooze / Edit / Delete) is used everywhere.

const FORMAT_ICONS = {
  pdf: '📄', image: '🖼️', audio: '🎙️', link: '🔗', note: '📝',
  spreadsheet: '📊', data: '🧩', textfile: '📃', other: '📦'
};
// The coin image is defined once in index.html (#coin) and reused everywhere.
function coinIcon() {
  return '<svg class="coin" role="img" aria-label="coins"><use href="#coin"/></svg>';
}

function coinHtml(amount, prefix = '') {
  return `${prefix}${amount}${coinIcon()}`;
}

const SNOOZE_CHOICES = [['Tomorrow', 1], ['In 3 days', 3], ['Next week', 7]];
const PRIORITY_LEVELS = ['High', 'Medium', 'Low'];

let sortOptions = {domains: [], formats: {}};
let sectionsData = null;
let openTasksCache = [];
let sectionFormat = '';
let sectionGroup = 'domain';
const openSections = new Set(['Unsorted']);
const openPriorities = new Set(['High']);
let refreshing = false;
let refreshAgain = false;
let lastRefreshDay = '';

function h(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function isSnoozed(task) {
  return Boolean(task.snoozed_until) && task.snoozed_until > localIso(new Date());
}

function isoInDays(days) {
  const date = new Date();
  date.setDate(date.getDate() + days);
  return localIso(date);
}

function byDueThenId(a, b) {
  const left = a.due_on || '9999-12-31';
  const right = b.due_on || '9999-12-31';
  return left === right ? a.id - b.id : left < right ? -1 : 1;
}

async function loadSortOptions() {
  try {
    sortOptions = await fetchJson('/api/sorting/options', undefined, 'Unable to load sections.');
  } catch {
    sortOptions = {domains: ['Unsorted'], formats: {}};
  }
}

// Everything the screens need, fetched once and coalesced so the many
// "reload after this change" calls cost a single round of requests.
async function refreshAll() {
  if (refreshing) {
    refreshAgain = true;
    return;
  }
  refreshing = true;
  try {
    do {
      refreshAgain = false;
      if (!sortOptions.domains.length) await loadSortOptions();
      const filter = document.getElementById('taskStatusFilter').value;
      const [open, sections, backlog] = await Promise.all([
        fetchJson('/api/tasks?status=open', undefined, 'Unable to load tasks.'),
        fetchJson('/api/sections', undefined, 'Unable to load sections.'),
        filter === 'backlog'
          ? fetchJson('/api/tasks?status=backlog', undefined, 'Unable to load backlog.')
          : Promise.resolve(null)
      ]);
      lastRefreshDay = localIso(new Date());
      openTasksCache = open;
      sectionsData = sections;
      renderAttention(open);
      renderTasksScreen(filter === 'backlog' ? backlog : open, filter);
      renderSections();
      renderTray();
      setNavCount('tasks', open.length, 'open tasks');
      const unsorted = sections.sections.find(s => s.domain === 'Unsorted');
      setNavCount('inbox', unsorted ? unsorted.item_count : 0, 'items to sort');
    } while (refreshAgain);
  } catch {
    setStatus('taskStatus', 'We could not load your tasks. Reload to try again.', true);
  } finally {
    refreshing = false;
  }
  loadGame();
  loadCalendar();
}

// Older call sites ask for one list at a time; they all mean "refresh".
function loadTasks() { return refreshAll(); }
function loadNotes() { return refreshAll(); }
function loadAttention() { return refreshAll(); }
function updateNavCounts() { /* counts are set by refreshAll */ }

// ---------- The task row ----------

const ICONS = {
  check: '<path d="M20 6 9 17l-5-5"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
  trash: '<path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="m19 6-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/>',
  more: '<circle cx="5" cy="12" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="19" cy="12" r="1.2"/>',
  undo: '<path d="M3 7v6h6"/><path d="M21 17a9 9 0 0 0-15-6.7L3 13"/>'
};

function iconSvg(name) {
  return `<svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${ICONS[name]}</svg>`;
}

// A square button that shows only an icon. The words live in the tooltip and
// the accessible name, so nothing is lost for screen readers or hover.
function iconButton(icon, label, className, onClick) {
  const button = h('button', `icon-btn ${className || ''}`.trim());
  button.type = 'button';
  button.innerHTML = iconSvg(icon);
  button.title = label;
  button.setAttribute('aria-label', label);
  if (onClick) button.addEventListener('click', onClick);
  return button;
}

function menu(icon, label) {
  const details = h('details', 'row-menu');
  const summary = h('summary', 'icon-btn secondary');
  summary.innerHTML = iconSvg(icon);
  summary.title = label;
  summary.setAttribute('aria-label', label);
  const pop = h('div', 'menu-pop');
  details.append(summary, pop);
  return {details, pop};
}

function menuItem(label, onClick) {
  const button = h('button', 'ghost menu-item', label);
  button.type = 'button';
  button.addEventListener('click', event => {
    event.target.closest('details').open = false;
    onClick(event);
  });
  return button;
}

document.addEventListener('click', event => {
  document.querySelectorAll('details.row-menu[open]').forEach(details => {
    if (!details.contains(event.target)) details.open = false;
  });
});

async function taskAction(path, body, failure) {
  const options = {method: 'POST'};
  if (body !== undefined) {
    options.headers = {'Content-Type': 'application/json'};
    options.body = JSON.stringify(body);
  }
  return fetchJson(path, options, failure);
}

async function completeTask(task, row) {
  row.classList.add('task-completing');
  try {
    const done = await taskAction(`/api/tasks/${task.id}/complete`, undefined, 'Unable to complete task.');
    await new Promise(resolve => setTimeout(resolve, 300));
    const rescued = done && done.rescue_bonus ? ` · +${done.rescue_bonus} rescue bonus! You beat the procrastination on this one.` : '';
    showToast(`Done: ${task.text}${rescued}`, {
      actionLabel: 'Undo',
      onAction: async () => {
        await taskAction(`/api/tasks/${task.id}/reopen`, undefined, 'Unable to undo.');
        await refreshAll();
      }
    });
  } catch {
    row.classList.remove('task-completing');
    showToast('Could not complete that task.');
    return;
  }
  await refreshAll();
}

async function deleteTask(task, row) {
  try {
    await taskAction(`/api/tasks/${task.id}/delete`, undefined, 'Unable to delete task.');
    row.classList.add('task-binned');
    await new Promise(resolve => setTimeout(resolve, 350));
    showToast('Deleted. It stays in Backlog.', {
      actionLabel: 'Undo',
      onAction: async () => {
        await taskAction(`/api/tasks/${task.id}/restore`, undefined, 'Unable to undo.');
        await refreshAll();
      }
    });
  } catch {
    showToast('Could not delete that task.');
    return;
  }
  await refreshAll();
}

async function snoozeTask(task, days, label) {
  try {
    await taskAction(`/api/tasks/${task.id}/snooze`, {until: isoInDays(days)}, 'Unable to snooze task.');
    showToast(`Snoozed until ${label.toLowerCase()}.`, {
      actionLabel: 'Undo',
      onAction: async () => {
        await taskAction(`/api/tasks/${task.id}/snooze`, {until: localIso(new Date())}, 'Unable to undo.');
        await refreshAll();
      }
    });
  } catch {
    showToast('Could not snooze that task.');
    return;
  }
  await refreshAll();
}

async function patchTask(taskId, body, message) {
  try {
    await fetchJson(
      `/api/tasks/${taskId}`,
      {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)},
      'Unable to update task.'
    );
    if (message) showToast(message);
    await refreshAll();
  } catch {
    showToast('Could not update that task.');
  }
}

function openTaskEditor(task, row) {
  const form = h('form', 'task-edit');
  const text = h('input');
  text.value = task.text;
  text.maxLength = 500;
  text.required = true;
  text.setAttribute('aria-label', 'Task');
  const grid = h('div', 'task-edit-grid');

  const priority = h('select');
  for (const level of PRIORITY_LEVELS) {
    const option = h('option', '', `${level} · ${({High: 30, Medium: 20, Low: 10})[level]} coins`);
    option.value = level;
    option.selected = level === task.priority;
    priority.append(option);
  }
  const due = h('input');
  due.type = 'date';
  due.value = task.due_on || '';
  const domain = h('select');
  const auto = h('option', '', 'Section: automatic');
  auto.value = '';
  domain.append(auto);
  for (const name of sortOptions.domains.filter(d => d !== 'Unsorted')) {
    const option = h('option', '', name);
    option.value = name;
    option.selected = task.domain_source === 'user' && task.domain === name;
    domain.append(option);
  }
  for (const [label, control] of [['Priority', priority], ['Deadline', due], ['Section', domain]]) {
    const wrap = h('label', '', label);
    wrap.append(control);
    grid.append(wrap);
  }
  const buttons = h('div', 'task-actions');
  const save = h('button', '', 'Save');
  save.type = 'submit';
  const cancel = h('button', 'ghost', 'Cancel');
  cancel.type = 'button';
  cancel.addEventListener('click', () => refreshAll());
  buttons.append(save, cancel);
  form.append(text, grid, buttons);

  form.addEventListener('submit', async event => {
    event.preventDefault();
    const body = {};
    if (text.value.trim() !== task.text) body.text = text.value.trim();
    if (priority.value !== task.priority) body.priority = priority.value;
    if (due.value && due.value !== task.due_on) body.due_on = due.value;
    const wanted = domain.value || null;
    const current = task.domain_source === 'user' ? task.domain : null;
    if (wanted !== current) body.domain = wanted;
    if (!Object.keys(body).length) {
      await refreshAll();
      return;
    }
    await patchTask(task.id, body, 'Task updated.');
  });

  row.replaceChildren(form);
  row.draggable = false;
  text.focus();
  text.select();
}

function rowBadges(task) {
  const wrap = h('span', 'task-badges');
  wrap.append(h('span', priorityClass(task.priority), task.priority));
  if (task.priority_raised) {
    const raised = h('span', 'pill raised-pill', '↑ due soon');
    raised.title = `Raised from ${task.base_priority} because the deadline is close. Edit the priority to keep it as you choose.`;
    wrap.append(raised);
  }
  const worth = h('span', 'points-chip');
  worth.innerHTML = coinHtml(task.points_value, '+');
  worth.title = `Worth ${task.points_value} coins`;
  wrap.append(worth);
  if (task.due_on) {
    const badge = h('span', 'days-badge');
    badge.dataset.dueOn = task.due_on;
    paintDaysBadge(badge);
    wrap.append(badge);
  }
  if (task.radar) wrap.append(radarBadge(task.radar));
  if (isSnoozed(task)) wrap.append(h('span', 'pill snoozed-pill', `Snoozed until ${task.snoozed_until}`));
  if (task.slot_start) wrap.append(h('span', 'pill slot-pill', `🕘 ${formatSlot(task.slot_start, task.slot_end)}`));
  return wrap;
}

const RADAR_LABELS = {on_track: '🟢', watch: '🟡 Watch', at_risk: '🔴 At risk'};
const RADAR_TITLES = {on_track: 'On track', watch: 'Watch', at_risk: 'At risk'};

// Procrastination Radar badge. Hover (or tap) shows every reason behind the score.
function radarBadge(radar) {
  const badge = h('button', `pill radar-pill radar-${radar.level}`, RADAR_LABELS[radar.level]);
  badge.type = 'button';
  const lines = radar.reasons.map(r => `• ${r.text} (${r.points > 0 ? '+' : ''}${r.points})`);
  const summary = `${RADAR_TITLES[radar.level]}: ${radar.score}/100`;
  badge.title = lines.length ? `${summary}\n${lines.join('\n')}` : `${summary}\nNothing is pushing this task yet.`;
  badge.setAttribute('aria-label', `Radar ${summary}`);
  badge.addEventListener('click', event => {
    event.stopPropagation();
    showToast(lines.length ? `${summary} · ${radar.reasons.map(r => r.text).join(' · ')}` : `${summary}. Nothing is pushing this task yet.`);
  });
  return badge;
}

// "Start 10 min": book a 10-minute slot from now, so the usual slot reminder asks "done?" after.
async function startTenMinutes(task) {
  const start = new Date();
  const end = new Date(start.getTime() + 10 * 60 * 1000);
  try {
    await taskAction(`/api/tasks/${task.id}/slot`, {start: start.toISOString(), end: end.toISOString()}, 'Unable to start.');
  } catch {
    showToast('Could not start the timer for that task.');
    return;
  }
  showToast(`Go! 10 minutes on “${task.text}”. I'll check in when it's up.`);
  await refreshAll();
}

function renderTaskRow(task, {showSection = true} = {}) {
  const row = h('div', 'task');
  row.dataset.taskId = String(task.id);
  const head = h('div', 'task-title');
  head.append(h('strong', '', task.text), rowBadges(task));
  const meta = h('div', 'task-meta');
  const bits = [];
  if (showSection) bits.push(task.domain);
  if (task.due_on) bits.push(`${relativeDueLabel(task.due_on)} · ${task.due_on}`);
  else bits.push('No deadline');
  meta.textContent = bits.join(' · ');

  const actions = h('div', 'task-actions');
  const complete = iconButton('check', 'Complete', 'complete-btn', () => completeTask(task, row));

  const snooze = menu('clock', 'Snooze');
  for (const [label, days] of SNOOZE_CHOICES) {
    snooze.pop.append(menuItem(label, () => snoozeTask(task, days, label)));
  }
  if (isSnoozed(task)) {
    snooze.pop.append(menuItem('Wake up now', async () => {
      await taskAction(`/api/tasks/${task.id}/snooze`, {until: localIso(new Date())}, 'Unable to wake task.');
      await refreshAll();
    }));
  }

  const edit = iconButton('edit', 'Edit', 'secondary', () => openTaskEditor(task, row));
  const del = iconButton('trash', 'Delete', 'danger', () => deleteTask(task, row));
  actions.append(complete, snooze.details, edit, del);
  if (task.radar && task.radar.level === 'at_risk') {
    const start = h('button', 'secondary start-ten-btn', '▶ Start 10 min');
    start.type = 'button';
    start.title = 'Just start: book 10 minutes from now';
    start.addEventListener('click', () => startTenMinutes(task));
    actions.prepend(start);
  }

  const more = menu('more', 'More actions');
  if (!task.due_on && task.suggested_due_on) {
    more.pop.append(menuItem(`Set deadline ${task.suggested_due_on}`, () => patchTask(task.id, {due_on: task.suggested_due_on}, `Deadline set for ${task.suggested_due_on}.`)));
  }
  if (task.timing_text && !task.timing_confirmed) {
    more.pop.append(menuItem('Confirm date', async () => {
      await taskAction(`/api/tasks/${task.id}/confirm-timing`, {timing_text: task.timing_text}, 'Unable to confirm.');
      showToast('Date confirmed.');
      await refreshAll();
    }));
  }
  if (task.priority === 'High' && task.due_on) {
    more.pop.append(menuItem('Find a time', () => toggleSlots(task, row)));
  }
  if (task.slot_start) {
    more.pop.append(menuItem('Clear time slot', async () => {
      await fetchJson(`/api/tasks/${task.id}/slot`, {method: 'DELETE'}, 'Unable to clear the slot.');
      showToast('Time slot cleared.');
      await refreshAll();
    }));
  }
  if (task.google_event_url) {
    more.pop.append(menuItem('Add to Google Calendar', () => window.open(task.google_event_url, '_blank', 'noopener')));
  }
  if (task.timing_confirmed && (task.due_on || task.timing_text)) {
    more.pop.append(menuItem('Preview calendar export', () => previewCalendarForTask(task)));
  }
  if (more.pop.children.length) actions.append(more.details);

  row.append(head, meta, actions);
  row.draggable = true;
  row.classList.add('task-draggable');
  row.addEventListener('dragstart', event => {
    event.dataTransfer.setData('text/x-task-id', String(task.id));
    event.dataTransfer.effectAllowed = 'move';
    row.classList.add('task-dragging');
  });
  row.addEventListener('dragend', () => row.classList.remove('task-dragging'));
  return row;
}

// Rows for tasks that are not open: done, or deleted and waiting in Backlog.
function renderStoredTaskRow(task, state) {
  const row = h('div', 'task task-stored');
  row.dataset.taskId = String(task.id);
  const head = h('div', 'task-title');
  const label = state === 'done' ? 'Done' : state === 'done (binned)' ? 'Done · in Backlog' : 'Deleted · in Backlog';
  head.append(h('strong', '', task.text), h('span', priorityClass(task.priority), task.priority), h('span', 'pill', label));
  const meta = h('div', 'task-meta');
  const extra = task.completed_at ? ` · done ${task.completed_at.slice(0, 10)} · ` : '';
  meta.textContent = `${task.domain}${extra}`;
  if (task.completed_at) {
    const kept = h('span', 'coins-kept');
    kept.innerHTML = `${coinHtml(task.points_awarded || 0, '+')} kept`;
    meta.append(kept);
  }
  const actions = h('div', 'task-actions');
  if (state === 'done') {
    const reopen = iconButton('undo', 'Reopen', '', async () => {
      await taskAction(`/api/tasks/${task.id}/reopen`, undefined, 'Unable to reopen.');
      showToast('Task reopened.');
      await refreshAll();
    });
    const bin = iconButton('trash', 'Move to bin', 'secondary', () => binTask(task.id, row));
    actions.append(reopen, bin);
  } else {
    const restore = iconButton('undo', 'Restore', '', async () => {
      try {
        await taskAction(`/api/tasks/${task.id}/restore`, undefined, 'Unable to restore.');
        showToast(task.status === 'dismissed' ? 'Task is open again.' : 'Task restored.');
        await refreshAll();
        if (!document.getElementById('searchResults').hidden) loadSearch();
      } catch {
        showToast('Could not restore that task.');
      }
    });
    actions.append(restore);
  }
  row.append(head, meta, actions);
  return row;
}

async function binTask(taskId, card) {
  try {
    await taskAction(`/api/tasks/${taskId}/bin`, undefined, 'Unable to bin task.');
    if (card) {
      card.classList.add('task-binned');
      await new Promise(resolve => setTimeout(resolve, 450));
    }
    showToast('Binned. Find it any time in Tasks → Backlog.', {
      actionLabel: 'Undo',
      onAction: async () => {
        await taskAction(`/api/tasks/${taskId}/restore`, undefined, 'Unable to undo.');
        await refreshAll();
      }
    });
  } catch {
    showToast('Only finished tasks go in the bin. Use Delete for an open task.');
    return;
  }
  await refreshAll();
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
    binTask(id, document.querySelector(`[data-task-id="${id}"]`));
  });
}
setupBinZone();

// ---------- Today: Needs your attention, by priority ----------

function renderAttention(openTasks) {
  const root = document.getElementById('attention');
  root.replaceChildren();
  const active = openTasks.filter(task => !isSnoozed(task));
  for (const level of PRIORITY_LEVELS) {
    const tasks = active.filter(task => task.priority === level).sort(byDueThenId);
    const section = h('details', `prio-section prio-${level.toLowerCase()}`);
    section.open = openPriorities.has(level);
    section.addEventListener('toggle', () => {
      if (section.open) openPriorities.add(level);
      else openPriorities.delete(level);
    });
    const summary = h('summary');
    summary.append(
      h('span', 'prio-name', `${level} priority`),
      h('span', 'prio-count', String(tasks.length)),
      h('span', 'prio-pts muted')
    );
    summary.lastChild.innerHTML = `${coinHtml(({High: 30, Medium: 20, Low: 10})[level], '+')} each`;
    section.append(summary);
    if (!tasks.length) {
      section.append(h('p', 'muted prio-empty', 'Nothing here.'));
    }
    for (const task of tasks) section.append(renderTaskRow(task));
    root.append(section);
  }
  const snoozed = openTasks.length - active.length;
  if (snoozed) {
    root.append(h('p', 'muted prio-snoozed', `${snoozed} snoozed task${snoozed === 1 ? '' : 's'} hidden until their date. Find them in Tasks.`));
  }
}

// ---------- Tasks screen ----------

function changeTaskStatusFilter() {
  const status = document.getElementById('taskStatusFilter').value;
  updateUrl({task_status: status === 'open' ? '' : status});
  refreshAll();
}

function renderTasksScreen(tasks, filter) {
  const root = document.getElementById('tasksList');
  root.replaceChildren();
  document.getElementById('taskDrops').hidden = filter !== 'open';
  paintDayStrip();
  if (!tasks.length) {
    root.innerHTML = filter === 'backlog'
      ? emptyStateHtml({icon: 'check', title: 'Backlog is empty', text: 'Finished tasks you bin, and tasks you delete, wait here with their coins kept.'})
      : emptyStateHtml({icon: 'check', title: 'No open tasks', text: 'Say or type a task above, or analyze your inbox to turn notes into tasks.', action: '<a class="button-link" href="#inbox">Go to Inbox</a>'});
    return;
  }
  const sorted = filter === 'open'
    ? [...tasks].sort((a, b) => PRIORITY_LEVELS.indexOf(a.priority) - PRIORITY_LEVELS.indexOf(b.priority) || byDueThenId(a, b))
    : tasks;
  for (const task of sorted) {
    root.append(filter === 'backlog'
      ? renderStoredTaskRow(task, task.status === 'dismissed' ? 'deleted' : 'done (binned)')
      : renderTaskRow(task));
  }
}

// ---------- Sections (domains): tasks and items together ----------

function moveItemToDomain(itemId, domain) {
  return moveToSection('items', itemId, domain);
}

async function moveToSection(kind, id, domain) {
  const target = kind === 'items' ? `/api/items/${id}/domain` : `/api/tasks/${id}`;
  try {
    await fetchJson(
      target,
      {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({domain: domain === 'Unsorted' ? null : domain})},
      'Unable to move.'
    );
    showToast(`Moved to ${domain}.`);
    await refreshAll();
  } catch {
    showToast('Could not move that.');
  }
}

function paintSectionChips(data) {
  const chips = document.getElementById('sortChips');
  chips.replaceChildren();
  const items = data.sections.flatMap(s => s.items);
  const make = (label, active, onClick) => {
    const chip = h('button', `chip${active ? ' chip-on' : ''}`, label);
    chip.type = 'button';
    chip.addEventListener('click', onClick);
    return chip;
  };
  chips.append(make(`All formats · ${items.length}`, !sectionFormat, () => { sectionFormat = ''; renderSections(); }));
  for (const [key, name] of Object.entries(sortOptions.formats)) {
    const count = items.filter(item => item.file_format === key).length;
    if (!count) continue;
    chips.append(make(`${FORMAT_ICONS[key] || ''} ${name} · ${count}`, sectionFormat === key, () => {
      sectionFormat = sectionFormat === key ? '' : key;
      renderSections();
    }));
  }
  document.querySelectorAll('[data-section-group]').forEach(button => {
    button.classList.toggle('chip-on', button.dataset.sectionGroup === sectionGroup);
  });
}

function makeItemCard(item) {
  const card = renderNote(item);
  card.draggable = true;
  card.dataset.itemId = String(item.id);
  card.addEventListener('dragstart', event => {
    event.dataTransfer.setData('text/x-item-id', String(item.id));
    event.dataTransfer.effectAllowed = 'move';
  });
  const chip = h('span', 'pill format-pill', `${FORMAT_ICONS[item.file_format] || '📦'} ${sortOptions.formats[item.file_format] || item.file_format}`);
  card.prepend(chip);
  return card;
}

function renderSections() {
  const root = document.getElementById('sectionsList');
  if (!root || !sectionsData) return;
  paintSectionChips(sectionsData);
  root.replaceChildren();
  const groups = sectionGroup === 'domain'
    ? sectionsData.sections.map(s => ({
      key: s.domain, label: s.domain, tasks: s.tasks,
      items: s.items.filter(item => !sectionFormat || item.file_format === sectionFormat),
      done: s.done_count
    }))
    : Object.entries(sortOptions.formats).map(([key, name]) => ({
      key: `fmt-${key}`, label: `${FORMAT_ICONS[key] || ''} ${name}`, tasks: [],
      items: sectionsData.sections.flatMap(s => s.items).filter(item => item.file_format === key),
      done: 0
    })).filter(group => group.items.length);

  if (!groups.length) {
    root.innerHTML = emptyStateHtml({icon: 'inbox', title: 'Nothing to show', text: 'Save a thought, link or file on Today and it will be sorted into a section.'});
    return;
  }
  for (const group of groups) {
    const details = h('details', `section-group${group.key === 'Unsorted' ? ' section-unsorted' : ''}`);
    details.dataset.domain = group.key;
    details.open = openSections.has(group.key);
    details.addEventListener('toggle', () => {
      if (details.open) openSections.add(group.key);
      else openSections.delete(group.key);
    });
    const summary = h('summary');
    const bits = [];
    if (sectionGroup === 'domain') bits.push(`${group.tasks.length} open`);
    bits.push(`${group.items.length} item${group.items.length === 1 ? '' : 's'}`);
    if (group.done) bits.push(`${group.done} done`);
    summary.append(h('span', 'section-name', group.label), h('span', 'muted section-counts', bits.join(' · ')));
    details.append(summary);

    if (group.tasks.length) {
      details.append(h('h3', 'section-sub', 'Tasks'));
      for (const task of [...group.tasks].sort((a, b) => PRIORITY_LEVELS.indexOf(a.priority) - PRIORITY_LEVELS.indexOf(b.priority) || byDueThenId(a, b))) {
        details.append(renderTaskRow(task, {showSection: false}));
      }
    }
    if (group.items.length) {
      details.append(h('h3', 'section-sub', 'Items'));
      for (const item of group.items) {
        if (!pendingDeletes.has(item.id)) details.append(makeItemCard(item));
      }
    }
    if (!group.tasks.length && !group.items.length) {
      details.append(h('p', 'muted section-empty', 'Empty. Drag a task or item onto this section, or drop a file anywhere.'));
    }
    if (sectionGroup === 'domain') {
      const accepts = event => ['text/x-item-id', 'text/x-task-id'].some(type => event.dataTransfer.types.includes(type));
      details.addEventListener('dragover', event => {
        if (!accepts(event)) return;
        event.preventDefault();
        details.classList.add('section-over');
      });
      details.addEventListener('dragleave', event => {
        if (!details.contains(event.relatedTarget)) details.classList.remove('section-over');
      });
      details.addEventListener('drop', event => {
        details.classList.remove('section-over');
        const itemId = Number(event.dataTransfer.getData('text/x-item-id'));
        const taskId = Number(event.dataTransfer.getData('text/x-task-id'));
        if (!itemId && !taskId) return;
        event.preventDefault();
        event.stopPropagation();
        if (itemId) moveToSection('items', itemId, group.key);
        else moveToSection('tasks', taskId, group.key);
      });
    }
    root.append(details);
  }
}

function setSectionGroup(mode) {
  sectionGroup = mode;
  renderSections();
}

// ---------- Inbox: what still needs sorting, and search ----------

function renderTray() {
  const root = document.getElementById('trayList');
  if (!root || !sectionsData) return;
  root.replaceChildren();
  const unsorted = sectionsData.sections.find(s => s.domain === 'Unsorted');
  const items = unsorted ? unsorted.items.filter(item => !pendingDeletes.has(item.id)) : [];
  document.getElementById('trayCount').textContent = items.length ? `(${items.length})` : '';
  if (!items.length) {
    root.innerHTML = emptyStateHtml({icon: 'inbox', title: 'Everything is sorted', text: 'New notes, links and files land here only when they do not clearly belong in a section.'});
    return;
  }
  for (const item of items) {
    const wrap = h('div', 'tray-item');
    wrap.append(makeItemCard(item));
    const mover = h('label', 'tray-move', 'Move to ');
    const select = h('select');
    const placeholder = h('option', '', 'Choose a section…');
    placeholder.value = '';
    select.append(placeholder);
    for (const name of sortOptions.domains.filter(d => d !== 'Unsorted')) {
      const option = h('option', '', name);
      option.value = name;
      select.append(option);
    }
    select.addEventListener('change', () => {
      if (select.value) moveToSection('items', item.id, select.value);
    });
    mover.append(select);
    wrap.append(mover);
    root.append(wrap);
  }
}

function currentSearchQuery() {
  return (new URLSearchParams(window.location.search).get('q') || '').trim();
}

async function loadSearch() {
  const box = document.getElementById('searchResults');
  const query = currentSearchQuery();
  document.getElementById('globalSearch').value = query;
  if (!query) {
    box.hidden = true;
    box.replaceChildren();
    return;
  }
  box.hidden = false;
  box.replaceChildren(h('p', 'muted', 'Searching…'));
  try {
    const result = await fetchJson(`/api/find?q=${encodeURIComponent(query)}`, undefined, 'Search failed.');
    box.replaceChildren();
    const head = h('div', 'search-head');
    head.append(h('h2', '', `Results for “${query}”`));
    const clear = h('button', 'ghost', 'Clear search');
    clear.type = 'button';
    clear.addEventListener('click', clearSearch);
    head.append(clear);
    box.append(head);
    if (!result.tasks.length && !result.items.length) {
      box.append(h('p', 'muted', 'Nothing matches. Done and deleted tasks are searched too.'));
      return;
    }
    if (result.tasks.length) {
      box.append(h('h3', 'section-sub', `Tasks (${result.tasks.length})`));
      for (const task of result.tasks) {
        box.append(task.state === 'open' ? renderTaskRow(task) : renderStoredTaskRow(task, task.state));
      }
    }
    if (result.items.length) {
      box.append(h('h3', 'section-sub', `Items (${result.items.length})`));
      for (const item of result.items) box.append(makeItemCard(item));
    }
  } catch {
    box.replaceChildren(h('p', 'muted', 'Search failed. Please try again.'));
  }
}

function clearSearch() {
  updateUrl({q: ''});
  document.getElementById('globalSearch').value = '';
  loadSearch();
}

function searchEverything(event) {
  event.preventDefault();
  const input = document.getElementById('globalSearch');
  const query = input.value.trim();
  const url = new URL(window.location.href);
  if (query) url.searchParams.set('q', query);
  else url.searchParams.delete('q');
  url.hash = 'inbox';
  window.history.pushState({}, '', url);
  lastListQuery = url.search;
  showView('inbox');
  loadSearch();
  input.blur();
}

function syncControlsFromUrl() {
  const params = new URLSearchParams(window.location.search);
  document.getElementById('globalSearch').value = params.get('q') || '';
  const taskStatus = params.get('task_status');
  document.getElementById('taskStatusFilter').value = taskStatus === 'backlog' ? 'backlog' : 'open';
}

// ---------- Calendar: finished tasks live here ----------

function renderCalendar() {
  const title = document.getElementById('calendarTitle');
  const grid = document.getElementById('calendarGrid');
  if (!title || !grid) return;
  title.textContent = new Intl.DateTimeFormat(undefined, {month: 'long', year: 'numeric'}).format(calendarCursor);
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
    const cell = h('div', 'calendar-day');
    if (day.getMonth() !== month) cell.classList.add('muted-day');
    if (day.getTime() === today.getTime()) cell.classList.add('today');
    cell.append(h('span', 'calendar-date', String(day.getDate())));
    const isoDate = localIso(day);
    for (const entry of calendarTasks.filter(task => task.due_on === isoDate)) {
      const event = h('div', `calendar-entry${entry.source === 'inbox' ? ' inbox-entry' : ''}${entry.source === 'done' ? ' done-entry' : ''}`);
      if (entry.source === 'done') {
        event.textContent = `✓ ${entry.text}`;
        event.title = `Done: ${entry.text}${entry.points ? ` (+${entry.points} coins)` : ''}. Drag to the bin to move it to Backlog.`;
        event.draggable = true;
        event.dataset.taskId = String(entry.task_id);
        event.addEventListener('dragstart', dragEvent => {
          dragEvent.dataTransfer.setData('text/x-task-id', String(entry.task_id));
          dragEvent.dataTransfer.effectAllowed = 'move';
        });
      } else {
        event.textContent = entry.text;
        event.title = `${entry.text} — ${entry.timing_text || entry.due_on}`;
      }
      cell.append(event);
    }
    grid.append(cell);
  }
}

routeFromHash();
renderGreeting();
setUpCaptureBox();
showSkeleton('tasksList', 2);

syncControlsFromUrl();
loadAuthUser();
refreshAll();
loadSearch();
loadLatestAnalysis();
// A new day changes days-left, urgency and auto-raised priorities, so reload
// the lists when the date rolls over (also when the tab wakes up).
function refreshIfNewDay() {
  if (lastRefreshDay && localIso(new Date()) !== lastRefreshDay) refreshAll();
}
window.setInterval(() => {
  refreshDynamicDates();
  refreshIfNewDay();
}, 60 * 1000);
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) {
    refreshDynamicDates();
    refreshIfNewDay();
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
      const choice = h('div', 'slot-choice');
      const schedule = actionButton(slot.label, 'secondary slot-btn', async () => {
        try {
          await taskAction(`/api/tasks/${task.id}/slot`, {start: slot.start, end: slot.end}, 'Unable to save the slot.');
          showToast(`Scheduled ${slot.label}. Your pet will remind you.`);
          await refreshAll();
        } catch {
          showToast('Could not save that slot.');
        }
      });
      schedule.title = 'Save this time on the task. Your pet reminds you before it starts.';
      const google = h('a', 'slot-google', 'Google');
      google.href = slot.google_url;
      google.target = '_blank';
      google.rel = 'noopener';
      google.title = 'Also add it to Google Calendar';
      choice.append(schedule, google);
      panel.append(choice);
    }
    const note = document.createElement('p');
    note.className = 'muted slots-note';
    note.textContent = result.calendar_loaded
      ? 'Avoids the meetings in your imported calendar. Click a time to schedule it; “Google” also opens Google Calendar to confirm.'
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
    <p class="sub">Compete on weekly coins with friends or colleagues. Only your name, coins, streak and tasks done are shared — never task text.</p>
    <div class="team-forms">
      <form id="teamCreateForm" class="team-form">
        <label>Create a team <input name="name" maxlength="40" minlength="2" required placeholder="Team name"></label>
        <label class="check"><input type="checkbox" name="share" checked> Show my coins on the board</label>
        <button type="submit">Create</button>
      </form>
      <form id="teamJoinForm" class="team-form">
        <label>Join with a code <input name="code" maxlength="20" minlength="4" required placeholder="Invite code" autocomplete="off"></label>
        <label class="check"><input type="checkbox" name="share" checked> Show my coins on the board</label>
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
      <thead><tr><th>#</th><th>Name</th><th>Week ${coinIcon()}</th><th>Done</th><th>Streak</th></tr></thead>
      <tbody>${rows || '<tr><td colspan="5" class="muted">Nobody is sharing coins yet.</td></tr>'}</tbody>
    </table>
    ${team.private_count ? `<p class="muted team-private">${team.private_count} member${team.private_count === 1 ? ' keeps' : 's keep'} coins private.</p>` : ''}
    <div class="team-foot">
      <label class="check"><input type="checkbox" id="teamShare" ${team.i_share ? 'checked' : ''}> Show my coins on the board</label>
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
      showToast(event.target.checked ? 'Your coins are now visible to the team.' : 'Your coins are now private.');
    } catch (error) {
      setStatus('teamError', error.message, true);
    }
  });
  document.getElementById('teamLeave').addEventListener('click', async () => {
    if (!window.confirm('Leave this team? Your coins stay yours.')) return;
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


// ---- Phase 10: spoken "what's due today?" ----
let speaking = false;

async function speakBriefing() {
  const synth = window.speechSynthesis;
  if (speaking && synth) {
    synth.cancel();
    return;
  }
  let briefing;
  try {
    briefing = await fetchJson('/api/game/briefing', undefined, 'Unable to load the briefing.');
  } catch {
    showToast('Could not load today\'s briefing.');
    return;
  }
  if (!synth || typeof SpeechSynthesisUtterance === 'undefined') {
    showToast(briefing.text, {duration: 15000});
    return;
  }
  synth.cancel();
  const utterance = new SpeechSynthesisUtterance(briefing.text);
  utterance.lang = navigator.language || 'en-US';
  utterance.rate = 1;
  const button = document.getElementById('briefingButton');
  utterance.onstart = () => {
    speaking = true;
    button.textContent = '⏹ Stop reading';
  };
  const done = () => {
    speaking = false;
    button.textContent = '🗣️ What\'s due today?';
  };
  utterance.onend = done;
  utterance.onerror = done;
  showToast(briefing.text, {duration: 12000});
  synth.speak(utterance);
}

document.getElementById('briefingButton').addEventListener('click', speakBriefing);


// ---- Resizable navigation ----
const NAV_DEFAULT = 248;
const NAV_COMPACT_BELOW = 160;

function applyNavWidth(width, {save = true} = {}) {
  const slider = document.getElementById('navWidth');
  const clamped = Math.max(Number(slider.min), Math.min(Number(slider.max), Math.round(width)));
  document.documentElement.style.setProperty('--nav-w', `${clamped}px`);
  document.querySelector('.app-shell').classList.toggle('nav-compact', clamped < NAV_COMPACT_BELOW);
  slider.value = String(clamped);
  slider.setAttribute('aria-valuetext', clamped < NAV_COMPACT_BELOW ? 'Icons only' : `${clamped} pixels wide`);
  if (save) {
    try { localStorage.setItem('navWidth', String(clamped)); } catch { /* storage unavailable */ }
  }
}

(function setupNavResize() {
  const slider = document.getElementById('navWidth');
  let saved = NAV_DEFAULT;
  try {
    const stored = Number(localStorage.getItem('navWidth'));
    if (stored) saved = stored;
  } catch { /* storage unavailable */ }
  applyNavWidth(saved, {save: false});
  slider.addEventListener('input', () => applyNavWidth(Number(slider.value)));
  slider.addEventListener('dblclick', () => applyNavWidth(NAV_DEFAULT));
})();


// ---- Coin shop and pets ----
function formatSlot(startIso, endIso) {
  const start = new Date(startIso);
  const end = new Date(endIso);
  const day = start.toLocaleDateString(undefined, {weekday: 'short', day: 'numeric', month: 'short'});
  const time = date => date.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
  return `${day} ${time(start)}–${time(end)}`;
}

let shopData = null;

async function loadShopBalance() {
  try {
    shopData = await fetchJson('/api/shop', undefined, 'Unable to load the shop.');
    document.getElementById('shopBalance').innerHTML = coinHtml(shopData.balance);
    if (document.getElementById('shopDialog').open) renderShop();
  } catch { /* the shop is optional */ }
}

async function openShop() {
  const dialog = document.getElementById('shopDialog');
  await loadShopBalance();
  renderShop();
  if (!dialog.open) dialog.showModal();
}

async function shopAction(url, body, failure) {
  const response = await fetch(url, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  });
  if (!response.ok) {
    let detail = failure;
    try { detail = (await response.json()).detail || failure; } catch { /* keep default */ }
    throw new Error(typeof detail === 'string' ? detail : failure);
  }
  return response.json();
}

function renderShop() {
  if (!shopData) return;
  document.getElementById('shopDialogBalance').innerHTML = `${coinHtml(shopData.balance)} to spend`;
  const grid = document.getElementById('petGrid');
  grid.replaceChildren();
  for (const pet of shopData.items) {
    const card = h('div', `pet-card${pet.active ? ' pet-active' : ''}${pet.owned ? '' : ' pet-locked'}`);
    card.append(h('div', 'pet-emoji', pet.emoji));
    card.append(h('strong', '', pet.name), h('div', 'muted pet-species', pet.species), h('p', 'pet-blurb', pet.blurb));
    const action = h('div', 'pet-action');
    if (pet.active) {
      action.append(h('span', 'pill', 'Your pet'));
    } else if (pet.owned) {
      const select = h('button', '', 'Choose');
      select.type = 'button';
      select.addEventListener('click', async () => {
        try {
          shopData = await shopAction('/api/pet/select', {pet_id: pet.id}, 'Could not choose that pet.');
          showToast(`${pet.name} is your pet now.`);
          renderShop();
          loadPetSettings();
          if (window.LifeInboxPet.isMounted()) window.LifeInboxPet.refresh();
        } catch (error) { showToast(error.message); }
      });
      action.append(select);
    } else {
      const buy = h('button', pet.affordable ? '' : 'secondary');
      buy.type = 'button';
      buy.innerHTML = `Buy · ${coinHtml(pet.price)}`;
      buy.disabled = !pet.affordable;
      buy.title = pet.affordable ? `Buy ${pet.name}` : `You need ${pet.price - shopData.balance} more coins`;
      buy.addEventListener('click', async () => {
        try {
          shopData = await shopAction('/api/shop/buy', {item_id: pet.id}, 'Could not buy that pet.');
          showToast(`🎉 ${pet.name} the ${pet.species} joined you!`);
          document.getElementById('shopBalance').innerHTML = coinHtml(shopData.balance);
          renderShop();
          if (window.LifeInboxPet.isMounted()) window.LifeInboxPet.refresh();
        } catch (error) { showToast(error.message); }
      });
      action.append(buy);
    }
    card.append(action);
    grid.append(card);
  }
}

document.getElementById('shopButton').addEventListener('click', openShop);
document.getElementById('shopClose').addEventListener('click', () => document.getElementById('shopDialog').close());


async function loadPetSettings() {
  try {
    const state = await fetchJson('/api/pet/state', undefined, 'Unable to load your pet.');
    document.getElementById('petName').value = state.pet.name;
    document.getElementById('petInPage').checked = state.in_page;
    return state;
  } catch { return null; }
}

async function savePetSettings(body) {
  const response = await fetch('/api/pet/settings', {
    method: 'PATCH',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  });
  if (!response.ok) throw new Error('Could not save pet settings.');
  const state = await response.json();
  syncInPagePet(state);
  return state;
}

document.getElementById('shopButton').addEventListener('click', loadPetSettings);
document.getElementById('petName').addEventListener('change', async event => {
  try {
    const state = await savePetSettings({name: event.target.value});
    event.target.value = state.pet.name;
    showToast(`Your pet is called ${state.pet.name}.`);
  } catch (error) { showToast(error.message); }
});
document.getElementById('petInPage').addEventListener('change', async event => {
  try {
    await savePetSettings({in_page: event.target.checked});
    showToast(event.target.checked ? 'Your pet is roaming this page.' : 'Your pet left this page.');
  } catch (error) { showToast(error.message); }
});


// The optional in-page pet (the desktop companion shows the same pet on screen).
async function syncInPagePet(known) {
  try {
    const state = known || await fetchJson('/api/pet/state', undefined, 'Unable to load your pet.');
    const pet = window.LifeInboxPet;
    if (state.in_page && !pet.isMounted()) pet.mount(document.getElementById('petLayer'), {greet: false});
    else if (!state.in_page && pet.isMounted()) pet.unmount();
    else if (pet.isMounted()) pet.refresh();
  } catch { /* the pet is optional */ }
}
syncInPagePet();
