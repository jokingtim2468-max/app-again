import { useEffect, useRef, useState } from 'react';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';
import { api, WS } from '../../api';

interface Box { id: string; name: string; image: string; status: string; cpu_limit: number; mem_limit_mb: number }

export default function TerminalWidget() {
  const host = useRef<HTMLDivElement>(null);
  const [boxes, setBoxes] = useState<Box[]>([]);
  const [cid, setCid] = useState<string>('');
  const [err, setErr] = useState('');
  const [docker, setDocker] = useState<boolean | null>(null);

  const load = async () => {
    try {
      const h = await api<{ docker: boolean }>('/api/health'); setDocker(h.docker);
      const b = await api<Box[]>('/api/containers'); setBoxes(b);
      if (!cid && b.find((x) => x.status === 'running')) setCid(b.find((x) => x.status === 'running')!.id);
    } catch (e) { setErr(String(e)); }
  };
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!cid || !host.current) return;
    const term = new Terminal({ fontFamily: 'JetBrains Mono, Cascadia Code, Consolas, monospace', fontSize: 12, cursorBlink: true,
      theme: { background: '#05060A', foreground: '#E3E7F0', cursor: '#6CF0C2', selectionBackground: '#2C3347' } });
    const fit = new FitAddon(); term.loadAddon(fit); term.open(host.current);
    const ro = new ResizeObserver(() => { try { fit.fit(); } catch { /* hidden */ } }); ro.observe(host.current);
    const ws = new WebSocket(`${WS}/ws/containers/${cid}`); ws.binaryType = 'arraybuffer';
    ws.onopen = () => { term.writeln(`\x1b[32m● attached ${cid}\x1b[0m`); fit.fit(); };
    ws.onmessage = (m) => term.write(typeof m.data === 'string' ? m.data : new Uint8Array(m.data));
    ws.onclose = () => term.writeln('\r\n\x1b[31m● disconnected\x1b[0m');
    const sub = term.onData((d) => ws.readyState === 1 && ws.send(new TextEncoder().encode(d)));
    return () => { sub.dispose(); ws.close(); ro.disconnect(); term.dispose(); };
  }, [cid]);

  const spawn = async () => {
    setErr('');
    try { const b = await api<Box>('/api/containers', { method: 'POST', body: '{}' }); setCid(b.id); load(); }
    catch (e) { setErr(String(e)); }
  };
  const kill = async () => { if (!cid) return; await api(`/api/containers/${cid}`, { method: 'DELETE' }); setCid(''); load(); };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div className="row" style={{ padding: '4px 8px', borderBottom: '1px solid var(--line)' }}>
        <select aria-label="Container" value={cid} onChange={(e) => setCid(e.target.value)} style={{ flex: 1 }}>
          <option value="">— select sandbox —</option>
          {boxes.map((b) => <option key={b.id} value={b.id}>{b.name} · {b.image} · {b.status} · {b.cpu_limit}c/{b.mem_limit_mb}MB</option>)}
        </select>
        <button onClick={spawn} disabled={docker === false}>+ New</button>
        <button className="ghost" onClick={kill} disabled={!cid}>✕ Remove</button>
      </div>
      {err && <div className="neg" style={{ padding: '4px 8px' }}>{err}</div>}
      {docker === false
        ? <div className="empty">Docker engine not reachable.<br /><span className="mut">Start Docker Desktop, then reopen this widget.</span></div>
        : cid ? <div ref={host} style={{ flex: 1, background: '#05060A', padding: 4, minHeight: 0 }} />
          : <div className="empty">Create or select a network-isolated sandbox.</div>}
    </div>
  );
}
