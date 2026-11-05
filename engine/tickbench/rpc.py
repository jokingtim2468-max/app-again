"""JSON-RPC over stdin/stdout for the desktop app.

Request:  {"id": 1, "method": "run", "params": {...}}            (one JSON object per line)
Response: {"id": 1, "result": ...} or {"id": 1, "error": {message, hint, line, file, kind}}
Events:   {"event": "progress", "id": 1, "pct": 0.42}
"""

from __future__ import annotations

import json
import math
import os
import queue
import sys
import threading
import traceback

import numpy as np

from . import __version__
from .contracts import CONTRACTS
from .data.loader import describe as describe_bars
from .detect import TYPES, detect
from .errors import Cancelled, TickbenchError

_out_lock = threading.Lock()
_cancel: set = set()
_store = None


def _clean(o):
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, (np.floating,)):
        f = float(o)
        return f if math.isfinite(f) else None
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, np.ndarray):
        return _clean(o.tolist())
    return o


def dumps(o) -> str:
    return json.dumps(_clean(o), separators=(",", ":"), allow_nan=False)


def send(msg: dict) -> None:
    line = dumps(msg)
    with _out_lock:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


def store():
    global _store
    if _store is None:
        from .store import Store
        _store = Store()
    return _store


def examples_dir() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(here, "..", "examples"), os.path.join(getattr(sys, "_MEIPASS", here), "examples"),
                 os.path.join(os.path.dirname(sys.executable), "examples")):
        if os.path.isdir(cand):
            return os.path.abspath(cand)
    return ""


# ------------------------------------------------------------------------------ methods
def m_ping(p, rid):
    return {"version": __version__, "python": sys.version.split()[0]}


def m_detect(p, rid):
    from .runner import read_script
    src, _ = read_script(p["path"])
    det = detect(src, os.path.basename(p["path"]))
    det["types"] = TYPES
    det["preview"] = src[:4000]
    det["lines"] = src.count("\n") + 1
    if det["type"] != "unknown":
        try:
            det["describe"] = m_describe({"path": p["path"], "kind": det["type"]}, rid)
        except TickbenchError as e:
            det["describeError"] = e.to_dict()
    return det


def m_describe(p, rid):
    from .adapters import build_adapter
    from .runner import read_script
    src, extra = read_script(p["path"])
    kind = p.get("kind") or detect(src, os.path.basename(p["path"]))["type"]
    ad = build_adapter(kind, src, os.path.basename(p["path"]), p.get("options"), extra)
    d = ad.describe() if hasattr(ad, "describe") else {"params": []}
    d["kind"] = kind
    return d


def m_load_data(p, rid):
    from .runner import load_data
    b = load_data(p)
    d = describe_bars(b)
    step = max(1, len(b) // 160)
    d["spark"] = [round(float(x), 6) for x in b.close[::step]]
    d["sample"] = [{"time": int(b.time[k]), "open": float(b.open[k]), "high": float(b.high[k]), "low": float(b.low[k]),
                    "close": float(b.close[k]), "volume": float(b.volume[k])} for k in range(min(5, len(b)))]
    d["rowsDropped"] = b.meta.get("rows_dropped", 0)
    return d


def m_run(p, rid):
    from .runner import run
    last = [-1.0]

    def progress(x):
        if x - last[0] >= 0.02:
            last[0] = x
            send({"event": "progress", "id": rid, "pct": round(x, 3)})

    result = run(p["script"], p["data"], p.get("settings"), p.get("params"), progress, lambda: rid in _cancel)
    if p.get("label"):
        result["label"] = p["label"]
    payload = dumps(result)
    if p.get("save", True):
        try:
            store().save(result, payload)
        except Exception as e:  # history is a convenience; never fail the run because of it
            result.setdefault("warnings", []).append(f"Couldn't save run history: {e}")
    return json.loads(payload)


def m_runs_list(p, rid):
    return store().list(int(p.get("limit", 200)))


def m_runs_get(p, rid):
    s = store().get(p["id"])
    if s is None:
        raise TickbenchError("That run is no longer in the history.")
    return json.loads(s)


def m_runs_delete(p, rid):
    return store().delete(p["id"])


def m_examples(p, rid):
    root = examples_dir()
    out = {"strategies": [], "data": [], "root": root}
    if not root:
        return out
    for sub, key in (("strategies", "strategies"), ("data", "data")):
        d = os.path.join(root, sub)
        if os.path.isdir(d):
            for fn in sorted(os.listdir(d)):
                if not fn.startswith("."):
                    out[key].append({"name": fn, "path": os.path.join(d, fn)})
    return out


def m_contracts(p, rid):
    return [{"root": k, **v} for k, v in CONTRACTS.items()]


EXT_FOR_KIND = {"pine": ".pine", "mql4": ".mq4", "mql5": ".mq5", "python-native": ".py", "backtesting.py": ".py",
                "backtrader": ".py", "javascript": ".js", "tradovate-indicator": ".js", "tradovate-strategy": ".js",
                "rules-json": ".json", "rules-yaml": ".yaml"}


def _scripts_dir() -> str:
    from .store import data_dir
    d = os.path.join(data_dir(), "scripts")
    os.makedirs(d, exist_ok=True)
    return d


def m_save_script(p, rid):
    """Turn pasted text into a real script file (extension picked from detection) and return its path."""
    import re
    import time
    text = str(p.get("text") or "")
    if not text.strip():
        raise TickbenchError("Nothing to save: the pasted text is empty.", hint="Paste your strategy code first.")
    kind = p.get("kind") or detect(text, "")["type"]
    ext = EXT_FOR_KIND.get(kind, ".txt")
    base = re.sub(r"[^A-Za-z0-9_-]+", "_", str(p.get("name") or "").strip()).strip("_")
    if not base:
        base = "pasted_" + time.strftime("%Y%m%d_%H%M%S")
    base = re.sub(r"\.(pine|mq4|mq5|py|js|json|ya?ml|txt)$", "", base, flags=re.I)
    # each pasted script gets its own folder, so files added for it stay together
    folder = os.path.join(_scripts_dir(), base)
    n = 2
    while os.path.exists(folder):
        folder = os.path.join(_scripts_dir(), f"{base}_{n}")
        n += 1
    os.makedirs(folder)
    path = os.path.join(folder, base + ext)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return {"path": path, "kind": kind}


def m_add_files(p, rid):
    """Copy supporting files (e.g. modules a Tradovate strategy require()s) into the script's folder."""
    import shutil
    folder = os.path.dirname(os.path.abspath(p["scriptPath"]))
    added = []
    for src in p.get("files") or []:
        if not os.path.isfile(src):
            raise TickbenchError(f"File not found: {src}")
        dst = os.path.join(folder, os.path.basename(src))
        if os.path.abspath(src) != os.path.abspath(dst):
            shutil.copyfile(src, dst)
        added.append(os.path.basename(dst))
    return {"folder": folder, "added": added, "files": sorted(f for f in os.listdir(folder) if not f.startswith("."))}


def m_list_files(p, rid):
    folder = os.path.dirname(os.path.abspath(p["scriptPath"]))
    return {"folder": folder, "files": sorted(f for f in os.listdir(folder) if not f.startswith("."))}


def m_cancel(p, rid):
    _cancel.add(p["id"])
    return True


METHODS = {"ping": m_ping, "detect": m_detect, "describe": m_describe, "loadData": m_load_data, "run": m_run,
           "runs.list": m_runs_list, "runs.get": m_runs_get, "runs.delete": m_runs_delete,
           "examples": m_examples, "contracts": m_contracts, "cancel": m_cancel,
           "saveScript": m_save_script, "addFiles": m_add_files, "listFiles": m_list_files}


def handle(req: dict) -> None:
    rid = req.get("id")
    method = req.get("method")
    fn = METHODS.get(method)
    if fn is None:
        send({"id": rid, "error": {"message": f"Unknown method {method}", "kind": "RpcError"}})
        return
    try:
        res = fn(req.get("params") or {}, rid)
        send({"id": rid, "result": res})
    except Cancelled as e:
        send({"id": rid, "error": e.to_dict()})
    except TickbenchError as e:
        send({"id": rid, "error": e.to_dict()})
    except Exception as e:  # unexpected: include a short trace for bug reports
        tb = traceback.format_exc(limit=6)
        send({"id": rid, "error": {"message": f"{type(e).__name__}: {e}", "hint": "This looks like a Tickbench bug.",
                                   "kind": "InternalError", "trace": tb}})
    finally:
        _cancel.discard(rid)


def serve() -> None:
    work: queue.Queue = queue.Queue()

    def worker():
        while True:
            req = work.get()
            if req is None:
                return
            handle(req)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    send({"event": "ready", "version": __version__})
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            send({"event": "log", "text": f"bad request line: {line[:80]}"})
            continue
        if req.get("method") == "cancel":
            handle(req)  # answer immediately, even while a run is busy
        else:
            work.put(req)
    work.put(None)
    t.join()  # stdin closed: finish queued requests before exiting
