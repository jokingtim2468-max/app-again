"""Script adapters: each one turns a strategy file into a StrategyAdapter the engine can run."""

from __future__ import annotations

from ..errors import TickbenchError


def build_adapter(kind: str, source: str, filename: str = "strategy", options: dict | None = None,
                  extra_files: dict[str, str] | None = None):
    options = options or {}
    if kind in ("python", "python-native", "backtesting.py", "backtrader"):
        from .python_adapter import PythonAdapter
        return PythonAdapter(source, filename, flavor=kind)
    if kind in ("pine", "pine-v4", "pine-v5", "pine-v6"):
        from .pine.adapter import PineAdapter
        return PineAdapter(source, filename)
    if kind in ("mql4", "mql5"):
        from .mql.adapter import MqlAdapter
        return MqlAdapter(source, filename, dialect=kind)
    if kind == "javascript":
        from .js_adapter import JsAdapter
        return JsAdapter(source, filename)
    if kind in ("rules-json", "rules-yaml"):
        from .rules_adapter import RulesAdapter
        return RulesAdapter(source, filename, fmt=kind)
    if kind == "tradovate-indicator":
        from .tradovate.indicator import TradovateIndicatorAdapter
        return TradovateIndicatorAdapter(source, filename, signal=options.get("signal"), extra_files=extra_files)
    if kind == "tradovate-strategy":
        from .tradovate.strategy import TradovateStrategyAdapter
        return TradovateStrategyAdapter(source, filename, extra_files=extra_files)
    raise TickbenchError(f"Unknown script type '{kind}'.")
