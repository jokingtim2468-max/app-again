"""Pine Script lexer and parser (v4 / v5 / v6 common subset).

Produces a small AST of ``Node`` objects. Indentation (4 spaces or a tab) opens blocks; a line is
a continuation of the previous one when brackets are still open, when the previous line ends with
an operator or comma, or when it is indented by a non-multiple of 4 (Pine's wrapping rule).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ...errors import ScriptError, UnsupportedFeature

KEYWORDS = {"if", "else", "for", "to", "by", "in", "while", "switch", "var", "varip", "and", "or", "not",
            "true", "false", "break", "continue", "import", "export", "method", "type", "enum"}
TYPE_WORDS = {"int", "float", "bool", "string", "color", "line", "label", "box", "table", "array", "matrix",
              "map", "linefill", "polyline", "series", "simple", "const"}
CONT_END = {"+", "-", "*", "/", "%", "==", "!=", "<", ">", "<=", ">=", "and", "or", "not", "?", ":", ",", "(",
            "[", ":=", "=", "+=", "-=", "*=", "/=", "%="}

TOKEN_RE = re.compile(r"""
    (?P<ws>[ \t]+)
  | (?P<color>\#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?\b)
  | (?P<num>(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?)
  | (?P<str>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')
  | (?P<op>:=|=>|==|!=|<=|>=|\+=|-=|\*=|/=|%=|[-+*/%<>=?:,()\[\].])
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
""", re.X)


@dataclass
class Tok:
    kind: str     # num str color name op NEWLINE INDENT DEDENT EOF
    value: Any
    line: int
    col: int = 0
    end: int = 0


@dataclass
class Node:
    kind: str
    line: int
    a: Any = None
    b: Any = None
    c: Any = None
    d: Any = None
    text: str = ""
    nid: int = 0
    kids: list = field(default_factory=list)


def _strip_comment(line: str) -> str:
    out = []
    q = None
    i = 0
    while i < len(line):
        ch = line[i]
        if q:
            out.append(ch)
            if ch == "\\" and i + 1 < len(line):
                out.append(line[i + 1])
                i += 2
                continue
            if ch == q:
                q = None
        else:
            if ch in "\"'":
                q = ch
            elif ch == "/" and line[i + 1:i + 2] == "/":
                break
            out.append(ch)
        i += 1
    return "".join(out).rstrip()


def _indent_width(line: str) -> int:
    w = 0
    for ch in line:
        if ch == " ":
            w += 1
        elif ch == "\t":
            w += 4
        else:
            break
    return w


def tokenize(src: str) -> list[Tok]:
    lines = src.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    logical: list[tuple[int, int, list[Tok]]] = []  # (indent, line_no, tokens)
    depth = 0
    for ln, raw in enumerate(lines, start=1):
        text = _strip_comment(raw)
        if not text.strip():
            continue
        indent = _indent_width(text)
        toks: list[Tok] = []
        pos = 0
        body = text
        while pos < len(body):
            m = TOKEN_RE.match(body, pos)
            if not m:
                raise ScriptError(f"Unexpected character '{body[pos]}'", line=ln,
                                  hint="Check for a stray symbol or an unclosed string.")
            kind = m.lastgroup
            val = m.group(kind)
            if kind != "ws":
                if kind == "num":
                    v = float(val) if any(c in val for c in ".eE") else int(val)
                    toks.append(Tok("num", v, ln, m.start(), m.end()))
                elif kind == "str":
                    s = val[1:-1].encode("utf-8").decode("unicode_escape") if "\\" in val else val[1:-1]
                    toks.append(Tok("str", s, ln, m.start(), m.end()))
                elif kind == "op":
                    toks.append(Tok("op", val, ln, m.start(), m.end()))
                    if val in "([":
                        depth += 1
                    elif val in ")]":
                        depth = max(0, depth - 1)
                else:
                    toks.append(Tok(kind, val, ln, m.start(), m.end()))
            pos = m.end()
        if not toks:
            continue
        prev = logical[-1] if logical else None
        is_cont = False
        if prev is not None:
            last = prev[2][-1]
            if _open_depth(prev[2]) > 0:
                is_cont = True                      # inside unclosed ( or [
            elif last.kind == "op" and last.value in CONT_END and last.value != "=":
                is_cont = True                      # line ended with an operator or comma
            elif last.kind == "name" and last.value in ("and", "or", "not"):
                is_cont = True
            elif indent % 4 != 0 and indent > prev[0]:
                is_cont = True                      # Pine's wrap rule: non-multiple-of-4 indent
        if is_cont and prev is not None:
            prev[2].extend(toks)
        else:
            logical.append((indent, ln, toks))
        depth = 0

    out: list[Tok] = []
    stack = [0]
    for indent, ln, toks in logical:
        if indent > stack[-1]:
            stack.append(indent)
            out.append(Tok("INDENT", None, ln))
        else:
            while indent < stack[-1]:
                stack.pop()
                out.append(Tok("DEDENT", None, ln))
            if indent != stack[-1]:
                raise ScriptError("Indentation doesn't match any outer block.", line=ln,
                                  hint="Indent block bodies by exactly 4 spaces or one tab.")
        out.extend(toks)
        out.append(Tok("NEWLINE", None, ln))
    last_ln = logical[-1][1] if logical else 1
    while len(stack) > 1:
        stack.pop()
        out.append(Tok("DEDENT", None, last_ln))
    out.append(Tok("EOF", None, last_ln))
    return out


def _open_depth(toks: list[Tok]) -> int:
    d = 0
    for t in toks:
        if t.kind == "op":
            if t.value in "([":
                d += 1
            elif t.value in ")]":
                d -= 1
    return d


class Parser:
    def __init__(self, src: str):
        self.src_lines = src.replace("\r\n", "\n").split("\n")
        self.toks = tokenize(src)
        self.p = 0
        self.nid = 0
        self.cond_stack: list[str] = []

    # ------------------------------------------------------------- helpers
    def node(self, kind, line, **kw) -> Node:
        self.nid += 1
        n = Node(kind, line, nid=self.nid)
        for k, v in kw.items():
            setattr(n, k, v)
        return n

    @property
    def t(self) -> Tok:
        return self.toks[self.p]

    def peek(self, k=1) -> Tok:
        return self.toks[min(self.p + k, len(self.toks) - 1)]

    def at(self, kind, value=None) -> bool:
        t = self.t
        return t.kind == kind and (value is None or t.value == value)

    def at_op(self, *vals) -> bool:
        return self.t.kind == "op" and self.t.value in vals

    def at_kw(self, *vals) -> bool:
        return self.t.kind == "name" and self.t.value in vals

    def eat(self, kind, value=None) -> Tok:
        if not self.at(kind, value):
            want = value or kind
            got = self.t.value if self.t.value is not None else self.t.kind
            raise ScriptError(f"Expected '{want}' but found '{got}'", line=self.t.line,
                              hint="Check the syntax on this line.")
        t = self.t
        self.p += 1
        return t

    def skip_newlines(self):
        while self.at("NEWLINE"):
            self.p += 1

    def text_of(self, start: int, end: int) -> str:
        toks = self.toks[start:end]
        toks = [t for t in toks if t.kind not in ("NEWLINE", "INDENT", "DEDENT", "EOF")]
        if not toks:
            return ""
        parts = []
        for t in toks:
            if t.kind == "str":
                parts.append(f'"{t.value}"')
            else:
                parts.append(str(t.value))
        s = " ".join(parts)
        s = re.sub(r"\s*\.\s*", ".", s)
        s = re.sub(r"\(\s+", "(", s)
        s = re.sub(r"\s+\)", ")", s)
        s = re.sub(r"\s+,", ",", s)
        s = re.sub(r"\[\s+", "[", s)
        s = re.sub(r"\s+\]", "]", s)
        s = re.sub(r"(\w)\s+\(", r"\1(", s)
        return s

    # ------------------------------------------------------------- program
    def parse(self) -> list[Node]:
        stmts = []
        self.skip_newlines()
        while not self.at("EOF"):
            if self.at("INDENT"):
                raise ScriptError("Unexpected indentation.", line=self.t.line,
                                  hint="Only the bodies of if/for/while/switch and functions are indented.")
            s = self.statement()
            if s is not None:
                stmts.append(s)
            self.skip_newlines()
        return stmts

    def block(self) -> list[Node]:
        self.eat("NEWLINE")
        self.skip_newlines()
        self.eat("INDENT")
        stmts = []
        while not self.at("DEDENT") and not self.at("EOF"):
            s = self.statement()
            if s is not None:
                stmts.append(s)
            self.skip_newlines()
        if self.at("DEDENT"):
            self.p += 1
        return stmts

    # ------------------------------------------------------------- statements
    def statement(self) -> Node | None:
        t = self.t
        line = t.line
        if t.kind == "name":
            v = t.value
            if v in ("import", "export", "method", "type", "enum"):
                raise UnsupportedFeature(f"'{v}' declarations aren't supported.", line=line,
                                         hint="Libraries, methods and user-defined types can't be run yet.")
            if v == "if":
                return self.if_stmt()
            if v == "for":
                return self.for_stmt()
            if v == "while":
                return self.while_stmt()
            if v == "switch":
                return self.switch_stmt()
            if v == "break":
                self.p += 1
                return self.node("break", line)
            if v == "continue":
                self.p += 1
                return self.node("continue", line)
            if v in ("var", "varip"):
                return self.declaration()
            if self.is_func_def():
                return self.func_def()
            if self.is_typed_decl():
                return self.declaration()
            nxt = self.peek()
            if nxt.kind == "op" and nxt.value == "=":
                return self.declaration()
            if nxt.kind == "op" and nxt.value in (":=", "+=", "-=", "*=", "/=", "%="):
                return self.reassign()
        if t.kind == "op" and t.value == "[" and self.is_tuple_decl():
            return self.tuple_decl()
        start = self.p
        e = self.expr()
        n = self.node("exprstmt", line, a=e)
        n.text = self.text_of(start, self.p)
        if not self.at("NEWLINE") and not self.at("EOF") and not self.at("DEDENT"):
            raise ScriptError(f"Unexpected '{self.t.value}' after expression.", line=self.t.line)
        return n

    def is_func_def(self) -> bool:
        if not (self.t.kind == "name" and self.peek().kind == "op" and self.peek().value == "("):
            return False
        d = 0
        k = self.p + 1
        while k < len(self.toks):
            tk = self.toks[k]
            if tk.kind == "NEWLINE" or tk.kind == "EOF":
                return False
            if tk.kind == "op" and tk.value == "(":
                d += 1
            elif tk.kind == "op" and tk.value == ")":
                d -= 1
                if d == 0:
                    nx = self.toks[k + 1]
                    return nx.kind == "op" and nx.value == "=>"
            k += 1
        return False

    def _skip_type(self, k: int) -> int:
        """Return index after a type spec starting at k, or -1."""
        tk = self.toks[k]
        if tk.kind != "name":
            return -1
        while tk.kind == "name" and tk.value in ("series", "simple", "const"):
            k += 1
            tk = self.toks[k]
        if tk.kind != "name":
            return -1
        k += 1
        if self.toks[k].kind == "op" and self.toks[k].value == ".":  # chart.point etc
            k += 2
        if self.toks[k].kind == "op" and self.toks[k].value == "<":
            d = 0
            while k < len(self.toks):
                if self.toks[k].kind == "op" and self.toks[k].value == "<":
                    d += 1
                elif self.toks[k].kind == "op" and self.toks[k].value == ">":
                    d -= 1
                    if d == 0:
                        k += 1
                        break
                elif self.toks[k].kind == "NEWLINE":
                    return -1
                k += 1
        if self.toks[k].kind == "op" and self.toks[k].value == "[" and self.toks[k + 1].kind == "op" and self.toks[k + 1].value == "]":
            k += 2  # float[] arr = ...
        return k

    def is_typed_decl(self) -> bool:
        if self.t.value not in TYPE_WORDS:
            return False
        k = self._skip_type(self.p)
        if k < 0:
            return False
        return (self.toks[k].kind == "name" and self.toks[k + 1].kind == "op" and self.toks[k + 1].value == "=")

    def is_tuple_decl(self) -> bool:
        d = 0
        k = self.p
        while k < len(self.toks):
            tk = self.toks[k]
            if tk.kind in ("NEWLINE", "EOF"):
                return False
            if tk.kind == "op" and tk.value == "[":
                d += 1
            elif tk.kind == "op" and tk.value == "]":
                d -= 1
                if d == 0:
                    nx = self.toks[k + 1]
                    return nx.kind == "op" and nx.value in ("=", ":=")
            k += 1
        return False

    def declaration(self) -> Node:
        line = self.t.line
        mode = None
        if self.at_kw("var", "varip"):
            mode = self.eat("name").value
        if self.t.kind == "name" and self.t.value in TYPE_WORDS and not (self.peek().kind == "op" and self.peek().value == "="):
            k = self._skip_type(self.p)
            if k > 0:
                self.p = k
        name = self.eat("name").value
        if name in KEYWORDS:
            raise ScriptError(f"'{name}' is a reserved word and can't be a variable name.", line=line)
        self.eat("op", "=")
        rhs = self.rhs()
        return self.node("decl", line, a=name, b=rhs, c=mode)

    def rhs(self) -> Node:
        if self.at_kw("if"):
            return self.if_stmt(as_expr=True)
        if self.at_kw("switch"):
            return self.switch_stmt(as_expr=True)
        if self.at_kw("for"):
            return self.for_stmt(as_expr=True)
        return self.expr()

    def reassign(self) -> Node:
        line = self.t.line
        name = self.eat("name").value
        op = self.eat("op").value
        rhs = self.rhs()
        return self.node("assign", line, a=name, b=rhs, c=op)

    def tuple_decl(self) -> Node:
        line = self.t.line
        self.eat("op", "[")
        names = []
        while True:
            names.append(self.eat("name").value)
            if self.at_op(","):
                self.p += 1
                continue
            break
        self.eat("op", "]")
        op = self.eat("op").value
        rhs = self.rhs()
        return self.node("tupledecl", line, a=names, b=rhs, c=op)

    def func_def(self) -> Node:
        line = self.t.line
        name = self.eat("name").value
        self.eat("op", "(")
        params = []
        while not self.at_op(")"):
            # optional type qualifiers before the param name
            while self.t.kind == "name" and self.peek().kind == "name":
                self.p += 1
            pname = self.eat("name").value
            default = None
            if self.at_op("="):
                self.p += 1
                default = self.expr()
            params.append((pname, default))
            if self.at_op(","):
                self.p += 1
        self.eat("op", ")")
        self.eat("op", "=>")
        if self.at("NEWLINE"):
            body = self.block()
        else:
            start = self.p
            e = self.expr()
            st = self.node("exprstmt", line, a=e)
            st.text = self.text_of(start, self.p)
            body = [st]
        return self.node("funcdef", line, a=name, b=params, c=body)

    def if_stmt(self, as_expr=False) -> Node:
        line = self.t.line
        self.eat("name", "if")
        start = self.p
        cond = self.expr()
        cond_text = self.text_of(start, self.p)
        self.cond_stack.append(cond_text)
        body = self.block()
        self.cond_stack.pop()
        orelse = None
        self.skip_newlines_if_else()
        if self.at_kw("else"):
            self.p += 1
            if self.at_kw("if"):
                orelse = [self.if_stmt(as_expr)]
            else:
                self.cond_stack.append(f"not ({cond_text})")
                orelse = self.block()
                self.cond_stack.pop()
        n = self.node("if", line, a=cond, b=body, c=orelse)
        n.text = cond_text
        return n

    def skip_newlines_if_else(self):
        # 'else' sits on its own line after the DEDENT that closed the if-body
        k = self.p
        while self.toks[k].kind == "NEWLINE":
            k += 1
        if self.toks[k].kind == "name" and self.toks[k].value == "else":
            self.p = k

    def for_stmt(self, as_expr=False) -> Node:
        line = self.t.line
        self.eat("name", "for")
        if self.at_op("["):  # for [i, x] in array
            self.p += 1
            idx = self.eat("name").value
            self.eat("op", ",")
            var = self.eat("name").value
            self.eat("op", "]")
            self.eat("name", "in")
            coll = self.expr()
            body = self.block()
            return self.node("forin", line, a=(idx, var), b=coll, c=body)
        var = self.eat("name").value
        if self.at_kw("in"):
            self.p += 1
            coll = self.expr()
            body = self.block()
            return self.node("forin", line, a=(None, var), b=coll, c=body)
        self.eat("op", "=")
        a = self.expr()
        self.eat("name", "to")
        b = self.expr()
        step = None
        if self.at_kw("by"):
            self.p += 1
            step = self.expr()
        body = self.block()
        n = self.node("for", line, a=var, b=(a, b, step), c=body)
        return n

    def while_stmt(self) -> Node:
        line = self.t.line
        self.eat("name", "while")
        cond = self.expr()
        body = self.block()
        return self.node("while", line, a=cond, b=body)

    def switch_stmt(self, as_expr=False) -> Node:
        line = self.t.line
        self.eat("name", "switch")
        subject = None
        if not self.at("NEWLINE"):
            subject = self.expr()
        self.eat("NEWLINE")
        self.skip_newlines()
        self.eat("INDENT")
        cases = []
        while not self.at("DEDENT") and not self.at("EOF"):
            cline = self.t.line
            if self.at_op("=>"):
                key = None
            else:
                key = self.expr()
            self.eat("op", "=>")
            if self.at("NEWLINE"):
                body = self.block()
            else:
                start = self.p
                e = self.rhs() if self.at_kw("if", "switch") else self.statement_inline()
                body = [e]
            cases.append((key, body))
            self.skip_newlines()
        if self.at("DEDENT"):
            self.p += 1
        return self.node("switch", line, a=subject, b=cases)

    def statement_inline(self) -> Node:
        """A single statement on the same line (used after `=>` in switch cases)."""
        t = self.t
        if t.kind == "name" and self.peek().kind == "op" and self.peek().value in (":=", "+=", "-=", "*=", "/=", "%="):
            return self.reassign()
        start = self.p
        line = t.line
        e = self.expr()
        n = self.node("exprstmt", line, a=e)
        n.text = self.text_of(start, self.p)
        return n

    # ------------------------------------------------------------- expressions
    def expr(self) -> Node:
        return self.ternary()

    def ternary(self) -> Node:
        cond = self.or_()
        if self.at_op("?"):
            line = self.t.line
            self.p += 1
            a = self.ternary()
            self.eat("op", ":")
            b = self.ternary()
            return self.node("ternary", line, a=cond, b=a, c=b)
        return cond

    def or_(self) -> Node:
        left = self.and_()
        while self.at_kw("or"):
            line = self.t.line
            self.p += 1
            right = self.and_()
            left = self.node("or", line, a=left, b=right)
        return left

    def and_(self) -> Node:
        left = self.not_()
        while self.at_kw("and"):
            line = self.t.line
            self.p += 1
            right = self.not_()
            left = self.node("and", line, a=left, b=right)
        return left

    def not_(self) -> Node:
        if self.at_kw("not"):
            line = self.t.line
            self.p += 1
            return self.node("not", line, a=self.not_())
        return self.equality()

    def equality(self) -> Node:
        left = self.comparison()
        while self.at_op("==", "!="):
            op = self.t.value
            line = self.t.line
            self.p += 1
            left = self.node("bin", line, a=op, b=left, c=self.comparison())
        return left

    def comparison(self) -> Node:
        left = self.additive()
        while self.at_op("<", ">", "<=", ">="):
            op = self.t.value
            line = self.t.line
            self.p += 1
            left = self.node("bin", line, a=op, b=left, c=self.additive())
        return left

    def additive(self) -> Node:
        left = self.term()
        while self.at_op("+", "-"):
            op = self.t.value
            line = self.t.line
            self.p += 1
            left = self.node("bin", line, a=op, b=left, c=self.term())
        return left

    def term(self) -> Node:
        left = self.unary()
        while self.at_op("*", "/", "%"):
            op = self.t.value
            line = self.t.line
            self.p += 1
            left = self.node("bin", line, a=op, b=left, c=self.unary())
        return left

    def unary(self) -> Node:
        if self.at_op("-", "+"):
            op = self.t.value
            line = self.t.line
            self.p += 1
            return self.node("neg" if op == "-" else "pos", line, a=self.unary())
        return self.postfix()

    def postfix(self) -> Node:
        e = self.primary()
        while True:
            if self.at_op("("):
                e = self.call(e)
            elif self.at_op("["):
                line = self.t.line
                self.p += 1
                idx = self.expr()
                self.eat("op", "]")
                e = self.node("hist", line, a=e, b=idx)
            elif self.at_op(".") and self.peek().kind == "name":
                line = self.t.line
                self.p += 1
                name = self.eat("name").value
                if e.kind == "name":
                    e = self.node("name", line, a=f"{e.a}.{name}")
                else:
                    e = self.node("member", line, a=e, b=name)
            elif self.at_op("<") and e.kind == "name" and e.a.endswith(("new", ".new")) and self._generic_ahead():
                # array.new<float>(...), map.new<string, float>()
                depth = 0
                while True:
                    if self.at_op("<"):
                        depth += 1
                    elif self.at_op(">"):
                        depth -= 1
                        if depth == 0:
                            self.p += 1
                            break
                    self.p += 1
            else:
                break
        return e

    def _generic_ahead(self) -> bool:
        k = self.p
        depth = 0
        while k < len(self.toks) and k < self.p + 12:
            tk = self.toks[k]
            if tk.kind == "op" and tk.value == "<":
                depth += 1
            elif tk.kind == "op" and tk.value == ">":
                depth -= 1
                if depth == 0:
                    nx = self.toks[k + 1]
                    return nx.kind == "op" and nx.value == "("
            elif tk.kind not in ("name",) and not (tk.kind == "op" and tk.value == ","):
                return False
            k += 1
        return False

    def call(self, fn: Node) -> Node:
        line = self.t.line
        self.eat("op", "(")
        args, kwargs = [], {}
        while not self.at_op(")"):
            if self.t.kind == "name" and self.peek().kind == "op" and self.peek().value == "=":
                k = self.eat("name").value
                self.eat("op", "=")
                kwargs[k] = self.expr()
            else:
                if kwargs:
                    raise ScriptError("Positional argument after a named one.", line=self.t.line)
                args.append(self.expr())
            if self.at_op(","):
                self.p += 1
            elif not self.at_op(")"):
                raise ScriptError(f"Expected ',' or ')' in call, found '{self.t.value}'", line=self.t.line)
        self.eat("op", ")")
        name = fn.a if fn.kind == "name" else None
        n = self.node("call", line, a=fn, b=args, c=kwargs, d=name)
        n.text = self.cond_stack[-1] if self.cond_stack else ""
        return n

    def primary(self) -> Node:
        t = self.t
        line = t.line
        if t.kind == "num":
            self.p += 1
            return self.node("num", line, a=t.value)
        if t.kind == "str":
            self.p += 1
            return self.node("str", line, a=t.value)
        if t.kind == "color":
            self.p += 1
            return self.node("str", line, a=t.value)
        if t.kind == "name":
            if t.value in ("true", "false"):
                self.p += 1
                return self.node("bool", line, a=t.value == "true")
            if t.value == "na" and not (self.peek().kind == "op" and self.peek().value == "("):
                self.p += 1
                return self.node("na", line)
            if t.value == "if":
                return self.if_stmt(as_expr=True)
            if t.value == "switch":
                return self.switch_stmt(as_expr=True)
            self.p += 1
            return self.node("name", line, a=t.value)
        if t.kind == "op" and t.value == "(":
            self.p += 1
            e = self.expr()
            self.eat("op", ")")
            return e
        if t.kind == "op" and t.value == "[":
            self.p += 1
            items = []
            while not self.at_op("]"):
                items.append(self.expr())
                if self.at_op(","):
                    self.p += 1
            self.eat("op", "]")
            return self.node("tuple", line, a=items)
        raise ScriptError(f"Unexpected '{t.value if t.value is not None else t.kind}'", line=line,
                          hint="Check the syntax on this line.")


def parse(src: str) -> list[Node]:
    return Parser(src).parse()
