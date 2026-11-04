import { useEffect, useState } from 'react';
import { api } from '../../api';

interface BotCfg { enabled: boolean; token: string; token_set?: boolean; allowed_user_ids: string[]; control_user_ids: string[]; alert_chat_ids?: (string | number)[]; alert_channel_ids?: string[]; prefix?: string; guild_id?: string }
interface Custom { name: string; description?: string; type: 'template' | 'alias'; value: string }
interface Settings { telegram: BotCfg; discord: BotCfg; notify: Record<string, boolean>; custom_commands: Custom[] }
interface Resp { settings: Settings; status: Record<string, { running: boolean; error: string | null; username?: string | null; enabled: boolean }>; notify_kinds: string[]; commands: [string, string][]; variables: string[] }

const list = (v: (string | number)[] | undefined) => (v ?? []).join(', ');
const parse = (s: string) => s.split(/[\s,]+/).map((x) => x.trim()).filter(Boolean);
const NOTIFY_LABEL: Record<string, string> = { startup: 'App launched', payout_ready: 'Payout ready', PASSED: 'Eval passed', FAILED: 'Account blown', PARKED: 'Eval parked (cap full)', UNPARKED: 'Eval released', TARGET_HIT: 'Profit target hit', DAILY_LIMIT_HIT: 'Daily loss limit hit', PAYOUT: 'Payout recorded', kill_switch: 'Kill switch', graduation_alert: 'Graduation / cashout', route_error: 'Order routing error' };

function Field({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <label style={{ display: 'grid', gridTemplateColumns: '180px 1fr', gap: 10, alignItems: 'center', padding: '4px 0' }}>
      <span className="mut">{label}</span>
      <span>{children}{hint && <div className="mut" style={{ fontSize: 11, marginTop: 2 }}>{hint}</div>}</span>
    </label>
  );
}

export default function SettingsPage() {
  const [r, setR] = useState<Resp | null>(null);
  const [s, setS] = useState<Settings | null>(null);
  const [msg, setMsg] = useState(''); const [err, setErr] = useState(''); const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState({ command: 'gm', out: '' });

  const load = () => api<Resp>('/api/settings/bots').then((x) => { setR(x); setS(x.settings); }).catch((e) => setErr(String(e)));
  useEffect(() => { load(); }, []);
  if (!s || !r) return <div className="empty">{err || 'Loading settings…'}</div>;

  const bot = (k: 'telegram' | 'discord', patch: Partial<BotCfg>) => setS({ ...s, [k]: { ...s[k], ...patch } });
  const save = async () => {
    setBusy(true); setErr(''); setMsg('');
    try { const x = await api<Resp>('/api/settings/bots', { method: 'PUT', body: JSON.stringify(s) }); setR(x); setS(x.settings); setMsg('Saved. Bots relaunched and commands re-registered.'); }
    catch (e) { setErr(String(e)); } finally { setBusy(false); }
  };
  const test = async (body: object) => {
    try { const x = await api<{ preview?: string; sent?: string[] }>('/api/settings/bots/test', { method: 'POST', body: JSON.stringify(body) });
      if (x.preview !== undefined) setPreview((p) => ({ ...p, out: x.preview ?? '' }));
      if (x.sent) setMsg(`Test alert sent via: ${x.sent.join(', ') || 'no running bots'}`); load(); }
    catch (e) { setErr(String(e)); }
  };
  const cc = (i: number, patch: Partial<Custom>) => setS({ ...s, custom_commands: s.custom_commands.map((c, j) => (j === i ? { ...c, ...patch } : c)) });

  const botCard = (k: "telegram" | "discord", title: string, help: React.ReactNode) => {
    const c = s[k]; const st = r.status[k];
    return (
      <section key={title} className="card" style={{ height: "auto", padding: 14 }}>
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <b style={{ fontSize: 14 }}>{title}</b>
          <span className="pill" style={{ color: st?.running ? 'var(--good)' : c.enabled ? 'var(--warn)' : 'var(--muted)' }}>
            <span className="dot" />{st?.running ? `online${st.username ? ` · @${st.username}` : ''}` : c.enabled ? 'starting / error' : 'off'}</span>
        </div>
        {st?.error && <div className="neg" style={{ fontSize: 11.5, marginTop: 4 }}>{st.error}</div>}
        <div style={{ marginTop: 8 }}>
          <Field label="Enabled"><input type="checkbox" checked={c.enabled} onChange={(e) => bot(k, { enabled: e.target.checked })} aria-label={`${k} enabled`} /></Field>
          <Field label="Bot token" hint={c.token_set ? 'Saved on this machine only. Leave as-is to keep it; paste a new one to replace.' : 'Paste the token from ' + (k === 'telegram' ? '@BotFather' : 'the Discord Developer Portal → Bot')}>
            <input type="password" value={c.token} onChange={(e) => bot(k, { token: e.target.value })} style={{ width: '100%' }} aria-label={`${k} token`} autoComplete="off" /></Field>
          {k === 'telegram'
            ? <Field label="Alert chat IDs" hint="Where alerts go (your user ID for DMs, or a group ID)."><input value={list(c.alert_chat_ids)} onChange={(e) => bot(k, { alert_chat_ids: parse(e.target.value) })} style={{ width: '100%' }} /></Field>
            : <>
              <Field label="Alert channel IDs" hint="Right-click a channel → Copy Channel ID (Developer Mode on)."><input value={list(c.alert_channel_ids)} onChange={(e) => bot(k, { alert_channel_ids: parse(e.target.value) })} style={{ width: '100%' }} /></Field>
              <Field label="Server (guild) ID" hint="Optional: slash commands appear instantly in this server (global ones can take up to 1h)."><input value={c.guild_id ?? ''} onChange={(e) => bot(k, { guild_id: e.target.value })} /></Field>
              <Field label="Prefix" hint="For text commands like !status (needs the Message Content intent)."><input value={c.prefix ?? '!'} onChange={(e) => bot(k, { prefix: e.target.value || '!' })} style={{ width: 50 }} /></Field>
            </>}
          <Field label="Allowed users" hint="User IDs that may use read commands. Empty = anyone who can message the bot."><input value={list(c.allowed_user_ids)} onChange={(e) => bot(k, { allowed_user_ids: parse(e.target.value) })} style={{ width: '100%' }} /></Field>
          <Field label="Control users 🔒" hint="Only these IDs can run kill / flatten / resume / requested / paid / rejected. The bot replies with your ID if you're not listed."><input value={list(c.control_user_ids)} onChange={(e) => bot(k, { control_user_ids: parse(e.target.value) })} style={{ width: '100%' }} /></Field>
        </div>
        <div className="mut" style={{ fontSize: 11, marginTop: 6 }}>{help}</div>
      </section>
    );
  };

  return (
    <div style={{ padding: 16, display: 'grid', gap: 14, maxWidth: 1200 }}>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <h2 style={{ margin: 0, fontSize: 16, letterSpacing: '.08em' }}>SETTINGS · BOTS</h2>
        <div className="row">
          <button onClick={() => test({ send_alert: true })}>Send test alert</button>
          <button className="primary" onClick={save} disabled={busy}>{busy ? 'Saving…' : 'Save & relaunch bots'}</button>
        </div>
      </div>
      {msg && <div className="pos">{msg}</div>}
      {err && <div className="neg">{err}</div>}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(480px, 1fr))', gap: 14 }}>
        {botCard("telegram", "Telegram", <>Create a bot with @BotFather → /newbot, paste the token. Message your bot once, then send /help. Commands (incl. custom) appear in Telegram's “/” menu at launch.</>)}
        {botCard("discord", "Discord", <>Developer Portal → New Application → Bot → Reset Token. Enable <b>Message Content Intent</b>. Invite with scopes <span className="mono">bot applications.commands</span> and Send Messages permission. Slash commands register at launch.</>)}
      </div>

      <section className="card" style={{ height: "auto", padding: 14 }}>
        <b style={{ fontSize: 14 }}>Alerts</b>
        <div className="row" style={{ flexWrap: 'wrap', gap: 14, marginTop: 8 }}>
          {r.notify_kinds.map((k) => (
            <label key={k} className="row"><input type="checkbox" checked={!!s.notify[k]} onChange={(e) => setS({ ...s, notify: { ...s.notify, [k]: e.target.checked } })} />{NOTIFY_LABEL[k] ?? k}</label>))}
        </div>
      </section>

      <section className="card" style={{ height: "auto", padding: 14 }}>
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <b style={{ fontSize: 14 }}>Custom commands</b>
          <button onClick={() => setS({ ...s, custom_commands: [...s.custom_commands, { name: `cmd${s.custom_commands.length + 1}`, description: '', type: 'template', value: 'Fleet P&L today {fleet_day_pnl}' }] })}>+ Add command</button>
        </div>
        <div className="mut" style={{ fontSize: 11.5, margin: '6px 0' }}>
          <b>template</b>: text with live values, e.g. <span className="mono">{'Ready {ready_now_net} · blown {blown}'}</span>. <b>alias</b>: run built-in commands in order, separated by <span className="mono">;</span> (e.g. <span className="mono">status; ready; outcomes</span>).
          Variables: {r.variables.map((v) => <span key={v} className="mono" style={{ marginRight: 6 }}>{`{${v}}`}</span>)}
        </div>
        <table><thead><tr><th>Name</th><th>Description</th><th>Type</th><th>Value</th><th /></tr></thead>
          <tbody>{s.custom_commands.map((c, i) => (
            <tr key={i}>
              <td><input value={c.name} onChange={(e) => cc(i, { name: e.target.value })} style={{ width: 110 }} aria-label="Command name" /></td>
              <td><input value={c.description ?? ''} onChange={(e) => cc(i, { description: e.target.value })} style={{ width: 180 }} aria-label="Description" /></td>
              <td><select value={c.type} onChange={(e) => cc(i, { type: e.target.value as Custom['type'] })}><option value="template">template</option><option value="alias">alias</option></select></td>
              <td><input value={c.value} onChange={(e) => cc(i, { value: e.target.value })} style={{ width: '100%', minWidth: 340 }} aria-label="Value" /></td>
              <td><div className="row"><button className="ghost" onClick={() => { setPreview({ command: c.name, out: '' }); test({ command: c.name }); }} title="Preview (save first for new commands)">▶</button>
                <button className="ghost" onClick={() => setS({ ...s, custom_commands: s.custom_commands.filter((_, j) => j !== i) })} aria-label="Remove">✕</button></div></td>
            </tr>))}</tbody></table>
        <div className="row" style={{ marginTop: 10 }}>
          <span className="mut">Try any command:</span>
          <input value={preview.command} onChange={(e) => setPreview({ ...preview, command: e.target.value })} onKeyDown={(e) => e.key === 'Enter' && test({ command: preview.command })} style={{ width: 200 }} aria-label="Preview command" />
          <button onClick={() => test({ command: preview.command })}>Run preview</button>
        </div>
        {preview.out && <pre className="mono" style={{ background: '#05060A', border: '1px solid var(--line)', borderRadius: 6, padding: 10, whiteSpace: 'pre-wrap', fontSize: 12 }}>{preview.out}</pre>}
        <p className="h" style={{ marginTop: 10 }}>All commands registered at launch</p>
        <div className="mono mut" style={{ fontSize: 11.5 }}>{r.commands.map(([n, d]) => <div key={n}>/{n} — {d}</div>)}</div>
      </section>
    </div>
  );
}
