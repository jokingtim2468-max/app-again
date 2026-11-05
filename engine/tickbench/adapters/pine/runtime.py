"""Pine Script execution: the AST is compiled to Python closures, then the whole script runs once per bar.

Series model
* Every variable declaration owns a *slot* with a current value and a per-bar history (``x[1]``).
* ``var`` / ``varip`` slots keep their value across bars; others start each bar as ``na``.
* Each call site of a user function gets its own frame, so series and ``ta.*`` state inside
  functions behave like TradingView's (one instance per call site).
* ``ta.*`` built-ins keep streaming state per call site (``frame.state[node_id]``).
"""

from __future__ import annotations

import math
from typing import Any, Callable

from ...errors import ScriptError, UnsupportedFeature
from .parser import Node

NA = math.nan
MAX_LOOP = 1_000_000


def is_na(v) -> bool:
    return v is None or (isinstance(v, float) and v != v)


def truthy(v) -> bool:
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    if isinstance(v, float):
        return v == v and v != 0.0
    if isinstance(v, int):
        return v != 0
    return bool(v)


class BreakEx(Exception):
    pass


class ContinueEx(Exception):
    pass


class Slot:
    __slots__ = ("cur", "hist", "persist", "inited")

    def __init__(self, persist: bool):
        self.cur: Any = NA
        self.hist: list = []
        self.persist = persist
        self.inited = False


class Frame:
    __slots__ = ("slots", "state", "children", "last_bar")

    def __init__(self, nslots: int, persist: list[bool]):
        self.slots = [Slot(p) for p in persist]
        self.state: dict[int, Any] = {}
        self.children: dict[int, "Frame"] = {}
        self.last_bar = -1

    def commit(self):
        for s in self.slots:
            s.hist.append(s.cur)
            if not s.persist:
                s.cur = NA


class Scope:
    """Compile-time scope: name -> slot index, plus whether it belongs to the global frame."""

    def __init__(self, parent: "Scope | None", is_func: bool, func: "FuncInfo | None" = None):
        self.parent = parent
        self.names: dict[str, int] = {}
        self.is_func = is_func
        self.func = func

    def lookup(self, name) -> tuple[bool, int] | None:
        s = self
        while s is not None:
            if name in s.names:
                return (s.owner_is_global(), s.names[name])
            s = s.parent
        return None

    def owner_is_global(self) -> bool:
        s = self
        while s is not None:
            if s.is_func:
                return False
            s = s.parent
        return True


class FuncInfo:
    def __init__(self, name: str, params: list, line: int):
        self.name = name
        self.params = params
        self.line = line
        self.persist: list[bool] = []
        self.body: Callable | None = None
        self.param_slots: list[int] = []
        self.defaults: list = []


class Runtime:
    """Holds per-run state that compiled closures read: current frame, bar index, globals."""

    def __init__(self, host):
        self.host = host               # PineAdapter: bars, broker, ctx, builtins
        self.i = 0
        self.root: Frame | None = None
        self.frame: Frame | None = None
        self.visited: list[Frame] = []
        self.loop_count = 0


class Compiler:
    def __init__(self, builtins, constants, line_text: Callable[[int], str]):
        self.builtins = builtins      # name -> callable(rt, nid, args, kwargs, node)
        self.constants = constants    # name -> value or callable(rt)
        self.global_persist: list[bool] = []
        self.funcs: dict[str, FuncInfo] = {}
        self.cur_func: FuncInfo | None = None
        self.line_text = line_text

    # ---------------------------------------------------------------- slots
    def _new_slot(self, scope: Scope, name: str, persist: bool) -> tuple[bool, int]:
        is_global = scope.owner_is_global()
        lst = self.global_persist if is_global else self.cur_func.persist
        lst.append(persist)
        idx = len(lst) - 1
        scope.names[name] = idx
        return is_global, idx

    # ---------------------------------------------------------------- program
    def compile_program(self, stmts: list[Node]) -> Callable:
        scope = Scope(None, False)
        body = self.block(stmts, scope)
        return body

    def block(self, stmts: list[Node], scope: Scope) -> Callable:
        fns = [self.stmt(s, scope) for s in stmts]
        fns = [f for f in fns if f is not None]
        if not fns:
            return lambda rt: NA
        if len(fns) == 1:
            return fns[0]

        def run(rt, fns=fns):
            v = NA
            for f in fns:
                v = f(rt)
            return v
        return run

    # ---------------------------------------------------------------- statements
    def stmt(self, n: Node, scope: Scope) -> Callable | None:
        f = self._stmt(n, scope)
        if f is None:
            return None
        line = n.line

        def guarded(rt, f=f):
            try:
                return f(rt)
            except (BreakEx, ContinueEx):
                raise
            except ScriptError as e:
                if e.line is None:
                    e.line = line
                raise
            except RecursionError:
                raise
            except Exception as e:  # turn Python errors into script errors that point at the Pine line
                raise ScriptError(f"Runtime error: {type(e).__name__}: {e}", line=line) from e
        return guarded

    def _stmt(self, n: Node, scope: Scope) -> Callable | None:
        k = n.kind
        if k == "exprstmt":
            return self.expr(n.a, scope)
        if k == "decl":
            return self.decl(n, scope)
        if k == "assign":
            return self.assign(n, scope)
        if k == "tupledecl":
            return self.tupledecl(n, scope)
        if k == "funcdef":
            self.funcdef(n, scope)
            return None
        if k in ("if", "for", "forin", "while", "switch"):
            return self.expr(n, scope)
        if k == "break":
            def brk(rt):
                raise BreakEx()
            return brk
        if k == "continue":
            def cont(rt):
                raise ContinueEx()
            return cont
        raise ScriptError(f"Unsupported statement '{k}'.", line=n.line)

    def _slot_ref(self, is_global, idx):
        if is_global:
            return lambda rt: rt.root.slots[idx]
        return lambda rt: rt.frame.slots[idx]

    def decl(self, n: Node, scope: Scope) -> Callable:
        rhs = self.expr(n.b, scope)
        persist = n.c in ("var", "varip")
        if n.a in scope.names:
            raise ScriptError(f"'{n.a}' is already declared in this scope. Use ':=' to change it.", line=n.line)
        is_global, idx = self._new_slot(scope, n.a, persist)
        ref = self._slot_ref(is_global, idx)
        if persist:
            def run(rt):
                s = ref(rt)
                if not s.inited:
                    s.cur = rhs(rt)
                    s.inited = True
                return s.cur
        else:
            def run(rt):
                s = ref(rt)
                v = rhs(rt)
                s.cur = v
                return v
        return run

    def assign(self, n: Node, scope: Scope) -> Callable:
        found = scope.lookup(n.a)
        if found is None:
            raise ScriptError(f"Can't assign to '{n.a}' before it is declared.", line=n.line,
                              hint=f"Declare it first: {n.a} = 0.0")
        ref = self._slot_ref(*found)
        rhs = self.expr(n.b, scope)
        op = n.c
        if op == ":=":
            def run(rt):
                v = rhs(rt)
                ref(rt).cur = v
                return v
        else:
            f = BINOPS[op[0]]

            def run(rt):
                s = ref(rt)
                v = f(s.cur, rhs(rt))
                s.cur = v
                return v
        return run

    def tupledecl(self, n: Node, scope: Scope) -> Callable:
        rhs = self.expr(n.b, scope)
        refs = []
        for name in n.a:
            if n.c == ":=":
                found = scope.lookup(name)
                if found is None:
                    raise ScriptError(f"Can't assign to '{name}' before it is declared.", line=n.line)
                refs.append(self._slot_ref(*found))
            elif name == "_":
                refs.append(None)
            else:
                refs.append(self._slot_ref(*self._new_slot(scope, name, False)))
        count = len(refs)

        def run(rt):
            v = rhs(rt)
            if not isinstance(v, (tuple, list)):
                v = (v,) + (NA,) * (count - 1)
            for r, x in zip(refs, v):
                if r is not None:
                    r(rt).cur = x
            return v
        return run

    def funcdef(self, n: Node, scope: Scope) -> None:
        if self.cur_func is not None:
            raise ScriptError("Functions can't be defined inside other functions.", line=n.line)
        fi = FuncInfo(n.a, n.b, n.line)
        self.funcs[n.a] = fi  # register first so the body can see its own name (recursion is rejected at call)
        self.cur_func = fi
        fscope = Scope(scope, True, fi)
        for pname, default in n.b:
            _, idx = self._new_slot(fscope, pname, False)
            fi.param_slots.append(idx)
            fi.defaults.append(self.expr(default, scope) if default is not None else None)
        fi.body = self.block(n.c, fscope)
        self.cur_func = None

    # ---------------------------------------------------------------- expressions
    def expr(self, n: Node, scope: Scope) -> Callable:
        k = n.kind
        if k == "num":
            v = n.a
            return lambda rt: v
        if k == "str":
            v = n.a
            return lambda rt: v
        if k == "bool":
            v = n.a
            return lambda rt: v
        if k == "na":
            return lambda rt: NA
        if k == "name":
            return self.name(n, scope)
        if k == "tuple":
            items = [self.expr(x, scope) for x in n.a]
            return lambda rt: tuple(f(rt) for f in items)
        if k == "bin":
            f = BINOPS[n.a]
            a, b = self.expr(n.b, scope), self.expr(n.c, scope)
            return lambda rt: f(a(rt), b(rt))
        if k == "and":
            a, b = self.expr(n.a, scope), self.expr(n.b, scope)
            return lambda rt: truthy(a(rt)) and truthy(b(rt))
        if k == "or":
            a, b = self.expr(n.a, scope), self.expr(n.b, scope)
            return lambda rt: truthy(a(rt)) or truthy(b(rt))
        if k == "not":
            a = self.expr(n.a, scope)
            return lambda rt: not truthy(a(rt))
        if k == "neg":
            a = self.expr(n.a, scope)

            def neg(rt):
                v = a(rt)
                return NA if v is None else -v
            return neg
        if k == "pos":
            return self.expr(n.a, scope)
        if k == "ternary":
            c, a, b = self.expr(n.a, scope), self.expr(n.b, scope), self.expr(n.c, scope)
            return lambda rt: a(rt) if truthy(c(rt)) else b(rt)
        if k == "hist":
            return self.hist(n, scope)
        if k == "call":
            return self.call(n, scope)
        if k == "member":
            obj = self.expr(n.a, scope)
            field = n.b

            def member(rt):
                o = obj(rt)
                if isinstance(o, dict) and field in o:
                    return o[field]
                return getattr(o, field, NA)
            return member
        if k == "if":
            return self.if_(n, scope)
        if k == "for":
            return self.for_(n, scope)
        if k == "forin":
            return self.forin(n, scope)
        if k == "while":
            return self.while_(n, scope)
        if k == "switch":
            return self.switch(n, scope)
        raise ScriptError(f"Unsupported expression '{k}'.", line=n.line)

    def name(self, n: Node, scope: Scope) -> Callable:
        name = n.a
        found = scope.lookup(name)
        if found is not None:
            is_global, idx = found
            if is_global:
                return lambda rt: rt.root.slots[idx].cur
            return lambda rt: rt.frame.slots[idx].cur
        c = self.constants.get(name)
        if c is not None:
            if callable(c):
                return c
            return lambda rt: c
        if name in self.constants:  # explicit None constant
            return lambda rt: None
        # Pine v4: bare series names like `tr`, `vwap`
        alt = self.constants.get("ta." + name)
        if alt is not None and callable(alt):
            return alt
        raise ScriptError(f"Unknown variable '{name}'.", line=n.line,
                          hint="Check the spelling, or declare it before use.")

    def hist(self, n: Node, scope: Scope) -> Callable:
        offset = self.expr(n.b, scope)
        inner = n.a
        if inner.kind == "name":
            found = scope.lookup(inner.a)
            if found is not None:
                is_global, idx = found

                def h(rt):
                    s = (rt.root if is_global else rt.frame).slots[idx]
                    k = offset(rt)
                    if is_na(k):
                        return NA
                    k = int(k)
                    if k == 0:
                        return s.cur
                    hl = s.hist
                    return hl[-k] if 0 < k <= len(hl) else NA
                return h
            series = self.constants.get("__series__:" + inner.a)
            if series is not None:
                def hs(rt):
                    k = offset(rt)
                    if is_na(k):
                        return NA
                    j = rt.i - int(k)
                    return series(rt, j) if 0 <= j <= rt.i else NA
                return hs
        # history of an arbitrary expression: record its value each time it's evaluated
        ev = self.expr(inner, scope)
        nid = n.nid

        def hx(rt):
            v = ev(rt)
            st = rt.frame.state
            buf = st.get(nid)
            if buf is None:
                buf = st[nid] = {}
            buf[rt.i] = v
            k = offset(rt)
            if is_na(k):
                return NA
            k = int(k)
            if k == 0:
                return v
            return buf.get(rt.i - k, NA)
        return hx

    def call(self, n: Node, scope: Scope) -> Callable:
        name = n.d
        args = [self.expr(a, scope) for a in n.b]
        kwargs = {k: self.expr(v, scope) for k, v in n.c.items()}
        if name is None:
            # method-style call on a value: obj.method(...)
            if n.a.kind == "member":
                obj = self.expr(n.a.a, scope)
                meth = n.a.b
                fn = self.builtins.get("array." + meth)
                if fn is None:
                    raise UnsupportedFeature(f"Method '.{meth}()' isn't supported.", line=n.line)
                nid = n.nid

                def mcall(rt):
                    return fn(rt, nid, [obj(rt)] + [a(rt) for a in args], {k: v(rt) for k, v in kwargs.items()}, n)
                return mcall
            raise ScriptError("This expression can't be called.", line=n.line)
        # method call on a variable: arr.push(x) parsed as name "arr.push"
        if "." in name and name not in self.builtins:
            head, _, meth = name.rpartition(".")
            found = scope.lookup(head)
            if found is not None:
                fn = self.builtins.get("array." + meth)
                if fn is None:
                    raise UnsupportedFeature(f"Method '.{meth}()' isn't supported.", line=n.line)
                getter = self.name(Node("name", n.line, a=head), scope)
                nid = n.nid

                def vcall(rt):
                    return fn(rt, nid, [getter(rt)] + [a(rt) for a in args], {k: v(rt) for k, v in kwargs.items()}, n)
                return vcall
        if name in self.funcs:
            return self.user_call(n, self.funcs[name], args, kwargs)
        fn = self.builtins.get(name)
        if fn is None:
            for prefix in ("ta.", "math.", "str."):
                fn = self.builtins.get(prefix + name)
                if fn is not None:
                    break
        if fn is None:
            ns = name.split(".")[0]
            if ns in ("request", "matrix", "map", "polyline", "ticker", "chart"):
                raise UnsupportedFeature(f"{name}() isn't supported (no multi-symbol/advanced objects yet).",
                                         line=n.line, hint="Remove or replace that call to backtest this script.")
            raise UnsupportedFeature(f"{name}() isn't supported yet.", line=n.line,
                                     hint="Tickbench runs the common Pine subset; this built-in is missing.")
        nid = n.nid
        if not kwargs:
            def bcall(rt):
                return fn(rt, nid, [a(rt) for a in args], {}, n)
            return bcall

        def bcallk(rt):
            return fn(rt, nid, [a(rt) for a in args], {k: v(rt) for k, v in kwargs.items()}, n)
        return bcallk

    def user_call(self, n: Node, fi: FuncInfo, args, kwargs) -> Callable:
        nid = n.nid
        pnames = [p[0] for p in fi.params]
        if len(args) > len(pnames):
            raise ScriptError(f"{fi.name}() takes {len(pnames)} argument(s), got {len(args)}.", line=n.line)
        for k in kwargs:
            if k not in pnames:
                raise ScriptError(f"{fi.name}() has no parameter '{k}'.", line=n.line)
        if self.cur_func is fi:
            raise ScriptError(f"{fi.name}() calls itself; Pine doesn't allow recursion.", line=n.line)

        def ucall(rt):
            vals = []
            for i, pname in enumerate(pnames):
                if i < len(args):
                    vals.append(args[i](rt))
                elif pname in kwargs:
                    vals.append(kwargs[pname](rt))
                elif fi.defaults[i] is not None:
                    vals.append(fi.defaults[i](rt))
                else:
                    vals.append(NA)
            parent = rt.frame
            fr = parent.children.get(nid)
            if fr is None:
                fr = parent.children[nid] = Frame(len(fi.persist), fi.persist)
            if fr.last_bar != rt.i:
                fr.last_bar = rt.i
                rt.visited.append(fr)
            for idx, v in zip(fi.param_slots, vals):
                fr.slots[idx].cur = v
            rt.frame = fr
            try:
                return fi.body(rt)
            finally:
                rt.frame = parent
        return ucall

    def if_(self, n: Node, scope: Scope) -> Callable:
        cond = self.expr(n.a, scope)
        body = self.block(n.b, Scope(scope, False))
        orelse = self.block(n.c, Scope(scope, False)) if n.c else None
        if orelse is None:
            return lambda rt: body(rt) if truthy(cond(rt)) else NA
        return lambda rt: body(rt) if truthy(cond(rt)) else orelse(rt)

    def for_(self, n: Node, scope: Scope) -> Callable:
        inner = Scope(scope, False)
        is_global, idx = self._new_slot(inner, n.a, False)
        ref = self._slot_ref(is_global, idx)
        a, b, step = n.b
        fa, fb = self.expr(a, scope), self.expr(b, scope)
        fs = self.expr(step, scope) if step is not None else None
        body = self.block(n.c, inner)
        line = n.line

        def run(rt):
            start, end = fa(rt), fb(rt)
            if is_na(start) or is_na(end):
                return NA
            st = fs(rt) if fs else (1 if end >= start else -1)
            if st == 0 or is_na(st):
                raise ScriptError("for-loop step is 0.", line=line)
            st = abs(st) if end >= start else -abs(st)
            v = NA
            x = start
            slot = ref(rt)
            while (x <= end) if st > 0 else (x >= end):
                rt.loop_count += 1
                if rt.loop_count > MAX_LOOP:
                    raise ScriptError("Loop ran more than 1,000,000 iterations on one bar.", line=line)
                slot.cur = x
                try:
                    v = body(rt)
                except ContinueEx:
                    pass
                except BreakEx:
                    break
                x += st
            return v
        return run

    def forin(self, n: Node, scope: Scope) -> Callable:
        inner = Scope(scope, False)
        idx_name, var = n.a
        iref = self._slot_ref(*self._new_slot(inner, idx_name, False)) if idx_name else None
        vref = self._slot_ref(*self._new_slot(inner, var, False))
        coll = self.expr(n.b, scope)
        body = self.block(n.c, inner)

        def run(rt):
            c = coll(rt)
            items = getattr(c, "items", c) or []
            v = NA
            for i, x in enumerate(list(items)):
                if iref:
                    iref(rt).cur = i
                vref(rt).cur = x
                try:
                    v = body(rt)
                except ContinueEx:
                    pass
                except BreakEx:
                    break
            return v
        return run

    def while_(self, n: Node, scope: Scope) -> Callable:
        cond = self.expr(n.a, scope)
        body = self.block(n.b, Scope(scope, False))
        line = n.line

        def run(rt):
            v = NA
            while truthy(cond(rt)):
                rt.loop_count += 1
                if rt.loop_count > MAX_LOOP:
                    raise ScriptError("while-loop ran more than 1,000,000 iterations on one bar.", line=line)
                try:
                    v = body(rt)
                except ContinueEx:
                    pass
                except BreakEx:
                    break
            return v
        return run

    def switch(self, n: Node, scope: Scope) -> Callable:
        subject = self.expr(n.a, scope) if n.a is not None else None
        cases = []
        for key, body in n.b:
            k = self.expr(key, scope) if key is not None else None
            cases.append((k, self.block(body, Scope(scope, False))))

        def run(rt):
            if subject is not None:
                s = subject(rt)
                for k, body in cases:
                    if k is None or k(rt) == s:
                        return body(rt)
            else:
                for k, body in cases:
                    if k is None or truthy(k(rt)):
                        return body(rt)
            return NA
        return run


def _num(v):
    return NA if v is None else v


def _add(a, b):
    if a is None or b is None:
        return NA
    try:
        return a + b
    except TypeError:
        if isinstance(a, str) or isinstance(b, str):
            return f"{a}{b}"
        raise


def _div(a, b):
    if a is None or b is None:
        return NA
    try:
        return a / b
    except ZeroDivisionError:
        return NA


def _mod(a, b):
    if a is None or b is None:
        return NA
    try:
        return math.fmod(a, b)
    except (ZeroDivisionError, ValueError):
        return NA


def _cmp(f):
    def g(a, b):
        if a is None or b is None:
            return False
        try:
            return f(a, b)
        except TypeError:
            return False
    return g


def _eq(a, b):
    if is_na(a) and is_na(b):
        return False
    return a == b


def _ne(a, b):
    if is_na(a) or is_na(b):
        return False
    return a != b


BINOPS: dict[str, Callable] = {
    "+": _add,
    "-": lambda a, b: NA if a is None or b is None else a - b,
    "*": lambda a, b: NA if a is None or b is None else a * b,
    "/": _div,
    "%": _mod,
    "==": _eq,
    "!=": _ne,
    "<": _cmp(lambda a, b: a < b),
    ">": _cmp(lambda a, b: a > b),
    "<=": _cmp(lambda a, b: a <= b),
    ">=": _cmp(lambda a, b: a >= b),
}
