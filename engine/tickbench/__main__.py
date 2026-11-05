"""Command line: ``python -m tickbench rpc`` (desktop app backend) or ``python -m tickbench run ...``."""

from __future__ import annotations

import argparse
import json
import sys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="tickbench", description="Backtest trading scripts.")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("rpc", help="serve JSON-RPC on stdin/stdout (used by the desktop app)")
    r = sub.add_parser("run", help="backtest a script on a CSV or Yahoo symbol")
    r.add_argument("script")
    r.add_argument("data", help="CSV path, or yahoo:SYMBOL[:interval]")
    r.add_argument("--kind", help="force the script type")
    r.add_argument("--set", action="append", default=[], help="setting=value (e.g. initial_capital=5000)")
    r.add_argument("--param", action="append", default=[], help="name=value strategy input")
    r.add_argument("--trades", action="store_true", help="print the trade list")
    r.add_argument("--json", action="store_true", help="print the full result as JSON")
    d = sub.add_parser("detect", help="identify a script's type")
    d.add_argument("script")
    args = ap.parse_args(argv)

    if args.cmd == "rpc" or args.cmd is None and not sys.stdin.isatty():
        from .rpc import serve
        serve()
        return 0
    if args.cmd == "detect":
        from .detect import detect
        from .runner import read_script
        src, _ = read_script(args.script)
        print(json.dumps(detect(src, args.script), indent=2))
        return 0
    if args.cmd == "run":
        from .errors import TickbenchError
        from .runner import run

        def val(v):
            for f in (int, float):
                try:
                    return f(v)
                except ValueError:
                    pass
            return {"true": True, "false": False}.get(v.lower(), v)

        if args.data.startswith("yahoo:"):
            parts = args.data.split(":")
            data = {"source": "yahoo", "symbol": parts[1], "interval": parts[2] if len(parts) > 2 else "1d"}
        else:
            data = {"source": "csv", "path": args.data}
        settings = {k: val(v) for k, v in (s.split("=", 1) for s in args.set)}
        params = {k: val(v) for k, v in (s.split("=", 1) for s in args.param)}
        script = {"path": args.script}
        if args.kind:
            script["kind"] = args.kind
        try:
            res = run(script, data, settings, params)
        except TickbenchError as e:
            where = f" (line {e.line})" if e.line else ""
            print(f"error{where}: {e.message}\n{e.hint}", file=sys.stderr)
            return 1
        if args.json:
            from .rpc import dumps
            print(dumps(res))
            return 0
        s = res["stats"]
        print(f"{res['script']['filename']}  [{res['script']['kind']}]  {res['data']['symbol']} "
              f"{res['data']['timeframe']}  {res['data']['bars']} bars  ({res['elapsedMs']} ms)")
        for k in ("netProfit", "netProfitPct", "cagr", "buyHoldPct", "maxDrawdownPct", "sharpe", "sortino",
                  "trades", "winRate", "profitFactor", "expectancy", "avgBarsHeld", "exposurePct", "commission"):
            v = s.get(k)
            print(f"  {k:<16} {'—' if v is None else (f'{v:,.2f}' if isinstance(v, float) else v)}")
        if args.trades:
            for t in res["trades"]:
                print(f"  #{t['id']:<4} {t['side']:<5} {t['qty']:>8g}  bar {t['entryBar']:>5} @ {t['entryPrice']:<12.6g}"
                      f" -> bar {t['exitBar']!s:>5} @ {t['exitPrice']!s:<12.8}  {t['pnl']:>12,.2f}  {t['exitReason']}")
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
