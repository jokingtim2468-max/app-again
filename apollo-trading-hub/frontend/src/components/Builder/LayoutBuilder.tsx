import { useMemo, useState } from 'react';
import { Layout, Layouts, Responsive, WidthProvider } from 'react-grid-layout';
import 'react-grid-layout/css/styles.css';
import 'react-resizable/css/styles.css';
import { useLayoutStore, WIDGET_META, WidgetItem } from '../../stores/useLayoutStore';
import WidgetContainer from '../UI/WidgetContainer';
import ChartWidget from '../Widgets/ChartWidget';
import DomWidget from '../Widgets/DomWidget';
import FleetWidget from '../Widgets/FleetWidget';
import TapeWidget from '../Widgets/TapeWidget';
import BacktestWidget from '../Widgets/BacktestWidget';
import TerminalWidget from '../Widgets/TerminalWidget';
import AccountsWidget from '../Widgets/AccountsWidget';
import PayoutsWidget from '../Widgets/PayoutsWidget';

const Grid = WidthProvider(Responsive);
export const ROW_HEIGHT = 30;
const COLS = { lg: 12, md: 12, sm: 6, xs: 2 };
const BREAKPOINTS = { lg: 1200, md: 900, sm: 600, xs: 0 };

function renderWidget(w: WidgetItem) {
  const s = w.settings;
  switch (w.type) {
    case 'widget-chart': return <ChartWidget timeframe={String(s.timeframe ?? '1m')} showDelta={s.show_delta !== false} showLevels={s.show_levels !== false} />;
    case 'widget-dom': return <DomWidget levels={Number(s.levels ?? 12)} />;
    case 'widget-fleet': return <FleetWidget compact={Boolean(s.compact)} />;
    case 'widget-tape': return <TapeWidget minSize={Number(s.min_size ?? 10)} blockSize={Number(s.block_size ?? 10)} />;
    case 'widget-backtest': return <BacktestWidget />;
    case 'widget-terminal': return <TerminalWidget />;
    case 'widget-accounts': return <AccountsWidget />;
    case 'widget-payouts': return <PayoutsWidget />;
  }
}

function SettingsEditor({ w }: { w: WidgetItem }) {
  const update = useLayoutStore((st) => st.updateSettings);
  const s = w.settings;
  switch (w.type) {
    case 'widget-chart': return (<>
      <label className="row">Timeframe <select value={String(s.timeframe ?? '1m')} onChange={(e) => update(w.i, { timeframe: e.target.value })}><option>1m</option><option>5m</option><option>15m</option></select></label>
      <label className="row"><input type="checkbox" checked={s.show_delta !== false} onChange={(e) => update(w.i, { show_delta: e.target.checked })} /> Volume delta</label>
      <label className="row"><input type="checkbox" checked={s.show_levels !== false} onChange={(e) => update(w.i, { show_levels: e.target.checked })} /> Session levels</label>
    </>);
    case 'widget-dom': return <label className="row">Levels each side <input type="number" min={5} max={40} value={Number(s.levels ?? 12)} onChange={(e) => update(w.i, { levels: +e.target.value })} style={{ width: 60 }} /></label>;
    case 'widget-fleet': return <label className="row"><input type="checkbox" checked={Boolean(s.compact)} onChange={(e) => update(w.i, { compact: e.target.checked })} /> Compact strip</label>;
    case 'widget-tape': return (<>
      <label className="row">Min size <input type="number" min={1} value={Number(s.min_size ?? 10)} onChange={(e) => update(w.i, { min_size: +e.target.value })} style={{ width: 60 }} /></label>
      <label className="row">Block highlight ≥ <input type="number" min={1} value={Number(s.block_size ?? 10)} onChange={(e) => update(w.i, { block_size: +e.target.value })} style={{ width: 60 }} /></label>
    </>);
    default: return null;
  }
}

/** react-grid-layout canvas shared by the Workspace (runtime) and the Builder (studio, with guides). */
export default function LayoutBuilder({ studio = false }: { studio?: boolean }) {
  const { widgets, locked, maximized, setWidgets, removeWidget, setMax } = useLayoutStore();
  const [bp, setBp] = useState('lg');
  const editable = !locked;

  const layouts: Layouts = useMemo(() => ({
    lg: widgets.map((w) => ({ i: w.i, x: w.x, y: w.y, w: w.w, h: w.h, minW: WIDGET_META[w.type].minW, minH: WIDGET_META[w.type].minH })),
  }), [widgets]);

  const onChange = (cur: Layout[]) => {
    if (bp !== 'lg' && bp !== 'md') return; // narrow breakpoints are derived views; don't overwrite the 12-col layout
    const byId = new Map(cur.map((l) => [l.i, l]));
    setWidgets(widgets.map((w) => { const l = byId.get(w.i); return l ? { ...w, x: l.x, y: l.y, w: l.w, h: l.h } : w; }));
  };

  if (!widgets.length) {
    return <div className="empty" style={{ height: '70vh' }}>Empty workspace.<br /><span className="mut">Open the Builder tab and add widgets from the catalog.</span></div>;
  }
  return (
    <div className={studio && editable ? 'grid-guides' : undefined}
      style={studio ? { minHeight: '100%', backgroundSize: `calc((100% - 8px) / 12) ${ROW_HEIGHT + 8}px`, backgroundPosition: '4px 4px' } : { minHeight: '100%' }}>
      <Grid
        className="layout" layouts={layouts} breakpoints={BREAKPOINTS} cols={COLS} rowHeight={ROW_HEIGHT} margin={[8, 8]} containerPadding={[8, 8]}
        isDraggable={editable} isResizable={editable} draggableHandle=".drag-handle" draggableCancel=".no-drag"
        compactType={null} preventCollision resizeHandles={['se', 'e', 's']}
        onBreakpointChange={(b) => setBp(b)} onLayoutChange={onChange}
      >
        {widgets.map((w) => (
          <div key={w.i} data-widget={w.type}>
            <WidgetContainer
              title={`${WIDGET_META[w.type].name}${w.type === 'widget-chart' ? ` · ${w.settings.timeframe ?? '1m'}` : ''}`}
              locked={locked} maximized={maximized === w.i}
              onClose={() => removeWidget(w.i)} onToggleMax={() => setMax(maximized === w.i ? null : w.i)}
              settings={['widget-chart', 'widget-dom', 'widget-fleet', 'widget-tape'].includes(w.type) ? <SettingsEditor w={w} /> : undefined}
            >
              {renderWidget(w)}
            </WidgetContainer>
          </div>
        ))}
      </Grid>
    </div>
  );
}
