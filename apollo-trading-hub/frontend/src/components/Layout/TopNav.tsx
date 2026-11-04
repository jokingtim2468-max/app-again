import { useEffect, useState } from 'react';
import { useFleetStore, usd } from '../../stores/useFleetStore';
import { useLayoutStore } from '../../stores/useLayoutStore';
import type { Route } from './LeftRail';

export default function TopNav({ route, go }: { route: Route; go: (r: Route) => void }) {
  const { online, mode, accounts, symbol, last, kill, start } = useFleetStore();
  const { presets, saved, activeName, load, dirty, locked, setLocked } = useLayoutStore();
  const [arm, setArm] = useState(false);
  useEffect(() => start(), [start]);
  useEffect(() => { if (!arm) return; const t = setTimeout(() => setArm(false), 4000); return () => clearTimeout(t); }, [arm]);

  const dayPnl = accounts.reduce((s, a) => s + a.closed_balance - a.day_start_balance + a.open_pnl, 0);
  const atRisk = accounts.filter((a) => a.distance_to_mll < 1000 && !a.liquidated).length;
  const names = [...Object.keys(presets), ...Object.keys(saved).filter((n) => !(n in presets))];
  const live = mode.startsWith('LIVE');

  return (
    <header style={{ gridColumn: 2, display: 'flex', alignItems: 'center', gap: 14, padding: '0 12px', borderBottom: '1px solid var(--line)', background: '#0C0E14' }}>
      <strong style={{ letterSpacing: '.18em', fontSize: 11 }}>APOLLO<span className="mut"> TRADING</span></strong>
      <div role="tablist" className="row" style={{ gap: 2 }}>
        {(['workspace', 'builder', 'settings'] as Route[]).map((r) => (
          <button key={r} data-tour={`tab-${r}`} role="tab" aria-selected={route === r} onClick={() => go(r)} className="ghost"
            style={{ color: route === r ? 'var(--text)' : undefined, borderBottom: route === r ? '2px solid var(--accent)' : '2px solid transparent', borderRadius: 0, height: 44 }}>
            {r === 'workspace' ? 'Workspace' : r === 'builder' ? 'Builder' : 'Settings'}
          </button>
        ))}
      </div>
      <select data-tour="layout" aria-label="Active layout" value={activeName} onChange={(e) => load(e.target.value)} style={{ maxWidth: 200 }}>
        {names.map((n) => <option key={n} value={n}>{n}{n in presets && !(n in saved) ? ' (preset)' : ''}</option>)}
      </select>
      <button data-tour="lock" className="ghost" onClick={() => setLocked(!locked)} aria-pressed={locked} title="Lock grid positions during live execution"
        style={{ color: locked ? 'var(--warn)' : undefined }}>{locked ? '🔒 Locked' : '✎ Edit'}</button>
      {dirty && <span className="warn" style={{ fontSize: 11 }}>● unsaved</span>}
      <div style={{ flex: 1 }} />
      <span className="mono mut">{symbol} <span style={{ color: 'var(--text)' }}>{last ? last.toFixed(1) : '—'}</span></span>
      <span data-tour="mode" className="pill" style={{ color: !online ? 'var(--bad)' : live ? 'var(--warn)' : 'var(--accent)' }} title="Execution mode">
        <span className="dot" />{online ? mode : 'BACKEND OFFLINE'}
      </span>
      <span className="pill mono" title="Fleet day PnL (closed + open)">
        Fleet <b className={dayPnl >= 0 ? 'pos' : 'neg'}>{usd(dayPnl)}</b>
        {atRisk > 0 && <span className="neg"> · {atRisk} near MLL</span>}
      </span>
      <button className="ghost" title="App tour" aria-label="App tour" onClick={() => window.dispatchEvent(new Event('apollo:tour'))}>?</button>
      <button data-tour="kill" className="danger" disabled={!online} aria-label="Fleet kill switch"
        onClick={() => { if (arm) { kill(); setArm(false); } else setArm(true); }}
        title="Flatten + halt every account">{arm ? 'CONFIRM KILL ALL' : '⏻ KILL SWITCH'}</button>
    </header>
  );
}
