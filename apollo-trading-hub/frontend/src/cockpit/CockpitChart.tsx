import { useEffect, useRef, useState } from 'react';
import {
  CandlestickSeries, ColorType, createChart, createSeriesMarkers, CrosshairMode, IChartApi, IPriceLine, ISeriesApi,
  ISeriesMarkersPluginApi, LineSeries, LineStyle, SeriesMarker, Time, UTCTimestamp,
} from 'lightweight-charts';
import { api, onEvent } from '../api';
import { useCockpit } from './store';

interface Bar { time: number; open: number; high: number; low: number; close: number; volume: number }
const TF: Record<string, number> = { '1m': 60, '5m': 300, '15m': 900 };

/** Candles + Asian high/low, session VWAP, unfilled FVGs, the latest liquidity sweep and the open trade's entry/SL/TP. */
export default function CockpitChart({ height = 380 }: { height?: number }) {
  const el = useRef<HTMLDivElement>(null);
  const [tf, setTf] = useState('5m');
  const intel = useCockpit((s) => s.intel);
  const r = useRef<{ chart?: IChartApi; c?: ISeriesApi<'Candlestick'>; vwap?: ISeriesApi<'Line'>; lines: IPriceLine[]; mk?: ISeriesMarkersPluginApi<Time>; last?: Bar }>({ lines: [] });

  useEffect(() => {
    if (!el.current) return;
    const chart = createChart(el.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: '#0F172A' }, textColor: '#94A3B8', fontSize: 11, attributionLogo: false },
      grid: { vertLines: { color: '#162036' }, horzLines: { color: '#162036' } },
      rightPriceScale: { borderColor: '#1E293B' }, timeScale: { borderColor: '#1E293B', timeVisible: true, rightOffset: 6 },
      crosshair: { mode: CrosshairMode.Normal }, localization: { priceFormatter: (p: number) => p.toFixed(2) },
    });
    const c = chart.addSeries(CandlestickSeries, { upColor: '#10B981', downColor: '#F43F5E', wickUpColor: '#10B981', wickDownColor: '#F43F5E', borderVisible: false });
    const vwap = chart.addSeries(LineSeries, { color: '#F59E0B', lineWidth: 1, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });
    r.current = { chart, c, vwap, lines: [], mk: createSeriesMarkers(c, []) };
    return () => { chart.remove(); r.current = { lines: [] }; };
  }, []);

  useEffect(() => {  // history + rolling VWAP for the timeframe
    let dead = false;
    api<{ bars: Bar[] }>(`/api/market/bars?tf=${tf}&limit=400`).then((d) => {
      if (dead || !r.current.c) return;
      r.current.c.setData(d.bars.map((b) => ({ ...b, time: b.time as UTCTimestamp })));
      let pv = 0, v = 0, day = -1;
      r.current.vwap!.setData(d.bars.map((b) => {
        const et = new Date((b.time - 5 * 3600) * 1000); const sess = et.getUTCHours() >= 18 ? et.getUTCDate() + 1 : et.getUTCDate();
        if (sess !== day) { day = sess; pv = 0; v = 0; }
        const w = Math.max(b.volume, 1); pv += ((b.high + b.low + b.close) / 3) * w; v += w;
        return { time: b.time as UTCTimestamp, value: pv / v };
      }));
      r.current.last = d.bars[d.bars.length - 1];
    }).catch(() => undefined);
    const off = onEvent((e) => {  // live ticks into the forming bar
      if (e.type !== 'trade' || !r.current.c) return;
      const p = Number(e.price), sec = TF[tf], t = Math.floor(Number(e.time) / sec) * sec;
      const l = r.current.last;
      const b = l && l.time === t ? { ...l, high: Math.max(l.high, p), low: Math.min(l.low, p), close: p } : { time: t, open: p, high: p, low: p, close: p, volume: 0 };
      r.current.last = b;
      r.current.c.update({ ...b, time: b.time as UTCTimestamp });
    });
    return () => { dead = true; off(); };
  }, [tf]);

  useEffect(() => {  // overlays from the intel snapshot
    const { c, mk } = r.current;
    if (!c || !intel) return;
    r.current.lines.forEach((l) => c.removePriceLine(l));
    const L: IPriceLine[] = [];
    const add = (price: number | undefined | null, color: string, title: string, style = LineStyle.Dashed, width: 1 | 2 = 1) => {
      if (price != null) L.push(c.createPriceLine({ price, color, title, lineStyle: style, lineWidth: width, axisLabelVisible: true }));
    };
    add(intel.asian.asian_high, '#A78BFA', 'ASIA H'); add(intel.asian.asian_low, '#A78BFA', 'ASIA L');
    intel.confluence.fvgs.slice(-3).forEach((g) => {
      const col = g.side === 'bull' ? '#10B98199' : '#F43F5E99';
      add(g.high, col, `FVG ${g.side === 'bull' ? '▲' : '▼'}`, LineStyle.Dotted); add(g.low, col, '', LineStyle.Dotted);
    });
    const t = intel.engine.open_trade;
    if (t) {
      add(t.entry, '#22D3EE', `ENTRY ${t.side.toUpperCase()}`, LineStyle.Solid, 2);
      add(t.sl, t.be ? '#F59E0B' : '#F43F5E', t.be ? 'BE STOP' : 'SL', LineStyle.Solid);
      add(t.tp, '#10B981', 'TP', LineStyle.Solid);
    }
    intel.engine.pending_limits.forEach((o) => add(o.price, '#60A5FA', `${o.action.toUpperCase()} LMT`, LineStyle.LargeDashed));
    r.current.lines = L;
    const sw = intel.confluence.sweep;
    const m: SeriesMarker<Time>[] = sw.time ? [{
      time: (Math.floor(sw.time / TF[tf]) * TF[tf]) as UTCTimestamp, position: sw.side === 'long' ? 'belowBar' : 'aboveBar',
      color: sw.side === 'long' ? '#10B981' : '#F43F5E', shape: sw.side === 'long' ? 'arrowUp' : 'arrowDown', text: sw.asian ? 'ASIA SWEEP' : 'SWEEP',
    }] : [];
    mk?.setMarkers(m);
  }, [intel, tf]);

  return (
    <div>
      <div className="row" style={{ marginBottom: 8 }}>
        {Object.keys(TF).map((k) => <button key={k} className={k === tf ? 'primary' : 'ghost'} onClick={() => setTf(k)}>{k.toUpperCase()}</button>)}
        <span className="sub" style={{ marginLeft: 'auto' }}>
          <span style={{ color: '#A78BFA' }}>━ Asian H/L</span> · <span style={{ color: '#F59E0B' }}>━ VWAP</span> · <span style={{ color: '#10B981' }}>┅ FVG</span> · <span style={{ color: '#22D3EE' }}>━ Entry</span>
        </span>
      </div>
      <div ref={el} style={{ height }} />
    </div>
  );
}
