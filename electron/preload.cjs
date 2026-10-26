const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('soulseek', Object.freeze({
  rpc: (method, params = {}) => ipcRenderer.invoke('soulseek:rpc', method, params),
  chooseDirectory: () => ipcRenderer.invoke('soulseek:directory'),
  revealFile: path => ipcRenderer.invoke('soulseek:reveal', path),
  getCredentials: () => ipcRenderer.invoke('soulseek:credentials-info'),
  saveCredentials: values => ipcRenderer.invoke('soulseek:credentials-save', values),
  notify: (title, body) => ipcRenderer.invoke('soulseek:notify', title, body),
  platform: process.platform,
}));
