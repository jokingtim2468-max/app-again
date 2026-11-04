import { ReactNode, useState } from 'react';

interface Props {
  title: string; children: ReactNode; locked: boolean; maximized: boolean;
  onClose: () => void; onToggleMax: () => void; settings?: ReactNode; badge?: ReactNode;
}

/** Universal card chrome: drag-handle header (#12151E, 1px #212636), maximize, settings, close. */
export default function WidgetContainer({ title, children, locked, maximized, onClose, onToggleMax, settings, badge }: Props) {
  const [showSettings, setShowSettings] = useState(false);
  return (
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
}
