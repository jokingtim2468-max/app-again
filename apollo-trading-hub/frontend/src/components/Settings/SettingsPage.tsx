import { useEffect, useRef, useState } from 'react';
import { api } from '../../api';
import Tour, { TourStep } from '../UI/Tour';

interface BotCfg { enabled: boolean; token: string; token_set?: boolean; allowed_user_ids: string[]; control_user_ids: string[]; alert_chat_ids?: (string | number)[]; alert_channel_ids?: string[]; prefix?: string; guild_id?: string }
interface Custom { name: string; description?: string; type: 'template' | 'alias'; value: string }
interface Settings { mode: 'own' | 'relay'; relay: { url: string; access_key: string; install_id: string; secret: string }; telegram: BotCfg; discord: BotCfg; notify: Record<string, boolean>; custom_commands: Custom[] }
interface Dest { name?: string; kinds: string[] }
interface Link { id: string; platform: 'discord' | 'telegram'; chat_id: string; guild_id?: string | null; title: string; linked_by: string; linked_by_name?: string; linked_at: string; destinations: Record<string, Dest> }
interface BotStatus { running: boolean; error: string | null; username?: string | null; enabled?: boolean; invite_url?: string | null }
interface Status { mode: string; telegram?: BotStatus; discord?: BotStatus; relay?: { running: boolean; error: string | null; info?: { discord?: { online: boolean; invite_url: string | null }; telegram?: { online: boolean; username: string | null } } } }
interface Resp { settings: Settings; status: Status; links: Link[]; notify_kinds: string[]; commands: [string, string][]; variables: string[] }

const list = (v: (string | number)[] | undefined) => (v ?? []).join(', ');
const parse = (s: string) => s.split(/[\s,]+/).map((x) => x.trim()).filter(Boolean);
const LABEL: Record<string, string> = { startup: 'App launched', payout_ready: 'Payout ready', PASSED: 'Eval passed', FAILED: 'Account blown', PARKED: 'Eval parked', UNPARKED: 'Eval released', TARGET_HIT: 'Target hit', DAILY_LIMIT_HIT: 'Daily loss limit', PAYOUT: 'Payout recorded', kill_switch: 'Kill switch', graduation_alert: 'Graduation', route_error: 'Order errors' };
const TOUR_KEY = 'apollo.tour.settings';

function Steps({ items }: { items: React.ReactNode[] }) {
  return <ol style={{ margin: '6px 0 0', paddingLeft: 20, lineHeight: 1.65, fontSize: 12.5 }}>{items.map((x, i) => <li key={i}>{x}</li>)}</ol>;
}
function Field({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <label style={{ display: 'grid', gridTemplateColumns: '170px 1fr', gap: 10, alignItems: 'center', padding: '4px 0' }}>
      <span className="mut">{label}</span>
      <span>{children}{hint && <div className="mut" style={{ fontSize: 11, marginTop: 2 }}>{hint}</div>}</span>
    </label>
  );
}
function Section({ title, tour, children, right }: { title: string; tour: string; children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <section data-tour={tour} className="card" style={{ height: 'auto', padding: 14 }}>
      <div className="row" style={{ justifyContent: 'space-between', marginBottom: 6 }}><b style={{ fontSize: 14 }}>{title}</b>{right}</div>
      {children}
    </section>
  );
}

export default function SettingsPage() {
  const [r, setR] = useState<Resp | null>(null);
  const [s, setS] = useState<Settings | null>(null);
  const [msg, setMsg] = useState(''); const [err, setErr] = useState(''); const [busy, setBusy] = useState(false);
  const [code, setCode] = useState<{ code: string; expires: number; control: boolean } | null>(null);
  const [grant, setGrant] = useState(true);
  const [channels, setChannels] = useState<Record<string, { id: string; name: string }[]>>({});
  const [dirtyLinks, setDirtyLinks] = useState<Record<string, Link>>({});
  const [preview, setPreview] = useState({ command: 'gm', out: '' });
  const [tour, setTour] = useState(false);
  const [now, setNow] = useState(Date.now());
  const linkCount = useRef<number | null>(null);

  const load = () => api<Resp>('/api/settings/bots').then((x) => {
    setR(x); setS((cur) => cur ?? x.settings);
    if (linkCount.current !== null && x.links.length > linkCount.current) { setMsg(`✅ Linked: ${x.links[x.links.length - 1].title}. Choose where its alerts go in step 4.`); setCode(null); }
    linkCount.current = x.links.length;
  }).catch((e) => setErr(String(e)));
  useEffect(() => { load(); try { if (!localStorage.getItem(TOUR_KEY)) setTimeout(() => setTour(true), 600); } catch { /* storage blocked */ } }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (!code) return; const t = setInterval(() => { setNow(Date.now()); load(); }, 2500); return () => clearInterval(t); }, [code]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!s || !r) return <div className="empty">{err || 'Loading settings…'}</div>;

  const st = r.status;
  const relayInfo = st.relay?.info;
  const discordInvite = s.mode === 'relay' ? relayInfo?.discord?.invite_url : st.discord?.invite_url;
  const tgUser = s.mode === 'relay' ? relayInfo?.telegram?.username : st.telegram?.username;
  const connected = s.mode === 'relay' ? !!st.relay?.running : !!(st.telegram?.running || st.discord?.running);

  const bot = (k: 'telegram' | 'discord', patch: Partial<BotCfg>) => setS({ ...s, [k]: { ...s[k], ...patch } });
  const save = async () => {
    setBusy(true); setErr(''); setMsg('');
    try { const x = await api<Resp>('/api/settings/bots', { method: 'PUT', body: JSON.stringify(s) }); setR(x); setS(x.settings); setMsg('Saved. Bots relaunched and every command re-registered.'); }
    catch (e) { setErr(String(e)); } finally { setBusy(false); }
  };
  const genCode = async () => {
    setErr('');
    try { const c = await api<{ code: string; expires_in: number; control: boolean }>('/api/settings/bots/code', { method: 'POST', body: JSON.stringify({ grant_control: grant }) });
      setCode({ code: c.code, expires: Date.now() + c.expires_in * 1000, control: c.control }); linkCount.current = r.links.length; }
    catch (e) { setErr(String(e)); }
  };
  const test = async (body: object) => {
    try { const x = await api<{ preview?: string; sent?: string[] }>('/api/settings/bots/test', { method: 'POST', body: JSON.stringify(body) });
      if (x.preview !== undefined) setPreview((p) => ({ ...p, out: x.preview ?? '' }));
      if (x.sent) setMsg(x.sent.length ? `Test alert sent to ${x.sent.length} destination(s).` : 'No destinations yet: link a chat in step 3 first.'); }
    catch (e) { setErr(String(e)); }
  };
  const link = (l: Link) => dirtyLinks[l.id] ?? l;
  const setDest = (l: Link, cid: string, name: string, kind: string | null, on: boolean) => {
    const cur = link(l); const d = { ...cur.destinations };
    const row = d[cid] ?? { name, kinds: [] };
    const kinds = kind === null ? (on ? [...r.notify_kinds] : []) : on ? [...new Set([...row.kinds, kind])] : row.kinds.filter((k) => k !== kind);
    if (kinds.length) d[cid] = { name, kinds }; else delete d[cid];
    setDirtyLinks({ ...dirtyLinks, [l.id]: { ...cur, destinations: d } });
  };
  const saveLink = async (l: Link) => {
    try { await api(`/api/settings/bots/links/${encodeURIComponent(l.id)}`, { method: 'PUT', body: JSON.stringify({ destinations: link(l).destinations }) });
      const rest = { ...dirtyLinks }; delete rest[l.id]; setDirtyLinks(rest); setMsg(`Alert destinations saved for ${l.title}.`); load(); }
    catch (e) { setErr(String(e)); }
  };
  const unlink = async (l: Link) => { if (!window.confirm(`Unlink ${l.title}? Alerts and commands there will stop.`)) return; await api(`/api/settings/bots/links/${encodeURIComponent(l.id)}`, { method: 'DELETE' }); load(); };
  const loadChannels = async (l: Link) => {
    try { setChannels({ ...channels, [l.id]: await api<{ id: string; name: string }[]>(`/api/settings/bots/channels?guild_id=${l.guild_id}`) }); }
    catch (e) { setErr(String(e)); }
  };
  const cc = (i: number, patch: Partial<Custom>) => setS({ ...s, custom_commands: s.custom_commands.map((c, j) => (j === i ? { ...c, ...patch } : c)) });
  const left = code ? Math.max(0, Math.round((code.expires - now) / 1000)) : 0;

  const tourSteps: TourStep[] = [
    { title: 'Welcome to Apollo bots', body: 'Get alerts and run commands from Discord and Telegram. This tour takes about a minute. Use ← → or the buttons.' },
    { target: '[data-tour="mode"]', title: '1. Pick how you connect', body: 'Shared Apollo bot (recommended): just add the Apollo bot to your server, nothing to create.\nMy own bot: create a bot yourself and paste its token.' },
    { target: '[data-tour="setup"]', title: '2. Follow the steps', body: 'Every step is written out here, with buttons to invite the bot to Discord or open it in Telegram. Click Save & relaunch when done.' },
    { target: '[data-tour="connect"]', title: '3. Link your server or chat', body: 'Click “Generate code”, then in Discord type /verify CODE in the channel you want, or send it to the bot in Telegram. The app connects by itself.' },
    { target: '[data-tour="destinations"]', title: '4. Choose where alerts go', body: 'After linking, pick which channels get which alerts: payouts in one channel, blown accounts in another, or everything in one place.' },
    { target: '[data-tour="alerts"]', title: '5. Turn alert types on/off', body: 'Master switches for each alert type across all destinations.' },
    { target: '[data-tour="access"]', title: '6. Who can use the bot', body: 'People who verify are added automatically. Only “Control users” can run kill, flatten or payout commands.' },
    { target: '[data-tour="custom"]', title: '7. Make your own commands', body: 'Templates show live numbers ({ready_now_net}, {blown}…). Aliases run several commands at once. They are registered every time Apollo launches.' },
    { target: '[data-tour="help"]', title: 'Replay any time', body: 'Click “? Tutorial” to see this again. You are all set.' },
  ];

  return (
    <div style={{ padding: 16, display: 'grid', gap: 14, maxWidth: 1240 }}>
      {tour && <Tour steps={tourSteps} storageKey={TOUR_KEY} onClose={() => setTour(false)} />}
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <div className="row">
          <h2 style={{ margin: 0, fontSize: 16, letterSpacing: '.08em' }}>SETTINGS · BOTS & ALERTS</h2>
          <span className="pill" style={{ color: connected ? 'var(--good)' : 'var(--muted)' }}><span className="dot" />{connected ? 'connected' : 'not connected'}</span>
        </div>
        <div className="row">
          <button data-tour="help" onClick={() => setTour(true)}>? Tutorial</button>
          <button onClick={() => test({ send_alert: true })}>Send test alert</button>
          <button className="primary" onClick={save} disabled={busy}>{busy ? 'Saving…' : 'Save & relaunch'}</button>
        </div>
      </div>
      {msg && <div className="pos">{msg}</div>}
      {err && <div className="neg">{err}</div>}

      <Section title="1 · How do you want to connect?" tour="mode">
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
          {([['relay', 'Shared Apollo bot', 'Recommended. Add the Apollo bot to your Discord server or open it in Telegram, then /verify. No bot to create, no tokens.'],
            ['own', 'My own bot', 'Create your own Discord and/or Telegram bot and paste its token. The bot runs inside this app.']] as const).map(([k, t, d]) => (
            <button key={k} onClick={() => setS({ ...s, mode: k })} style={{ textAlign: 'left', padding: 12, borderColor: s.mode === k ? 'var(--accent)' : 'var(--line-2)', background: s.mode === k ? '#0F2A22' : undefined }}>
              <b>{s.mode === k ? '◉' : '○'} {t}</b><div className="mut" style={{ fontSize: 12, marginTop: 4 }}>{d}</div>
            </button>))}
        </div>
      </Section>

      <Section title={s.mode === 'relay' ? '2 · Set up the shared Apollo bot' : '2 · Set up your own bot'} tour="setup">
        {s.mode === 'relay' ? (<>
          <Field label="Apollo bot server URL" hint="Address of the Apollo Bot Relay, e.g. https://bot.yourdomain.com (from whoever runs the Apollo bot)."><input value={s.relay.url} onChange={(e) => setS({ ...s, relay: { ...s.relay, url: e.target.value } })} style={{ width: '100%' }} aria-label="Relay URL" /></Field>
          <Field label="Access key" hint="Only if the relay owner set one."><input type="password" value={s.relay.access_key} onChange={(e) => setS({ ...s, relay: { ...s.relay, access_key: e.target.value } })} aria-label="Relay access key" autoComplete="off" /></Field>
          <div className="row" style={{ margin: '6px 0' }}>
            <span className="pill" style={{ color: st.relay?.running ? 'var(--good)' : 'var(--muted)' }}><span className="dot" />{st.relay?.running ? 'connected to the Apollo bot server' : 'not connected'}</span>
            {st.relay?.error && <span className="neg" style={{ fontSize: 11.5 }}>{st.relay.error}</span>}
          </div>
          <Steps items={[
            <>Enter the URL above and click <b>Save & relaunch</b>. The status should turn green.</>,
            <>Discord: {discordInvite ? <a href={discordInvite} target="_blank" rel="noreferrer"><button className="primary">Add Apollo bot to my server ↗</button></a> : <span className="mut">(invite button appears once connected)</span>}, choose your server and click Authorize.</>,
            <>Telegram: {tgUser ? <a href={`https://t.me/${tgUser}`} target="_blank" rel="noreferrer"><button className="primary">Open @{tgUser} ↗</button></a> : <span className="mut">(button appears once connected)</span>}, press Start (or add it to a group).</>,
            <>Go to step 3 to link it with a code.</>]} />
          <details style={{ marginTop: 10 }}><summary className="mut" style={{ cursor: 'pointer' }}>I'm the one who runs the Apollo bot (relay owner)</summary>
            <Steps items={[
              <>Create the bots once: Discord Developer Portal → New Application → Bot → Reset Token (turn on <b>Message Content Intent</b>); Telegram @BotFather → /newbot.</>,
              <>On a small always-on server, from the <span className="mono">apollo-trading-hub</span> folder: <span className="mono">docker build -t apollo-relay -f relay/Dockerfile .</span></>,
              <><span className="mono">docker run -d --restart unless-stopped -p 8787:8787 -v apollo-relay:/data -e RELAY_DISCORD_TOKEN=… -e RELAY_TELEGRAM_TOKEN=… -e RELAY_ACCESS_KEY=… apollo-relay</span></>,
              <>Put it behind HTTPS (Caddy, nginx or Cloudflare Tunnel) and give your users the URL (and access key).</>]} />
          </details>
        </>) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(470px, 1fr))', gap: 14 }}>
            {(['discord', 'telegram'] as const).map((k) => { const c = s[k]; const bs = st[k]; return (
              <div key={k} style={{ border: '1px solid var(--line)', borderRadius: 8, padding: 12 }}>
                <div className="row" style={{ justifyContent: 'space-between' }}><b>{k === 'discord' ? 'Discord' : 'Telegram'}</b>
                  <span className="pill" style={{ color: bs?.running ? 'var(--good)' : c.enabled ? 'var(--warn)' : 'var(--muted)' }}><span className="dot" />{bs?.running ? `online${bs.username ? ` · ${bs.username}` : ''}` : c.enabled ? 'starting / error' : 'off'}</span></div>
                {bs?.error && <div className="neg" style={{ fontSize: 11.5 }}>{bs.error}</div>}
                {k === 'discord' ? <Steps items={[
                  <>Open <a href="https://discord.com/developers/applications" target="_blank" rel="noreferrer">discord.com/developers/applications</a> → <b>New Application</b> → name it (e.g. Apollo).</>,
                  <>Left menu <b>Bot</b> → <b>Reset Token</b> → copy it and paste it below.</>,
                  <>Same page: turn on <b>Message Content Intent</b> (needed for <span className="mono">!commands</span>).</>,
                  <>Tick Enabled, click <b>Save & relaunch</b>, then {bs?.invite_url ? <a href={bs.invite_url} target="_blank" rel="noreferrer"><button className="primary">Invite bot to my server ↗</button></a> : 'use the invite button that appears here'}.</>,
                  <>Optional: paste your Server ID so slash commands appear instantly (right-click the server → Copy Server ID, with Developer Mode on).</>]} />
                  : <Steps items={[
                    <>In Telegram, open <a href="https://t.me/BotFather" target="_blank" rel="noreferrer">@BotFather</a> → send <span className="mono">/newbot</span> → choose a name and a username.</>,
                    <>Copy the token it gives you and paste it below.</>,
                    <>Tick Enabled and click <b>Save & relaunch</b>.</>,
                    <>Open your bot{bs?.username ? <> (<a href={`https://t.me/${bs.username}`} target="_blank" rel="noreferrer">@{bs.username}</a>)</> : ''} and press <b>Start</b>, or add it to a group.</>]} />}
                <div style={{ marginTop: 8 }}>
                  <Field label="Enabled"><input type="checkbox" checked={c.enabled} onChange={(e) => bot(k, { enabled: e.target.checked })} aria-label={`${k} enabled`} /></Field>
                  <Field label="Bot token" hint={c.token_set ? 'Saved on this computer only. Paste a new one to replace it.' : undefined}><input type="password" value={c.token} onChange={(e) => bot(k, { token: e.target.value })} style={{ width: '100%' }} aria-label={`${k} token`} autoComplete="off" /></Field>
                  {k === 'discord' && <>
                    <Field label="Server ID (optional)"><input value={c.guild_id ?? ''} onChange={(e) => bot(k, { guild_id: e.target.value })} /></Field>
                    <Field label="Text prefix"><input value={c.prefix ?? '!'} onChange={(e) => bot(k, { prefix: e.target.value || '!' })} style={{ width: 50 }} /></Field>
                  </>}
                </div>
              </div>); })}
          </div>)}
      </Section>

      <Section title="3 · Link your server or chat" tour="connect">
        <Steps items={[<>Click <b>Generate code</b>.</>, <><b>Discord:</b> in the channel where you want alerts, type <span className="mono">/verify CODE</span> (or <span className="mono">!verify CODE</span>).</>,
          <><b>Telegram:</b> send <span className="mono">/verify CODE</span> to the bot, or in a group where the bot is a member.</>, <>This page updates by itself once it's linked. Codes expire after 10 minutes and work once.</>]} />
        <div className="row" style={{ marginTop: 10, flexWrap: 'wrap' }}>
          <button className="primary" onClick={genCode} disabled={!connected} title={connected ? '' : 'Connect a bot first (step 2)'}>Generate code</button>
          <label className="row"><input type="checkbox" checked={grant} onChange={(e) => setGrant(e.target.checked)} />The person who verifies can run control commands (kill, flatten, paid…)</label>
          {!connected && <span className="warn" style={{ fontSize: 11.5 }}>Finish step 2 and Save first.</span>}
        </div>
        {code && left > 0 && (
          <div style={{ marginTop: 10, border: '1px dashed var(--accent)', borderRadius: 8, padding: 14, textAlign: 'center' }}>
            <div className="mut">Type this in Discord or Telegram:</div>
            <div className="mono" style={{ fontSize: 30, letterSpacing: '.2em', margin: '6px 0', color: 'var(--accent)' }}>/verify {code.code}</div>
            <div className="row" style={{ justifyContent: 'center' }}>
              <button onClick={() => navigator.clipboard.writeText(`/verify ${code.code}`).then(() => setMsg('Copied.')).catch(() => undefined)}>Copy</button>
              <span className="mut">expires in {Math.floor(left / 60)}:{String(left % 60).padStart(2, '0')} · waiting for /verify…</span>
            </div>
          </div>)}
      </Section>

      <Section title="4 · Where alerts go" tour="destinations">
        {!r.links.length && <div className="mut">Nothing linked yet. Link a server or chat in step 3, then choose its alert channels here.</div>}
        {r.links.map((l0) => { const l = link(l0); const isD = l.platform === 'discord' && !!l.guild_id;
          const rows = isD ? (channels[l.id] ?? Object.entries(l.destinations).map(([id, d]) => ({ id, name: d.name ?? id }))) : [{ id: l.chat_id, name: l.title }];
          return (
            <div key={l.id} style={{ border: '1px solid var(--line)', borderRadius: 8, padding: 10, marginBottom: 10 }}>
              <div className="row" style={{ justifyContent: 'space-between' }}>
                <span><b>{l.platform === 'discord' ? '🎮' : '✈'} {l.title}</b> <span className="mut">· {l.platform} · linked by {l.linked_by_name || l.linked_by} on {l.linked_at.slice(0, 10)}</span></span>
                <div className="row">
                  {isD && <button onClick={() => loadChannels(l)}>Show all channels</button>}
                  {dirtyLinks[l.id] && <button className="primary" onClick={() => saveLink(l0)}>Save destinations</button>}
                  <button className="ghost" onClick={() => unlink(l0)}>Unlink</button>
                </div>
              </div>
              <div style={{ overflowX: 'auto' }}><table style={{ marginTop: 6 }}>
                <thead><tr><th>{isD ? 'Channel' : 'Chat'}</th><th>All</th>{r.notify_kinds.map((k) => <th key={k} style={{ fontSize: 10.5 }}>{LABEL[k] ?? k}</th>)}</tr></thead>
                <tbody>{rows.map((c) => { const d = l.destinations[c.id]; const all = !!d && d.kinds.length === r.notify_kinds.length; return (
                  <tr key={c.id}><td>{isD ? '#' : ''}{c.name}</td>
                    <td><input type="checkbox" checked={all} onChange={(e) => setDest(l0, c.id, c.name, null, e.target.checked)} aria-label={`all alerts to ${c.name}`} /></td>
                    {r.notify_kinds.map((k) => <td key={k} style={{ textAlign: 'center' }}><input type="checkbox" checked={!!d?.kinds.includes(k)} onChange={(e) => setDest(l0, c.id, c.name, k, e.target.checked)} aria-label={`${LABEL[k]} to ${c.name}`} /></td>)}
                  </tr>); })}</tbody></table></div>
            </div>); })}
      </Section>

      <Section title="5 · Alert types" tour="alerts">
        <div className="mut" style={{ fontSize: 11.5, marginBottom: 6 }}>Master switches. An alert is sent only if it's on here and ticked for a destination above.</div>
        <div className="row" style={{ flexWrap: 'wrap', gap: 14 }}>
          {r.notify_kinds.map((k) => <label key={k} className="row"><input type="checkbox" checked={!!s.notify[k]} onChange={(e) => setS({ ...s, notify: { ...s.notify, [k]: e.target.checked } })} />{LABEL[k] ?? k}</label>)}
        </div>
      </Section>

      <Section title="6 · Who can use the bot" tour="access">
        <div className="mut" style={{ fontSize: 11.5 }}>People who /verify are added automatically. Anyone else is refused and shown their ID so you can add them here.</div>
        {(['discord', 'telegram'] as const).map((k) => (
          <div key={k} style={{ marginTop: 6 }}><b style={{ fontSize: 12 }}>{k === 'discord' ? 'Discord' : 'Telegram'}</b>
            <Field label="Allowed users (read)"><input value={list(s[k].allowed_user_ids)} onChange={(e) => bot(k, { allowed_user_ids: parse(e.target.value) })} style={{ width: '100%' }} /></Field>
            <Field label="Control users 🔒" hint="kill · flatten · resume · requested · paid · rejected"><input value={list(s[k].control_user_ids)} onChange={(e) => bot(k, { control_user_ids: parse(e.target.value) })} style={{ width: '100%' }} /></Field>
          </div>))}
      </Section>

      <Section title="7 · Custom commands" tour="custom" right={<button onClick={() => setS({ ...s, custom_commands: [...s.custom_commands, { name: `cmd${s.custom_commands.length + 1}`, description: '', type: 'template', value: 'Fleet P&L today {fleet_day_pnl}' }] })}>+ Add command</button>}>
        <Steps items={[<><b>template</b>: text with live values, e.g. <span className="mono">{'Ready {ready_now_net} · blown {blown}'}</span></>,
          <><b>alias</b>: runs commands in order, separated by <span className="mono">;</span>, e.g. <span className="mono">status; ready; outcomes</span></>,
          <>Click <b>Save & relaunch</b>. They're registered in Telegram's / menu and as Discord slash commands every time Apollo launches. On the shared bot, run them as <span className="mono">/apollo yourcommand</span>.</>]} />
        <div className="mut" style={{ fontSize: 11, margin: '6px 0' }}>Variables: {r.variables.map((v) => <span key={v} className="mono" style={{ marginRight: 6 }}>{`{${v}}`}</span>)}</div>
        <table><thead><tr><th>Name</th><th>Description</th><th>Type</th><th>Value</th><th /></tr></thead>
          <tbody>{s.custom_commands.map((c, i) => (
            <tr key={i}>
              <td><input value={c.name} onChange={(e) => cc(i, { name: e.target.value })} style={{ width: 110 }} aria-label="Command name" /></td>
              <td><input value={c.description ?? ''} onChange={(e) => cc(i, { description: e.target.value })} style={{ width: 170 }} aria-label="Description" /></td>
              <td><select value={c.type} onChange={(e) => cc(i, { type: e.target.value as Custom['type'] })}><option value="template">template</option><option value="alias">alias</option></select></td>
              <td><input value={c.value} onChange={(e) => cc(i, { value: e.target.value })} style={{ width: '100%', minWidth: 320 }} aria-label="Value" /></td>
              <td><div className="row"><button className="ghost" onClick={() => { setPreview({ command: c.name, out: '' }); test({ command: c.name }); }} title="Preview (save first for new commands)">▶</button>
                <button className="ghost" onClick={() => setS({ ...s, custom_commands: s.custom_commands.filter((_, j) => j !== i) })} aria-label="Remove">✕</button></div></td>
            </tr>))}</tbody></table>
        <div className="row" style={{ marginTop: 10 }}>
          <span className="mut">Try any command:</span>
          <input value={preview.command} onChange={(e) => setPreview({ ...preview, command: e.target.value })} onKeyDown={(e) => e.key === 'Enter' && test({ command: preview.command })} style={{ width: 200 }} aria-label="Preview command" />
          <button onClick={() => test({ command: preview.command })}>Run preview</button>
        </div>
        {preview.out && <pre className="mono" style={{ background: '#05060A', border: '1px solid var(--line)', borderRadius: 6, padding: 10, whiteSpace: 'pre-wrap', fontSize: 12 }}>{preview.out}</pre>}
        <details style={{ marginTop: 8 }}><summary className="mut" style={{ cursor: 'pointer' }}>All commands ({r.commands.length})</summary>
          <div className="mono mut" style={{ fontSize: 11.5 }}>{r.commands.map(([n, d]) => <div key={n}>/{n} — {d}</div>)}</div></details>
      </Section>
    </div>
  );
}
