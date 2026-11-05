import { ColorType, createChart, CrosshairMode, DeepPartial, IChartApi, LineStyle, TimeChartOptions, UTCTimestamp } from "lightweight-charts";
import { cssVar } from "../hooks";

export const toTime = (ms: number) => Math.floor(ms / 1000) as UTCTimestamp;

export function baseOptions(height: number, opts: { timeVisible?: boolean; showTime?: boolean } = {}): DeepPartial<TimeChartOptions> {
  return {
    height,
    autoSize: true,
    layout: {
      background: { type: ColorType.Solid, color: "transparent" },
      textColor: cssVar("--data-axis"),
      fontFamily: cssVar("--font-num") || "JetBrains Mono",
      fontSize: 11,
      attributionLogo: false,
    },
    grid: {
      vertLines: { color: cssVar("--data-grid") },
      horzLines: { color: cssVar("--data-grid") },
    },
    rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.08, bottom: 0.06 } },
    timeScale: { borderVisible: false, timeVisible: !!opts.timeVisible, secondsVisible: false, visible: opts.showTime !== false,
      rightOffset: 2, fixLeftEdge: true, fixRightEdge: true },
    crosshair: {
      mode: CrosshairMode.Normal,
      vertLine: { color: cssVar("--ink-3"), style: LineStyle.Dashed, width: 1, labelBackgroundColor: cssVar("--panel-2") },
      horzLine: { color: cssVar("--ink-3"), style: LineStyle.Dashed, width: 1, labelBackgroundColor: cssVar("--panel-2") },
    },
    handleScale: { axisPressedMouseMove: { time: true, price: false } },
  };
}

/** Keep the visible range of two charts in sync (equity + drawdown, price + oscillator). */
export function syncCharts(a: IChartApi, b: IChartApi): () => void {
  let lock = false;
  const ab = (r: unknown) => {
    if (lock || !r) return;
    lock = true;
    b.timeScale().setVisibleLogicalRange(r as never);
    lock = false;
  };
  const ba = (r: unknown) => {
    if (lock || !r) return;
    lock = true;
    a.timeScale().setVisibleLogicalRange(r as never);
    lock = false;
  };
  a.timeScale().subscribeVisibleLogicalRangeChange(ab);
  b.timeScale().subscribeVisibleLogicalRangeChange(ba);
  return () => {
    a.timeScale().unsubscribeVisibleLogicalRangeChange(ab);
    b.timeScale().unsubscribeVisibleLogicalRangeChange(ba);
  };
}

export { createChart };
