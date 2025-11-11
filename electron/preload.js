const { contextBridge, ipcRenderer } = require('electron');

// Expose protected methods to the renderer process
contextBridge.exposeInMainWorld('electron', {
  /**
   * Open a native file picker dialog to select a .mexproj file
   * @returns {Promise<string|null>} Full file path or null if canceled
   */
  openProjectDialog: () => ipcRenderer.invoke('open-project-dialog'),

  /**
   * Open a native file picker dialog to select a vanilla Melee ISO
   * @returns {Promise<string|null>} Full file path or null if canceled
   */
  openIsoDialog: () => ipcRenderer.invoke('open-iso-dialog'),

  /**
   * Open a native directory picker dialog
   * @returns {Promise<string|null>} Full directory path or null if canceled
   */
  selectDirectory: () => ipcRenderer.invoke('select-directory-dialog'),

  /**
   * Check if running in Electron
   * @returns {boolean} Always returns true
   */
  isElectron: true,

  /**
   * Listen for nucleus:// protocol imports
   * @param {function} callback Function called with {url, name} when import is triggered
   * @returns {function} Cleanup function to remove listener
   */
  onNucleusImport: (callback) => {
    const listener = (event, data) => callback(data);
    ipcRenderer.on('nucleus-import', listener);
    // Return cleanup function
    return () => ipcRenderer.removeListener('nucleus-import', listener);
  }
});

// Log that preload script loaded successfully
console.log('[Preload] Electron API bridge initialized');
