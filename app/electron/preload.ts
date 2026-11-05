import { contextBridge, ipcRenderer, webUtils } from "electron";

type Listener = (ev: Record<string, unknown>) => void;

contextBridge.exposeInMainWorld("tickbench", {
  call: (method: string, params?: unknown) => ipcRenderer.invoke("engine:call", method, params),
  cancel: (id: number) => ipcRenderer.invoke("engine:cancel", id),
  onEvent: (fn: Listener) => {
    const h = (_e: unknown, ev: Record<string, unknown>) => fn(ev);
    ipcRenderer.on("engine:event", h);
    return () => ipcRenderer.removeListener("engine:event", h);
  },
  onStarted: (fn: (info: { method: string; id: number }) => void) => {
    const h = (_e: unknown, info: { method: string; id: number }) => fn(info);
    ipcRenderer.on("engine:started", h);
    return () => ipcRenderer.removeListener("engine:started", h);
  },
  openScript: () => ipcRenderer.invoke("dialog:openScript"),
  openData: () => ipcRenderer.invoke("dialog:openData"),
  openFiles: () => ipcRenderer.invoke("dialog:openFiles"),
  pathForFile: (f: File) => webUtils.getPathForFile(f),
  info: () => ipcRenderer.invoke("app:info"),
  openExternal: (url: string) => ipcRenderer.invoke("app:openExternal", url),
  showItem: (p: string) => ipcRenderer.invoke("app:showItem", p),
  onUpdate: (fn: (s: { state: string; version?: string; percent?: number; message?: string }) => void) => {
    const h = (_e: unknown, s: { state: string }) => fn(s as never);
    ipcRenderer.on("update:status", h);
    return () => ipcRenderer.removeListener("update:status", h);
  },
  installUpdate: () => ipcRenderer.invoke("update:install"),
  checkUpdate: () => ipcRenderer.invoke("update:check"),
});
