"""Pine Script (v4/v5/v6 strategy & indicator subset) -> Python, executed bar-by-bar with Pine semantics.

Pipeline: tokenizer -> indentation-aware parser -> Python source (kept in the harness copy for inspection) -> run.
Semantics implemented:
  * every variable is a series: x[1] is last bar's value; `var`/`varip` persist, plain declarations recompute each bar
  * ta.* / math.* / input.* / strategy.* / nz / na / fixnan, tuples [a, b] = f(), ternaries, switch, for/while, => functions
  * each ta.* call site keeps its own state (like Pine), so ta calls inside `if` blocks behave correctly
  * strategy.entry/close/close_all/exit(stop, limit, profit, loss) -> target positions; orders fill next bar open
Not executable: request.security of other symbols/timeframes, drawings (ignored), arrays/matrices/maps beyond basics.
"""
from __future__ import annotations

import math
import re
from collections import deque

import numpy as np
import pandas as pd

NA = float("nan")


class PineError(ValueError):
    pass


# ======================= tokenizer =======================
TOKEN = re.compile(r"""
 (?P<ws>[ \t]+) | (?P<comment>//[^\n]*) | (?P<nl>\n) |
 (?P<num>\d+\.\d*(?:[eE][-+]?\d+)?|\.\d+(?:[eE][-+]?\d+)?|\d+(?:[eE][-+]?\d+)?) |
 (?P<str>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*') |
 (?P<color>\#[0-9a-fA-F]{6,8}) |
 (?P<op>:=|=>|==|!=|<=|>=|\+=|-=|\*=|/=|%=|[-+*/%<>=?:,()\[\].]) |
 (?P<name>[A-Za-z_][A-Za-z0-9_]*)
""", re.X)
KEYWORDS = {"if", "else", "for", "to", "by", "while", "var", "varip", "and", "or", "not", "true", "false", "na",
            "switch", "break", "continue", "in", "import", "export", "method", "type"}
TYPES = {"int", "float", "bool", "string", "color", "series", "simple", "const", "line", "label", "box", "table", "array"}


def tokenize(src: str) -> list[list]:
    """Returns logical lines: [indent, [tokens...]]. Continuation lines (indent not a multiple of 4 / open brackets) are joined."""
    src = src.replace("\r\n", "\n").replace("\t", "    ")
    lines: list[list] = []
    for raw in src.split("\n"):
        if not raw.strip() or raw.strip().startswith("//"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        toks, pos = [], 0
        body = raw.lstrip(" ")
        while pos < len(body):
            m = TOKEN.match(body, pos)
            if not m:
                raise PineError(f"unexpected character {body[pos]!r} in: {raw.strip()}")
            pos = m.end()
            kind = m.lastgroup
            if kind in ("ws", "comment", "nl"):
                continue
            toks.append((kind, m.group()))
        if not toks:
            continue
        if toks[0] == ("op", "@") or (toks[0][0] == "name" and toks[0][1] in ("indicator", "study", "strategy", "library")
                                       and len(toks) > 1 and toks[1] == ("op", "(")):
            lines.append([indent, toks, True])  # declaration
            continue
        prev = lines[-1] if lines else None
        cont = prev is not None and (_open_brackets(prev[1]) > 0 or prev[1][-1][1] in (",", "+", "-", "*", "/", "and", "or", "?", ":", "=", ":=", "=>")
                                     or (indent % 4 != 0 and indent > prev[0]))
        if cont and not (prev[1][-1][1] == "=>" and indent > prev[0] and indent % 4 == 0):
            prev[1].extend(toks)
        else:
            lines.append([indent, toks, False])
    return lines


def _open_brackets(toks) -> int:
    n = 0
    for k, v in toks:
        if v in ("(", "["):
            n += 1
        elif v in (")", "]"):
            n -= 1
    return n


# ======================= expression parser -> python =======================
PREC = {"or": 1, "and": 2, "==": 4, "!=": 4, "<": 5, ">": 5, "<=": 5, ">=": 5, "+": 6, "-": 6, "*": 7, "/": 7, "%": 7}
NAMESPACES = {"ta", "math", "strategy", "input", "str", "color", "request", "array", "timeframe", "syminfo", "barstate",
              "session", "plot", "hline", "location", "shape", "size", "position", "display", "line", "label", "box",
              "table", "alert", "extend", "xloc", "yloc", "format", "currency", "dayofweek", "order", "scale", "text",
              "font", "adjustment", "barmerge", "ticker", "matrix", "map", "runtime", "log", "chart", "polyline",
              "earnings", "dividends", "splits", "math"}
BUILTIN_SERIES = {"open", "high", "low", "close", "volume", "hl2", "hlc3", "ohlc4", "hlcc4", "bar_index", "time",
                  "time_close", "year", "month", "dayofmonth", "hour", "minute", "second", "weekofyear", "last_bar_index", "timenow"}
FUNCS = {"nz", "na", "fixnan", "plot", "plotshape", "plotchar", "plotarrow", "plotcandle", "plotbar", "bgcolor",
         "barcolor", "fill", "hline", "alertcondition", "alert", "max", "min", "abs", "round", "int", "float", "bool",
         "string", "tostring", "iff", "sma", "ema", "rsi", "crossover", "crossunder", "cross", "atr", "highest", "lowest",
         "stdev", "change", "rma", "wma", "vwma", "macd", "stoch", "cci", "mom", "roc", "sum", "valuewhen", "barssince",
         "security", "input", "study", "indicator", "strategy", "log", "sqrt", "pow", "sign", "tr", "vwap", "cum",
         "falling", "rising", "pivothigh", "pivotlow", "linreg", "dev", "percentrank", "bb", "supertrend", "dmi", "hma",
         "timestamp", "dayofweek", "color", "rgb", "time", "na"}
V4_TA = {"sma", "ema", "rsi", "crossover", "crossunder", "cross", "atr", "highest", "lowest", "stdev", "change", "rma",
         "wma", "vwma", "macd", "stoch", "cci", "mom", "roc", "sum", "valuewhen", "barssince", "tr", "vwap", "cum",
         "falling", "rising", "pivothigh", "pivotlow", "linreg", "dev", "percentrank", "bb", "supertrend", "dmi", "hma", "iff"}


class Parser:
    def __init__(self, toks, ctx):
        self.t, self.i, self.ctx = toks, 0, ctx

    def peek(self, k=0):
        j = self.i + k
        return self.t[j] if j < len(self.t) else ("eof", "")

    def next(self):
        tok = self.peek(); self.i += 1; return tok

    def expect(self, v):
        tok = self.next()
        if tok[1] != v:
            raise PineError(f"expected {v!r} got {tok[1]!r}")
        return tok

    def expr(self, min_prec=0) -> str:
        left = self.unary()
        while True:
            k, v = self.peek()
            if v == "?" and min_prec == 0:
                self.next()
                a = self.expr(0)
                self.expect(":")
                b = self.expr(0)
                left = f"({a} if _truthy({left}) else {b})"
                continue
            p = PREC.get(v)
            if p is None or p <= min_prec - 1 or p < min_prec:
                break
            self.next()
            right = self.expr(p + 1)
            if v in ("and", "or"):
                left = f"(_truthy({left}) {v} _truthy({right}))"
            elif v in ("+", "-", "*", "/", "%"):
                left = f"_op({left!s}, {right!s}, {v!r})"
            else:
                left = f"_cmp({left}, {right}, {v!r})"
        return left

    def unary(self) -> str:
        k, v = self.peek()
        if v == "not":
            self.next(); return f"(not _truthy({self.unary()}))"
        if v == "-":
            self.next(); return f"_neg({self.unary()})"
        if v == "+":
            self.next(); return self.unary()
        return self.postfix(self.atom())

    def atom(self) -> str:
        k, v = self.next()
        if k == "num":
            return v
        if k == "str":
            return repr(bytes(v[1:-1], "utf-8").decode("unicode_escape"))
        if k == "color":
            return repr(v)
        if v == "(":
            e = self.expr(); self.expect(")"); return f"({e})"
        if v == "[":  # tuple literal / array literal
            items = []
            while self.peek()[1] != "]":
                items.append(self.expr())
                if self.peek()[1] == ",":
                    self.next()
            self.expect("]")
            return f"({', '.join(items)},)"
        if v == "true":
            return "True"
        if v == "false":
            return "False"
        if v == "na" and self.peek()[1] != "(":
            return "NA"
        if k == "name" or v in ("na",):
            # dotted name
            name = v
            while self.peek()[1] == "." and self.peek(1)[0] == "name":
                self.next(); name += "." + self.next()[1]
            # generic type args like array.new<float>(...)
            if self.peek()[1] == "<" and name.split(".")[-1] in ("new", "new_float", "new_int"):
                while self.next()[1] != ">":
                    pass
            if self.peek()[1] == "(":
                return self.call(name)
            return self.ref(name)
        raise PineError(f"unexpected token {v!r}")

    def ref(self, name: str) -> str:
        root = name.split(".")[0]
        if root in NAMESPACES and "." in name:
            return f"_ns({name!r})"
        if name in self.ctx.locals_stack[-1]:
            return f"{_pyname(name)}"
        if name in BUILTIN_SERIES or name in self.ctx.declared:
            return f"V[{name!r}]"
        if name in ("strategy", "na"):
            return f"_ns({name!r})"
        self.ctx.declared.add(name)  # forward reference (declared later)
        return f"V[{name!r}]"

    def call(self, name: str) -> str:
        self.expect("(")
        args, kwargs = [], []
        while self.peek()[1] != ")":
            if self.peek()[0] == "name" and self.peek(1)[1] == "=" and self.peek(2)[1] != "=":
                key = self.next()[1]; self.next()
                kwargs.append(f"{key}={self.expr()}")
            else:
                args.append(self.expr())
            if self.peek()[1] == ",":
                self.next()
        self.expect(")")
        site = self.ctx.new_site()
        a = ", ".join(args + kwargs)
        if name in self.ctx.user_funcs:
            return f"{_pyname(name)}({a})"
        if self.ctx.version <= 4 and name in V4_TA:
            name = "ta." + name if name != "iff" else "iff"
        return f"_call({name!r}, {site}, {a})" if a else f"_call({name!r}, {site})"

    def postfix(self, base: str) -> str:
        while True:
            if self.peek()[1] == "[":
                self.next(); n = self.expr(); self.expect("]")
                m = re.fullmatch(r"V\['(\w+)'\]", base)
                if m:
                    base = f"_hist({m.group(1)!r}, {n})"
                elif re.fullmatch(r"\w+", base) and base.startswith("p_"):
                    base = f"_lhist(_L, {base[2:]!r}, {n})"
                else:
                    base = f"_index({base}, {n})"
            elif self.peek()[1] == "." and self.peek(1)[0] == "name":  # method call on expression: x.method()
                self.next(); meth = self.next()[1]
                if self.peek()[1] == "(":
                    inner = self.call(f"__method__.{meth}")
                    base = inner.replace("_call(", f"_mcall({base}, ", 1)
                else:
                    base = f"_attr({base}, {meth!r})"
            else:
                return base


def _pyname(n: str) -> str:
    return "p_" + n


# ======================= statement compiler =======================
class Ctx:
    def __init__(self, version: int):
        self.version, self.sites, self.declared = version, 0, set()
        self.user_funcs: set[str] = set()
        self.locals_stack: list[set] = [set()]

    def new_site(self) -> int:
        self.sites += 1
        return self.sites


def compile_pine(src: str) -> tuple[str, dict]:
    m = re.search(r"//\s*@version\s*=\s*(\d+)", src)
    version = int(m.group(1)) if m else 5
    lines = tokenize(src)
    ctx = Ctx(version)
    meta = {"version": version, "kind": "indicator", "title": "", "decl": {}}
    # pre-scan user functions so calls resolve
    for ind, toks, decl in lines:
        if not decl and ind == 0 and len(toks) >= 3 and toks[0][0] == "name" and toks[1][1] == "(":
            depth, j = 0, 1
            while j < len(toks):
                if toks[j][1] == "(":
                    depth += 1
                elif toks[j][1] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            if j + 1 < len(toks) and toks[j + 1][1] == "=>":
                ctx.user_funcs.add(toks[0][1])
    out = ["def _bar(V, _call, _hist, _ns, _truthy, _op, _cmp, _neg, _index, _mcall, _attr, _lhist, NA):"]
    body, i = [], 0
    funcs: list[str] = []

    def block(start: int, indent: int, dst: list[str], level: int, in_func: bool) -> int:
        j = start
        while j < len(lines) and lines[j][0] >= indent:
            if lines[j][0] > indent:
                raise PineError(f"unexpected indentation near: {' '.join(t[1] for t in lines[j][1])[:80]}")
            j = stmt(j, dst, level, in_func)
        return j

    def stmt(j: int, dst: list[str], level: int, in_func: bool) -> int:
        ind, toks, decl = lines[j]
        pad = "    " * level
        if decl:
            if toks[0][0] == "name":
                p = Parser(toks, ctx)
                meta["kind"] = toks[0][1].replace("study", "indicator")
                meta["decl"] = p.expr()
            return j + 1
        if toks[0][1] in ("import", "export", "type", "method"):
            raise PineError(f"Pine '{toks[0][1]}' (libraries/UDTs) isn't supported; inline the code")
        p = Parser(toks, ctx)
        k0, v0 = toks[0]
        # function definition
        if k0 == "name" and v0 in ctx.user_funcs and ind == 0 and "=>" in [t[1] for t in toks]:
            arrow = [t[1] for t in toks].index("=>")
            params = [t[1] for t in toks[2:arrow] if t[0] == "name" and t[1] not in TYPES]
            params = [x for x in params if x not in ("simple", "series")]
            ctx.locals_stack.append(set(params))
            fdst = [f"def {_pyname(v0)}({', '.join(_pyname(x) + '=NA' for x in params)}):",
                    "    _L = {}"]
            if arrow + 1 < len(toks):
                e = Parser(toks[arrow + 1:], ctx).expr()
                fdst.append(f"    return {e}")
                nj = j + 1
            else:
                sub: list[str] = []
                nj = block(j + 1, lines[j + 1][0], sub, 1, True) if j + 1 < len(lines) else j + 1
                # last expression statement is the return value
                last = sub[-1]
                if last.strip().startswith("_ret = "):
                    sub.append("    return _ret")
                fdst += sub
            ctx.locals_stack.pop()
            funcs.append("\n".join(fdst))
            return nj
        if v0 == "if":
            p.next()
            cond = p.expr()
            dst.append(f"{pad}if _truthy({cond}):")
            nj = block(j + 1, lines[j + 1][0], dst, level + 1, in_func) if j + 1 < len(lines) and lines[j + 1][0] > ind else j + 1
            if nj == j + 1:
                dst.append(f"{pad}    pass")
            while nj < len(lines) and lines[nj][0] == ind and lines[nj][1][0][1] == "else":
                et = lines[nj][1]
                if len(et) > 1 and et[1][1] == "if":
                    c2 = Parser(et[2:], ctx).expr()
                    dst.append(f"{pad}elif _truthy({c2}):")
                else:
                    dst.append(f"{pad}else:")
                nn = nj + 1
                nj = block(nn, lines[nn][0], dst, level + 1, in_func) if nn < len(lines) and lines[nn][0] > ind else nn
                if nj == nn:
                    dst.append(f"{pad}    pass")
            return nj
        if v0 == "for":
            p.next()
            var_ = p.next()[1]
            if p.peek()[1] == "in":
                p.next(); it = p.expr()
                dst.append(f"{pad}for {_pyname(var_)} in list({it}):")
            else:
                p.expect("="); a = p.expr(1); p.expect("to"); b = p.expr(1)
                step = "1"
                if p.peek()[1] == "by":
                    p.next(); step = p.expr(1)
                dst.append(f"{pad}for {_pyname(var_)} in _range({a}, {b}, {step}):")
            ctx.locals_stack[-1].add(var_)
            nj = block(j + 1, lines[j + 1][0], dst, level + 1, in_func)
            return nj
        if v0 == "while":
            p.next(); c = p.expr()
            dst.append(f"{pad}_guard = 0")
            dst.append(f"{pad}while _truthy({c}):")
            dst.append(f"{pad}    _guard += 1")
            dst.append(f"{pad}    if _guard > 100000: raise RuntimeError('while loop exceeded 100k iterations')")
            return block(j + 1, lines[j + 1][0], dst, level + 1, in_func)
        if v0 in ("break", "continue"):
            dst.append(f"{pad}{v0}")
            return j + 1
        # declarations / assignments
        is_var = v0 in ("var", "varip")
        k = 1 if is_var else 0
        while k < len(toks) - 1 and toks[k][0] == "name" and toks[k][1] in TYPES and toks[k + 1][0] == "name":
            k += 1  # skip type annotations: float x = ..., var int y = ...
        if toks[k][1] == "[" and "=" in [t[1] for t in toks]:  # tuple destructuring
            eq = [t[1] for t in toks].index("=")
            names = [t[1] for t in toks[k + 1:eq] if t[0] == "name"]
            rhs = Parser(toks[eq + 1:], ctx)
            if rhs.peek()[1] in ("if", "switch"):
                raise PineError("tuple from if/switch expression not supported")
            e = rhs.expr()
            dst.append(f"{pad}_t = {e}")
            for n_i, n in enumerate(names):
                ctx.declared.add(n)
                dst.append(f"{pad}{_target(n, ctx, in_func)} = _t[{n_i}]")
            return j + 1
        if k + 1 < len(toks) and toks[k][0] == "name" and toks[k + 1][1] in ("=", ":=", "+=", "-=", "*=", "/=", "%="):
            name, op = toks[k][1], toks[k + 1][1]
            rhs_toks = toks[k + 2:]
            tgt = _target(name, ctx, in_func, declare=(op == "="))
            if rhs_toks and rhs_toks[0][1] in ("if", "switch"):
                # value-returning if/switch: compile into _ret then assign
                sub_lines_end, code = _expr_block(j, rhs_toks, ind, level, in_func)
                dst.extend(code)
                val = "_ret"
                nj = sub_lines_end
            else:
                val = Parser(rhs_toks, ctx).expr()
                nj = j + 1
            if op in ("+=", "-=", "*=", "/=", "%="):
                val = f"_op({tgt}, {val}, {op[0]!r})"
            if is_var:
                dst.append(f"{pad}if {name!r} not in V['__init__']:")
                dst.append(f"{pad}    V['__init__'].add({name!r}); {tgt} = {val}")
            else:
                dst.append(f"{pad}{tgt} = {val}")
            if in_func:
                dst.append(f"{pad}_ret = {tgt}")
            return nj
        if v0 == "switch":
            nj, code = _expr_block(j, toks, ind, level, in_func)
            dst.extend(code)
            return nj
        # expression statement (function call like strategy.entry(...), or last expr of a function)
        e = Parser(toks, ctx).expr()
        dst.append(f"{pad}_ret = {e}" if in_func else f"{pad}{e}")
        return j + 1

    def _expr_block(j, toks, ind, level, in_func):
        """if/switch used as an expression (x = if c ...). Each branch's last value -> _ret."""
        pad = "    " * level
        code = [f"{pad}_ret = NA"]
        if toks[0][1] == "if":
            cond = Parser(toks[1:], ctx).expr()
            code.append(f"{pad}if _truthy({cond}):")
            nj = block(j + 1, lines[j + 1][0], code, level + 1, True)
            while nj < len(lines) and lines[nj][0] == ind and lines[nj][1][0][1] == "else":
                et = lines[nj][1]
                code.append(f"{pad}elif _truthy({Parser(et[2:], ctx).expr()}):" if len(et) > 1 and et[1][1] == "if" else f"{pad}else:")
                nj = block(nj + 1, lines[nj + 1][0], code, level + 1, True)
            return nj, code
        # switch [expr]
        subject = Parser(toks[1:], ctx).expr() if len(toks) > 1 else None
        nj = j + 1
        first = True
        case_indent = lines[nj][0] if nj < len(lines) else ind + 4
        while nj < len(lines) and lines[nj][0] == case_indent:
            ct = lines[nj][1]
            arrow = [t[1] for t in ct].index("=>")
            lhs, rhs = ct[:arrow], ct[arrow + 1:]
            if not lhs:
                code.append(f"{pad}else:")
            else:
                c = Parser(lhs, ctx).expr()
                test = f"_cmp({subject}, {c}, '==')" if subject else f"_truthy({c})"
                code.append(f"{pad}{'if' if first else 'elif'} {test}:")
            first = False
            if rhs:
                code.append(f"{pad}    _ret = {Parser(rhs, ctx).expr()}")
                nj += 1
            else:
                nj = block(nj + 1, lines[nj + 1][0], code, level + 1, True)
        return nj, code

    while i < len(lines):
        i = stmt(i, body, 1, False)
    code = "\n".join(funcs) + "\n" + "\n".join(out + (body or ["    pass"]))
    # user functions need the runtime helpers: compile them inside a factory closure
    full = ("def _factory(V, _call, _hist, _ns, _truthy, _op, _cmp, _neg, _index, _mcall, _attr, _lhist, NA, _range):\n"
            + "\n".join("    " + ln for ln in code.split("\n"))
            + "\n    return _bar\n")
    meta["sites"] = ctx.sites
    meta["user_functions"] = sorted(ctx.user_funcs)
    return full, meta


def _target(name: str, ctx: Ctx, in_func: bool, declare: bool = False) -> str:
    if in_func:
        if declare or name in ctx.locals_stack[-1]:
            ctx.locals_stack[-1].add(name)
            return _pyname(name)
    ctx.declared.add(name)
    return f"V[{name!r}]"


# ======================= runtime =======================
def _isna(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def _truthy(x) -> bool:
    return False if _isna(x) else bool(x)


def _op(a, b, op):
    if _isna(a) or _isna(b):
        if op == "+" and (isinstance(a, str) or isinstance(b, str)):
            return f"{'' if _isna(a) else a}{'' if _isna(b) else b}"
        return NA
    if op == "/":
        return NA if b == 0 else a / b
    if op == "%":
        return NA if b == 0 else math.fmod(a, b)
    return a + b if op == "+" else a - b if op == "-" else a * b


def _cmp(a, b, op):
    if op in ("==", "!=") and (isinstance(a, (str, bool)) or isinstance(b, (str, bool))):
        return (a == b) if op == "==" else (a != b)
    if _isna(a) or _isna(b):
        return False
    return {"==": a == b, "!=": a != b, "<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[op]


def _neg(a):
    return NA if _isna(a) else -a


def _range(a, b, step=1):
    a, b, step = int(a), int(b), int(step) if not _isna(step) else 1
    step = abs(step) if b >= a else -abs(step)
    return range(a, b + (1 if step > 0 else -1), step)


class _Hist:
    def __init__(self, n: int):
        self.vals: deque = deque(maxlen=n)

    def push(self, v):
        self.vals.append(v)

    def get(self, n: int):
        n = int(n)
        if n <= 0:
            raise PineError("history offset must be >= 1 here")
        return self.vals[-n] if n <= len(self.vals) else NA


class TA:
    """Incremental ta.* functions; `site` gives each call its own state, as in Pine."""
    def __init__(self, rt: "PineRuntime"):
        self.rt, self.s = rt, {}

    def _st(self, site, **init):
        if site not in self.s:
            self.s[site] = dict(init)
        return self.s[site]

    def _buf(self, site, x, n=5000):
        st = self._st(site, buf=deque(maxlen=n))
        st["buf"].append(NA if _isna(x) else float(x))
        return np.array(st["buf"], dtype=float)

    def sma(self, site, src, length):
        b = self._buf(site, src, int(length))
        return float(b.mean()) if len(b) >= length and not np.isnan(b).any() else NA

    def ema(self, site, src, length, _alpha=None):
        st = self._st(site, v=NA, n=0, seed=[])
        if _isna(src):
            return st["v"]
        a = _alpha or 2 / (length + 1)
        if _isna(st["v"]):
            st["seed"].append(src)
            if len(st["seed"]) >= length:
                st["v"] = sum(st["seed"][-int(length):]) / length
            return st["v"]
        st["v"] = a * src + (1 - a) * st["v"]
        return st["v"]

    def rma(self, site, src, length):
        return self.ema(site, src, length, _alpha=1 / length)

    def wma(self, site, src, length):
        b = self._buf(site, src, int(length))
        if len(b) < length or np.isnan(b).any():
            return NA
        w = np.arange(1, int(length) + 1)
        return float((b * w).sum() / w.sum())

    def hma(self, site, src, length):
        a = self.wma((site, 1), src, max(1, int(length / 2)))
        b = self.wma((site, 2), src, length)
        return self.wma((site, 3), _op(_op(2, a, "*"), b, "-"), max(1, int(math.sqrt(length))))

    def vwma(self, site, src, length):
        v = self.rt.V["volume"]
        return _op(self.sma((site, 1), _op(src, v, "*"), length), self.sma((site, 2), v, length), "/")

    def stdev(self, site, src, length, biased=True):
        b = self._buf(site, src, int(length))
        return float(b.std(ddof=0 if biased else 1)) if len(b) >= length and not np.isnan(b).any() else NA

    def dev(self, site, src, length):
        b = self._buf(site, src, int(length))
        return float(np.abs(b - b.mean()).mean()) if len(b) >= length else NA

    def highest(self, site, src=None, length=None):
        if length is None:
            src, length = self.rt.V["high"], src
        b = self._buf(site, src, int(length))
        return float(np.nanmax(b)) if len(b) >= length else NA

    def lowest(self, site, src=None, length=None):
        if length is None:
            src, length = self.rt.V["low"], src
        b = self._buf(site, src, int(length))
        return float(np.nanmin(b)) if len(b) >= length else NA

    def highestbars(self, site, src, length):
        b = self._buf(site, src, int(length))
        return -(len(b) - 1 - int(np.nanargmax(b))) if len(b) >= length else NA

    def lowestbars(self, site, src, length):
        b = self._buf(site, src, int(length))
        return -(len(b) - 1 - int(np.nanargmin(b))) if len(b) >= length else NA

    def change(self, site, src, length=1):
        b = self._buf(site, src, int(length) + 1)
        return float(b[-1] - b[0]) if len(b) > length else NA

    def mom(self, site, src, length):
        return self.change(site, src, length)

    def roc(self, site, src, length):
        b = self._buf(site, src, int(length) + 1)
        return float(100 * (b[-1] - b[0]) / b[0]) if len(b) > length and b[0] else NA

    def rsi(self, site, src, length):
        st = self._st(site, prev=NA)
        prev, st["prev"] = st["prev"], src
        d = _op(src, prev, "-")
        up = self.rma((site, 1), NA if _isna(d) else max(d, 0.0), length)
        dn = self.rma((site, 2), NA if _isna(d) else max(-d, 0.0), length)
        if _isna(up) or _isna(dn):
            return NA
        return 100.0 if dn == 0 else 0.0 if up == 0 else 100 - 100 / (1 + up / dn)

    def tr(self, site=None, handle_na=False):
        V, H = self.rt.V, self.rt.H
        pc = H["close"].get(1) if "close" in H else NA
        if _isna(pc):
            return V["high"] - V["low"] if handle_na or True else NA
        return max(V["high"] - V["low"], abs(V["high"] - pc), abs(V["low"] - pc))

    def atr(self, site, length):
        return self.rma(site, self.tr(), length)

    def crossover(self, site, a, b):
        st = self._st(site, pa=NA, pb=NA)
        r = not _isna(st["pa"]) and not _isna(st["pb"]) and _cmp(a, b, ">") and st["pa"] <= st["pb"]
        st["pa"], st["pb"] = a, b
        return bool(r)

    def crossunder(self, site, a, b):
        st = self._st(site, pa=NA, pb=NA)
        r = not _isna(st["pa"]) and not _isna(st["pb"]) and _cmp(a, b, "<") and st["pa"] >= st["pb"]
        st["pa"], st["pb"] = a, b
        return bool(r)

    def cross(self, site, a, b):
        return self.crossover((site, 1), a, b) or self.crossunder((site, 2), a, b)

    def rising(self, site, src, length):
        b = self._buf(site, src, int(length) + 1)
        return bool(len(b) > length and all(b[-1] > b[:-1]))

    def falling(self, site, src, length):
        b = self._buf(site, src, int(length) + 1)
        return bool(len(b) > length and all(b[-1] < b[:-1]))

    def cum(self, site, src):
        st = self._st(site, v=0.0)
        if not _isna(src):
            st["v"] += src
        return st["v"]

    def macd(self, site, src, fast, slow, signal):
        m = _op(self.ema((site, 1), src, fast), self.ema((site, 2), src, slow), "-")
        s = self.ema((site, 3), m, signal)
        return (m, s, _op(m, s, "-"))

    def bb(self, site, src, length, mult):
        basis = self.sma((site, 1), src, length)
        dev = _op(mult, self.stdev((site, 2), src, length), "*")
        return (basis, _op(basis, dev, "+"), _op(basis, dev, "-"))

    def stoch(self, site, src, high, low, length):
        hh, ll = self.highest((site, 1), high, length), self.lowest((site, 2), low, length)
        return _op(100 * 1.0, _op(_op(src, ll, "-"), _op(hh, ll, "-"), "/"), "*")

    def cci(self, site, src, length):
        m = self.sma((site, 1), src, length)
        d = self.dev((site, 2), src, length)
        return _op(_op(src, m, "-"), _op(0.015, d, "*"), "/")

    def vwap(self, site, src=None, anchor=None):
        V = self.rt.V
        src = V["hlc3"] if src is None else src
        st = self._st(site, pv=0.0, v=0.0, day=None)
        day = self.rt.session_day()
        if day != st["day"]:
            st.update(pv=0.0, v=0.0, day=day)
        st["pv"] += src * V["volume"]; st["v"] += V["volume"]
        return st["pv"] / st["v"] if st["v"] else NA

    def barssince(self, site, cond):
        st = self._st(site, n=NA)
        st["n"] = 0 if _truthy(cond) else (NA if _isna(st["n"]) else st["n"] + 1)
        return st["n"]

    def valuewhen(self, site, cond, src, occurrence=0):
        st = self._st(site, vals=deque(maxlen=int(occurrence) + 1))
        if _truthy(cond):
            st["vals"].appendleft(src)
        return st["vals"][int(occurrence)] if len(st["vals"]) > occurrence else NA

    def pivothigh(self, site, src=None, left=None, right=None):
        if right is None:
            src, left, right = self.rt.V["high"], src, left
        b = self._buf(site, src, int(left) + int(right) + 1)
        if len(b) < left + right + 1:
            return NA
        c = b[int(left)]
        return float(c) if c == b.max() and (b == c).sum() == 1 else NA

    def pivotlow(self, site, src=None, left=None, right=None):
        if right is None:
            src, left, right = self.rt.V["low"], src, left
        b = self._buf(site, src, int(left) + int(right) + 1)
        if len(b) < left + right + 1:
            return NA
        c = b[int(left)]
        return float(c) if c == b.min() and (b == c).sum() == 1 else NA

    def linreg(self, site, src, length, offset=0):
        b = self._buf(site, src, int(length))
        if len(b) < length:
            return NA
        x = np.arange(int(length)); k, c = np.polyfit(x, b, 1)
        return float(c + k * (length - 1 - offset))

    def percentrank(self, site, src, length):
        b = self._buf(site, src, int(length) + 1)
        return float(100 * (b[:-1] <= b[-1]).sum() / length) if len(b) > length else NA

    def supertrend(self, site, factor, atr_period):
        V = self.rt.V
        atr = self.atr((site, 1), atr_period)
        st = self._st(site, up=NA, dn=NA, dir=1, pclose=NA)
        if _isna(atr):
            st["pclose"] = V["close"]; return (NA, NA)
        up = V["hl2"] - factor * atr
        dn = V["hl2"] + factor * atr
        up = max(up, st["up"]) if not _isna(st["up"]) and st["pclose"] > st["up"] else up
        dn = min(dn, st["dn"]) if not _isna(st["dn"]) and st["pclose"] < st["dn"] else dn
        d = st["dir"]
        if d == 1 and V["close"] > (st["dn"] if not _isna(st["dn"]) else dn):
            d = -1
        elif d == -1 and V["close"] < (st["up"] if not _isna(st["up"]) else up):
            d = 1
        st.update(up=up, dn=dn, dir=d, pclose=V["close"])
        return (up if d == -1 else dn, d)

    def dmi(self, site, di_len, adx_len):
        V, H = self.rt.V, self.rt.H
        ph, pl = H["high"].get(1), H["low"].get(1)
        upm = _op(V["high"], ph, "-"); dnm = _op(pl, V["low"], "-")
        plus = upm if _cmp(upm, dnm, ">") and _cmp(upm, 0, ">") else 0.0
        minus = dnm if _cmp(dnm, upm, ">") and _cmp(dnm, 0, ">") else 0.0
        trr = self.rma((site, 1), self.tr(), di_len)
        p = _op(100.0, _op(self.rma((site, 2), plus, di_len), trr, "/"), "*")
        m = _op(100.0, _op(self.rma((site, 3), minus, di_len), trr, "/"), "*")
        s = _op(p, m, "+")
        adx = self.rma((site, 4), _op(100.0, _op(abs(_op(p, m, "-")) if not _isna(_op(p, m, "-")) else NA, s, "/"), "*"), adx_len)
        return (p, m, adx)


class Strategy:
    long, short = "long", "short"
    fixed, cash, percent_of_equity = "fixed", "cash", "percent_of_equity"

    def __init__(self, rt):
        self.rt = rt
        self.position_size = 0.0
        self.position_avg_price = NA
        self.default_qty = 1.0
        self.exits: dict = {}
        self.notes: set = set()
        self.pyramiding = 1

    # --- orders ---
    def entry(self, id, direction, qty=None, limit=None, stop=None, comment=None, when=True, **k):
        if not _truthy(when):
            return
        if limit is not None and not _isna(limit) or stop is not None and not _isna(stop):
            self.notes.add("strategy.entry limit/stop prices treated as market orders (next bar open)")
        d = 1 if direction in ("long", True, 1) else -1
        q = self.default_qty if qty is None or _isna(qty) else float(qty)
        if d * self.position_size > 0 and self.pyramiding > 1:
            self.position_size += d * q
        elif d * self.position_size <= 0:
            self.position_size = d * q
        self.position_avg_price = self.rt.V["close"]

    def order(self, id, direction, qty=None, **k):
        d = 1 if direction in ("long", True, 1) else -1
        self.position_size += d * (self.default_qty if qty is None else float(qty))

    def close(self, id=None, when=True, qty=None, qty_percent=None, comment=None, **k):
        if _truthy(when):
            self.position_size = 0.0
            self.exits.clear()

    def close_all(self, when=True, comment=None, **k):
        self.close(when=when)

    def cancel(self, id=None, **k):
        self.exits.pop(id, None)

    def cancel_all(self, **k):
        self.exits.clear()

    def exit(self, id, from_entry=None, qty=None, qty_percent=None, profit=None, limit=None, loss=None, stop=None,
             trail_price=None, trail_points=None, trail_offset=None, when=True, comment=None, **k):
        if not _truthy(when):
            return
        if trail_points is not None or trail_price is not None:
            self.notes.add("strategy.exit trailing stops approximated as fixed stops")
        self.exits[id] = {"profit": profit, "limit": limit, "loss": loss, "stop": stop}

    def risk(self, *a, **k):
        self.notes.add("strategy.risk.* rules ignored (Apollo applies LucidFlex risk rules instead)")

    def check_exits(self):
        """Called at the start of each bar: stops/limits hit within this bar flatten the position."""
        if not self.position_size or not self.exits:
            return
        V, avg, mt = self.rt.V, self.position_avg_price, self.rt.mintick
        long = self.position_size > 0
        for e in self.exits.values():
            stop = e["stop"] if e["stop"] is not None and not _isna(e["stop"]) else (
                avg - e["loss"] * mt if long else avg + e["loss"] * mt) if e["loss"] is not None and not _isna(e["loss"]) else None
            lim = e["limit"] if e["limit"] is not None and not _isna(e["limit"]) else (
                avg + e["profit"] * mt if long else avg - e["profit"] * mt) if e["profit"] is not None and not _isna(e["profit"]) else None
            hit = (stop is not None and (V["low"] <= stop if long else V["high"] >= stop)) or \
                  (lim is not None and (V["high"] >= lim if long else V["low"] <= lim))
            if hit:
                self.position_size, self.exits = 0.0, {}
                self.rt.exit_hits += 1
                return


class _Namespace:
    def __init__(self, name, rt): self._name, self._rt = name, rt
    def __getattr__(self, k): return self._rt.ns(f"{self._name}.{k}")


class PineRuntime:
    def __init__(self, src: str, inputs: dict | None = None):
        self.src = src
        self.py, self.meta = compile_pine(src)
        self.inputs = inputs or {}
        self.used_inputs: dict = {}
        self.unsupported: set = set()
        self.exit_hits = 0
        self.mintick = 0.1

    # -------- namespace values (non-call) --------
    def ns(self, name: str):
        consts = {"strategy.long": "long", "strategy.short": "short", "strategy.position_size": self.strat.position_size,
                  "strategy.position_avg_price": self.strat.position_avg_price, "strategy.equity": 150000.0,
                  "strategy.fixed": "fixed", "strategy.cash": "cash", "strategy.percent_of_equity": "percent_of_equity",
                  "strategy.opentrades": 1 if self.strat.position_size else 0, "strategy.closedtrades": 0,
                  "strategy.netprofit": 0.0, "strategy.initial_capital": 150000.0,
                  "syminfo.mintick": self.mintick, "syminfo.pointvalue": 10.0, "syminfo.ticker": "MGC",
                  "syminfo.tickerid": "COMEX:MGC1!", "syminfo.timezone": "America/New_York", "syminfo.currency": "USD",
                  "timeframe.period": self.tf, "timeframe.multiplier": self.tf_mult, "timeframe.isintraday": True,
                  "timeframe.isdaily": self.tf == "D", "timeframe.isminutes": True, "timeframe.isseconds": False,
                  "barstate.isfirst": self.i == 0, "barstate.islast": self.i == self.n - 1,
                  "barstate.isconfirmed": True, "barstate.isrealtime": False, "barstate.ishistory": True,
                  "barstate.isnew": True, "barstate.islastconfirmedhistory": self.i == self.n - 1,
                  "math.pi": math.pi, "math.e": math.e, "dayofweek.monday": 2, "dayofweek.friday": 6,
                  "session.ismarket": True, "session.isfirstbar": False}
        if name in consts:
            return consts[name]
        if name.startswith(("color.", "shape.", "location.", "size.", "plot.style", "line.style", "display.", "position.",
                            "extend.", "xloc.", "yloc.", "text.", "font.", "format.", "hline.style", "label.style",
                            "alert.freq", "currency.", "scale.", "order.", "adjustment.", "barmerge.")):
            return name
        raise PineError(f"unsupported Pine value {name}")

    # -------- function calls --------
    def call(self, name, site, *a, **k):
        r = self._call(name, site, a, k)
        return r

    def _call(self, name, site, a, k):
        V = self.V
        if name.startswith("ta."):
            fn = getattr(self.ta, name[3:], None)
            if fn is None:
                raise PineError(f"{name} not implemented yet; supported: {sorted(m for m in dir(self.ta) if not m.startswith('_'))}")
            return fn(site, *a, **k)
        if name.startswith("math."):
            f = name[5:]
            if f in ("max", "min"):
                vals = [x for x in a if not _isna(x)]
                return (max if f == "max" else min)(vals) if vals else NA
            if f == "abs": return NA if _isna(a[0]) else abs(a[0])
            if f == "round":
                if _isna(a[0]): return NA
                return round(a[0], int(a[1])) if len(a) > 1 else float(math.floor(a[0] + 0.5))
            if f == "round_to_mintick": return NA if _isna(a[0]) else round(a[0] / self.mintick) * self.mintick
            if f == "avg": return float(np.mean(a))
            if f == "sum": return self.ta.cum((site, "s"), a[0]) if False else self._sum(site, a[0], a[1])
            m = {"sqrt": math.sqrt, "log": math.log, "log10": math.log10, "exp": math.exp, "floor": math.floor,
                 "ceil": math.ceil, "sign": lambda x: (x > 0) - (x < 0), "pow": math.pow, "sin": math.sin, "cos": math.cos,
                 "tan": math.tan, "atan": math.atan, "asin": math.asin, "acos": math.acos, "todegrees": math.degrees,
                 "toradians": math.radians, "random": lambda *x: float(np.random.default_rng(int(x[2]) if len(x) > 2 else 42).uniform(x[0] if x else 0, x[1] if len(x) > 1 else 1))}
            if f in m:
                return NA if any(_isna(x) for x in a) else m[f](*a)
            raise PineError(f"{name} not supported")
        if name.startswith("input") or name == "input":
            return self._input(name, site, a, k)
        if name.startswith("strategy."):
            f = name.split(".", 1)[1]
            if f.startswith("risk."):
                return self.strat.risk()
            fn = getattr(self.strat, f, None)
            if fn is None:
                self.unsupported.add(name); return NA
            return fn(*a, **k)
        if name in ("strategy", "indicator", "study"):
            return None
        if name == "nz":
            return (a[1] if len(a) > 1 else 0.0) if _isna(a[0]) else a[0]
        if name == "na":
            return _isna(a[0]) if a else NA
        if name == "fixnan":
            st = self.ta._st(site, v=NA)
            if not _isna(a[0]): st["v"] = a[0]
            return st["v"]
        if name == "iff":
            return a[1] if _truthy(a[0]) else a[2]
        if name in ("max", "min", "abs", "round", "sqrt", "log", "pow", "sign"):
            return self._call("math." + name, site, a, k)
        if name in ("int", "float"):
            return NA if _isna(a[0]) else (int(a[0]) if name == "int" else float(a[0]))
        if name in ("bool",):
            return _truthy(a[0])
        if name in ("str.tostring", "tostring", "str.format", "str.length", "str.contains"):
            return str(a[0]) if a else ""
        if name == "timestamp":
            nums = [x for x in a if isinstance(x, (int, float))]
            return pd.Timestamp(*[int(x) for x in nums[:5]], tz="UTC").value // 10**6 if len(nums) >= 3 else NA
        if name in ("request.security", "security"):
            sym, tf, expr = (a + (None, None, None))[:3]
            if tf in (self.tf, "", None, "timeframe.period"):
                self.unsupported.add("request.security(same timeframe) -> passthrough")
                return expr
            raise PineError(f"request.security on another timeframe/symbol ({sym}, {tf}) can't be reproduced; "
                            "move that logic to the chart timeframe or export signals to CSV")
        if name.startswith(("plot", "bgcolor", "barcolor", "fill", "hline", "alert", "label.", "line.", "box.", "table.",
                            "color.", "log.", "runtime.", "polyline.", "chart.")) or name in ("plot", "plotshape", "plotchar", "alertcondition", "alert", "fill", "hline", "bgcolor", "barcolor", "plotarrow", "plotcandle", "plotbar"):
            if name == "runtime.error":
                raise PineError(f"script raised runtime.error: {a[0] if a else ''}")
            return name if name.startswith("color.") else None
        if name.startswith("array."):
            return self._array(name[6:], a)
        if name in ("dayofweek", "hour", "minute", "month", "year", "dayofmonth"):
            return V[name]
        if name == "time":
            return V["time"]
        raise PineError(f"Pine function {name}() not supported")

    def _sum(self, site, src, length):
        b = self.ta._buf((site, "sum"), src, int(length))
        return float(b.sum()) if len(b) >= length else NA

    def _array(self, f, a):
        if f.startswith("new") or f == "from":
            if f == "from":
                return list(a)
            n = int(a[0]) if a else 0
            return [a[1] if len(a) > 1 else NA for _ in range(n)]
        arr = a[0]
        ops = {"push": lambda: arr.append(a[1]), "unshift": lambda: arr.insert(0, a[1]), "pop": lambda: arr.pop(),
               "shift": lambda: arr.pop(0), "get": lambda: arr[int(a[1])], "set": lambda: arr.__setitem__(int(a[1]), a[2]),
               "size": lambda: len(arr), "sum": lambda: float(np.nansum(arr)), "avg": lambda: float(np.nanmean(arr)) if arr else NA,
               "max": lambda: float(np.nanmax(arr)) if arr else NA, "min": lambda: float(np.nanmin(arr)) if arr else NA,
               "clear": lambda: arr.clear(), "includes": lambda: a[1] in arr, "first": lambda: arr[0], "last": lambda: arr[-1],
               "stdev": lambda: float(np.nanstd(arr)) if arr else NA, "remove": lambda: arr.pop(int(a[1]))}
        if f not in ops:
            raise PineError(f"array.{f} not supported")
        return ops[f]()

    def _input(self, name, site, a, k):
        title = k.get("title") or (a[1] if len(a) > 1 and isinstance(a[1], str) else None)
        default = k.get("defval", a[0] if a else NA)
        key = title or f"input_{site}"
        val = self.inputs.get(key, default)
        shown = val
        if name == "input.source":
            if isinstance(val, str):
                shown, val = val, self.V.get(val, default)
            else:  # default given as a series value: report which builtin it is
                shown = next((b for b in ("close", "open", "high", "low", "hl2", "hlc3", "ohlc4") if self.V.get(b) == val), "custom")
        self.used_inputs[key] = shown
        return val

    def session_day(self):
        return (self.ts + pd.Timedelta(hours=7)).date()

    # -------- execution --------
    def run(self, bars: pd.DataFrame) -> np.ndarray:
        decl = self.meta
        self.n = len(bars)
        secs = (bars.index[1] - bars.index[0]).total_seconds() if len(bars) > 1 else 60
        self.tf_mult = max(1, int(secs // 60))
        self.tf = "D" if secs >= 86400 else str(self.tf_mult)
        self.V: dict = {"__init__": set()}
        self.H: dict[str, _Hist] = {}
        self.ta = TA(self)
        self.strat = Strategy(self)
        ns = {"V": self.V, "_call": self.call, "_hist": self._hist, "_ns": self.ns, "_truthy": _truthy, "_op": _op,
              "_cmp": _cmp, "_neg": _neg, "_index": self._index, "_mcall": self._mcall, "_attr": self._attr,
              "_lhist": lambda L, n, k: NA, "NA": NA, "_range": _range}
        g: dict = {"NA": NA}
        exec(self.py, g)
        bar = g["_factory"](**ns)
        self._apply_decl()
        o, h, l, c, v = (bars[x].to_numpy(dtype=float) for x in ("open", "high", "low", "close", "volume"))
        idx_et = bars.index.tz_convert("America/New_York")
        out = np.zeros(self.n)
        persistent = set()
        for i in range(self.n):
            self.i, self.ts = i, idx_et[i]
            V = self.V
            # non-var user variables reset to na each bar (Pine semantics), var ones persist
            for k_ in list(V):
                if k_ not in ("__init__",) and k_ not in V["__init__"] and k_ not in BUILTIN_SERIES:
                    V[k_] = NA
            V.update(open=o[i], high=h[i], low=l[i], close=c[i], volume=v[i], hl2=(h[i] + l[i]) / 2,
                     hlc3=(h[i] + l[i] + c[i]) / 3, ohlc4=(o[i] + h[i] + l[i] + c[i]) / 4, hlcc4=(h[i] + l[i] + 2 * c[i]) / 4,
                     bar_index=i, last_bar_index=self.n - 1, time=int(bars.index[i].value // 10**6),
                     year=self.ts.year, month=self.ts.month, dayofmonth=self.ts.day, hour=self.ts.hour, minute=self.ts.minute,
                     second=self.ts.second, dayofweek=(self.ts.day_of_week + 1) % 7 + 1, weekofyear=self.ts.isocalendar()[1],
                     timenow=int(bars.index[-1].value // 10**6))
            self.strat.check_exits()
            bar(V, self.call, self._hist, self.ns, _truthy, _op, _cmp, _neg, self._index, self._mcall, self._attr, None, NA)
            for k_, val in V.items():
                if k_ == "__init__":
                    continue
                self.H.setdefault(k_, _Hist(5000)).push(val)
            out[i] = self.strat.position_size
        # Pine quantities are in the script's own units; normalise so a full position (default qty x pyramiding)
        # = 1.0 = the backtest's lot_size_micros. Keeps sizing consistent whatever default_qty_value says.
        full = max(self.strat.default_qty, 1e-12) * max(1, self.strat.pyramiding)
        return np.clip(out / full, -1.0, 1.0)

    def _apply_decl(self):
        d = self.meta.get("decl")
        if not d or self.meta["kind"] != "strategy":
            return
        kw = dict(re.findall(r"(\w+)=([^,)]+)", d))
        if "default_qty_value" in kw:
            try:
                self.strat.default_qty = float(eval(kw["default_qty_value"], {"_op": _op, "NA": NA}))
            except Exception:
                pass
        if "pyramiding" in kw:
            try:
                self.strat.pyramiding = int(float(kw["pyramiding"]))
            except ValueError:
                pass
        if kw.get("default_qty_type", "").strip("'\"").endswith(("percent_of_equity", "cash")):
            self.strat.default_qty = 1.0
            self.strat.notes.add("default_qty_type percent/cash mapped to 1 unit (Apollo sizes by lot_size_micros)")

    def _hist(self, name, n):
        if not isinstance(n, (int, float)) or _isna(n):
            return NA
        if int(n) == 0:
            return self.V.get(name, NA)
        h = self.H.get(name)
        return h.get(n) if h else NA

    def _index(self, val, n):
        raise PineError("history reference [] on an expression/function parameter isn't supported; assign it to a variable first")

    def _mcall(self, obj, name, site, *a, **k):
        meth = name.split(".", 1)[1]
        if isinstance(obj, list):
            return self._array(meth, (obj,) + a)
        raise PineError(f"method .{meth}() not supported")

    def _attr(self, obj, k):
        raise PineError(f"field access .{k} not supported")
