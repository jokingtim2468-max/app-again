#!/usr/bin/env python3
"""MT5 bridge for WSL/Linux backends. Run on WINDOWS next to a logged-in MetaTrader 5 terminal:

    pip install MetaTrader5 && python scripts\\mt5_bridge.py      (listens on 127.0.0.1:54982)

The Apollo backend (e.g. inside WSL for Antigravity) reaches it via APOLLO_MT5_BRIDGE_URL. With WSL2 default
NAT networking use the Windows host IP (cat /etc/resolv.conf -> nameserver) and start with --host 0.0.0.0;
with networkingMode=mirrored, 127.0.0.1 works. Read-only: it exposes market data, never order functions.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.src.data import mt5_data  # noqa: E402

c = mt5_data.client()
if not isinstance(c, mt5_data._Direct):
    sys.exit("MetaTrader5 package not installed in this (Windows) Python: pip install MetaTrader5")


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        ts = lambda k: datetime.fromtimestamp(float(q[k]), timezone.utc)
        try:
            if u.path == "/status":
                c.connect(); a = c.mt5.account_info(); body = {"server": a.server, "login": a.login}
            elif u.path == "/info": body = c.info(q["symbol"])
            elif u.path == "/rates": body = c.rates(q["symbol"], q["tf"], ts("start"), ts("end"))
            elif u.path == "/ticks": body = c.ticks(q["symbol"], ts("start"), ts("end"))
            elif u.path == "/tick": body = c.tick(q["symbol"])
            elif u.path == "/book": body = c.book(q["symbol"])
            else: return self._send(404, {"error": "not found"})
            self._send(200, body)
        except Exception as e:
            self._send(400, {"error": f"{type(e).__name__}: {e}"})

    def _send(self, code, body):
        b = json.dumps(body).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--host", default="127.0.0.1"); ap.add_argument("--port", type=int, default=54982)
    a = ap.parse_args()
    print(f"MT5 bridge on http://{a.host}:{a.port}  (Ctrl+C to stop)")
    ThreadingHTTPServer((a.host, a.port), H).serve_forever()
