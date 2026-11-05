// Bridge to the engine. In the desktop app this is Electron IPC (window.tickbench). In a plain
// browser (development / screenshots) it falls back to scripts/dev_bridge.py over HTTP.
import type { EngineError } from "./types";

interface Bridge {
  call(method: string, params?: unknown): Promise<{ ok: boolean; id: number; result?: unknown; error?: EngineError }>;
  cancel(id: number): Promise<unknown>;
  onEvent(fn: (ev: Record<string, unknown>) => void): () => void;
  onStarted(fn: (info: { method: string; id: number }) => void): () => void;
  openScript(): Promise<string | null>;
  openData(): Promise<string | null>;
  pathForFile(f: File): string;
  info(): Promise<{ version: string; platform: string; packaged: boolean }>;
  openExternal(url: string): Promise<void>;
  showItem(p: string): Promise<void>;
  onUpdate(fn: (s: UpdateStatus) => void): () => void;
  installUpdate(): Promise<void>;
  checkUpdate(): Promise<unknown>;
}

export interface UpdateStatus { state: string; version?: string; percent?: number; message?: string }

declare global {
  interface Window { tickbench?: Bridge }
}

const DEV_URL = "http://127.0.0.1:8765";

function httpBridge(): Bridge {
  let nextId = 1;
  const listeners = new Set<(ev: Record<string, unknown>) => void>();
  const started = new Set<(info: { method: string; id: number }) => void>();
  return {
    async call(method, params) {
      const id = nextId++;
      started.forEach((f) => f({ method, id }));
      const r = await fetch(`${DEV_URL}/rpc`, { method: "POST", body: JSON.stringify({ id, method, params }) });
      const msg = await r.json();
      for (const ev of msg.events ?? []) listeners.forEach((f) => f(ev));
      return msg.error ? { ok: false, id, error: msg.error } : { ok: true, id, result: msg.result };
    },
    async cancel() { return true; },
    onEvent(fn) { listeners.add(fn); return () => { listeners.delete(fn); }; },
    onStarted(fn) { started.add(fn); return () => { started.delete(fn); }; },
    async openScript() { return window.prompt("Path to a strategy script") || null; },
    async openData() { return window.prompt("Path to a CSV file") || null; },
    pathForFile(f) { return (f as File & { path?: string }).path ?? f.name; },
    async info() { return { version: "dev", platform: "browser", packaged: false }; },
    async openExternal(url) { window.open(url, "_blank"); },
    async showItem() {},
    onUpdate(fn) { fn({ state: "dev" }); return () => {}; },
    async installUpdate() {},
    async checkUpdate() { return { state: "dev" }; },
  };
}

export const bridge: Bridge = window.tickbench ?? httpBridge();

export class EngineFailure extends Error {
  constructor(public detail: EngineError) { super(detail.message); }
}

export async function call<T>(method: string, params?: unknown): Promise<T> {
  let r;
  try {
    r = await bridge.call(method, params);
  } catch (e) {
    throw new EngineFailure({ message: String((e as Error).message ?? e), hint: "The engine couldn't be reached." });
  }
  if (!r.ok) throw new EngineFailure(r.error ?? { message: "Unknown engine error" });
  return r.result as T;
}
