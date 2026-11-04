import { useEffect, useRef, useState } from 'react';
import { api, WS } from '../../api';
import { useAgentStore } from '../../stores/useAgentStore';

interface Box { id: string; name: string; image: string; status: string; cpu_limit: number; mem_limit_mb: number; cpu_percent?: number; mem_usage_mb?: number }

export default function VMViewer() {
  const { containerId, setContainer } = useAgentStore();
  const [boxes, setBoxes] = useState<Box[]>([]);
  const [out, setOut] = useState(''); const [cmd, setCmd] = useState('');
  const [err, setErr] = useState('');
  const ws = useRef<WebSocket | null>(null); const termRef = useRef<HTMLDivElement>(null);

  const load = () => api<Box[]>('/api/containers').then(setBoxes).catch((e) => setErr(String(e)));
  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t); }, []);
  useEffect(() => {
    ws.current?.close(); setOut('');
    if (!containerId) return;
    const s = new WebSocket(`${WS}/ws/containers/${containerId}`);
    s.onmessage = (m) => setOut((o) => o + (m.data === '\u0004' ? '\n$ ' : m.data));
    s.onopen = () => setOut(`connected to ${containerId}\n$ `);
    ws.current = s; return () => s.close();
  }, [containerId]);
  useEffect(() => { termRef.current?.scrollTo(0, termRef.current.scrollHeight); }, [out]);

  const spawn = async () => { try { const b = await api<Box>('/api/containers', { method: 'POST', body: '{}' }); setContainer(b.id); load(); } catch (e) { setErr(String(e)); } };
  const kill = async (id: string) => { await api(`/api/containers/${id}`, { method: 'DELETE' }); if (id === containerId) setContainer(null); load(); };

  return (
    <div className="grid">
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <p className="h" style={{ margin: 0 }}>Docker sandboxes · network-isolated</p>
        <button onClick={spawn}>+ New sandbox</button>
      </div>
      {err && <div className="neg">{err}</div>}
      <div className="wire" style={{ overflowX: 'auto' }}>
        <table><thead><tr><th>ID</th><th>Name</th><th>Image</th><th>Status</th><th>CPU</th><th>RAM</th><th></th></tr></thead>
          <tbody>{boxes.map((b) => (
            <tr key={b.id} style={{ background: b.id === containerId ? 'var(--panel-2)' : undefined }}>
              <td>{b.id}</td><td>{b.name}</td><td>{b.image}</td><td className={b.status === 'running' ? 'pos' : 'mut'}>{b.status}</td>
              <td>{b.cpu_percent ?? 0}% / {b.cpu_limit}c</td><td>{b.mem_usage_mb ?? 0} / {b.mem_limit_mb} MB</td>
              <td><div className="row" style={{ justifyContent: 'flex-end' }}><button onClick={() => setContainer(b.id)}>Attach</button><button onClick={() => kill(b.id)}>✕</button></div></td>
            </tr>))}</tbody></table>
      </div>
      <div ref={termRef} className="term" aria-live="polite">{containerId ? out : 'Attach a sandbox to open a terminal.'}</div>
      <form className="row" onSubmit={(e) => { e.preventDefault(); if (cmd && ws.current?.readyState === 1) { ws.current.send(cmd); setOut((o) => o + cmd + '\n'); setCmd(''); } }}>
        <input style={{ flex: 1, fontFamily: 'var(--mono)' }} value={cmd} onChange={(e) => setCmd(e.target.value)} placeholder="command" disabled={!containerId} aria-label="Command" />
        <button disabled={!containerId}>Run</button>
      </form>
    </div>
  );
}
