// the desktop app passes the engine's port in the URL (?port=), since 5050 may be taken by another program
const PORT = new URLSearchParams(window.location.search).get('port') || '5050';
export const API = `http://127.0.0.1:${PORT}`;
export const WS = `ws://127.0.0.1:${PORT}`;

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API}${path}`, { ...init, headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) } });
  if (!r.ok) {
    let msg = `${r.status}`;
    try { const j = await r.json(); msg += ` ${typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)}`; } catch { /* non-json */ }
    throw new Error(msg);
  }
  return r.json() as Promise<T>;
}

type Handler = (e: Record<string, unknown>) => void;
const handlers = new Set<Handler>();
let sock: WebSocket | null = null;

/** One shared /ws/events socket for every widget, with auto-reconnect. */
export function onEvent(h: Handler): () => void {
  handlers.add(h);
  if (!sock) {
    const open = () => {
      sock = new WebSocket(`${WS}/ws/events`);
      sock.onmessage = (m) => { const e = JSON.parse(m.data); handlers.forEach((fn) => fn(e)); };
      sock.onclose = () => { sock = null; if (handlers.size) setTimeout(open, 2000); };
    };
    open();
  }
  return () => { handlers.delete(h); };
}
