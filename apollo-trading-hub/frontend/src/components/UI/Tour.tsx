import { useEffect, useLayoutEffect, useState } from 'react';

export interface TourStep { target?: string; title: string; body: string; before?: () => void }

/** Lightweight guided tour: dims the page, highlights the target element and explains it. */
export default function Tour({ steps, onClose, storageKey }: { steps: TourStep[]; onClose: () => void; storageKey?: string }) {
  const [i, setI] = useState(0);
  const [box, setBox] = useState<DOMRect | null>(null);
  const step = steps[i];

  useEffect(() => { step.before?.(); }, [i]); // eslint-disable-line react-hooks/exhaustive-deps
  useLayoutEffect(() => {
    let raf = 0; let tries = 0;
    const find = () => {
      const el = step.target ? document.querySelector(step.target) : null;
      if (el) { el.scrollIntoView({ block: 'center', behavior: 'smooth' }); setTimeout(() => setBox(el.getBoundingClientRect()), 250); }
      else if (step.target && tries++ < 20) raf = window.setTimeout(find, 100);
      else setBox(null);
    };
    find();
    return () => clearTimeout(raf);
  }, [i, step.target]);
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') finish(); if (e.key === 'ArrowRight') next(); if (e.key === 'ArrowLeft') setI((x) => Math.max(0, x - 1)); };
    window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k);
  });
  const finish = () => { try { if (storageKey) localStorage.setItem(storageKey, '1'); } catch { /* storage blocked */ } onClose(); };
  const next = () => (i < steps.length - 1 ? setI(i + 1) : finish());

  const pad = 6;
  const card: React.CSSProperties = box
    ? { top: Math.min(window.innerHeight - 230, box.bottom + 12), left: Math.max(12, Math.min(window.innerWidth - 380, box.left)) }
    : { top: '35%', left: '50%', transform: 'translateX(-50%)' };
  return (
    <div role="dialog" aria-label="Tutorial" style={{ position: 'fixed', inset: 0, zIndex: 200 }}>
      <svg style={{ position: 'fixed', inset: 0, width: '100%', height: '100%' }} onClick={finish} aria-hidden>
        <defs><mask id="tour-mask"><rect width="100%" height="100%" fill="#fff" />
          {box && <rect x={box.left - pad} y={box.top - pad} width={box.width + pad * 2} height={box.height + pad * 2} rx="8" fill="#000" />}</mask></defs>
        <rect width="100%" height="100%" fill="rgba(5,6,10,.72)" mask="url(#tour-mask)" />
        {box && <rect x={box.left - pad} y={box.top - pad} width={box.width + pad * 2} height={box.height + pad * 2} rx="8" fill="none" stroke="#6CF0C2" strokeWidth="2" />}
      </svg>
      <div style={{ position: 'fixed', width: 360, background: '#12151E', border: '1px solid #6CF0C2', borderRadius: 10, padding: 14, boxShadow: '0 20px 60px #000c', ...card }}>
        <div className="mut" style={{ fontSize: 11 }}>Step {i + 1} of {steps.length}</div>
        <b style={{ display: 'block', margin: '4px 0 6px', fontSize: 14 }}>{step.title}</b>
        <div style={{ fontSize: 12.5, lineHeight: 1.5, whiteSpace: 'pre-line' }}>{step.body}</div>
        <div className="row" style={{ justifyContent: 'space-between', marginTop: 12 }}>
          <button className="ghost" onClick={finish}>Skip tutorial</button>
          <div className="row">
            {i > 0 && <button onClick={() => setI(i - 1)}>Back</button>}
            <button className="primary" onClick={next}>{i < steps.length - 1 ? 'Next' : 'Done'}</button>
          </div>
        </div>
      </div>
    </div>
  );
}
