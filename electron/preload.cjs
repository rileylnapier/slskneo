const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('soulseek', Object.freeze({
  rpc: (method, params = {}) => ipcRenderer.invoke('soulseek:rpc', method, params),
  chooseDirectory: () => ipcRenderer.invoke('soulseek:directory'),
  revealFile: path => ipcRenderer.invoke('soulseek:reveal', path),
  getCredentials: () => ipcRenderer.invoke('soulseek:credentials-info'),
  saveYouTube: key => ipcRenderer.invoke('soulseek:youtube-save', key),
  saveSoundCloud: values => ipcRenderer.invoke('soulseek:soundcloud-save', values),
  saveCredentials: values => ipcRenderer.invoke('soulseek:credentials-save', values),
  notify: (title, body) => ipcRenderer.invoke('soulseek:notify', title, body),
  platform: process.platform,
  openLocalAudio: (trackId, fileId) => ipcRenderer.invoke('soulseek:open-local-audio', trackId, fileId),
  openRepresentationSource: key => ipcRenderer.invoke('soulseek:representation-source', key),
  openMusicLink: url => ipcRenderer.invoke('soulseek:music-link', url),
  importDiscovery: source => ipcRenderer.invoke('soulseek:discovery-import', source),
  seedDiscovery: () => ipcRenderer.invoke('soulseek:discovery-seed'),
}));
