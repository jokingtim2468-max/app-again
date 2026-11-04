import { useEffect, useState } from 'react';
import LeftRail, { Route } from './components/Layout/LeftRail';
import TopNav from './components/Layout/TopNav';
import LayoutBuilder from './components/Builder/LayoutBuilder';
import WidgetCatalog from './components/Builder/WidgetCatalog';
import LayoutToolbar from './components/Builder/LayoutToolbar';
import { useLayoutStore } from './stores/useLayoutStore';
import SettingsPage from './components/Settings/SettingsPage';

const routeFromHash = (): Route => (window.location.hash.startsWith('#/builder') ? 'builder' : window.location.hash.startsWith('#/settings') ? 'settings' : 'workspace');

export default function App() {
  const [route, setRoute] = useState<Route>(routeFromHash);
  const { init, toast } = useLayoutStore();
  useEffect(() => { init(); }, [init]);
  useEffect(() => { const f = () => setRoute(routeFromHash()); window.addEventListener('hashchange', f); return () => window.removeEventListener('hashchange', f); }, []);
  const go = (r: Route) => { window.location.hash = r === 'workspace' ? '#/' : `#/${r}`; setRoute(r); };

  return (
    <div className="app">
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
