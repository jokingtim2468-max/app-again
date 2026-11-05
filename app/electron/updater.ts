// Auto-update from GitHub Releases (electron-updater). Downloads in the background and
// tells the window; the user chooses when to restart.
import { app, BrowserWindow, ipcMain } from "electron";
import { autoUpdater } from "electron-updater";

export function setupUpdater(getWin: () => BrowserWindow | null) {
  const send = (s: Record<string, unknown>) => getWin()?.webContents.send("update:status", s);
  ipcMain.handle("update:install", () => autoUpdater.quitAndInstall(false, true));
  ipcMain.handle("update:check", async () => {
    if (!app.isPackaged) return { state: "dev" };
    try {
      const r = await autoUpdater.checkForUpdates();
      return { state: "checked", version: r?.updateInfo.version };
    } catch (e) {
      return { state: "error", message: String((e as Error).message ?? e) };
    }
  });
  if (!app.isPackaged) {
    send({ state: "dev" });
    return;
  }
  autoUpdater.autoDownload = true;
  autoUpdater.autoInstallOnAppQuit = true;
  autoUpdater.on("checking-for-update", () => send({ state: "checking" }));
  autoUpdater.on("update-available", (i) => send({ state: "available", version: i.version }));
  autoUpdater.on("update-not-available", () => send({ state: "current" }));
  autoUpdater.on("download-progress", (p) => send({ state: "downloading", percent: Math.round(p.percent) }));
  autoUpdater.on("update-downloaded", (i) => send({ state: "ready", version: i.version }));
  autoUpdater.on("error", (e) => send({ state: "error", message: String(e?.message ?? e) }));
  const check = () => autoUpdater.checkForUpdates().catch(() => undefined);
  setTimeout(check, 4000);
  setInterval(check, 6 * 60 * 60 * 1000);
}
