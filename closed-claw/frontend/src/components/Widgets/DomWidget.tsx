import { useEffect, useMemo, useState } from 'react';
import { api, onEvent } from '../../api';
import { useFleetStore } from '../../stores/useFleetStore';

type Level = [number, number];
interface Bar { close: number; volume: number }

export default function DomWidget({ levels = 12 }: { levels?: number }) {
  const [book, setBook] = useState<{ bids: Level[]; asks: Level[] }>({ bids: [], asks: [] });
  const [last, setLast] = useState(0);
  const [traded, setTraded] = useState<Record<string, number>>({});
  const [profile, setProfile] = useState<Record<string, number>>({});
  const [qty, setQty] = useState(5); const [tp, setTp] = useState(40); const [sl, setSl] = useState(30);
  const [busy, setBusy] = useState(false);
  const { order, lastError, accounts, master } = useFleetStore();
  const pos = accounts.find((a) => a.account_id === master);

  useEffect(() => {
    api<{ bids: Level[]; asks: Level[]; last: number }>('/api/market/dom').then((d) => { setBook(d); setLast(d.last); }).catch(() => undefined);
    const loadProfile = () => api<{ bars: Bar[] }>('/api/market/bars?tf=1m&limit=1440').then((d) => {
      const p: Record<string, number> = {};
      for (const b of d.bars) { const k = b.close.toFixed(1); p[k] = (p[k] || 0) + b.volume; }
      setProfile(p);
    }).catch(() => undefined);
    loadProfile(); const t = setInterval(loadProfile, 60000);
    const off = onEvent((e) => {
      if (e.type === 'dom') setBook({ bids: e.bids as Level[], asks: e.asks as Level[] });
      if (e.type === 'trade') {
        const k = Number(e.price).toFixed(1);
        setLast(Number(e.price));
        setTraded((s) => ({ ...s, [k]: (s[k] || 0) + Number(e.size) }));
      }
    });
    return () => { clearInterval(t); off(); };
  }, []);

  const rows = useMemo(() => {
    const bid = new Map(book.bids.map(([p, s]) => [p.toFixed(1), s]));
    const ask = new Map(book.asks.map(([p, s]) => [p.toFixed(1), s]));
    const center = book.bids[0]?.[0] ?? last;
    if (!center) return [];
    const out: { p: string; bid?: number; ask?: number; vol: number; tr: number }[] = [];
    for (let i = levels; i >= -levels + 1; i--) {
      const p = (Math.round(center * 10) / 10 + i * 0.1).toFixed(1);
      out.push({ p, bid: bid.get(p), ask: ask.get(p), vol: profile[p] || 0, tr: traded[p] || 0 });
    }
    return out;
  }, [book, last, profile, traded, levels]);
  const maxSize = Math.max(1, ...book.bids.map((b) => b[1]), ...book.asks.map((a) => a[1]));
  const maxVol = Math.max(1, ...rows.map((r) => r.vol));

  const send = async (side: 'Buy' | 'Sell', bracket: boolean) => {
    setBusy(true);
    try {
      if (bracket) await fetchBracket(side, qty, tp, sl); else await order(side, qty);
    } finally { setBusy(false); }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ flex: 1, overflow: 'auto' }}>
        <table aria-label="Depth of market">
          <thead><tr><th style={{ textAlign: 'left' }}>Profile</th><th>Bid</th><th style={{ textAlign: 'center' }}>Price</th><th style={{ textAlign: 'left' }}>Ask</th><th>Traded</th></tr></thead>
          <tbody>
            {rows.map((r) => {
              const isLast = r.p === last.toFixed(1);
              return (
                <tr key={r.p} style={{ background: isLast ? '#1B2131' : undefined }}>
                  <td style={{ padding: '2px 6px', width: '22%' }}><div style={{ height: 8, width: `${(r.vol / maxVol) * 100}%`, background: '#2C3347', borderRadius: 2 }} /></td>
                  <td style={{ padding: '2px 6px', position: 'relative', color: 'var(--bid)' }}>
                    {r.bid !== undefined && <><div style={{ position: 'absolute', right: 0, top: 2, bottom: 2, width: `${(r.bid / maxSize) * 100}%`, background: 'rgba(61,220,151,.12)' }} />{r.bid}</>}
                  </td>
                  <td style={{ padding: '2px 6px', textAlign: 'center', color: isLast ? 'var(--warn)' : 'var(--text)', fontWeight: isLast ? 600 : 400 }}>{r.p}</td>
                  <td style={{ padding: '2px 6px', textAlign: 'left', position: 'relative', color: 'var(--ask)' }}>
                    {r.ask !== undefined && <><div style={{ position: 'absolute', left: 0, top: 2, bottom: 2, width: `${(r.ask / maxSize) * 100}%`, background: 'rgba(255,93,108,.12)' }} />{r.ask}</>}
                  </td>
                  <td className="mut" style={{ padding: '2px 6px' }}>{r.tr || ''}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {!rows.length && <div className="empty">Waiting for book…</div>}
      </div>
      <div style={{ borderTop: '1px solid var(--line)', padding: 8, display: 'grid', gap: 6 }}>
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <label className="row mut">Qty <input type="number" min={1} max={100} value={qty} onChange={(e) => setQty(Math.max(1, +e.target.value))} style={{ width: 54 }} /></label>
          <label className="row mut">TP <input type="number" min={1} value={tp} onChange={(e) => setTp(+e.target.value)} style={{ width: 50 }} />t</label>
          <label className="row mut">SL <input type="number" min={1} value={sl} onChange={(e) => setSl(+e.target.value)} style={{ width: 50 }} />t</label>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
          <button className="primary" disabled={busy} onClick={() => send('Buy', true)}>Buy bracket</button>
          <button className="danger" disabled={busy} onClick={() => send('Sell', true)}>Sell bracket</button>
          <button disabled={busy} onClick={() => send('Buy', false)}>Buy MKT</button>
          <button disabled={busy} onClick={() => send('Sell', false)}>Sell MKT</button>
        </div>
        <div className="row mono" style={{ justifyContent: 'space-between', fontSize: 11 }}>
          <span className="mut">Fleet ×5 · 1:1 copy</span>
          {pos && pos.position_qty !== 0
            ? <span className={pos.open_pnl >= 0 ? 'pos' : 'neg'}>{pos.position_qty > 0 ? 'L' : 'S'}{Math.abs(pos.position_qty)} @ {pos.avg_price.toFixed(1)} · ${pos.open_pnl.toFixed(0)}</span>
            : <span className="mut">flat</span>}
          <button className="ghost" onClick={() => api('/api/fleet/flatten', { method: 'POST' })}>Flatten</button>
        </div>
        {lastError && <div className="neg" style={{ fontSize: 11 }}>{lastError}</div>}
      </div>
    </div>
  );
}

async function fetchBracket(action: 'Buy' | 'Sell', qty: number, tp_ticks: number, sl_ticks: number) {
  await api('/api/fleet/order', { method: 'POST', body: JSON.stringify({ action, qty, tp_ticks, sl_ticks }) });
  await useFleetStore.getState().refresh();
}
