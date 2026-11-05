"""Python strategies.

Three flavours are accepted, auto-detected from the imports:

* **Tickbench native** – define ``on_bar(ctx)`` (and optionally ``init(ctx)`` and a ``PARAMS`` dict).
* **backtesting.py** – a ``Strategy`` subclass with ``init()`` / ``next()``; ``self.I``, ``self.buy``,
  ``self.position`` and ``backtesting.lib.crossover`` behave like the real library.
* **backtrader** – a ``bt.Strategy`` subclass with ``params``, ``__init__`` indicators and ``next()``.

The real libraries are *not* used: small compatible stand-ins route every order to the
Tickbench broker, so results, costs and statistics are identical across script types.
"""

from __future__ import annotations

import contextlib
import io
import math
import sys
import traceback
import types
from typing import Any

import numpy as np

from ..core.engine import RunContext, StrategyAdapter
from ..errors import ScriptError
from .api import StrategyAPI
from . import bt_shims


def detect_flavor(source: str) -> str:
    if "import backtrader" in source or "from backtrader" in source:
        return "backtrader"
    if "from backtesting" in source or "import backtesting" in source:
        return "backtesting.py"
    return "python-native"


class _LogWriter(io.TextIOBase):
    def __init__(self, ctx: RunContext):
        self.ctx = ctx
        self.buf = ""

    def write(self, s: str) -> int:
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            if line.strip():
                self.ctx.log("log", line)
        return len(s)


def _script_error(e: BaseException, filename: str, prefix: str = "") -> ScriptError:
    tb = traceback.extract_tb(e.__traceback__)
    line = None
    for fr in reversed(tb):
        if fr.filename == filename:
            line = fr.lineno
            break
    msg = f"{prefix}{type(e).__name__}: {e}"
    return ScriptError(msg, line=line, file=filename, hint="Fix the line shown, then run again.")


class PythonAdapter(StrategyAdapter):
    def __init__(self, source: str, filename: str = "strategy.py", flavor: str = "python"):
        self.source = source
        self.filename = filename
        self.flavor = detect_flavor(source) if flavor in ("python", None) else flavor
        self.name = filename

    # ---------------------------------------------------------------- loading
    def _load_module(self, ctx: RunContext | None = None) -> types.ModuleType:
        mod = types.ModuleType("tickbench_user_strategy")
        mod.__file__ = self.filename
        saved = {k: sys.modules.get(k) for k in bt_shims.MODULE_NAMES}
        shim_mods = bt_shims.make_modules()
        sys.modules.update(shim_mods)
        out = _LogWriter(ctx) if ctx else io.StringIO()
        try:
            code = compile(self.source, self.filename, "exec")
        except SyntaxError as e:
            raise ScriptError(f"Python syntax error: {e.msg}", line=e.lineno, file=self.filename,
                              hint="Check brackets, colons and indentation on that line.") from e
        try:
            with contextlib.redirect_stdout(out):
                exec(code, mod.__dict__)
        except ScriptError:
            raise
        except Exception as e:
            raise _script_error(e, self.filename, "Error while loading the script — ") from e
        finally:
            for k, v in saved.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v
        mod.__dict__["__shims__"] = shim_mods
        return mod

    def describe(self) -> dict:
        mod = self._load_module()
        params: dict[str, Any] = {}
        if self.flavor == "python-native":
            params = dict(getattr(mod, "PARAMS", None) or getattr(mod, "params", None) or {})
        elif self.flavor == "backtesting.py":
            cls = bt_shims.find_strategy_class(mod, mod.__shims__["backtesting"].Strategy)
            params = bt_shims.bpy_params(cls) if cls else {}
        elif self.flavor == "backtrader":
            cls = bt_shims.find_strategy_class(mod, mod.__shims__["backtrader"].Strategy)
            params = bt_shims.btr_params(cls) if cls else {}
        return {"flavor": self.flavor, "params": [
            {"name": k, "default": v, "type": type(v).__name__} for k, v in params.items()
            if isinstance(v, (int, float, bool, str))]}

    # ---------------------------------------------------------------- running
    def setup(self, ctx: RunContext) -> None:
        self.ctx = ctx
        self.out = _LogWriter(ctx)
        mod = self._load_module(ctx)
        self.mod = mod
        user_params = {k: v for k, v in ctx.params.items() if not k.startswith("_")}
        if self.flavor == "python-native":
            defaults = dict(getattr(mod, "PARAMS", None) or {})
            defaults.update(user_params)
            self.api = StrategyAPI(ctx, defaults)
            self.on_bar_fn = (getattr(mod, "on_bar", None) or getattr(mod, "onBar", None)
                              or getattr(mod, "next", None))
            if not callable(self.on_bar_fn):
                raise ScriptError("No on_bar(ctx) function found.", file=self.filename,
                                  hint="Define `def on_bar(ctx):` — it is called once per bar.")
            init = getattr(mod, "init", None) or getattr(mod, "initialize", None) or getattr(mod, "setup", None)
            if callable(init):
                self._call(init, self.api)
            self.runner = lambda: self._call(self.on_bar_fn, self.api)
        elif self.flavor == "backtesting.py":
            shim = mod.__shims__["backtesting"]
            cls = bt_shims.find_strategy_class(mod, shim.Strategy)
            if cls is None:
                raise ScriptError("No backtesting.py Strategy subclass found.", file=self.filename,
                                  hint="Define `class MyStrategy(Strategy):` with init() and next().")
            self.strat = bt_shims.BpyRunner(cls, ctx, user_params)
            with contextlib.redirect_stdout(self.out):
                self._guard(self.strat.init)
            self.runner = lambda: self.strat.step()
        else:
            shim = mod.__shims__["backtrader"]
            cls = bt_shims.find_strategy_class(mod, shim.Strategy)
            if cls is None:
                raise ScriptError("No backtrader Strategy subclass found.", file=self.filename,
                                  hint="Define `class MyStrategy(bt.Strategy):` with next().")
            self.strat = bt_shims.BtrRunner(cls, ctx, user_params, shim)
            with contextlib.redirect_stdout(self.out):
                self._guard(self.strat.init)
            self.runner = lambda: self.strat.step()

    def _guard(self, fn, *a):
        try:
            return fn(*a)
        except ScriptError:
            raise
        except Exception as e:
            raise _script_error(e, self.filename, f"Error on bar {self.ctx.i} — ") from e

    def _call(self, fn, *a):
        with contextlib.redirect_stdout(self.out):
            return self._guard(fn, *a)

    def on_close(self, ctx: RunContext, i: int) -> None:
        with contextlib.redirect_stdout(self.out):
            self._guard(self.runner)
