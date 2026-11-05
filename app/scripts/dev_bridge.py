"""Tiny HTTP bridge so the UI can run in a normal browser during development:

    python app/scripts/dev_bridge.py          # serves http://127.0.0.1:8765/rpc
    cd app && npx vite                         # open http://localhost:5173

Each POST {id, method, params} is handled by the same engine code the desktop app uses.
Only listens on localhost.
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "engine"))

from tickbench import rpc  # noqa: E402


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "http://localhost:5173")
        self.send_header("Access-Control-Allow-Headers", "content-type")

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_POST(self):  # noqa: N802
        req = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
        out: list = []
        original = rpc.send
        rpc.send = out.append
        try:
            rpc.handle(req)
        finally:
            rpc.send = original
        reply = next((m for m in out if "result" in m or "error" in m), {"error": {"message": "no reply"}})
        reply["events"] = [m for m in out if "event" in m]
        body = rpc.dumps(reply).encode()
        self.send_response(200)
        self._cors()
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print("Tickbench dev bridge on http://127.0.0.1:8765/rpc")
    ThreadingHTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
