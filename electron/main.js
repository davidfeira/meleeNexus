const { app, BrowserWindow, ipcMain, dialog } = require('electron');
const { spawn, exec } = require('child_process');
const path = require('path');
const fs = require('fs');

let pythonProcess = null;
let mainWindow = null;

// Determine if we're in development or production
const isDev = process.env.NODE_ENV === 'development' || !app.isPackaged;

function getResourcePath(relativePath) {
  if (isDev) {
    // In development, paths are relative to project root
    return path.join(__dirname, '..', relativePath);
  } else {
    // In production, use app resources
    return path.join(process.resourcesPath, relativePath);
  }
}

function startFlaskServer() {
  console.log('[Electron] Starting Flask backend...');

  let backendCmd, backendArgs, backendCwd;

  if (isDev) {
    // Development: Run Python script directly
    const backendPath = getResourcePath('backend/mex_api.py');
    console.log('[Electron] Dev mode - Backend path:', backendPath);

    if (!fs.existsSync(backendPath)) {
      console.error('[Electron] Backend file not found:', backendPath);
      return;
    }

    backendCmd = 'python';
    backendArgs = [backendPath];
    backendCwd = path.dirname(backendPath);
  } else {
    // Production: Use bundled executable (platform-aware)
    const backendName = process.platform === 'win32' ? 'mex_backend.exe' : 'mex_backend';
    const backendExe = path.join(process.resourcesPath, 'backend', backendName);
    console.log('[Electron] Production mode - Backend exe:', backendExe);

    if (!fs.existsSync(backendExe)) {
      console.error('[Electron] Backend executable not found:', backendExe);
      return;
    }

    backendCmd = backendExe;
    backendArgs = [];
    backendCwd = path.join(process.resourcesPath, 'backend');
  }

  // Spawn options with hidden window
  const spawnOptions = {
    cwd: backendCwd,
    stdio: ['ignore', 'pipe', 'pipe']
  };

  // Hide CMD window on Windows
  if (process.platform === 'win32') {
    spawnOptions.windowsHide = true;
  }

  pythonProcess = spawn(backendCmd, backendArgs, spawnOptions);

  pythonProcess.stdout.on('data', (data) => {
    console.log(`[Flask] ${data.toString().trim()}`);
  });

  pythonProcess.stderr.on('data', (data) => {
    console.error(`[Flask Error] ${data.toString().trim()}`);
  });

  pythonProcess.on('close', (code) => {
    console.log(`[Flask] Process exited with code ${code}`);
    pythonProcess = null;
  });

  pythonProcess.on('error', (err) => {
    console.error('[Flask] Failed to start:', err);
  });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1024,
    minHeight: 768,
    backgroundColor: '#1a1a1a',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      enableRemoteModule: false
    },
    icon: path.join(__dirname, '../viewer/public/favicon.ico')
  });

  // Load the app
  if (isDev) {
    // In development, load from Vite dev server
    mainWindow.loadURL('http://localhost:3000');
    mainWindow.webContents.openDevTools();
  } else {
    // In production, load built files
    const indexPath = path.join(__dirname, '../viewer/dist/index.html');
    mainWindow.loadFile(indexPath);
  }

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// IPC Handlers for file dialogs
ipcMain.handle('open-project-dialog', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openFile'],
    filters: [
      { name: 'MEX Project', extensions: ['mexproj'] }
    ],
    title: 'Open MEX Project'
  });

  if (result.canceled || result.filePaths.length === 0) {
    return null;
  }

  return result.filePaths[0];
});

ipcMain.handle('open-iso-dialog', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openFile'],
    filters: [
      { name: 'GameCube ISO', extensions: ['iso', 'gcm'] },
      { name: 'All Files', extensions: ['*'] }
    ],
    title: 'Select Vanilla Melee ISO (v1.02)'
  });

  if (result.canceled || result.filePaths.length === 0) {
    return null;
  }

  return result.filePaths[0];
});

ipcMain.handle('select-directory-dialog', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openDirectory', 'createDirectory'],
    title: 'Select Project Output Directory'
  });

  if (result.canceled || result.filePaths.length === 0) {
    return null;
  }

  return result.filePaths[0];
});

// Register nucleus:// protocol handler
if (process.defaultApp) {
  if (process.argv.length >= 2) {
    app.setAsDefaultProtocolClient('nucleus', process.execPath, [path.resolve(process.argv[1])]);
  }
} else {
  app.setAsDefaultProtocolClient('nucleus');
}

// Handle nucleus:// URLs
const handleNucleusUrl = async (url) => {
  console.log('[Nucleus Protocol] Received URL:', url);

  // Parse nucleus://import?url=...&name=...&title=...
  const urlObj = new URL(url);
  const action = urlObj.hostname; // 'import'
  const downloadUrl = urlObj.searchParams.get('url');
  const modName = urlObj.searchParams.get('name');
  const modTitle = urlObj.searchParams.get('title');

  console.log('[Nucleus Protocol DEBUG] action:', action);
  console.log('[Nucleus Protocol DEBUG] downloadUrl:', downloadUrl);
  console.log('[Nucleus Protocol DEBUG] modName:', modName);
  console.log('[Nucleus Protocol DEBUG] modTitle:', modTitle);
  console.log('[Nucleus Protocol DEBUG] modTitle type:', typeof modTitle);
  console.log('[Nucleus Protocol DEBUG] modTitle length:', modTitle?.length);

  if (action === 'import' && downloadUrl) {
    console.log('[Nucleus Protocol] Importing mod:', modName, 'title:', modTitle, 'from', downloadUrl);

    // Show window if hidden
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();

      // Send message to renderer to trigger import
      mainWindow.webContents.send('nucleus-import', {
        url: downloadUrl,
        name: modName,
        title: modTitle
      });
    }
  }
};

// Handle protocol URLs on macOS/Linux (when app is already running)
app.on('open-url', (event, url) => {
  event.preventDefault();
  handleNucleusUrl(url);
});

// Handle protocol URLs on Windows (when app is already running or being launched)
const gotTheLock = app.requestSingleInstanceLock();
if (!gotTheLock) {
  app.quit();
} else {
  app.on('second-instance', (event, commandLine, workingDirectory) => {
    // Someone tried to run a second instance with a nucleus:// URL
    // Focus our window and handle the URL
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }

    // The nucleus:// URL is in commandLine
    const url = commandLine.find(arg => arg.startsWith('nucleus://'));
    if (url) {
      handleNucleusUrl(url);
    }
  });
}

// App lifecycle
app.whenReady().then(() => {
  console.log('[Electron] App ready');

  // Start Flask backend
  startFlaskServer();

  // Wait a bit for Flask to start, then create window
  setTimeout(() => {
    createWindow();
  }, 2000);

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });

  // Handle nucleus:// URL if app was launched with one
  if (process.platform === 'win32') {
    const url = process.argv.find(arg => arg.startsWith('nucleus://'));
    if (url) {
      setTimeout(() => handleNucleusUrl(url), 3000); // Wait for Flask + window
    }
  }
});

app.on('window-all-closed', () => {
  // On macOS, keep app running unless explicitly quit
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('before-quit', async (event) => {
  console.log('[Electron] Shutting down...');

  // Kill Flask backend
  if (pythonProcess && !pythonProcess.killed) {
    event.preventDefault(); // Prevent immediate quit
    console.log('[Electron] Attempting graceful Flask shutdown...');

    // First try graceful shutdown via API
    try {
      const http = require('http');
      await new Promise((resolve) => {
        const req = http.request({
          hostname: '127.0.0.1',
          port: 5000,
          path: '/api/mex/shutdown',
          method: 'POST',
          timeout: 2000
        }, (res) => {
          console.log('[Electron] Shutdown request sent, status:', res.statusCode);
          resolve();
        });

        req.on('error', (err) => {
          console.log('[Electron] Graceful shutdown failed:', err.message);
          resolve();
        });

        req.on('timeout', () => {
          console.log('[Electron] Shutdown request timed out');
          req.destroy();
          resolve();
        });

        req.end();
      });

      // Give it a moment to shut down
      await new Promise(resolve => setTimeout(resolve, 1000));
    } catch (e) {
      console.log('[Electron] Could not reach shutdown endpoint:', e.message);
    }

    // Now force kill if still running
    if (pythonProcess && !pythonProcess.killed) {
      console.log('[Electron] Force killing Flask process...');

      // Detect if running under Wine (Wine sets WINEPREFIX or other Wine-specific env vars)
      const isWine = process.env.WINEPREFIX || process.env.WINE;

      if (process.platform === 'win32' && !isWine) {
        // On native Windows, use taskkill to terminate the entire process tree
        exec(`taskkill /F /T /PID ${pythonProcess.pid}`, (error) => {
          if (error) {
            console.error('[Electron] Error killing process tree:', error);
            // Try alternative method - kill by name
            exec('taskkill /F /IM mex_backend.exe 2>nul & taskkill /F /IM python.exe 2>nul', () => {
              pythonProcess = null;
              app.quit();
            });
          } else {
            console.log('[Electron] Flask process tree terminated');
            pythonProcess = null;
            app.quit();
          }
        });
      } else {
        // On Unix systems (including Wine), kill process group
        const backendName = process.platform === 'win32' ? 'mex_backend.exe' : 'mex_backend';
        try {
          // Try to kill process group first
          process.kill(-pythonProcess.pid);
          console.log('[Electron] Process group killed');
        } catch (e) {
          // Fallback to direct kill
          pythonProcess.kill('SIGKILL');
        }
        // Also try pkill as backup
        exec(`pkill -f ${backendName}`, () => {
          pythonProcess = null;
          app.quit();
        });
      }
    } else {
      pythonProcess = null;
      app.quit();
    }
  }
});

// Handle uncaught errors
process.on('uncaughtException', (error) => {
  console.error('[Electron] Uncaught exception:', error);
});
