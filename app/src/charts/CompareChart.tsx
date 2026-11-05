import { useEffect, useRef } from "react";
import { pct } from "../format";
import { cssVar, useThemeKey } from "../hooks";
import type { RunResult } from "../types";
import { baseOptions, createChart, toTime } from "./lw";

export const COMPARE_VARS = ["--data-1", "--data-2", "--data-3", "--data-4"];

/** Equity of several runs indexed to % return so they share one axis. */
export function CompareChart({ runs }: { runs: RunResult[] }) {
  const el = useRef<HTMLDivElement>(null);
  const theme = useThemeKey();
  useEffect(() => {
    if (!el.current) return;
    const chart = createChart(el.current, baseOptions(360, { timeVisible: false }));
    chart.applyOptions({ rightPriceScale: { minimumWidth: 70 } });
    runs.slice(0, 4).forEach((r, k) => {
      const base = r.settings.initial_capital as number;
      const s = chart.addLineSeries({ color: cssVar(COMPARE_VARS[k]), lineWidth: 2, priceLineVisible: false,
        priceFormat: { type: "custom", formatter: (v: number) => pct(v, { sign: true, d: 0 }) } });
      const seen = new Set<number>();
      s.setData(r.equity.flatMap((v, i) => {
        const t = toTime(r.bars.time[i]);
        if (seen.has(t)) return [];
        seen.add(t);
        return [{ time: t, value: (v / base - 1) * 100 }];
      }));
    });
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [runs, theme]);
  return <div ref={el} style={{ height: 360 }} />;
}
