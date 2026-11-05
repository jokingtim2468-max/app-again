import { app, BrowserWindow, dialog, ipcMain, nativeTheme, shell } from "electron";
import path from "path";
import { Engine } from "./engine";
import { setupUpdater } from "./updater";

let win: BrowserWindow | null = null;
const engine = new Engine((ev) => win?.webContents.send("engine:event", ev));

function createWindow() {
  win = new BrowserWindow({
    width: 1480,
    height: 920,
    minWidth: 1100,
    minHeight: 700,
    backgroundColor: nativeTheme.shouldUseDarkColors ? "#0F1214" : "#F4F2EC",
    title: "Tickbench",
    autoHideMenuBar: true,
    show: false,
    icon: path.join(__dirname, "..", "build", "icon.png"),
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  win.once("ready-to-show", () => win?.show());
  const devUrl = process.env.VITE_DEV_SERVER_URL;
  if (devUrl) win.loadURL(devUrl);
  else win.loadFile(path.join(__dirname, "..", "dist", "index.html"));
  // links open in the user's browser, never inside the app
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:/.test(url)) shell.openExternal(url);
    return { action: "deny" };
  });
  win.webContents.on("will-navigate", (e, url) => {
    if (!url.startsWith("file:") && !url.startsWith(devUrl ?? "http://localhost:5173")) e.preventDefault();
  });
}

ipcMain.handle("engine:call", async (_e, method: string, params: unknown) => {
  const { id, promise } = await engine.call(method, params);
  win?.webContents.send("engine:started", { method, id });
  try {
    return { ok: true, id, result: await promise };
  } catch (err) {
    const e = err as Record<string, unknown>;
    return { ok: false, id, error: e && e.message ? e : { message: String(err) } };
  }
});

ipcMain.handle("engine:cancel", async (_e, id: number) => {
  const { promise } = await engine.call("cancel", { id });
  return promise;
});

ipcMain.handle("dialog:openScript", async () => {
  const r = await dialog.showOpenDialog(win!, {
    title: "Open a strategy script",
    properties: ["openFile"],
    filters: [
      { name: "Strategy scripts", extensions: ["pine", "txt", "mq4", "mq5", "mqh", "py", "js", "mjs", "json", "yaml", "yml"] },
      { name: "All files", extensions: ["*"] },
    ],
  });
  return r.canceled ? null : r.filePaths[0];
});

ipcMain.handle("dialog:openFiles", async () => {
  const r = await dialog.showOpenDialog(win!, {
    title: "Add files the strategy uses",
    properties: ["openFile", "multiSelections"],
    filters: [{ name: "All files", extensions: ["*"] }],
  });
  return r.canceled ? [] : r.filePaths;
});

ipcMain.handle("dialog:openData", async () => {
  const r = await dialog.showOpenDialog(win!, {
    title: "Open price data (CSV)",
    properties: ["openFile"],
    filters: [{ name: "Price data", extensions: ["csv", "txt", "tsv"] }, { name: "All files", extensions: ["*"] }],
  });
  return r.canceled ? null : r.filePaths[0];
});

ipcMain.handle("app:info", () => ({ version: app.getVersion(), platform: process.platform, packaged: app.isPackaged }));
ipcMain.handle("app:openExternal", (_e, url: string) => {
  if (/^https:\/\//.test(url)) shell.openExternal(url);
});
ipcMain.handle("app:showItem", (_e, p: string) => shell.showItemInFolder(p));

app.whenReady().then(() => {
  createWindow();
  engine.start().catch((err) => win?.webContents.send("engine:event", { event: "fatal", text: String(err.message ?? err) }));
  setupUpdater(() => win);
  app.on("activate", () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
});

app.on("window-all-closed", () => {
  engine.stop();
  if (process.platform !== "darwin") app.quit();
});
app.on("before-quit", () => engine.stop());
