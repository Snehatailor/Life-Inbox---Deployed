// Life Inbox desktop companion.
//
// One transparent, frameless, always-on-top window covers the primary display's
// work area and shows the /pet page. The window ignores the mouse everywhere
// except over the pet (the page tells us when the pointer is over it), so you
// can keep working underneath.

const fs = require('fs');
const path = require('path');
const { app, BrowserWindow, Tray, Menu, ipcMain, Notification, screen, shell, nativeImage } = require('electron');

// Which Life Inbox to talk to: the server that launched us (LIFE_INBOX_URL),
// else the site this download was built for (config.json), else a local run.
function configuredUrl() {
  try {
    const config = JSON.parse(fs.readFileSync(path.join(__dirname, 'config.json'), 'utf8'));
    return typeof config.url === 'string' ? config.url : '';
  } catch {
    return '';
  }
}

const BASE_URL = (process.env.LIFE_INBOX_URL || configuredUrl() || 'http://127.0.0.1:8000').replace(/\/+$/, '');
// Installed copies (not ones a local server starts) stay in your system: they
// start when you log in, which you can switch off from the tray menu.
const MANAGES_LOGIN_ITEM = app.isPackaged && !process.env.LIFE_INBOX_URL;
const SELF_TEST = process.env.PET_SELF_TEST === '1';
const RETRY_MS = 5000;

let win = null;
let tray = null;
let retryTimer = null;

function workArea() {
  return screen.getPrimaryDisplay().workArea;
}

// On Windows the 'floating' level only sits behind the taskbar and is not truly
// topmost, so other apps cover the pet. 'screen-saver' stays above them.
function keepOnTop() {
  if (win) win.setAlwaysOnTop(true, process.platform === 'win32' ? 'screen-saver' : 'floating');
}

function showPet() {
  win.showInactive();
  keepOnTop();
}

function createWindow() {
  const { x, y, width, height } = workArea();
  win = new BrowserWindow({
    x, y, width, height,
    transparent: true,
    frame: false,
    hasShadow: false,
    resizable: false,
    movable: false,
    skipTaskbar: true,
    alwaysOnTop: true,
    focusable: false, // only focusable while the note panel is open
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      backgroundThrottling: false
    }
  });
  keepOnTop();
  win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  win.setIgnoreMouseEvents(true, { forward: true });

  // Keep the page on Life Inbox; send anything else to the real browser.
  win.webContents.on('will-navigate', (event, url) => {
    if (!url.startsWith(BASE_URL)) {
      event.preventDefault();
      shell.openExternal(url);
    }
  });
  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  win.webContents.on('did-finish-load', () => {
    clearTimeout(retryTimer);
    if (tray) tray.setToolTip('Life Inbox pet');
    if (SELF_TEST) {
      console.log(`SELF_TEST ok: loaded ${win.webContents.getURL()}`);
      setTimeout(() => app.quit(), 500);
    }
  });
  win.webContents.on('did-fail-load', (_event, code, description, _url, isMainFrame) => {
    if (!isMainFrame) return;
    console.error(`Could not load ${BASE_URL}/pet (${code} ${description}). Retrying…`);
    if (tray) tray.setToolTip('Life Inbox pet: waiting for Life Inbox to start…');
    if (SELF_TEST) {
      console.log(`SELF_TEST failed: ${description}`);
      app.exit(1);
      return;
    }
    clearTimeout(retryTimer);
    retryTimer = setTimeout(() => win && win.loadURL(`${BASE_URL}/pet`), RETRY_MS);
  });

  win.once('ready-to-show', showPet);
  win.loadURL(`${BASE_URL}/pet`);
}

function firstRunSetup() {
  if (!MANAGES_LOGIN_ITEM) return;
  const marker = path.join(app.getPath('userData'), 'first-run-done');
  if (fs.existsSync(marker)) return;
  app.setLoginItemSettings({ openAtLogin: true });
  try { fs.writeFileSync(marker, new Date().toISOString()); } catch { /* ignore */ }
}

function startAtLoginItem() {
  if (!MANAGES_LOGIN_ITEM) return [];
  return [{
    label: 'Start when I log in',
    type: 'checkbox',
    checked: app.getLoginItemSettings().openAtLogin,
    click: item => app.setLoginItemSettings({ openAtLogin: item.checked })
  }];
}

function createTray() {
  const icon = nativeImage.createFromPath(path.join(__dirname, 'assets', 'tray.png'));
  tray = new Tray(icon.isEmpty() ? nativeImage.createEmpty() : icon);
  if (process.platform === 'darwin') tray.setTitle('🐾');
  tray.setToolTip('Life Inbox pet');
  const toggle = () => {
    if (!win) return;
    if (win.isVisible()) win.hide();
    else showPet();
  };
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: 'Show / hide pet', click: toggle },
      { label: 'Open Life Inbox', click: () => shell.openExternal(`${BASE_URL}/`) },
      { label: 'Reload pet', click: () => win && win.loadURL(`${BASE_URL}/pet`) },
      ...startAtLoginItem(),
      { type: 'separator' },
      { label: 'Quit', click: () => app.quit() }
    ])
  );
  tray.on('click', toggle);
}

ipcMain.on('pet:interactive', (event, interactive) => {
  if (win && event.sender === win.webContents) win.setIgnoreMouseEvents(!interactive, { forward: true });
});

ipcMain.on('pet:focusable', (event, focusable) => {
  if (!win || event.sender !== win.webContents) return;
  win.setFocusable(focusable);
  keepOnTop();
  if (focusable) win.focus();
  else win.blur();
});

ipcMain.on('pet:notify', (event, title, body) => {
  if (event.sender !== (win && win.webContents)) return;
  if (Notification.isSupported()) new Notification({ title, body, silent: false }).show();
});

ipcMain.on('pet:open-app', event => {
  if (win && event.sender === win.webContents) shell.openExternal(`${BASE_URL}/`);
});

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.whenReady().then(() => {
    if (process.platform === 'darwin' && app.dock) app.dock.hide();
    firstRunSetup();
    if (!SELF_TEST) createTray();
    createWindow();
    screen.on('display-metrics-changed', () => {
      if (win) win.setBounds(workArea());
    });
  });
  app.on('window-all-closed', () => app.quit());
}
