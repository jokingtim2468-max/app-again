import { app, BrowserWindow, shell } from 'electron';
import { autoUpdater } from 'electron-updater';
import path from 'path';

let win: BrowserWindow | null = null;

function create() {
  win = new BrowserWindow({
    width: 1480, height: 920, minWidth: 1100, minHeight: 700,
    backgroundColor: '#090A0F', title: 'Closed Claw', autoHideMenuBar: true,
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  if (process.env.VITE_DEV) win.loadURL('http://127.0.0.1:5173');
  else win.loadFile(path.join(__dirname, '../dist/index.html'));
  win.webContents.setWindowOpenHandler(({ url }) => { shell.openExternal(url); return { action: 'deny' }; });
}

app.whenReady().then(() => {
  create();
  if (app.isPackaged) autoUpdater.checkForUpdatesAndNotify().catch(() => undefined);
  app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) create(); });
});
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
