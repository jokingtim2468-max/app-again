"""Tree-walking interpreter for the MQL subset produced by parser.py."""

from __future__ import annotations

import math
from typing import Any

from ...errors import ScriptError, UnsupportedFeature
from .parser import INT_TYPES, Node

MAX_STEPS_PER_CALL = 5_000_000


class BreakSig(Exception):
    pass


class ContinueSig(Exception):
    pass


class ReturnSig(Exception):
    def __init__(self, value):
        self.value = value


class MqlArr:
    """Dynamic array. ``as_series`` flips indexing so [0] is the newest element."""

    __slots__ = ("items", "as_series", "elem_type", "fixed")

    def __init__(self, items=None, elem_type="double", fixed=False):
        self.items = list(items or [])
        self.as_series = False
        self.elem_type = elem_type
        self.fixed = fixed

    def _idx(self, k: int) -> int:
        k = int(k)
        n = len(self.items)
        j = n - 1 - k if self.as_series else k
        if not 0 <= j < n:
            raise ScriptError(f"Array out of range: index {k}, size {n}.",
                              hint="Check ArrayResize/CopyBuffer counts before reading.")
        return j

    def get(self, k):
        return self.items[self._idx(k)]

    def set(self, k, v):
        self.items[self._idx(k)] = v

    def __len__(self):
        return len(self.items)


class MStruct:
    """Plain struct value (MqlTick, MqlRates, MqlDateTime, MqlTradeRequest...)."""

    def __init__(self, typ: str, **fields):
        object.__setattr__(self, "_type", typ)
        object.__setattr__(self, "_f", dict(fields))

    def __getattr__(self, k):
        f = object.__getattribute__(self, "_f")
        if k in f:
            return f[k]
        return 0

    def __setattr__(self, k, v):
        self._f[k] = v

    def copy(self):
        return MStruct(self._type, **self._f)


STRUCT_DEFAULTS = {
    "MqlTick": dict(time=0, bid=0.0, ask=0.0, last=0.0, volume=0, time_msc=0, flags=0, volume_real=0.0),
    "MqlRates": dict(time=0, open=0.0, high=0.0, low=0.0, close=0.0, tick_volume=0, spread=0, real_volume=0),
    "MqlDateTime": dict(year=0, mon=0, day=0, hour=0, min=0, sec=0, day_of_week=0, day_of_year=0),
    "MqlTradeRequest": dict(action=0, magic=0, order=0, symbol="", volume=0.0, price=0.0, stoplimit=0.0, sl=0.0,
                            tp=0.0, deviation=0, type=0, type_filling=0, type_time=0, expiration=0, comment="",
                            position=0, position_by=0),
    "MqlTradeResult": dict(retcode=0, deal=0, order=0, volume=0.0, price=0.0, bid=0.0, ask=0.0, comment="",
                           request_id=0, retcode_external=0),
    "MqlTradeCheckResult": dict(retcode=0, balance=0.0, equity=0.0, profit=0.0, margin=0.0, margin_free=0.0,
                                margin_level=0.0, comment=""),
}


def cast(typ: str, v):
    if v is None:
        return v
    if typ in INT_TYPES or (typ and typ.startswith("ENUM_")):
        if isinstance(v, str):
            try:
                return int(float(v))
            except ValueError:
                return 0
        if isinstance(v, float):
            if math.isnan(v) or math.isinf(v):
                return 0
            return int(v)  # truncation toward zero, like C
        return int(v)
    if typ in ("double", "float"):
        if isinstance(v, str):
            try:
                return float(v)
            except ValueError:
                return 0.0
        return float(v)
    if typ == "bool":
        return bool(v)
    if typ == "string":
        return v if isinstance(v, str) else fmt_value(v)
    return v


def fmt_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        s = f"{v:.8f}".rstrip("0").rstrip(".")
        return s if s not in ("", "-0") else "0"
    return str(v)


def default_value(typ: str):
    if typ in INT_TYPES or typ.startswith("ENUM_"):
        return 0
    if typ in ("double", "float"):
        return 0.0
    if typ == "bool":
        return False
    if typ == "string":
        return ""
    if typ in STRUCT_DEFAULTS:
        return MStruct(typ, **STRUCT_DEFAULTS[typ])
    return 0


class Var:
    __slots__ = ("v", "t")

    def __init__(self, v, t):
        self.v = v
        self.t = t


def _arith(op, a, b, line):
    if isinstance(a, bool):
        a = int(a)
    if isinstance(b, bool):
        b = int(b)
    if op == "+":
        if isinstance(a, str) or isinstance(b, str):
            return (a if isinstance(a, str) else fmt_value(a)) + (b if isinstance(b, str) else fmt_value(b))
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if op == "/":
        if b == 0:
            raise ScriptError("Division by zero.", line=line, hint="Guard the divisor, e.g. if(x != 0).")
        if isinstance(a, int) and isinstance(b, int):
            q = abs(a) // abs(b)
            return q if (a >= 0) == (b >= 0) else -q
        return a / b
    if op == "%":
        if b == 0:
            raise ScriptError("Modulo by zero.", line=line)
        if isinstance(a, int) and isinstance(b, int):
            return a - b * int(a / b)
        return math.fmod(a, b)
    if op == "&":
        return int(a) & int(b)
    if op == "|":
        return int(a) | int(b)
    if op == "^":
        return int(a) ^ int(b)
    if op == "<<":
        return int(a) << int(b)
    if op == ">>":
        return int(a) >> int(b)
    if op == "==":
        return a == b
    if op == "!=":
        return a != b
    if op == "<":
        return a < b
    if op == ">":
        return a > b
    if op == "<=":
        return a <= b
    if op == ">=":
        return a >= b
    raise ScriptError(f"Unknown operator {op}", line=line)


class Interp:
    def __init__(self, program: list[Node], enums: dict, api):
        self.api = api                       # MqlApi: built-in functions, constants and dynamic names
        self.funcs: dict[str, Node] = {}
        self.globals: dict[str, Var] = {}
        self.scopes: list[dict[str, Var]] = []
        self.statics: dict[int, Var] = {}
        self.enum_values: dict[str, int] = {}
        for vals in enums.values():
            self.enum_values.update(vals)
        self.program = program
        self.steps = 0
        self.inputs: list[dict] = []
        for n in program:
            if n.kind == "func":
                self.funcs[n.a] = n

    # ------------------------------------------------------------------ globals
    def init_globals(self, overrides: dict) -> None:
        for n in self.program:
            if n.kind != "var":
                continue
            mods = n.d["mods"]
            is_input = any(m in ("input", "extern", "sinput") for m in mods)
            val = self.make_value(n)
            if is_input and n.a in overrides:
                val = cast(n.b, overrides[n.a])
            self.globals[n.a] = Var(val, n.b)

    def describe_inputs(self) -> list[dict]:
        out = []
        for n in self.program:
            if n.kind == "var" and any(m in ("input", "extern", "sinput") for m in n.d["mods"]):
                default = None
                try:
                    if n.c is not None:
                        default = self.eval(n.c)
                except Exception:
                    default = None
                if isinstance(default, MqlArr) or isinstance(default, MStruct):
                    continue
                out.append({"name": n.a, "title": n.d.get("comment") or n.a, "default": default,
                            "type": n.b if n.b in ("int", "double", "bool", "string", "datetime") else
                            ("int" if n.b in INT_TYPES or n.b.startswith("ENUM_") else n.b)})
        return out

    def make_value(self, n: Node):
        typ = n.b
        dims = n.d["dims"]
        if dims:
            size = None
            if dims[0] is not None:
                size = int(self.eval(dims[0]))
            if n.c is not None and n.c.kind == "initlist":
                items = [cast(typ, self.eval(x)) for x in n.c.a]
                if size and len(items) < size:
                    items += [default_value(typ)] * (size - len(items))
                return MqlArr(items, typ, fixed=size is not None)
            return MqlArr([default_value(typ)] * (size or 0), typ, fixed=size is not None)
        if typ in self.api.classes:
            return self.api.classes[typ]()
        if n.c is None:
            return default_value(typ)
        if n.c.kind == "initlist":
            if typ in STRUCT_DEFAULTS:
                s = default_value(typ)
                for k, x in zip(STRUCT_DEFAULTS[typ].keys(), n.c.a):
                    setattr(s, k, self.eval(x))
                return s
            return default_value(typ)
        v = self.eval(n.c)
        if isinstance(v, MStruct):
            return v.copy()
        return cast(typ, v)

    # ------------------------------------------------------------------ calls
    def has(self, name: str) -> bool:
        return name in self.funcs

    def call_user(self, name: str, args: list, ref_targets: list | None = None):
        fn = self.funcs[name]
        params = fn.b
        scope: dict[str, Var] = {}
        for i, p in enumerate(params):
            if i < len(args):
                v = args[i]
            elif p["default"] is not None:
                v = self.eval(p["default"])
            else:
                v = default_value(p["type"])
            if not p["array"] and not isinstance(v, (MqlArr, MStruct)) and not p["type"] in self.api.classes:
                v = cast(p["type"], v)
            scope[p["name"]] = Var(v, p["type"])
        saved = self.scopes
        self.scopes = [scope]
        try:
            self.exec(fn.c)
            result = default_value(fn.d) if fn.d != "void" else None
        except ReturnSig as r:
            result = r.value if fn.d == "void" else cast(fn.d, r.value) if r.value is not None else None
        finally:
            self.scopes = saved
        # copy-out for scalar reference parameters (int &x)
        if ref_targets:
            for i, p in enumerate(params):
                if p["ref"] and i < len(ref_targets) and ref_targets[i] is not None:
                    v = scope[p["name"]].v
                    if not isinstance(v, (MqlArr, MStruct)):
                        self.assign_to(ref_targets[i], v)
        return result

    # ------------------------------------------------------------------ statements
    def exec(self, n: Node):
        k = n.kind
        self.steps += 1
        if self.steps > MAX_STEPS_PER_CALL:
            raise ScriptError("The EA ran more than 5,000,000 steps on one tick (endless loop?).", line=n.line)
        if k == "block":
            self.scopes.append({})
            try:
                for s in n.a:
                    self.exec(s)
            finally:
                self.scopes.pop()
        elif k == "expr":
            self.eval(n.a)
        elif k == "decls":
            for d in n.a:
                self.declare_local(d)
        elif k == "var":
            self.declare_local(n)
        elif k == "if":
            if self.truth(self.eval(n.a)):
                self.exec(n.b)
            elif n.c is not None:
                self.exec(n.c)
        elif k == "for":
            self.scopes.append({})
            try:
                if n.a is not None:
                    self.exec(n.a) if n.a.kind == "decls" else [self.eval(x) for x in n.a.a]
                while n.b is None or self.truth(self.eval(n.b)):
                    try:
                        if n.d is not None:
                            self.exec(n.d)
                    except BreakSig:
                        break
                    except ContinueSig:
                        pass
                    if n.c is not None:
                        for x in n.c.a:
                            self.eval(x)
                    self.steps += 1
                    if self.steps > MAX_STEPS_PER_CALL:
                        raise ScriptError("A for-loop ran more than 5,000,000 steps (endless loop?).", line=n.line)
            finally:
                self.scopes.pop()
        elif k == "while":
            while self.truth(self.eval(n.a)):
                try:
                    self.exec(n.b)
                except BreakSig:
                    break
                except ContinueSig:
                    pass
        elif k == "dowhile":
            while True:
                try:
                    self.exec(n.b)
                except BreakSig:
                    break
                except ContinueSig:
                    pass
                if not self.truth(self.eval(n.a)):
                    break
        elif k == "switch":
            v = self.eval(n.a)
            start = None
            for idx, (val, _stmts) in enumerate(n.b):
                if val is not None and self.eval(val) == v:
                    start = idx
                    break
            if start is None:  # no case matched: jump to default, if any
                start = next((idx for idx, (val, _s) in enumerate(n.b) if val is None), None)
            if start is not None:
                try:
                    for _val, stmts in n.b[start:]:  # C fall-through until break
                        for s in stmts:
                            self.exec(s)
                except BreakSig:
                    pass
        elif k == "return":
            raise ReturnSig(self.eval(n.a) if n.a is not None else None)
        elif k == "break":
            raise BreakSig()
        elif k == "continue":
            raise ContinueSig()
        elif k in ("func", "proto"):
            pass
        else:
            raise ScriptError(f"Unsupported statement '{k}'.", line=n.line)

    def declare_local(self, d: Node):
        if "static" in d.d["mods"]:
            key = id(d)
            var = self.statics.get(key)
            if var is None:
                var = self.statics[key] = Var(self.make_value(d), d.b)
            self.scopes[-1][d.a] = var
            return
        self.scopes[-1][d.a] = Var(self.make_value(d), d.b)

    @staticmethod
    def truth(v) -> bool:
        if isinstance(v, float):
            return v != 0.0 and v == v
        return bool(v)

    # ------------------------------------------------------------------ names
    def lookup(self, name: str) -> Var | None:
        for s in reversed(self.scopes):
            if name in s:
                return s[name]
        return self.globals.get(name)

    def assign_to(self, target: Node, value):
        k = target.kind
        if k == "name":
            var = self.lookup(target.a)
            if var is None:
                raise ScriptError(f"'{target.a}' is not declared.", line=target.line)
            if isinstance(value, MStruct) and isinstance(var.v, MStruct):
                value = value.copy()
            var.v = cast(var.t, value) if not isinstance(value, (MqlArr, MStruct)) else value
            return var.v
        if k == "index":
            arr = self.eval(target.a)
            idx = self.eval(target.b)
            if isinstance(arr, MqlArr):
                arr.set(idx, cast(arr.elem_type, value))
                return value
            raise ScriptError("Can't index into this value.", line=target.line)
        if k == "member":
            obj = self.eval(target.a)
            setattr(obj, target.b, value)
            return value
        raise ScriptError("Left side of '=' isn't assignable.", line=target.line)

    # ------------------------------------------------------------------ expressions
    def eval(self, n: Node):
        k = n.kind
        if k == "num":
            return n.a
        if k == "str":
            return n.a
        if k == "name":
            var = self.lookup(n.a)
            if var is not None:
                return var.v
            if n.a in self.enum_values:
                return self.enum_values[n.a]
            return self.api.name(n.a, n.line)
        if k == "bin":
            op = n.a
            if op == "&&":
                return self.truth(self.eval(n.b)) and self.truth(self.eval(n.c))
            if op == "||":
                return self.truth(self.eval(n.b)) or self.truth(self.eval(n.c))
            a = self.eval(n.b)
            b = self.eval(n.c)
            try:
                return _arith(op, a, b, n.line)
            except TypeError as e:
                raise ScriptError(f"Can't apply '{op}' to {type(a).__name__} and {type(b).__name__}.", line=n.line) from e
        if k == "unary":
            v = self.eval(n.b)
            if n.a == "!":
                return not self.truth(v)
            if n.a == "-":
                return -v
            if n.a == "~":
                return ~int(v)
            return v
        if k == "assign":
            op = n.a
            if op == "=":
                return self.assign_to(n.b, self.eval(n.c))
            cur = self.eval(n.b)
            return self.assign_to(n.b, _arith(op[:-1], cur, self.eval(n.c), n.line))
        if k in ("preinc", "postinc"):
            cur = self.eval(n.b)
            new = cur + (1 if n.a == "++" else -1)
            self.assign_to(n.b, new)
            return new if k == "preinc" else cur
        if k == "ternary":
            return self.eval(n.b) if self.truth(self.eval(n.a)) else self.eval(n.c)
        if k == "index":
            base = self.eval(n.a)
            idx = self.eval(n.b)
            if isinstance(base, MqlArr):
                return base.get(idx)
            if hasattr(base, "series_get"):
                return base.series_get(int(idx))
            if isinstance(base, str):
                return ord(base[int(idx)])
            raise ScriptError("Can't index into this value.", line=n.line)
        if k == "member":
            obj = self.eval(n.a)
            if isinstance(obj, MStruct):
                return getattr(obj, n.b)
            v = getattr(obj, n.b, None)
            if v is None:
                raise ScriptError(f"Unknown member '{n.b}'.", line=n.line)
            return v
        if k == "call":
            return self.call(n)
        if k == "cast":
            return cast(n.a, self.eval(n.b))
        if k == "null":
            return None
        if k == "dt":
            return self.api.parse_datetime(n.a)
        if k == "initlist":
            return MqlArr([self.eval(x) for x in n.a])
        raise ScriptError(f"Unsupported expression '{k}'.", line=n.line)

    def call(self, n: Node):
        f = n.a
        if f.kind == "name":
            name = f.a
            if name in self.funcs:
                ref_targets = []
                params = self.funcs[name].b
                for i, a in enumerate(n.b):
                    ref_targets.append(a if i < len(params) and params[i]["ref"] and a.kind in ("name", "index", "member") else None)
                args = [self.eval(a) for a in n.b]
                return self.call_user(name, args, ref_targets)
            return self.api.call(name, n.b, self, n.line)
        if f.kind == "member":
            obj = self.eval(f.a)
            meth = getattr(obj, f.b, None)
            if meth is None or not callable(meth):
                raise UnsupportedFeature(f"Method '{f.b}()' isn't supported on this object.", line=n.line)
            return meth(*[self.eval(a) for a in n.b])
        raise ScriptError("This expression can't be called.", line=n.line)
