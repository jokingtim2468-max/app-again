import { useEffect, useState } from 'react';
import LeftRail, { Route } from './components/Layout/LeftRail';
import TopNav from './components/Layout/TopNav';
import LayoutBuilder from './components/Builder/LayoutBuilder';
import WidgetCatalog from './components/Builder/WidgetCatalog';
import LayoutToolbar from './components/Builder/LayoutToolbar';
import { useLayoutStore } from './stores/useLayoutStore';
import SettingsPage from './components/Settings/SettingsPage';
import Tour, { TourStep } from './components/UI/Tour';

const routeFromHash = (): Route => (window.location.hash.startsWith('#/builder') ? 'builder' : window.location.hash.startsWith('#/settings') ? 'settings' : 'workspace');

export default function App() {
  const [route, setRoute] = useState<Route>(routeFromHash);
  const { init, toast, load } = useLayoutStore();
  const [appTour, setAppTour] = useState(false);
  useEffect(() => { init(); try { if (!localStorage.getItem('apollo.tour.app')) setTimeout(() => setAppTour(true), 1200); } catch { /* storage blocked */ } }, [init]);
  useEffect(() => { const f = () => setAppTour(true); window.addEventListener('apollo:tour', f); return () => window.removeEventListener('apollo:tour', f); }, []);
  useEffect(() => { const f = () => setRoute(routeFromHash()); window.addEventListener('hashchange', f); return () => window.removeEventListener('hashchange', f); }, []);
  const go = (r: Route) => { window.location.hash = r === 'workspace' ? '#/' : `#/${r}`; setRoute(r); };
  const steps: TourStep[] = [
    { title: 'Welcome to Apollo Trading', body: 'A quick tour of the app (about a minute). Press → or Next. You can replay it from the ? button at the top.' , before: () => go('workspace') },
    { target: '[data-tour="rail"]', title: 'Navigation', body: 'Workspace (your trading screen), Builder (design layouts) and Settings (bots, alerts, commands).' },
    { target: '[data-tour="layout"]', title: 'Layouts', body: 'Switch workspaces: Execution Focus, Risk Command, Quant Lab, Payout Center, Reports, Account Setup, or your own saved layouts.' },
    { target: '[data-tour="lock"]', title: 'Edit / Lock', body: 'Drag and resize widgets in Edit mode. Lock the grid while trading so nothing moves.' },
    { target: '[data-tour="mode"]', title: 'Paper or live', body: 'Everything starts in PAPER mode. Live trading only happens when you set APOLLO_LIVE=1 and your firm rules are verified.' },
    { target: '[data-tour="kill"]', title: 'Kill switch', body: 'Flattens and halts every account at once (click twice to confirm). Individual kills are in the Fleet deck.' },
    { title: 'Payout Center', body: 'Shows which accounts can withdraw now, exact amounts, monthly ceilings and account outcomes (passed, blown, ROI).', before: () => load('Payout Center') },
    { title: 'Reports', body: 'Balance history, trade log, payout log, daily P&L and real profit (payouts minus costs). Export anything to CSV.', before: () => load('Reports') },
    { title: 'Account Setup', body: 'Add accounts from any firm and platform, set costs, firm caps and copy ratios.', before: () => load('Account Setup') },
    { target: '[data-tour="tab-builder"]', title: 'Builder', body: 'Add any widget from the catalog, arrange the grid and save your own layouts.', before: () => go('builder') },
    { target: '[data-tour="tab-settings"]', title: 'Settings: bots & alerts', body: 'Connect Discord or Telegram with a /verify code, choose where alerts go, and create custom commands. It has its own step-by-step tutorial.', before: () => go('settings') },
  ];

  return (
    <div className="app">
      {appTour && <Tour steps={steps} storageKey="apollo.tour.app" onClose={() => { setAppTour(false); go('workspace'); load('Execution Focus'); }} />}
      <LeftRail route={route} go={go} />
      <TopNav route={route} go={go} />
      <main className="content">
        {route === 'settings' ? <SettingsPage /> : route === 'builder' ? (
          <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
            <LayoutToolbar />
            <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
              <WidgetCatalog />
              <div style={{ flex: 1, overflow: 'auto' }}><LayoutBuilder studio /></div>
            </div>
          </div>
        ) : (
          <LayoutBuilder />
        )}
      </main>
      {toast && <div role="status" style={{ position: 'fixed', bottom: 16, right: 16, background: 'var(--surface)', border: '1px solid var(--accent)', borderRadius: 7, padding: '8px 14px', zIndex: 100 }}>{toast}</div>}
    </div>
  );
}
