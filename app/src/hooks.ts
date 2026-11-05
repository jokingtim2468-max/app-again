import { useEffect, useRef, useState } from "react";

/** Read a CSS custom property (theme-aware chart colours). */
export function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** Re-render when the theme attribute changes so charts can re-read their colours. */
export function useThemeKey(): string {
  const [k, setK] = useState(document.documentElement.dataset.theme ?? "dark");
  useEffect(() => {
    const obs = new MutationObserver(() => setK(document.documentElement.dataset.theme ?? "dark"));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => obs.disconnect();
  }, []);
  return k;
}

/** Count from 0 to `target` once per `key` (the run id): the results-arrive moment. */
export function useCountUp(target: number | null | undefined, key: string, ms = 650): number | null {
  const [v, setV] = useState<number | null>(target ?? null);
  const raf = useRef(0);
  useEffect(() => {
    if (target == null || !Number.isFinite(target)) { setV(target ?? null); return; }
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) { setV(target); return; }
    const t0 = performance.now();
    const tick = (t: number) => {
      const p = Math.min(1, (t - t0) / ms);
      const e = 1 - Math.pow(1 - p, 3);
      setV(target * e);
      if (p < 1) raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return v;
}

export function useLocal<T>(key: string, initial: T): [T, (v: T) => void] {
  const [v, setV] = useState<T>(() => {
    try {
      const s = localStorage.getItem(key);
      return s ? { ...initial, ...JSON.parse(s) } : initial;
    } catch {
      return initial;
    }
  });
  const set = (nv: T) => {
    setV(nv);
    try { localStorage.setItem(key, JSON.stringify(nv)); } catch { /* storage unavailable */ }
  };
  return [v, set];
}
