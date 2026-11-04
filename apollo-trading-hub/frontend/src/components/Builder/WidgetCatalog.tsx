import { useLayoutStore, WIDGET_META, WidgetType } from '../../stores/useLayoutStore';

const ICON: Record<WidgetType, string> = { 'widget-chart': '▁▃▅', 'widget-dom': '☰', 'widget-fleet': '⧉', 'widget-tape': '≋', 'widget-backtest': '∿', 'widget-terminal': '>_', 'widget-accounts': '⚇' };

export default function WidgetCatalog() {
  const { widgets, addWidget, locked } = useLayoutStore();
  return (
    <aside aria-label="Widget catalog" style={{ width: 268, flex: 'none', borderRight: '1px solid var(--line)', background: '#0C0E14', overflow: 'auto', padding: 10, display: 'grid', gap: 8, alignContent: 'start' }}>
      <p className="h" style={{ padding: '4px 2px' }}>Widget catalog</p>
      {(Object.keys(WIDGET_META) as WidgetType[]).map((t) => {
        const m = WIDGET_META[t];
        const count = widgets.filter((w) => w.type === t).length;
        return (
          <div key={t} style={{ background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 7, padding: 10, display: 'grid', gap: 6 }}>
            <div className="row" style={{ justifyContent: 'space-between' }}>
              <span className="row"><span className="mono" style={{ color: 'var(--accent)', width: 26 }}>{ICON[t]}</span><b style={{ fontSize: 12 }}>{m.name}</b></span>
              {count > 0 && <span className="pill mut">{count}</span>}
            </div>
            <div className="mut" style={{ fontSize: 11.5 }}>{m.desc}</div>
            <span className="mono mut" style={{ fontSize: 10.5 }}>{t} · default {m.w}×{m.h}</span>
            <div>
              <button className="primary" style={{ width: '100%' }} disabled={locked} onClick={() => addWidget(t)} title={locked ? 'Unlock to edit' : 'Add to workspace'}>+ Add to Workspace</button>
            </div>
          </div>
        );
      })}
    </aside>
  );
}
