import { useEffect, useState } from 'react';
import AppLogo from './components/UI/AppLogo';
import SettingsPage from './components/Settings/SettingsPage';
import AccountsWidget from './components/Widgets/AccountsWidget';
import PayoutsWidget from './components/Widgets/PayoutsWidget';
import ReportsWidget from './components/Widgets/ReportsWidget';
import DomWidget from './components/Widgets/DomWidget';
import TapeWidget from './components/Widgets/TapeWidget';
import Tour, { TourStep } from './components/UI/Tour';
import { useFleetStore } from './stores/useFleetStore';
import { REGIME_LABEL, useCockpit } from './cockpit/store';
import { Icon, Panel } from './cockpit/ui';
import CockpitChart from './cockpit/CockpitChart';
import Studio from './cockpit/Studio';
import {
  ConfluenceRadar, CopierMatrix, EngineControls, FleetCards, FleetTotals, LiveFeed, MacroPanel, PanicButton, ParamsForm,
  PricePill, QuickOrders, RegimeBanner, TradesTable, useParams,
} from './cockpit/panels';

const PAGES = [
  ['dashboard', 'Fleet Dashboard', 'dashboard'], ['market', 'Market Intel', 'radar'], ['control', 'Bot Control', 'bot'],
  ['execution', 'Execution', 'zap'], ['studio', 'Backtest Studio', 'flask'], ['ledger', 'Ledger', 'list'],
  ['accounts', 'Accounts & Payouts', 'wallet'], ['settings', 'Settings', 'settings'],
] as const;
type Page = typeof PAGES[number][0];
const fromHash = (): Page => (PAGES.find(([k]) => window.location.hash === `#/${k}`)?.[0] ?? 'dashboard');

function Header() {
  const { accounts, mode } = useFleetStore(); const { account, setAccount, intel } = useCockpit();
  const reg = intel ? REGIME_LABEL[intel.regime.regime] : null;
  return (
    <header className="top">
      <select value={account} onChange={(e) => setAccount(e.target.value)} aria-label="Account" style={{ minWidth: 170 }}>
        <option value="">Fleet aggregate</option>{accounts.map((a) => <option key={a.account_id} value={a.account_id}>{a.account_id}</option>)}
      </select>
      <PricePill />
      {reg && <span className={`chip ${reg[1]}`}>{reg[0]}</span>}
      {intel?.news.blackout && <span className="chip bad">NEWS LOCK</span>}
      <span style={{ marginLeft: 'auto' }} />
      <span className={`chip ${intel?.engine.mode === 'AUTONOMOUS' ? 'good' : 'mut'}`}>{intel?.engine.mode ?? '—'}</span>
      <span className={`chip ${mode === 'LIVE' ? 'bad' : 'mut'}`}>{mode}</span>
      <button className="ghost" title="Replay the tour" onClick={() => window.dispatchEvent(new Event('apollo:tour'))}><Icon name="help" /></button>
      <PanicButton />
    </header>
  );
}

function Dashboard() {
  const { p } = useParams();
  return (
    <div className="grid">
      <FleetTotals />
      <RegimeBanner />
      <FleetCards />
      <div className="grid g3">
        <Panel title="XAUUSD / MGC" className="span2"><CockpitChart /></Panel>
        <div className="grid"><ConfluenceRadar min={Number(p?.values.confluence_min ?? 6.8)} /><QuickOrders /></div>
      </div>
      <div className="grid g2"><MacroPanel /><LiveFeed /></div>
    </div>
  );
}

export default function App() {
  const [page, setPage] = useState<Page>(fromHash);
  const [collapsed, setCollapsed] = useState(false);
  const [tour, setTour] = useState(false);
  const startFleet = useFleetStore((s) => s.start); const startCockpit = useCockpit((s) => s.start);
  const { p } = useParams();
  useEffect(() => { const a = startFleet(), b = startCockpit(); return () => { a(); b(); }; }, [startFleet, startCockpit]);
  useEffect(() => { const f = () => setPage(fromHash()); window.addEventListener('hashchange', f); return () => window.removeEventListener('hashchange', f); }, []);
  useEffect(() => { try { if (!localStorage.getItem('apollo.tour.cockpit')) setTimeout(() => setTour(true), 1200); } catch { /* storage blocked */ } }, []);
  useEffect(() => { const f = () => setTour(true); window.addEventListener('apollo:tour', f); return () => window.removeEventListener('apollo:tour', f); }, []);
  const go = (k: Page) => { if (import.meta.env.VITE_DEMO !== '1') window.location.hash = `#/${k}`; setPage(k); };
  const steps: TourStep[] = [
    { title: 'Welcome to Apollo Trading', body: 'Your gold scalping cockpit and prop fleet manager. A one-minute tour; replay it any time from the ? button.', before: () => go('dashboard') },
    { target: '.top select', title: 'Account switcher', body: 'Look at one account, or the whole fleet added together.' },
    { target: '.top .chip.live', title: 'Live price', body: 'Bid, ask, last and spread. The spread turns amber when it is wider than your max spread, and entries pause.' },
    { target: '.panic', title: 'Panic button', body: 'Turns autonomous trading off, cancels limits, flattens every position and halts every account. Click twice to confirm.' },
    { title: 'Fleet dashboard', body: 'Each card shows the safe buffer above the trailing floor, progress to the profit target and how close the day is to the daily loss breaker.' },
    { title: 'Bot Control', body: 'Switch Autonomous / Manual and change TP, SL, breakeven, cooldowns, confluence threshold and quotas. Changes apply on the next tick.', before: () => go('control') },
    { title: 'Execution', body: 'One-click market and Asian-range limit orders with automatic brackets, Breakeven All, and the copy-trader matrix.', before: () => go('execution') },
    { title: 'Backtest Studio', body: 'Test the same rules on MT5 history with month-by-month results, an equity curve and a parameter grid optimizer.', before: () => go('studio') },
    { title: 'Ledger', body: 'Every trade with MFE, MAE, commission and net. Click a trade for the full breakdown.', before: () => go('ledger') },
  ];
  return (
    <div className={`shell ${collapsed ? 'collapsed' : ''}`}>
      {tour && <Tour steps={steps} storageKey="apollo.tour.cockpit" onClose={() => { setTour(false); go('dashboard'); }} />}
      <nav className="side" aria-label="Main">
        <div className="brand"><AppLogo size={22} /><span className="lbl">{!collapsed && 'APOLLO TRADING'}</span></div>
        {PAGES.map(([k, lbl, ic]) => (
          <a key={k} className={page === k ? 'on' : ''} onClick={() => go(k)} title={lbl}><Icon name={ic} /><span className="lbl">{!collapsed && lbl}</span></a>
        ))}
        <a style={{ marginTop: 'auto' }} onClick={() => setCollapsed(!collapsed)} title="Collapse sidebar"><Icon name="menu" /><span className="lbl">{!collapsed && 'Collapse'}</span></a>
      </nav>
      <Header />
      <main className="page">
        {page === 'dashboard' && <Dashboard />}
        {page === 'market' && (
          <div className="grid">
            <RegimeBanner />
            <div className="grid g3"><Panel title="Chart" className="span2"><CockpitChart height={460} /></Panel><ConfluenceRadar min={Number(p?.values.confluence_min ?? 6.8)} /></div>
            <div className="grid g3"><MacroPanel /><Panel title="Depth of market"><div style={{ height: 300 }}><DomWidget /></div></Panel><Panel title="Time & sales"><div style={{ height: 300 }}><TapeWidget /></div></Panel></div>
          </div>
        )}
        {page === 'control' && <div className="grid"><EngineControls /><RegimeBanner /><ParamsForm /></div>}
        {page === 'execution' && <div className="grid"><div className="grid g2"><QuickOrders /><LiveFeed max={260} /></div><CopierMatrix /></div>}
        {page === 'studio' && <Studio />}
        {page === 'ledger' && <div className="grid"><TradesTable /><LiveFeed max={500} /></div>}
        {page === 'accounts' && (
          <div className="grid">
            <Panel title="Accounts"><div style={{ height: 420 }}><AccountsWidget /></div></Panel>
            <Panel title="Payouts"><div style={{ height: 460 }}><PayoutsWidget /></div></Panel>
            <Panel title="Reports"><div style={{ height: 520 }}><ReportsWidget /></div></Panel>
          </div>
        )}
        {page === 'settings' && <SettingsPage />}
      </main>
    </div>
  );
}
