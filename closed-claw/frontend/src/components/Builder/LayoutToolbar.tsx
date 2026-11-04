import { useRef, useState } from 'react';
import { useLayoutStore } from '../../stores/useLayoutStore';

export default function LayoutToolbar() {
  const { presets, saved, activeName, load, save, reset, deleteSaved, locked, setLocked, dirty, exportJson, importJson, backendOnline, flash } = useLayoutStore();
  const [name, setName] = useState('');
  const file = useRef<HTMLInputElement>(null);
  const isPreset = activeName in presets && !(activeName in saved);

  const doSave = async (n: string) => {
    if (!n.trim()) return;
    try { await save(n.trim()); setName(''); } catch (e) { flash(`Save failed: ${e}`); }
  };
  const doExport = () => {
    const blob = new Blob([exportJson()], { type: 'application/json' });
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob);
    a.download = `apollo-layout-${activeName.replace(/\W+/g, '_')}.json`; a.click(); URL.revokeObjectURL(a.href);
  };
  const doImport = async (f?: File) => {
    if (!f) return;
    try { await importJson(await f.text()); } catch (e) { flash(`Import failed: ${e}`); }
    if (file.current) file.current.value = '';
  };

  return (
    <div className="row" style={{ padding: '8px 12px', borderBottom: '1px solid var(--line)', background: '#0C0E14', flexWrap: 'wrap' }}>
      <span className="h">Preset</span>
      <select aria-label="Load layout" value={activeName} onChange={(e) => load(e.target.value)}>
        <optgroup label="Templates">{Object.keys(presets).map((n) => <option key={n} value={n}>{n}</option>)}</optgroup>
        {Object.keys(saved).length > 0 && <optgroup label="Saved">{Object.keys(saved).map((n) => <option key={n} value={n}>{n}{saved[n].source === 'mcp' ? ' (agent)' : ''}</option>)}</optgroup>}
      </select>
      <button onClick={() => doSave(activeName)} disabled={!dirty || isPreset} title={isPreset ? 'Templates are read-only: use Save as' : 'Save changes'}>Save</button>
      <input aria-label="New preset name" placeholder="Save as…" value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && doSave(name)} style={{ width: 150 }} />
      <button className="primary" onClick={() => doSave(name)} disabled={!name.trim()}>Save preset</button>
      <button onClick={reset} disabled={!dirty}>Reset</button>
      {!isPreset && <button className="ghost" onClick={() => deleteSaved(activeName)} title="Delete this saved layout">Delete</button>}
      <span style={{ width: 1, height: 20, background: 'var(--line)' }} />
      <button onClick={doExport}>Export JSON</button>
      <button onClick={() => file.current?.click()}>Import JSON</button>
      <input ref={file} type="file" accept="application/json,.json" hidden onChange={(e) => doImport(e.target.files?.[0])} />
      <div style={{ flex: 1 }} />
      {!backendOnline && <span className="warn" style={{ fontSize: 11 }}>offline: saving to this device only</span>}
      <div role="group" aria-label="Edit or lock mode" className="row" style={{ gap: 0 }}>
        <button onClick={() => setLocked(false)} aria-pressed={!locked} style={{ borderRadius: '5px 0 0 5px', color: !locked ? 'var(--accent)' : 'var(--muted)' }}>✎ Edit</button>
        <button onClick={() => setLocked(true)} aria-pressed={locked} style={{ borderRadius: '0 5px 5px 0', color: locked ? 'var(--warn)' : 'var(--muted)' }}>🔒 Lock</button>
      </div>
    </div>
  );
}
