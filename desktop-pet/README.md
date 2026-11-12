# Life Inbox Pet

A desktop companion for [Life Inbox](https://life-inbox-0p9j.onrender.com): your pet walks along the bottom of your screen, takes quick notes, and reminds you of tasks, even when the browser is closed.

## Install

Download the file for your computer from the [latest release](../../releases/latest):

| Computer | File |
| --- | --- |
| Windows (most PCs) | `Life-Inbox-Pet-Setup-x64.exe` |
| Windows on ARM (Snapdragon) | `Life-Inbox-Pet-Setup-arm64.exe` |
| Mac (Intel and Apple Silicon) | `Life-Inbox-Pet-mac.dmg` |
| Linux | `Life-Inbox-Pet-linux-x86_64.AppImage` |

The installers are not code-signed yet:

- **Windows** may say "Windows protected your PC". Choose **More info**, then **Run anyway**.
- **Mac**: the first time, right-click the app and choose **Open**.
- **Linux**: make the AppImage executable (`chmod +x`), then run it.

## Use

1. After installing, the pet appears at the bottom of your screen.
2. Tap it and sign in with your Life Inbox email and password. It remembers you.
3. Tap it any time to save a note or make a task. It reminds you when tasks are due.

The pet starts when you log in to your computer. To stop that, right-click the tray icon (🐾) and untick **Start when I log in**. **Quit** is in the same menu.

## How it connects

`config.json` holds the Life Inbox address the pet talks to. When Life Inbox runs on your own computer, the server starts the pet itself and points it at the local copy instead (`LIFE_INBOX_URL`).

## Build

```bash
npm ci
npm start            # run from source
npm run dist:win     # Windows installers (x64 and ARM)
npm run dist:mac     # Mac (run on a Mac)
npm run dist:linux   # Linux AppImage
```

Pushing a tag such as `v1.0.1` builds every installer on GitHub Actions and publishes them as the latest release.

This folder is copied from `desktop-pet/` in the Life Inbox app, which is where changes should be made.
