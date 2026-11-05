"""Thin wrapper around an isolated V8 context (py-mini-racer)."""

from __future__ import annotations

import json
import os
import re

from ...core.bars import Bars
from ...errors import ScriptError

HERE = os.path.dirname(os.path.abspath(__file__))


def _read(name: str) -> str:
    with open(os.path.join(HERE, name), "r", encoding="utf-8") as f:
        return f.read()


def _js_error(e: Exception, filename: str) -> ScriptError:
    text = str(e)
    line = None
    m = re.search(r"(?:" + re.escape(filename) + r"|main\.js):(\d+)", text)
    if m:
        line = int(m.group(1))
    first = text.strip().splitlines()[0] if text.strip() else type(e).__name__
    return ScriptError(f"JavaScript error: {first}", line=line, file=filename,
                       hint="The line number points into your script.")


class JsRuntime:
    def __init__(self, filename: str):
        try:
            from py_mini_racer import MiniRacer
        except ImportError as e:  # pragma: no cover
            raise ScriptError("The JavaScript engine (py-mini-racer) is missing from this build.") from e
        self.filename = filename
        self.v8 = MiniRacer()
        self.v8.eval(_read("prelude.js"))
        # Tradovate's own helper modules, reachable as require("./tools/<Name>")
        tools = os.path.join(HERE, "tradovate_tools")
        for fn in sorted(os.listdir(tools)):
            if fn.endswith(".js"):
                name = fn[:-3]
                src = _read(os.path.join("tradovate_tools", fn))
                self.v8.call("__registerBuiltin", f"tools/{name}", src)
                self.v8.call("__registerBuiltin", name, src)
        for fn in sorted(os.listdir(os.path.join(HERE, "builtins"))):
            if fn.endswith(".js"):
                key = fn[:-3].replace("__", "/")
                src = _read(os.path.join("builtins", fn))
                self.v8.call("__registerBuiltin", key, src)
                self.v8.call("__registerBuiltin", key.split("/")[-1], src)

    def eval(self, code: str):
        try:
            return self.v8.eval(code)
        except Exception as e:
            raise _js_error(e, self.filename) from e

    def call(self, fn: str, *args):
        try:
            return self.v8.call(fn, *args)
        except Exception as e:
            raise _js_error(e, self.filename) from e

    def register_sources(self, main_source: str, extra: dict[str, str] | None = None) -> str:
        """Register the main script (path 'main.js') and sibling files; returns the main path."""
        main = "main.js"
        self.call("__register", main, main_source)
        for path, src in (extra or {}).items():
            p = path.lstrip("./")
            if src == main_source:
                main = p
            self.call("__register", p, src)
        return main

    def load_bars(self, bars: Bars) -> None:
        self.call("__load", json.dumps(bars.to_payload()))
