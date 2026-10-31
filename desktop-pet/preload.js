// The only things the pet page may ask the desktop app to do.
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('petBridge', {
  // The window is click-through except while the pointer is over the pet or its panel.
  setInteractive: interactive => ipcRenderer.send('pet:interactive', Boolean(interactive)),
  // The window can only take keyboard input while the note panel is open.
  setFocusable: focusable => ipcRenderer.send('pet:focusable', Boolean(focusable)),
  notify: (title, body) => ipcRenderer.send('pet:notify', String(title), String(body)),
  openApp: () => ipcRenderer.send('pet:open-app')
});
