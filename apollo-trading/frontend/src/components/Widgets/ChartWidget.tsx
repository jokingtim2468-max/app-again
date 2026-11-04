import { useEffect, useRef, useState } from 'react';
import {
  CandlestickSeries, ColorType, createChart, createSeriesMarkers, CrosshairMode, HistogramSeries, IChartApi,
  IPriceLine, ISeriesApi, ISeriesMarkersPluginApi, LineStyle, SeriesMarker, Time, UTCTimestamp,
} from 'lightweight-charts';
import { api, onEvent } from '../../api';

interface Bar { time: number; open: number; high: number; low: number; close: number; volume: number; delta: number }
interface Payload {
  source: string; bars: Bar[]; levels: Record<string, number>;
  positions: { account: string; qty: number; avg_price: number }[];
}
const TF_SEC: Record<string, number> = { '1m': 60, '5m': 300, '15m': 900 };
const LEVEL_STYLE: Record<string, [string, string]> = {
  session_high: ['#7AA2FF', 'S.HIGH'], session_low: ['#7AA2FF', 'S.LOW'], session_open: ['#7D859B', 'S.OPEN'],
  vwap: ['#F5C451', 'VWAP'], prior_high: ['#B48CFF', 'PDH'], prior_low: ['#B48CFF', 'PDL'], prior_close: ['#7D859B', 'PDC'],
};

export default function ChartWidget({ timeframe = '1m', showDelta = true, showLevels = true }: { timeframe?: string; showDelta?: boolean; showLevels?: boolean }) {
  const el = useRef<HTMLDivElement>(null);
  const [src, setSrc] = useState(''); const [err, setErr] = useState('');
  const refs = useRef<{ chart?: IChartApi; candles?: ISeriesApi<'Candlestick'>; vol?: ISeriesApi<'Histogram'>; lines: IPriceLine[]; markers?: ISeriesMarkersPluginApi<Time>; last?: Bar }>({ lines: [] });

  useEffect(() => {
    if (!el.current) return;
    const chart = createChart(el.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: '#12151E' }, textColor: '#7D859B', fontSize: 11, attributionLogo: false },
      grid: { vertLines: { color: '#1A1E2B' }, horzLines: { color: '#1A1E2B' } },
      rightPriceScale: { borderColor: '#212636' },
      timeScale: { borderColor: '#212636', timeVisible: true, secondsVisible: false, rightOffset: 6 },
      crosshair: { mode: CrosshairMode.Normal },
      localization: { priceFormatter: (p: number) => p.toFixed(1) },
    });
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: '#3DDC97', downColor: '#FF5D6C', wickUpColor: '#3DDC97', wickDownColor: '#FF5D6C', borderVisible: false,
      priceFormat: { type: 'price', precision: 1, minMove: 0.1 },
    });
    const vol = chart.addSeries(HistogramSeries, { priceScaleId: 'delta', priceFormat: { type: 'volume' }, lastValueVisible: false, priceLineVisible: false });
    chart.priceScale('delta').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    candles.priceScale().applyOptions({ scaleMargins: { top: 0.06, bottom: 0.2 } });
    refs.current = { chart, candles, vol, lines: [], markers: createSeriesMarkers(candles, []) };
    return () => { chart.remove(); refs.current = { lines: [] }; };
  }, []);

  useEffect(() => {
    let dead = false;
    const sec = TF_SEC[timeframe] ?? 60;
    const histo = (b: Bar) => showDelta
      ? { time: b.time as UTCTimestamp, value: b.delta, color: b.delta >= 0 ? 'rgba(61,220,151,.55)' : 'rgba(255,93,108,.55)' }
      : { time: b.time as UTCTimestamp, value: b.volume, color: 'rgba(122,162,255,.4)' };

    const draw = (d: Payload) => {
      const r = refs.current; if (!r.candles || !r.vol) return;
      r.candles.setData(d.bars.map((b) => ({ time: b.time as UTCTimestamp, open: b.open, high: b.high, low: b.low, close: b.close })));
      r.vol.setData(d.bars.map(histo));
      r.last = d.bars[d.bars.length - 1];
      r.lines.forEach((l) => r.candles!.removePriceLine(l)); r.lines = [];
      if (showLevels) for (const [k, v] of Object.entries(d.levels)) {
        const [color, title] = LEVEL_STYLE[k] ?? ['#555', k];
        r.lines.push(r.candles.createPriceLine({ price: v, color, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title }));
      }
      const master = d.positions[0];
      const marks: SeriesMarker<Time>[] = [];
      if (master && r.last) {
        const long = master.qty > 0;
        r.lines.push(r.candles.createPriceLine({ price: master.avg_price, color: long ? '#3DDC97' : '#FF5D6C', lineWidth: 2, lineStyle: LineStyle.Solid, axisLabelVisible: true, title: `${long ? 'LONG' : 'SHORT'} ${Math.abs(master.qty)} ×${d.positions.length}` }));
        marks.push({ time: r.last.time as UTCTimestamp, position: long ? 'belowBar' : 'aboveBar', color: long ? '#3DDC97' : '#FF5D6C', shape: long ? 'arrowUp' : 'arrowDown', text: `${Math.abs(master.qty)} @ ${master.avg_price.toFixed(1)}` });
      }
      r.markers?.setMarkers(marks);
    };

    const load = () => api<Payload>(`/api/market/bars?tf=${timeframe}&limit=800`)
      .then((d) => { if (!dead) { setSrc(d.source); setErr(''); draw(d); } })
      .catch((e) => !dead && setErr(String(e)));
    load().then(() => refs.current.chart?.timeScale().scrollToRealTime());
    const t = setInterval(load, 15000); // refresh levels / positions
    const off = onEvent((e) => {
      if (e.type !== 'trade') return;
      const r = refs.current; if (!r.candles || !r.vol) return;
      const price = Number(e.price), size = Number(e.size), ts = Math.floor(Number(e.time) / sec) * sec;
      const signed = e.side === 'B' ? size : -size;
      let b = r.last;
      if (!b || ts > b.time) b = { time: ts, open: price, high: price, low: price, close: price, volume: 0, delta: 0 };
      else if (ts < b.time) return;
      b = { ...b, high: Math.max(b.high, price), low: Math.min(b.low, price), close: price, volume: b.volume + size, delta: b.delta + signed };
      r.last = b;
      r.candles.update({ time: b.time as UTCTimestamp, open: b.open, high: b.high, low: b.low, close: b.close });
      r.vol.update(histo(b));
    });
    return () => { dead = true; clearInterval(t); off(); };
  }, [timeframe, showDelta, showLevels]);

  return (
    <div style={{ position: 'absolute', inset: 0 }}>
      <div ref={el} style={{ position: 'absolute', inset: 0 }} />
      <div className="mono" style={{ position: 'absolute', left: 8, top: 6, zIndex: 3, fontSize: 11, pointerEvents: 'none' }}>
        <span style={{ color: 'var(--text)' }}>MGC · {timeframe}</span>
        {src && <span className={src === 'SIM' ? 'warn' : 'pos'}> · {src}</span>}
        <span className="mut"> · {showDelta ? 'vol Δ' : 'volume'}</span>
      </div>
      {err && <div className="empty" style={{ position: 'absolute', inset: 0, zIndex: 4, background: '#12151Ecc' }}>Market data unavailable<br /><span className="mut">{err}</span></div>}
    </div>
  );
}
