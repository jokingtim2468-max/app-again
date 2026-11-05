"""Work out what kind of strategy script a file is.

Each type has weighted signatures (regexes). The extension adds a bonus but never decides
on its own, so a Pine script saved as .txt or a Tradovate indicator saved as .js is still
recognised. Returns the best type, a 0–1 confidence and the evidence that matched.
"""

from __future__ import annotations

import json
import re

TYPES = {
    "pine": "Pine Script (TradingView)",
    "mql4": "MQL4 Expert Advisor (MetaTrader 4)",
    "mql5": "MQL5 Expert Advisor (MetaTrader 5)",
    "python-native": "Python (Tickbench on_bar)",
    "backtesting.py": "Python (backtesting.py)",
    "backtrader": "Python (backtrader)",
    "javascript": "JavaScript strategy",
    "tradovate-indicator": "Tradovate custom indicator (JavaScript)",
    "tradovate-strategy": "Tradovate API strategy (JavaScript)",
    "rules-json": "No-code rules (JSON)",
    "rules-yaml": "No-code rules (YAML)",
}

SIGS: dict[str, list[tuple[str, float, str]]] = {
    "pine": [
        (r"//\s*@version\s*=\s*\d", 6, "//@version= header"),
        (r"^\s*strategy\s*\(", 4, "strategy(...) declaration"),
        (r"^\s*(indicator|study)\s*\(", 3, "indicator(...) declaration"),
        (r"\bta\.(sma|ema|rsi|crossover|crossunder|atr|macd)\s*\(", 3, "ta.* built-ins"),
        (r"\bstrategy\.(entry|exit|close|long|short)\b", 4, "strategy.entry/exit"),
        (r"\binput\.(int|float|bool|string|source)\s*\(", 2, "input.* calls"),
        (r":=", 1, ":= reassignment"),
        (r"^\s*plot\s*\(", 1, "plot(...)"),
    ],
    "mql4": [
        (r"\bOrderSend\s*\(", 4, "OrderSend()"),
        (r"\bOrdersTotal\s*\(", 2, "OrdersTotal()"),
        (r"\bOrderSelect\s*\(", 3, "OrderSelect()"),
        (r"\bOP_(BUY|SELL)\b", 3, "OP_BUY / OP_SELL"),
        (r"\bextern\s+\w+", 2, "extern inputs"),
        (r"\bint\s+start\s*\(\s*\)", 3, "start() entry point"),
        (r"\biMA\s*\([^;]*,[^;]*,[^;]*,[^;]*,[^;]*,[^;]*,[^;]*\)", 3, "7-argument iMA (MQL4)"),
        (r"\b(Bid|Ask)\b", 1, "Bid/Ask globals"),
        (r"\bClose\s*\[", 1, "Close[] series"),
    ],
    "mql5": [
        (r"#include\s*<Trade\\Trade\.mqh>", 6, "#include <Trade\\Trade.mqh>"),
        (r"\bCTrade\b", 4, "CTrade object"),
        (r"\bCopyBuffer\s*\(", 4, "CopyBuffer()"),
        (r"\bPositionsTotal\s*\(", 3, "PositionsTotal()"),
        (r"\bPositionSelect\w*\s*\(", 2, "PositionSelect()"),
        (r"\bSymbolInfoDouble\s*\(", 2, "SymbolInfoDouble()"),
        (r"\bMqlTick\b|\bMqlRates\b", 2, "MqlTick / MqlRates"),
        (r"\bENUM_\w+", 1, "ENUM_* types"),
        (r"\binput\s+(int|double|bool|string|ENUM_\w+|long|uint|ulong)\s+\w+", 2, "input declarations"),
        (r"_Symbol\b|_Point\b", 1, "_Symbol / _Point"),
    ],
    "_mql_common": [
        (r"\bvoid\s+OnTick\s*\(\s*\)", 5, "OnTick() handler"),
        (r"\bint\s+OnInit\s*\(\s*\)", 3, "OnInit() handler"),
        (r"#property\s+(copyright|link|version|strict)", 3, "#property directives"),
        (r"\bNormalizeDouble\s*\(", 1, "NormalizeDouble()"),
    ],
    "python": [
        (r"^\s*def\s+\w+\s*\(.*\)\s*:", 3, "def statements"),
        (r"^\s*(import|from)\s+\w+", 2, "import statements"),
        (r"^\s*class\s+\w+(\(.*\))?\s*:", 1, "class definition"),
        (r"\bself\.", 1, "self."),
    ],
    "python-native": [(r"^\s*def\s+on_bar\s*\(", 6, "on_bar(ctx) function"), (r"\bctx\.(buy|sell|close_position|sma|ema)\b", 3, "ctx.* API")],
    "backtesting.py": [(r"from\s+backtesting(\.lib)?\s+import|import\s+backtesting", 8, "imports backtesting.py"),
                       (r"\bself\.I\s*\(", 3, "self.I(...) indicators")],
    "backtrader": [(r"import\s+backtrader|from\s+backtrader", 8, "imports backtrader"),
                   (r"\bbt\.(Strategy|indicators|ind)\b", 3, "bt.Strategy / bt.indicators")],
    "_js": [
        (r"module\.exports\s*=", 3, "module.exports"),
        (r"\b(const|let|var)\s+\w+\s*=", 2, "const/let declarations"),
        (r"=>", 1, "arrow functions"),
        (r"\bfunction\s+\w*\s*\(", 1, "function keyword"),
        (r"\brequire\s*\(\s*['\"]", 2, "require(...)"),
    ],
    "tradovate-indicator": [
        (r"\bcalculator\s*:", 5, "calculator: in module.exports"),
        (r"\bmap\s*\(\s*d\b", 4, "map(d, ...) calculator method"),
        (r"\bpredef\.(paramSpecs|styles|filters)", 5, "predef.paramSpecs/styles"),
        (r"\bmeta\.(InputType|ParamType|HistogramDisplay)", 4, "meta.* definitions"),
        (r"\bd\.(value|close|high|low|open|volume)\s*\(\s*\)", 3, "d.value()/d.close() bar accessors"),
        (r"require\s*\(\s*['\"]\./tools/", 4, "require('./tools/...') Tradovate helpers"),
        (r"\bhistory\.(prior|back)\s*\(", 3, "history.prior()/back()"),
    ],
    "tradovate-strategy": [
        (r"extends\s+Strategy\b", 5, "class extends Strategy"),
        (r"\bTdEvent\.\w+", 6, "TdEvent.* events"),
        (r"orderStrategy/startOrderStrategy|order/placeOrder", 5, "Tradovate order endpoints"),
        (r"\bLongShortMode\b", 3, "LongShortMode"),
        (r"\bnext\s*\(\s*\w+\s*,\s*\[\s*event\s*,\s*payload\s*\]\s*\)", 5, "next(state, [event, payload])"),
        (r"\bDataBuffer\b|\bBarsTransformer\b", 3, "DataBuffer / BarsTransformer"),
        (r"\bdispatcher\b", 1, "dispatcher"),
    ],
    "javascript": [
        (r"\bonBar\s*[(:]", 5, "onBar handler"),
        (r"\bctx\.(buy|sell|exit|ta\.)", 4, "ctx.buy/sell API"),
    ],
}

EXT_HINTS = {
    ".pine": ("pine", 4), ".pinescript": ("pine", 4), ".mq4": ("mql4", 5), ".mq5": ("mql5", 5),
    ".mqh": ("mql5", 1), ".py": ("python", 4), ".js": ("_js", 3), ".mjs": ("_js", 3),
    ".json": ("rules-json", 3), ".yaml": ("rules-yaml", 3), ".yml": ("rules-yaml", 3),
}

RULE_KEYS = {"entry_long", "entry_short", "exit_long", "exit_short", "entry", "exit", "indicators", "stop_loss",
             "take_profit"}


def _score(text: str, sigs) -> tuple[float, list[str]]:
    total = 0.0
    ev = []
    for pat, w, label in sigs:
        if re.search(pat, text, re.MULTILINE):
            total += w
            ev.append(label)
    return total, ev


def _strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    return src


def detect(source: str, filename: str = "") -> dict:
    text = _strip_comments(source)[:200_000]
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    scores: dict[str, float] = {}
    evidence: dict[str, list[str]] = {}

    # structured rule files first: a parseable object with rule keys is unambiguous
    stripped = source.strip()
    if stripped.startswith("{"):
        try:
            obj = json.loads(stripped)
            if isinstance(obj, dict) and RULE_KEYS & set(obj):
                return _result("rules-json", 0.97, ["JSON object with " + ", ".join(sorted(RULE_KEYS & set(obj)))], {})
        except ValueError:
            pass
    if ext in (".yaml", ".yml") or re.search(r"^(entry_long|entry|indicators)\s*:", source, re.M):
        try:
            import yaml
            obj = yaml.safe_load(source)
            if isinstance(obj, dict) and RULE_KEYS & set(obj):
                return _result("rules-yaml", 0.95, ["YAML mapping with " + ", ".join(sorted(RULE_KEYS & set(obj)))], {})
        except Exception:
            pass

    for key in ("pine", "mql4", "mql5", "_mql_common", "python", "python-native", "backtesting.py", "backtrader",
                "_js", "tradovate-indicator", "tradovate-strategy", "javascript"):
        scores[key], evidence[key] = _score(text, SIGS[key])
    if ext in EXT_HINTS:
        k, w = EXT_HINTS[ext]
        scores[k] = scores.get(k, 0) + w
        evidence.setdefault(k, []).append(f"{ext} extension")

    # fold the shared groups into the concrete types
    for k in ("mql4", "mql5"):
        scores[k] += scores["_mql_common"]
        evidence[k] += evidence["_mql_common"]
    if ext == ".mq4":
        scores["mql5"] -= 4
    if ext == ".mq5":
        scores["mql4"] -= 4
    for k in ("python-native", "backtesting.py", "backtrader"):
        if scores[k] > 0:
            scores[k] += scores["python"]
            evidence[k] = evidence["python"] + evidence[k]
    if max(scores["python-native"], scores["backtesting.py"], scores["backtrader"]) == 0 and scores["python"] >= 6:
        scores["python-native"] = scores["python"] * 0.6
        evidence["python-native"] = evidence["python"] + ["no on_bar(): will look for next()/onBar"]
    for k in ("tradovate-indicator", "tradovate-strategy", "javascript"):
        if scores[k] > 0:
            scores[k] += scores["_js"]
            evidence[k] = evidence["_js"] + evidence[k]
    if scores["javascript"] == 0 and scores["_js"] >= 5 and max(scores["tradovate-indicator"], scores["tradovate-strategy"]) == 0:
        scores["javascript"] = scores["_js"] * 0.6
        evidence["javascript"] = evidence["_js"]
    # Pine `//` comments and `:=` look like other languages; penalise Pine when C/JS structure is strong
    if scores["_mql_common"] >= 5 or scores["_js"] >= 5:
        scores["pine"] -= 3

    candidates = {k: v for k, v in scores.items() if not k.startswith("_") and k != "python"}
    ranked = sorted(candidates.items(), key=lambda kv: kv[1], reverse=True)
    best, top = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0
    if top < 4:
        return _result("unknown", 0.0, [], {k: round(v, 1) for k, v in ranked[:4]})
    conf = min(0.99, 0.5 + 0.5 * (top - max(second, 0)) / max(top, 1)) if top >= 8 else min(0.75, top / 10)
    return _result(best, round(conf, 2), evidence.get(best, []), {k: round(v, 1) for k, v in ranked[:4] if v > 0})


def _result(kind: str, conf: float, ev: list[str], alts: dict) -> dict:
    return {"type": kind, "label": TYPES.get(kind, "Unknown"), "confidence": conf, "evidence": ev,
            "scores": alts, "pineVersion": None}


def pine_version(source: str) -> int | None:
    m = re.search(r"//\s*@version\s*=\s*(\d+)", source)
    return int(m.group(1)) if m else None
