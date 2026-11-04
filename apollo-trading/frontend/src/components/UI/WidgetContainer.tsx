import { ReactNode, useEffect, useState } from 'react';
import { createPortal } from 'react-dom';

interface Props {
  title: string; children: ReactNode; locked: boolean; maximized: boolean;
  onClose: () => void; onToggleMax: () => void; settings?: ReactNode; badge?: ReactNode;
}

/** Universal card chrome: drag-handle header (#12151E, 1px #212636), maximize, settings, close. */
export default function WidgetContainer({ title, children, locked, maximized, onClose, onToggleMax, settings, badge }: Props) {
  const [showSettings, setShowSettings] = useState(false);
  useEffect(() => {
    if (!maximized) return;
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && onToggleMax();
    window.addEventListener('keydown', esc); return () => window.removeEventListener('keydown', esc);
  }, [maximized, onToggleMax]);
  const card = (
    <div className={`card${maximized ? ' max' : ''}`}>
      <div className={`card-head${locked || maximized ? '' : ' draggable drag-handle'}`}>
        {!locked && !maximized && <span className="mut" aria-hidden style={{ letterSpacing: -2, fontSize: 11 }}>⋮⋮</span>}
        <span className="card-title">{title}</span>
        {badge}
        {settings && <button className="ghost no-drag" title="Widget settings" aria-label="Widget settings" aria-pressed={showSettings} onClick={() => setShowSettings((v) => !v)}>⚙</button>}
        <button className="ghost no-drag" title={maximized ? 'Restore' : 'Maximize'} aria-label={maximized ? 'Restore' : 'Maximize'} onClick={onToggleMax}>{maximized ? '❐' : '⛶'}</button>
        {!locked && <button className="ghost no-drag" title="Remove widget" aria-label="Remove widget" onClick={onClose}>✕</button>}
      </div>
      {showSettings && settings && <div className="settings no-drag">{settings}</div>}
      <div className="card-body no-drag">{children}</div>
    </div>
  );
  // grid items are CSS-transformed, which traps position:fixed; portal the maximized card to <body>
  return maximized ? <>{createPortal(card, document.body)}<div className="card empty mut">Maximized · Esc to restore</div></> : card;
}
