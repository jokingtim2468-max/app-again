import { useEffect, useState } from 'react';
import { api, onEvent } from '../../api';

interface Print { time: number; price: number; size: number; side: 'B' | 'S' }

export default function TapeWidget({ minSize = 10, blockSize = 10 }: { minSize?: number; blockSize?: number }) {
  const [prints, setPrints] = useState<Print[]>([]);
  const [paused, setPaused] = useState(false);
  useEffect(() => {
    api<Print[]>(`/api/market/tape?min_size=${minSize}&limit=200`).then(setPrints).catch(() => undefined);
  }, [minSize]);
  useEffect(() => onEvent((e) => {
    if (e.type !== 'trade' || paused || Number(e.size) < minSize) return;
    setPrints((p) => [{ time: Number(e.time), price: Number(e.price), size: Number(e.size), side: e.side as 'B' | 'S' }, ...p].slice(0, 300));
  }), [minSize, paused]);
  const buy = prints.filter((p) => p.side === 'B').reduce((s, p) => s + p.size, 0);
  const sell = prints.filter((p) => p.side === 'S').reduce((s, p) => s + p.size, 0);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div className="row mono" style={{ padding: '4px 8px', borderBottom: '1px solid var(--line)', fontSize: 11, justifyContent: 'space-between' }}>
        <span className="mut">≥{minSize} lots</span>
        <span><span className="pos">B {buy}</span> / <span className="neg">S {sell}</span></span>
        <button className="ghost" onClick={() => setPaused((v) => !v)}>{paused ? '▶ resume' : '⏸ pause'}</button>
      </div>
      <div style={{ flex: 1, overflow: 'auto' }}>
        <table aria-label="Time and sales">
          <thead><tr><th>Time</th><th>Price</th><th>Size</th></tr></thead>
          <tbody>{prints.map((p, i) => (
            <tr key={`${p.time}-${i}`} style={{ background: p.size >= blockSize ? (p.side === 'B' ? 'rgba(61,220,151,.10)' : 'rgba(255,93,108,.10)') : undefined }}>
              <td className="mut">{new Date(p.time * 1000).toLocaleTimeString([], { hour12: false })}</td>
              <td className={p.side === 'B' ? 'pos' : 'neg'}>{p.price.toFixed(1)}</td>
              <td style={{ fontWeight: p.size >= blockSize ? 700 : 400 }}>{p.size}</td>
            </tr>))}</tbody>
        </table>
        {!prints.length && <div className="empty">No prints ≥ {minSize} yet</div>}
      </div>
    </div>
  );
}
