"""Pine built-in variables and functions."""

from __future__ import annotations

import math
import random
from collections import deque
from datetime import datetime, timezone

from ... import indicators as ind
from ...errors import ScriptError, UnsupportedFeature
from .runtime import NA, is_na, truthy

BUILTINS: dict = {}
_LITERALS = {"NA": NA, "na": NA, "True": True, "False": False, "None": None}


def _literal(text: str):
    """Default values in @bi(params=...) specs: NA/True/False/None or a number/string literal."""
    if text in _LITERALS:
        return _LITERALS[text]
    import ast
    return ast.literal_eval(text)


def bi(*names, params: str = ""):
    """Register a built-in. ``params`` lists positional parameter names (``name=default`` allowed)."""
    spec = []
    for p in params.split():
        if "=" in p:
            k, v = p.split("=", 1)
            spec.append((k, _literal(v)))
        else:
            spec.append((p, NA))

    def deco(fn):
        def wrapper(rt, nid, args, kw, node, fn=fn, spec=spec):
            if spec:
                vals = {}
                for i, (k, d) in enumerate(spec):
                    if i < len(args):
                        vals[k] = args[i]
                    elif k in kw:
                        vals[k] = kw[k]
                    else:
                        vals[k] = d
                for k, v in kw.items():
                    if k not in vals:
                        vals[k] = v
                return fn(rt, nid, vals, node)
            return fn(rt, nid, args, kw, node)
        for n in names:
            BUILTINS[n] = wrapper
        return fn
    return deco


def _st(rt, nid, factory):
    st = rt.frame.state
    s = st.get(nid)
    if s is None:
        s = st[nid] = factory()
    return s


def _int(v, default=NA):
    if is_na(v):
        return default
    return int(v)


def _f(v):
    return NA if v is None else float(v)


# ============================================================================ ta.*
def _length_state(rt, nid, cls, length):
    L = _int(length, 1)
    st = rt.frame.state.get(nid)
    if st is None or st[0] != L:
        st = rt.frame.state[nid] = (L, cls(L))
    return st[1]


@bi("ta.sma", params="source length")
def _sma(rt, nid, a, node):
    return _length_state(rt, nid, ind.SMA, a["length"]).update(_f(a["source"]))


@bi("ta.ema", params="source length")
def _ema(rt, nid, a, node):
    return _length_state(rt, nid, ind.EMA, a["length"]).update(_f(a["source"]))


@bi("ta.rma", params="source length")
def _rma(rt, nid, a, node):
    return _length_state(rt, nid, ind.RMA, a["length"]).update(_f(a["source"]))


@bi("ta.wma", params="source length")
def _wma(rt, nid, a, node):
    return _length_state(rt, nid, ind.WMA, a["length"]).update(_f(a["source"]))


@bi("ta.vwma", params="source length")
def _vwma(rt, nid, a, node):
    return _length_state(rt, nid, ind.VWMA, a["length"]).update(_f(a["source"]), rt.host.bars.volume[rt.i])


class _HMA:
    def __init__(self, n):
        self.a = ind.WMA(max(1, n // 2))
        self.b = ind.WMA(n)
        self.c = ind.WMA(max(1, int(math.floor(math.sqrt(n)))))

    def update(self, x):
        a, b = self.a.update(x), self.b.update(x)
        if math.isnan(a) or math.isnan(b):
            self.c.update(NA)
            return NA
        return self.c.update(2 * a - b)


@bi("ta.hma", params="source length")
def _hma(rt, nid, a, node):
    return _length_state(rt, nid, _HMA, a["length"]).update(_f(a["source"]))


@bi("ta.rsi", params="source length")
def _rsi(rt, nid, a, node):
    return _length_state(rt, nid, ind.RSI, a["length"]).update(_f(a["source"]))


@bi("ta.atr", params="length")
def _atr(rt, nid, a, node):
    b, i = rt.host.bars, rt.i
    return _length_state(rt, nid, ind.ATR, a["length"]).update(b.high[i], b.low[i], b.close[i])


@bi("ta.tr", params="handle_na=False")
def _trf(rt, nid, a, node):
    b, i = rt.host.bars, rt.i
    if i == 0:
        return (b.high[0] - b.low[0]) if a["handle_na"] else NA
    pc = b.close[i - 1]
    return max(b.high[i] - b.low[i], abs(b.high[i] - pc), abs(b.low[i] - pc))


@bi("ta.stdev", params="source length biased=True")
def _stdev(rt, nid, a, node):
    L = _int(a["length"], 1)
    st = _st(rt, nid, lambda: ind.Stdev(L, bool(a["biased"])))
    return st.update(_f(a["source"]))


@bi("ta.variance", params="source length biased=True")
def _variance(rt, nid, a, node):
    v = _stdev(rt, nid, a, node)
    return v * v if not is_na(v) else NA


@bi("ta.dev", params="source length")
def _dev(rt, nid, a, node):
    L = _int(a["length"], 1)
    buf = _st(rt, nid, lambda: deque(maxlen=L))
    buf.append(_f(a["source"]))
    if len(buf) < L:
        return NA
    m = sum(buf) / L
    return sum(abs(x - m) for x in buf) / L


def _two_form(args, kw):
    """Normalise ta.highest(length) / ta.highest(source, length) argument forms."""
    if len(args) == 1 and "length" not in kw:
        return None, args[0]
    if len(args) >= 2:
        return args[0], args[1]
    return kw.get("source", args[0] if args else None), kw.get("length", args[0] if args else NA)


def _register_hl():
    def make(use_max, field, bars_mode=False):
        def fn(rt, nid, args, kw, node):
            src, length = _two_form(args, kw)
            if src is None:
                src = getattr(rt.host.bars, field)[rt.i]
            L = _int(length, 1)
            st = rt.frame.state.get(nid)
            if st is None:
                st = rt.frame.state[nid] = deque(maxlen=L)
            st.append(_f(src))
            if len(st) < L:
                return NA
            vals = list(st)
            if bars_mode:
                best = max(vals) if use_max else min(vals)
                # offset (<= 0) of the extreme bar, latest occurrence
                for k in range(len(vals) - 1, -1, -1):
                    if vals[k] == best:
                        return -(len(vals) - 1 - k)
                return NA
            vals = [v for v in vals if not is_na(v)]
            return (max(vals) if use_max else min(vals)) if vals else NA
        return fn
    for prefix in ("ta.", ""):
        BUILTINS[prefix + "highest"] = make(True, "high")
        BUILTINS[prefix + "lowest"] = make(False, "low")
        BUILTINS[prefix + "highestbars"] = make(True, "high", True)
        BUILTINS[prefix + "lowestbars"] = make(False, "low", True)


_register_hl()


@bi("ta.crossover", params="source1 source2")
def _crossover(rt, nid, a, node):
    return _st(rt, nid, ind.Cross).update(_f(a["source1"]), _f(a["source2"]))[0]


@bi("ta.crossunder", params="source1 source2")
def _crossunder(rt, nid, a, node):
    return _st(rt, nid, ind.Cross).update(_f(a["source1"]), _f(a["source2"]))[1]


@bi("ta.cross", params="source1 source2")
def _cross(rt, nid, a, node):
    u, d = _st(rt, nid, ind.Cross).update(_f(a["source1"]), _f(a["source2"]))
    return u or d


@bi("ta.change", params="source length=1")
def _change(rt, nid, a, node):
    src = a["source"]
    L = _int(a["length"], 1)
    buf = _st(rt, nid, lambda: deque(maxlen=L + 1))
    if isinstance(src, bool):
        buf.append(src)
        return len(buf) > L and buf[-1] != buf[0]
    buf.append(_f(src))
    if len(buf) <= L:
        return NA
    return buf[-1] - buf[0]


@bi("ta.mom", params="source length")
def _mom(rt, nid, a, node):
    return _change(rt, nid, a, node)


@bi("ta.roc", params="source length")
def _roc(rt, nid, a, node):
    return _length_state(rt, nid, ind.ROC, a["length"]).update(_f(a["source"]))


def _macd_entry(rt, nid, args, kw, node):
    src = args[0] if len(args) > 0 else kw.get("source")
    fast = args[1] if len(args) > 1 else kw.get("fastlen", 12)
    slow = args[2] if len(args) > 2 else kw.get("slowlen", 26)
    sig = args[3] if len(args) > 3 else kw.get("siglen", kw.get("signallen", 9))
    st = _st(rt, nid, lambda: ind.MACD(_int(fast, 12), _int(slow, 26), _int(sig, 9)))
    return st.update(_f(src))


BUILTINS["ta.macd"] = _macd_entry
BUILTINS["macd"] = _macd_entry


@bi("ta.bb", params="series length mult")
def _bb(rt, nid, a, node):
    st = _st(rt, nid, lambda: ind.Bollinger(_int(a["length"], 20), _f(a["mult"])))
    return st.update(_f(a["series"]))


@bi("ta.bbw", params="series length mult")
def _bbw(rt, nid, a, node):
    m, u, l = _bb(rt, nid, a, node)
    return (u - l) / m * 100 if not is_na(m) and m else NA


@bi("ta.stoch", params="source high low length")
def _stoch(rt, nid, a, node):
    st = _st(rt, nid, lambda: ind.Stoch(_int(a["length"], 14)))
    return st.update(_f(a["source"]), _f(a["high"]), _f(a["low"]))


@bi("ta.cci", params="source length")
def _cci(rt, nid, a, node):
    return _length_state(rt, nid, ind.CCI, a["length"]).update(_f(a["source"]))


@bi("ta.supertrend", params="factor atrPeriod")
def _supertrend(rt, nid, a, node):
    b, i = rt.host.bars, rt.i
    st = _st(rt, nid, lambda: ind.SuperTrend(_f(a["factor"]), _int(a["atrPeriod"], 10)))
    v, d = st.update(b.high[i], b.low[i], b.close[i])
    return (v, d if d else NA)


@bi("ta.cum", params="source")
def _cum(rt, nid, a, node):
    st = _st(rt, nid, lambda: [0.0])
    v = _f(a["source"])
    if not is_na(v):
        st[0] += v
    return st[0]


@bi("math.sum", "sum", params="source length")
def _msum(rt, nid, a, node):
    L = _int(a["length"], 1)
    buf = _st(rt, nid, lambda: deque(maxlen=L))
    buf.append(_f(a["source"]))
    if len(buf) < L or any(is_na(x) for x in buf):
        return NA
    return math.fsum(buf)


@bi("ta.rising", params="source length")
def _rising(rt, nid, a, node):
    L = _int(a["length"], 1)
    buf = _st(rt, nid, lambda: deque(maxlen=L + 1))
    buf.append(_f(a["source"]))
    if len(buf) <= L:
        return False
    cur = buf[-1]
    return all(cur > x for x in list(buf)[:-1])


@bi("ta.falling", params="source length")
def _falling(rt, nid, a, node):
    L = _int(a["length"], 1)
    buf = _st(rt, nid, lambda: deque(maxlen=L + 1))
    buf.append(_f(a["source"]))
    if len(buf) <= L:
        return False
    cur = buf[-1]
    return all(cur < x for x in list(buf)[:-1])


@bi("ta.barssince", params="condition")
def _barssince(rt, nid, a, node):
    st = _st(rt, nid, lambda: [None])
    if truthy(a["condition"]):
        st[0] = rt.i
    return NA if st[0] is None else rt.i - st[0]


@bi("ta.valuewhen", params="condition source occurrence=0")
def _valuewhen(rt, nid, a, node):
    st = _st(rt, nid, list)
    if truthy(a["condition"]):
        st.append(a["source"])
        if len(st) > 500:
            del st[0]
    k = _int(a["occurrence"], 0)
    return st[-1 - k] if len(st) > k else NA


def _pivot(rt, nid, args, kw, is_high):
    if len(args) == 2 or (len(args) < 3 and "source" not in kw):
        src = rt.host.bars.high[rt.i] if is_high else rt.host.bars.low[rt.i]
        left = args[0] if args else kw.get("leftbars")
        right = args[1] if len(args) > 1 else kw.get("rightbars")
    else:
        src = args[0] if args else kw.get("source")
        left = args[1] if len(args) > 1 else kw.get("leftbars")
        right = args[2] if len(args) > 2 else kw.get("rightbars")
    L, R = _int(left, 1), _int(right, 1)
    buf = _st(rt, nid, lambda: deque(maxlen=L + R + 1))
    buf.append(_f(src))
    if len(buf) < L + R + 1:
        return NA
    vals = list(buf)
    c = vals[L]
    if is_na(c):
        return NA
    others = vals[:L] + vals[L + 1:]
    if is_high:
        ok = all(c > x for x in vals[:L]) and all(c >= x for x in vals[L + 1:])
    else:
        ok = all(c < x for x in vals[:L]) and all(c <= x for x in vals[L + 1:])
    return c if ok and not any(is_na(x) for x in others) else NA


BUILTINS["ta.pivothigh"] = lambda rt, nid, args, kw, node: _pivot(rt, nid, args, kw, True)
BUILTINS["ta.pivotlow"] = lambda rt, nid, args, kw, node: _pivot(rt, nid, args, kw, False)


@bi("ta.linreg", params="source length offset=0")
def _linreg(rt, nid, a, node):
    L = _int(a["length"], 1)
    buf = _st(rt, nid, lambda: deque(maxlen=L))
    buf.append(_f(a["source"]))
    if len(buf) < L:
        return NA
    ys = list(buf)
    n = L
    xs = list(range(n))
    mx, my = sum(xs) / n, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den if den else 0.0
    inter = my - slope * mx
    return inter + slope * (n - 1 - _int(a["offset"], 0))


@bi("ta.percentrank", params="source length")
def _percentrank(rt, nid, a, node):
    L = _int(a["length"], 1)
    buf = _st(rt, nid, lambda: deque(maxlen=L + 1))
    buf.append(_f(a["source"]))
    if len(buf) <= L:
        return NA
    cur = buf[-1]
    return sum(1 for x in list(buf)[:-1] if x <= cur) / L * 100


class _DMI:
    def __init__(self, di_len, adx_len):
        self.tr = ind.RMA(di_len)
        self.p = ind.RMA(di_len)
        self.m = ind.RMA(di_len)
        self.adx = ind.RMA(adx_len)
        self.prev = None

    def update(self, h, l, c):
        if self.prev is None:
            self.prev = (h, l, c)
            return NA, NA, NA
        ph, pl, pc = self.prev
        self.prev = (h, l, c)
        up, down = h - ph, pl - l
        plus = up if up > down and up > 0 else 0.0
        minus = down if down > up and down > 0 else 0.0
        tr = max(h - l, abs(h - pc), abs(l - pc))
        t = self.tr.update(tr)
        p = self.p.update(plus)
        m = self.m.update(minus)
        if math.isnan(t) or t == 0:
            return NA, NA, NA
        pdi, mdi = 100 * p / t, 100 * m / t
        s = pdi + mdi
        adx = self.adx.update(100 * abs(pdi - mdi) / (s if s else 1))
        return pdi, mdi, adx


@bi("ta.dmi", params="diLength adxSmoothing")
def _dmi(rt, nid, a, node):
    b, i = rt.host.bars, rt.i
    st = _st(rt, nid, lambda: _DMI(_int(a["diLength"], 14), _int(a["adxSmoothing"], 14)))
    return st.update(b.high[i], b.low[i], b.close[i])


@bi("ta.vwap", params="source=NA anchor=NA")
def _vwap_fn(rt, nid, a, node):
    b, i = rt.host.bars, rt.i
    src = a["source"]
    if is_na(src):
        src = (b.high[i] + b.low[i] + b.close[i]) / 3
    st = _st(rt, nid, lambda: [None, 0.0, 0.0])
    day = int(b.time[i] // 86_400_000)
    if st[0] != day:
        st[0], st[1], st[2] = day, 0.0, 0.0
    st[1] += src * b.volume[i]
    st[2] += b.volume[i]
    return st[1] / st[2] if st[2] else src


@bi("fixnan", params="source")
def _fixnan(rt, nid, a, node):
    st = _st(rt, nid, lambda: [NA])
    v = a["source"]
    if not is_na(v):
        st[0] = v
    return st[0]


# ============================================================================ math / misc
@bi("nz", params="source replacement=0")
def _nz(rt, nid, a, node):
    return a["replacement"] if is_na(a["source"]) else a["source"]


@bi("na", params="x")
def _na(rt, nid, a, node):
    return is_na(a["x"])


def _simple(name, f):
    def fn(rt, nid, args, kw, node):
        try:
            if any(is_na(x) for x in args):
                return NA
            return f(*args, **kw)
        except (ValueError, OverflowError, ZeroDivisionError):
            return NA
    BUILTINS[name] = fn


for _n, _fn in {
    "abs": abs, "sqrt": math.sqrt, "exp": math.exp, "floor": math.floor, "ceil": math.ceil,
    "log": math.log, "log10": math.log10, "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan, "pow": math.pow,
    "sign": lambda x: (x > 0) - (x < 0), "todegrees": math.degrees, "toradians": math.radians,
}.items():
    _simple("math." + _n, _fn)


def _round(x, precision=None):
    if precision is None or is_na(precision):
        return int(math.floor(x + 0.5)) if x >= 0 else -int(math.floor(-x + 0.5))
    m = 10 ** int(precision)
    return math.floor(x * m + 0.5) / m


_simple("math.round", _round)


def _varargs(name, f):
    def fn(rt, nid, args, kw, node):
        vals = [x for x in args if not is_na(x)]
        if len(vals) != len(args):
            return NA
        return f(vals) if vals else NA
    BUILTINS[name] = fn


_varargs("math.max", max)
_varargs("math.min", min)
_varargs("math.avg", lambda v: sum(v) / len(v))
BUILTINS["math.random"] = lambda rt, nid, args, kw, node: random.uniform(args[0] if args else 0, args[1] if len(args) > 1 else 1)
BUILTINS["math.round_to_mintick"] = lambda rt, nid, args, kw, node: (
    NA if is_na(args[0]) else round(args[0] / rt.host.mintick) * rt.host.mintick)


@bi("iff", params="condition then _else")
def _iff(rt, nid, a, node):
    return a["then"] if truthy(a["condition"]) else a["_else"]


def _cast(f):
    def fn(rt, nid, args, kw, node):
        x = args[0] if args else kw.get("x")
        if is_na(x):
            return NA
        return f(x)
    return fn


BUILTINS["int"] = _cast(lambda x: int(x))
BUILTINS["float"] = _cast(float)
BUILTINS["bool"] = _cast(truthy)
BUILTINS["string"] = _cast(str)


def _tostring(rt, nid, args, kw, node):
    v = args[0] if args else kw.get("value")
    if is_na(v):
        return "NaN"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v)) if abs(v) < 1e15 else str(v)
    return str(v)


BUILTINS["str.tostring"] = _tostring
BUILTINS["tostring"] = _tostring


def _format(rt, nid, args, kw, node):
    fmt = str(args[0]) if args else ""
    vals = args[1:]
    for k, v in enumerate(vals):
        fmt = fmt.replace("{%d}" % k, _tostring(rt, nid, [v], {}, node))
        fmt = __import__("re").sub(r"\{%d,[^}]*\}" % k, _tostring(rt, nid, [v], {}, node), fmt)
    return fmt


BUILTINS["str.format"] = _format
BUILTINS["str.length"] = lambda rt, nid, args, kw, node: len(args[0]) if args[0] else 0
BUILTINS["str.contains"] = lambda rt, nid, args, kw, node: (args[1] in args[0]) if args[0] and args[1] else False
BUILTINS["str.upper"] = lambda rt, nid, args, kw, node: str(args[0]).upper()
BUILTINS["str.lower"] = lambda rt, nid, args, kw, node: str(args[0]).lower()
BUILTINS["str.substring"] = lambda rt, nid, args, kw, node: str(args[0])[int(args[1]):(int(args[2]) if len(args) > 2 else None)]
BUILTINS["str.tonumber"] = lambda rt, nid, args, kw, node: _safe_float(args[0])
BUILTINS["str.replace_all"] = lambda rt, nid, args, kw, node: str(args[0]).replace(str(args[1]), str(args[2]))
BUILTINS["str.startswith"] = lambda rt, nid, args, kw, node: str(args[0]).startswith(str(args[1]))
BUILTINS["str.endswith"] = lambda rt, nid, args, kw, node: str(args[0]).endswith(str(args[1]))


def _safe_float(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return NA


# ============================================================================ time
def _dt(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def _time_part(attr):
    def fn(rt, nid, args, kw, node):
        t = args[0] if args else kw.get("time", rt.host.bars.time[rt.i])
        if is_na(t):
            return NA
        d = _dt(t)
        if attr == "dayofweek":
            return (d.isoweekday() % 7) + 1  # Pine: Sunday=1 .. Saturday=7
        if attr == "weekofyear":
            return d.isocalendar()[1]
        return getattr(d, attr)
    return fn


for _a, _p in {"year": "year", "month": "month", "dayofmonth": "day", "dayofweek": "dayofweek", "hour": "hour",
               "minute": "minute", "second": "second", "weekofyear": "weekofyear"}.items():
    BUILTINS[_a] = _time_part(_p)


def _timestamp(rt, nid, args, kw, node):
    nums = [a for a in args if isinstance(a, (int, float)) and not isinstance(a, bool)]
    if args and isinstance(args[0], str) and len(nums) < 3:
        if len(args) == 1:
            try:
                return int(datetime.fromisoformat(args[0].replace("Z", "+00:00")).timestamp() * 1000)
            except ValueError:
                import pandas as pd
                return int(pd.Timestamp(args[0], tz="UTC").as_unit("ms").value)
    y, mo, d = int(nums[0]), int(nums[1]), int(nums[2])
    h = int(nums[3]) if len(nums) > 3 else 0
    mi = int(nums[4]) if len(nums) > 4 else 0
    s = int(nums[5]) if len(nums) > 5 else 0
    return int(datetime(y, mo, d, h, mi, s, tzinfo=timezone.utc).timestamp() * 1000)


BUILTINS["timestamp"] = _timestamp


# ============================================================================ arrays
class PineArray:
    __slots__ = ("items",)

    def __init__(self, items=None):
        self.items = list(items or [])

    def __repr__(self):
        return f"array{self.items[:5]}"


def _arr_new(rt, nid, args, kw, node):
    size = _int(args[0] if args else kw.get("size", 0), 0)
    init = args[1] if len(args) > 1 else kw.get("initial_value", NA)
    return PineArray([init] * size)


for _t in ("new_float", "new_int", "new_bool", "new_string", "new_color", "new_line", "new_label", "new_box", "new"):
    BUILTINS["array." + _t] = _arr_new
BUILTINS["array.from"] = lambda rt, nid, args, kw, node: PineArray(args)


def _arr(fn):
    def w(rt, nid, args, kw, node):
        a = args[0]
        if not isinstance(a, PineArray):
            raise ScriptError("Array function called on something that isn't an array (or is na).", line=node.line)
        return fn(a.items, *args[1:])
    return w


def _aget(items, i):
    i = int(i)
    if i < 0:
        i += len(items)
    if not 0 <= i < len(items):
        raise ScriptError(f"Array index {i} is out of bounds (size {len(items)}).")
    return items[i]


def _aset(items, i, v):
    items[int(i)] = v


ARRAY_FNS = {
    "push": lambda it, v: it.append(v), "unshift": lambda it, v: it.insert(0, v),
    "pop": lambda it: it.pop() if it else NA, "shift": lambda it: it.pop(0) if it else NA,
    "get": _aget, "set": _aset, "size": lambda it: len(it), "clear": lambda it: it.clear(),
    "sum": lambda it: math.fsum(x for x in it if not is_na(x)),
    "avg": lambda it: (math.fsum(x for x in it if not is_na(x)) / len([x for x in it if not is_na(x)])) if any(not is_na(x) for x in it) else NA,
    "max": lambda it, n=0: sorted([x for x in it if not is_na(x)], reverse=True)[int(n)] if it else NA,
    "min": lambda it, n=0: sorted([x for x in it if not is_na(x)])[int(n)] if it else NA,
    "first": lambda it: it[0] if it else NA, "last": lambda it: it[-1] if it else NA,
    "includes": lambda it, v: v in it, "indexof": lambda it, v: it.index(v) if v in it else -1,
    "remove": lambda it, i: it.pop(int(i)), "insert": lambda it, i, v: it.insert(int(i), v),
    "copy": lambda it: PineArray(it), "slice": lambda it, a, b=None: PineArray(it[int(a):(int(b) if b is not None else None)]),
    "reverse": lambda it: it.reverse(), "sort": lambda it, order=None: it.sort(reverse=(order == "descending")),
    "stdev": lambda it: float(__import__("numpy").std([x for x in it if not is_na(x)])) if it else NA,
    "median": lambda it: float(__import__("numpy").median([x for x in it if not is_na(x)])) if it else NA,
    "fill": lambda it, v, a=0, b=None: it.__setitem__(slice(int(a), int(b) if b is not None else None), [v] * len(it[int(a):(int(b) if b is not None else None)])),
    "concat": lambda it, other: (it.extend(other.items), PineArray(it))[1],
    "join": lambda it, sep=",": str(sep).join(str(x) for x in it),
}
for _n, _fn in ARRAY_FNS.items():
    BUILTINS["array." + _n] = _arr(_fn)


# ============================================================================ output / no-ops
def _plot(rt, nid, args, kw, node):
    series = args[0] if args else kw.get("series")
    title = (args[1] if len(args) > 1 else kw.get("title")) or f"Plot {node.line}"
    color = args[2] if len(args) > 2 else kw.get("color")
    rt.host.plot(str(title), series, color if isinstance(color, str) else None, kw)
    return NA


BUILTINS["plot"] = _plot


def _hline(rt, nid, args, kw, node):
    price = args[0] if args else kw.get("price")
    title = (args[1] if len(args) > 1 else kw.get("title")) or f"Level {price}"
    rt.host.plot(str(title), price, None, {"_hline": True})
    return NA


BUILTINS["hline"] = _hline


def _noop(rt, nid, args, kw, node):
    return NA


for _n in ("plotshape", "plotchar", "plotarrow", "plotcandle", "plotbar", "bgcolor", "barcolor", "fill",
           "alertcondition", "label.new", "label.delete", "label.set_text", "label.set_xy", "label.set_color",
           "label.set_y", "label.set_x", "line.new", "line.delete", "line.set_xy1", "line.set_xy2", "line.set_x2",
           "line.set_y1", "line.set_y2", "line.set_color", "line.set_extend", "box.new", "box.delete",
           "box.set_right", "box.set_left", "box.set_top", "box.set_bottom", "box.set_bgcolor",
           "table.new", "table.cell", "table.delete", "table.clear", "table.cell_set_text",
           "linefill.new", "max_bars_back", "library", "runtime.error"):
    BUILTINS[_n] = _noop


def _color_fn(rt, nid, args, kw, node):
    return args[0] if args else NA


for _n in ("color.new", "color.rgb", "color.from_gradient"):
    BUILTINS[_n] = _color_fn
BUILTINS["color.r"] = BUILTINS["color.g"] = BUILTINS["color.b"] = BUILTINS["color.t"] = lambda *a: NA


def _logmsg(kind):
    def fn(rt, nid, args, kw, node):
        msg = args[0] if args else kw.get("message", "")
        if len(args) > 1:
            msg = _format(rt, nid, args, kw, node)
        rt.host.ctx.log("log", f"{kind}{msg}")
        return NA
    return fn


BUILTINS["log.info"] = _logmsg("")
BUILTINS["log.warning"] = _logmsg("[warning] ")
BUILTINS["log.error"] = _logmsg("[error] ")
BUILTINS["alert"] = _logmsg("[alert] ")


def _runtime_error(rt, nid, args, kw, node):
    raise ScriptError(f"runtime.error: {args[0] if args else ''}", line=node.line)


BUILTINS["runtime.error"] = _runtime_error


# ============================================================================ inputs
def _input(kind):
    def fn(rt, nid, args, kw, node):
        defval = args[0] if args else kw.get("defval", NA)
        title = kw.get("title") or (args[1] if len(args) > 1 and isinstance(args[1], str) else None)
        return rt.host.input_value(node.nid, title, defval, kind, kw)
    return fn


for _k in ("int", "float", "bool", "string", "source", "color", "timeframe", "symbol", "session", "price",
           "time", "text_area", "enum"):
    BUILTINS["input." + _k] = _input(_k)
BUILTINS["input"] = _input("any")


def register_strategy(builtins: dict, host) -> None:
    """strategy.* functions bound to the adapter (broker access)."""
    from .strategy_api import make_strategy_builtins
    builtins.update(make_strategy_builtins(host))


def unsupported(name: str):
    def fn(rt, nid, args, kw, node):
        raise UnsupportedFeature(f"{name}() isn't supported.", line=node.line)
    return fn


BUILTINS["request.security"] = unsupported("request.security")
BUILTINS["security"] = unsupported("security")
