/**
 * Apollo Trading desktop shell.
 * - First launch: creates a private Python environment in the user's data folder and installs the engine's packages
 *   (shows a setup window). Re-runs automatically when an update changes the requirements.
 * - Every launch: starts the Apollo engine (FastAPI backend on 127.0.0.1:5050) in the background, waits until it is
 *   healthy, opens the app, and stops the engine when the app closes.
 * - Auto-updates from GitHub releases (packaged builds).
 * Data (accounts, logs, settings, layouts, strategies) lives in %APPDATA%/Apollo Trading and survives updates.
 */
import { app, BrowserWindow, dialog, shell } from 'electron';
import { autoUpdater } from 'electron-updater';
import { ChildProcess, spawn, spawnSync } from 'child_process';
import crypto from 'crypto';
import fs from 'fs';
import http from 'http';
import path from 'path';

const isWin = process.platform === 'win32';
const ROOT = app.isPackaged ? path.join(process.resourcesPath, 'apollo') : path.resolve(__dirname, '..', '..');
const DATA = app.getPath('userData');
const VENV = path.join(DATA, 'python');
const PY = isWin ? path.join(VENV, 'Scripts', 'python.exe') : path.join(VENV, 'bin', 'python');
const LOGS = path.join(DATA, 'logs');
const REQS = [path.join(ROOT, 'backend', 'requirements.txt'), path.join(ROOT, 'mcp-server', 'requirements.txt')];

let win: BrowserWindow | null = null;
let splash: BrowserWindow | null = null;
let engine: ChildProcess | null = null;
let quitting = false;

function log(line: string) {
  fs.mkdirSync(LOGS, { recursive: true });
  fs.appendFileSync(path.join(LOGS, 'desktop.log'), `[${new Date().toISOString()}] ${line}\n`);
}

// ---------- setup window ----------
function showSplash() {
  splash = new BrowserWindow({ width: 520, height: 300, frame: false, resizable: false, backgroundColor: '#090A0F', show: true,
    webPreferences: { contextIsolation: true, sandbox: true } });
  const html = `<body style="margin:0;background:#090A0F;color:#E3E7F0;font:14px 'Segoe UI',system-ui;display:grid;place-items:center;height:100vh">
    <div style="text-align:center;max-width:420px"><svg width="44" height="46" viewBox="0 0 100 104" fill="#EEF1F8"><path d="M50 4 L96 100 H72 L50 52 L28 100 H4 Z"/><path d="M50 66 L60 92 L50 85 L40 92 Z"/></svg>
    <h2 style="letter-spacing:.18em;font-size:15px;margin:14px 0 6px">APOLLO TRADING</h2>
    <div style="width:280px;height:4px;margin:18px auto 0;background:#1E2230;border-radius:2px;overflow:hidden"><div id="b" style="width:0;height:100%;background:#FFFFFF;border-radius:2px;transition:width .4s ease"></div></div></div></body>`;
  splash.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(html));
}
let lastStatus = '';
let pct = 0;
// phases map to a range of the bar; each output line inside a phase nudges it toward the range's end
const PHASES: Record<string, [number, number]> = {
  'Checking for updates…': [0, 2], 'Updating Apollo Trading…': [2, 10],
  'First-time setup: finding Python…': [2, 6], 'Creating Apollo\'s Python environment…': [6, 18], 'Updating pip…': [18, 26],
  'Installing the Apollo engine (one time, ~1–3 minutes)…': [26, 30], 'Installing the Apollo engine…': [30, 85],
  'Starting the Apollo engine…': [85, 98], 'Ready': [100, 100],
};
function setBar(p: number) {
  pct = Math.max(pct, Math.min(100, p));
  splash?.webContents.executeJavaScript(`document.getElementById('b').style.width='${pct.toFixed(1)}%'`).catch(() => undefined);
}
function status(text: string, _detail = '') {
  const [lo, hi] = PHASES[text] ?? [pct, pct];
  if (text !== lastStatus) { log(text); lastStatus = text; setBar(lo); }  // log each phase once, not every pip line
  else setBar(pct + (hi - pct) * 0.04);  // creep toward the phase end, never past it
}

// ---------- python environment ----------
function findPython(): { cmd: string; args: string[] } | null {
  const candidates: [string, string[]][] = isWin ? [['py', ['-3.12']], ['py', ['-3.11']], ['py', ['-3']], ['python', []]] : [['python3.12', []], ['python3', []], ['python', []]];
  for (const [cmd, args] of candidates) {
    const r = spawnSync(cmd, [...args, '-c', 'import sys; print(sys.version_info[:2] >= (3, 11))'], { encoding: 'utf8', windowsHide: true });
    if (r.status === 0 && r.stdout.trim() === 'True') return { cmd, args };
  }
  return null;
}
function run(cmd: string, args: string[], label: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const p = spawn(cmd, args, { cwd: ROOT, windowsHide: true, env: { ...process.env, PYTHONUTF8: '1' } });
    const out = fs.createWriteStream(path.join(LOGS, 'setup.log'), { flags: 'a' });
    p.stdout.pipe(out); p.stderr.pipe(out);
    p.stdout.on('data', (b) => { const t = String(b).trim().split('\n').pop(); if (t) status(label, t.slice(0, 90)); });
    p.on('exit', (code) => (code === 0 ? resolve() : reject(new Error(`${label} failed (code ${code}). See ${path.join(LOGS, 'setup.log')}`))));
    p.on('error', reject);
  });
}
async function ensurePython() {
  fs.mkdirSync(LOGS, { recursive: true });
  const hash = crypto.createHash('sha256').update(REQS.filter(fs.existsSync).map((f) => fs.readFileSync(f)).join('\n')).digest('hex');
  const stamp = path.join(VENV, '.apollo-req-hash');
  if (fs.existsSync(PY) && fs.existsSync(stamp) && fs.readFileSync(stamp, 'utf8') === hash) { setBar(80); return; }
  if (!fs.existsSync(PY)) {
    status('First-time setup: finding Python…');
    const base = findPython();
    if (!base) throw new Error('Python 3.11+ was not found. Install it (winget install -e --id Python.Python.3.12) and open Apollo again.');
    status('Creating Apollo\'s Python environment…');
    await run(base.cmd, [...base.args, '-m', 'venv', VENV], 'Creating Apollo\'s Python environment…');
  }
  status('Installing the Apollo engine (one time, ~1–3 minutes)…');
  await run(PY, ['-m', 'pip', 'install', '--disable-pip-version-check', '--upgrade', 'pip'], 'Updating pip…');
  await run(PY, ['-m', 'pip', 'install', '--disable-pip-version-check', ...REQS.filter(fs.existsSync).flatMap((r) => ['-r', r])], 'Installing the Apollo engine…');
  fs.writeFileSync(stamp, hash);
}

// ---------- update from the git repo ----------
// The installer script clones the repo to ~/ApolloTrading and records the commit it built in .apollo-installed-commit.
// On launch, if the branch on GitHub has moved on, run that script silently (rebuild + reinstall + relaunch) and quit.
const SRC = path.join(app.getPath('home'), 'ApolloTrading');
const BRANCH = 'claude/apollo-trading-hub';
function checkRepoUpdate(): boolean {
  const stampFile = path.join(SRC, '.apollo-installed-commit');
  if (!isWin || !app.isPackaged || !fs.existsSync(path.join(SRC, '.git')) || !fs.existsSync(stampFile)) return false;
  const r = spawnSync('git', ['-C', SRC, 'ls-remote', 'origin', `refs/heads/${BRANCH}`], { encoding: 'utf8', windowsHide: true, timeout: 15000 });
  const remote = r.status === 0 ? r.stdout.split(/\s/)[0] : '';
  const local = fs.readFileSync(stampFile, 'utf8').trim();
  if (!remote || remote === local) return false;
  log(`update available ${local.slice(0, 7)} -> ${remote.slice(0, 7)}; running installer`);
  const script = path.join(SRC, 'apollo-trading-hub', 'scripts', 'install_windows.ps1');
  spawn('powershell', ['-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden', '-File', script, '-Silent', '-Relaunch'],
    { detached: true, stdio: 'ignore', windowsHide: true }).unref();
  return true;
}

// ---------- engine ----------
function healthy(): Promise<boolean> {
  return new Promise((resolve) => {
    const req = http.get('http://127.0.0.1:5050/api/health', { timeout: 1500 }, (r) => { r.resume(); resolve(r.statusCode === 200); });
    req.on('error', () => resolve(false)); req.on('timeout', () => { req.destroy(); resolve(false); });
  });
}
async function startEngine() {
  if (await healthy()) { log('engine already running, reusing it'); status('Ready'); return; }
  killStaleEngines();
  status('Starting the Apollo engine…');
  const out = fs.openSync(path.join(LOGS, 'engine.log'), 'a');
  engine = spawn(PY, ['-m', 'backend.src.server'], {
    cwd: ROOT, windowsHide: true, stdio: ['ignore', out, out],
    env: { ...process.env, APOLLO_DATA_DIR: DATA, PYTHONUNBUFFERED: '1', PYTHONPATH: ROOT, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' },
  });
  engine.on('exit', (code) => {
    log(`engine exited with ${code}`);
    engine = null;
    if (!quitting && win) {
      log('restarting engine');
      win.webContents.executeJavaScript("console.warn('Apollo engine restarted')").catch(() => undefined);
      startEngine().catch(fail);  // auto-restart; the app reconnects on its own
    }
  });
  for (let i = 0; i < 120; i++) {
    if (await healthy()) { status('Ready'); return; }
    status('Starting the Apollo engine…');
    await new Promise((r) => setTimeout(r, 500));
  }
  let tail = '';
  try { tail = fs.readFileSync(path.join(LOGS, 'engine.log'), 'utf8').trim().split('\n').slice(-6).join('\n'); } catch { /* no log */ }
  throw new Error(`The engine did not start.\n\n${tail}\n\nFull log: ${path.join(LOGS, 'engine.log')}`);
}
// an engine left over from an earlier failed launch holds port 5050 without answering; stop any python from our venv
function killStaleEngines() {
  if (!isWin) return;
  const ps = `Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -like '${VENV.replace(/'/g, "''")}*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }`;
  spawnSync('powershell', ['-NoProfile', '-Command', ps], { windowsHide: true, timeout: 15000 });
}
function stopEngine() {
  if (!engine?.pid) return;
  if (isWin) spawnSync('taskkill', ['/pid', String(engine.pid), '/T', '/F'], { windowsHide: true });
  else engine.kill('SIGTERM');
  engine = null;
}

// ---------- windows ----------
function createMain() {
  win = new BrowserWindow({
    width: 1480, height: 920, minWidth: 1100, minHeight: 700, show: false,
    backgroundColor: '#090A0F', title: 'Apollo Trading', autoHideMenuBar: true,
    icon: path.join(__dirname, '..', 'build', 'icon.png'),
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  if (process.env.VITE_DEV) win.loadURL('http://127.0.0.1:5173');
  else win.loadFile(path.join(__dirname, '../dist/index.html'));
  win.once('ready-to-show', async () => { setBar(100); await new Promise((r) => setTimeout(r, 350)); win?.maximize(); win?.show(); splash?.close(); splash = null; });
  win.webContents.setWindowOpenHandler(({ url }) => { shell.openExternal(url); return { action: 'deny' }; });
  win.on('closed', () => { win = null; });
}
function fail(e: unknown) {
  log(`fatal: ${e}`);
  dialog.showErrorBox('Apollo Trading could not start', String(e instanceof Error ? e.message : e));
  quitting = true; stopEngine(); app.quit();
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => { if (win) { if (win.isMinimized()) win.restore(); win.focus(); } });
  app.whenReady().then(async () => {
    showSplash();
    try {
      status('Checking for updates…');
      if (checkRepoUpdate()) {
        status('Updating Apollo Trading…');
        setTimeout(() => { quitting = true; app.quit(); }, 1500);  // the installer relaunches the app when it finishes
        return;
      }
      await ensurePython();
      await startEngine();
      createMain();
      if (app.isPackaged) {
        autoUpdater.on('update-downloaded', () => log('update downloaded; installs on next restart'));
        autoUpdater.checkForUpdatesAndNotify().catch((e) => log(`update check failed: ${e}`));
      }
    } catch (e) { fail(e); }
  });
  app.on('before-quit', () => { quitting = true; stopEngine(); });
  app.on('window-all-closed', () => { app.quit(); });
}
