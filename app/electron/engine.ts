// Spawns the Python engine and speaks line-delimited JSON-RPC with it.
import { ChildProcessWithoutNullStreams, spawn } from "child_process";
import { app } from "electron";
import fs from "fs";
import path from "path";

type Pending = { resolve: (v: unknown) => void; reject: (e: unknown) => void };

export interface EngineError {
  message: string;
  hint?: string;
  line?: number | null;
  file?: string | null;
  kind?: string;
  trace?: string;
}

export class Engine {
  private proc: ChildProcessWithoutNullStreams | null = null;
  private nextId = 1;
  private pending = new Map<number, Pending>();
  private buf = "";
  private stderr = "";
  private ready: Promise<void> | null = null;
  constructor(private onEvent: (ev: Record<string, unknown>) => void) {}

  private command(): { cmd: string; args: string[]; cwd: string } {
    if (app.isPackaged) {
      const dir = path.join(process.resourcesPath, "engine");
      const exe = path.join(dir, process.platform === "win32" ? "tickbench-engine.exe" : "tickbench-engine");
      return { cmd: exe, args: ["rpc"], cwd: dir };
    }
    // development: run the engine from source
    const engineDir = path.resolve(__dirname, "..", "..", "engine");
    const py = process.env.TICKBENCH_PYTHON || (process.platform === "win32" ? "python" : "python3");
    return { cmd: py, args: ["-m", "tickbench", "rpc"], cwd: engineDir };
  }

  start(): Promise<void> {
    if (this.ready) return this.ready;
    this.ready = new Promise((resolve, reject) => {
      const { cmd, args, cwd } = this.command();
      if (app.isPackaged && !fs.existsSync(cmd)) {
        reject(new Error(`The backtest engine is missing (${cmd}). Reinstall Tickbench.`));
        return;
      }
      const env = { ...process.env, PYTHONIOENCODING: "utf-8", PYTHONUNBUFFERED: "1",
        TICKBENCH_DATA: path.join(app.getPath("userData"), "data") };
      const proc = spawn(cmd, args, { cwd, env, windowsHide: true });
      this.proc = proc;
      let started = false;
      proc.stdout.setEncoding("utf8");
      proc.stdout.on("data", (chunk: string) => {
        this.buf += chunk;
        let nl: number;
        while ((nl = this.buf.indexOf("\n")) >= 0) {
          const line = this.buf.slice(0, nl).trim();
          this.buf = this.buf.slice(nl + 1);
          if (!line) continue;
          let msg: Record<string, unknown>;
          try { msg = JSON.parse(line); } catch { continue; }
          if (msg.event === "ready") { started = true; resolve(); continue; }
          if (msg.event) { this.onEvent(msg); continue; }
          const p = this.pending.get(msg.id as number);
          if (!p) continue;
          this.pending.delete(msg.id as number);
          if (msg.error) p.reject(msg.error); else p.resolve(msg.result);
        }
      });
      proc.stderr.on("data", (d: Buffer) => { this.stderr = (this.stderr + d.toString()).slice(-8000); });
      proc.on("error", (err) => {
        if (!started) reject(new Error(`Couldn't start the engine: ${err.message}`));
      });
      proc.on("exit", (code) => {
        const msg: EngineError = { message: `The engine stopped (exit code ${code}).`,
          hint: "Tickbench will restart it on the next action.", trace: this.stderr, kind: "EngineExit" };
        for (const p of this.pending.values()) p.reject(msg);
        this.pending.clear();
        this.proc = null;
        this.ready = null;
        if (!started) reject(new Error(msg.message + "\n" + this.stderr));
      });
    });
    return this.ready;
  }

  async call(method: string, params: unknown = {}): Promise<{ id: number; promise: Promise<unknown> }> {
    await this.start();
    const id = this.nextId++;
    const promise = new Promise((resolve, reject) => this.pending.set(id, { resolve, reject }));
    this.proc!.stdin.write(JSON.stringify({ id, method, params }) + "\n");
    return { id, promise };
  }

  stop() {
    this.proc?.kill();
    this.proc = null;
  }
}
